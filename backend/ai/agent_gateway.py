"""高级 Agent Gateway：任务、事件、提案、应用与验证。"""
from __future__ import annotations

import copy
import json
import threading
import time
import urllib.request

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from ai.models import AgentEvent, AgentProposal, AgentTask, AgentUsage, AiConversation, AiMessage
from pages.models import Page
from pages.services import publish_page, save_draft


def add_event(task: AgentTask, type_: str, message: str = "", payload: dict | None = None) -> AgentEvent:
    return AgentEvent.objects.create(task=task, type=type_, message=message[:500], payload=payload or {})


def emit_agent_event(task: AgentTask, event: str, payload: dict | None = None) -> None:
    try:
        from appcore.events import emit_event
        emit_event(task.app, event, payload or {"task_id": task.id, "goal": task.goal})
    except Exception:
        pass


def _node_map(schema: dict) -> dict:
    return {k: v for k, v in (schema.get("nodes") or {}).items() if isinstance(v, dict)}


def build_diff(before: dict, after: dict) -> dict:
    b = _node_map(before)
    a = _node_map(after)
    added = [k for k in a if k not in b]
    removed = [k for k in b if k not in a]
    changed = []
    for key in b.keys() & a.keys():
        old, new = b[key], a[key]
        fields = []
        if old.get("type") != new.get("type"):
            fields.append("type")
        old_props, new_props = old.get("props") or {}, new.get("props") or {}
        for prop in old_props.keys() | new_props.keys():
            if old_props.get(prop) != new_props.get(prop):
                fields.append(f"props.{prop}")
        if old.get("style") != new.get("style"):
            fields.append("style")
        if old.get("children") != new.get("children"):
            fields.append("children")
        if fields:
            changed.append({"id": key, "type": new.get("type"), "fields": fields[:12]})
    return {
        "added": added[:50],
        "removed": removed[:50],
        "changed": changed[:50],
        "counts": {"added": len(added), "removed": len(removed), "changed": len(changed)},
    }


def three_way_diff(base: dict, current: dict, proposed: dict) -> dict:
    base_nodes = _node_map(base)
    current_nodes = _node_map(current)
    proposed_nodes = _node_map(proposed)
    conflicts = []
    for node_id in set(base_nodes) | set(current_nodes) | set(proposed_nodes):
        b, c, p = base_nodes.get(node_id), current_nodes.get(node_id), proposed_nodes.get(node_id)
        if c is not None and p is not None and c != b and p != b and c != p:
            conflicts.append({"node_id": node_id, "reason": "同一节点被并发修改"})
    return {
        "base_vs_current": build_diff(base, current),
        "base_vs_proposed": build_diff(base, proposed),
        "conflicts": conflicts[:50],
    }


def _create_proposal(task: AgentTask, *, kind: str, summary: str, ops=None, schema=None,
                     page: Page | None = None, message: AiMessage | None = None) -> AgentProposal:
    before = page.schema if page else {}
    if schema:
        after = schema
    else:
        from ai.agent import apply_patch

        after = apply_patch(before, ops or [])
    diff = build_diff(before, after) if page and kind in ("page_patch", "page_schema") else {}
    risk = "high" if any(op.get("op") in ("remove_node", "set_theme") for op in (ops or [])) else "medium"
    proposal = AgentProposal.objects.create(
        task=task, conversation=task.conversation if hasattr(task, "conversation") else None,
        message=message, kind=kind, target_type="page" if page else "app",
        target_id=page.id if page else task.app_id, base_version=page.version if page else None,
        base_schema=copy.deepcopy(page.schema) if page else {},
        summary=summary[:300], ops=ops or [], schema=schema or {}, diff=diff, risk=risk,
    )
    add_event(task, "proposal.created", summary[:300], {"proposal_id": proposal.id, "diff": diff})
    emit_agent_event(task, "agent.proposal.created", {"proposal_id": proposal.id, "summary": summary[:200]})
    return proposal


def _run_internal(task: AgentTask) -> None:
    user = task.user
    page = Page.objects.filter(app=task.app, id=task.page_id).first() if task.page_id else None
    conversation = AiConversation.objects.create(
        app=task.app, user=user, page_id=task.page_id,
        title=task.goal[:60],
    )
    task.provider = "platform"
    task.model = "builtin-agent"
    task.save(update_fields=["provider", "model", "updated_at"])
    add_event(task, "executor.selected", "使用平台内置 Agent", {"conversation_id": conversation.id})

    def on_event(event: dict) -> None:
        add_event(task, str(event.get("type") or "status"), str(event.get("text") or ""), event)

    from ai.agent import run_turn

    result = run_turn(
        conversation, task.goal, user,
        on_event=on_event,
        should_stop=lambda: task.cancel_requested,
    )
    assistant = AiMessage.objects.filter(conversation=conversation, role="assistant").order_by("-id").first()
    if assistant is None:
        raise RuntimeError("Agent 没有返回消息")
    proposal = assistant.proposal or {}
    if not proposal:
        task.result = {"assistant": assistant.content[:2000]}
        task.error = "Agent 没有生成可应用提案"
        task.status = "failed"
        task.finished_at = timezone.now()
        task.save()
        add_event(task, "task.failed", task.error)
        return
    kind = str(proposal.get("kind") or "page_patch")
    summary = str(proposal.get("summary") or "页面修改")
    created = _create_proposal(
        task, kind=kind, summary=summary, ops=proposal.get("ops") or [],
        schema=proposal.get("schema") or {}, page=page, message=assistant,
    )
    created.conversation = conversation
    created.save(update_fields=["conversation"])
    task.result = {
        "assistant": assistant.content[:4000],
        "proposal_id": created.id,
        "provider": "platform",
    }
    task.status = "waiting_approval"
    task.finished_at = timezone.now()
    task.save()
    add_event(task, "task.waiting_approval", "提案已生成，等待确认", {"proposal_id": created.id})
    emit_agent_event(task, "agent.task.waiting_approval", {"proposal_id": created.id})


def _external_dsh(task: AgentTask) -> None:
    url = str(getattr(settings, "DSH_AGENT_URL", "") or "").strip()
    sandbox_mode = str(getattr(settings, "DSH_SANDBOX_MODE", "http") or "http").lower()
    if not url and sandbox_mode not in ("process", "docker"):
        raise RuntimeError("未配置 DSH_AGENT_URL")
    page = Page.objects.filter(app=task.app, id=task.page_id).first() if task.page_id else None
    payload = {
        "task_id": task.id,
        "goal": task.goal,
        "mode": task.mode,
        "app": {"id": task.app_id, "code": task.app.code, "name": task.app.name},
        "page": None if page is None else {
            "id": page.id, "path": page.path, "name": page.name,
            "version": page.version, "schema": page.schema,
        },
    }
    def request_once() -> dict:
        if sandbox_mode in ("process", "docker"):
            from ai.sandbox import run_task_sandbox

            return run_task_sandbox(payload)
        headers = {"Content-Type": "application/json"}
        token = str(getattr(settings, "DSH_AGENT_TOKEN", "") or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            url.rstrip("/") + "/tasks", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers, method="POST",
        )
        with urllib.request.urlopen(req, timeout=int(getattr(settings, "DSH_AGENT_TIMEOUT", 300))) as resp:
            return json.loads(resp.read().decode("utf-8"))

    retries = max(1, int(getattr(settings, "DSH_AGENT_RETRIES", 2)))
    data = {}
    proposals = []
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            data = request_once()
            proposals = data.get("proposals") or []
            if isinstance(data.get("proposal"), dict):
                proposals = [data["proposal"]]
            if proposals:
                break
            last_error = "DSH 没有返回提案"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
        add_event(task, "dsh.retry", f"DSH 第 {attempt}/{retries} 次尝试未生成提案", {"error": last_error[:300]})
        if attempt < retries:
            time.sleep(1)
    task.provider = "dsh"
    task.model = str(data.get("model") or "dsh-agent")
    task.save(update_fields=["provider", "model", "updated_at"])
    proposals = data.get("proposals") or []
    if isinstance(data.get("proposal"), dict):
        proposals = [data["proposal"]]
    if not proposals:
        raise RuntimeError("DSH 没有返回提案")
    for item in proposals[:10]:
        _create_proposal(
            task, kind=str(item.get("kind") or "page_patch"),
            summary=str(item.get("summary") or "DSH 页面修改"),
            ops=item.get("ops") or [], schema=item.get("schema") or {}, page=page,
        )
    task.status = "waiting_approval"
    task.finished_at = timezone.now()
    task.result = {"executor": "dsh", "proposals": len(proposals)}
    task.save()
    add_event(task, "task.waiting_approval", "DSH 提案已生成", {"count": len(proposals)})


def enqueue_agent_task(task: AgentTask) -> None:
    """本地 eager 模式不能在请求线程里同步跑 DSH，否则创建接口会一直卡到完成。"""
    if bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", True)):
        thread = threading.Thread(
            target=run_agent_task.run, args=(task.id,), daemon=True,
            name=f"agent-task-{task.id}",
        )
        thread.start()
        return
    run_agent_task.delay(task.id)


@shared_task(name="ai.agent_gateway.run_agent_task")
def run_agent_task(task_id: int):
    task = AgentTask.objects.select_related("app", "user").filter(pk=task_id).first()
    if task is None or task.status not in ("pending", "running"):
        return "skip"
    task.status = "running"
    task.started_at = timezone.now()
    task.save(update_fields=["status", "started_at", "updated_at"])
    add_event(task, "task.started", "开始执行 Agent 任务")
    started = time.time()
    try:
        if getattr(settings, "DSH_AGENT_URL", "") or str(getattr(settings, "DSH_SANDBOX_MODE", "http")).lower() in ("process", "docker"):
            _external_dsh(task)
        else:
            _run_internal(task)
        if task.cancel_requested and task.status == "running":
            task.status = "cancelled"
            task.finished_at = timezone.now()
            task.save()
            add_event(task, "task.cancelled", "任务已取消")
    except Exception as exc:  # noqa: BLE001
        task.status = "failed"
        task.error = f"{type(exc).__name__}: {exc}"[:2000]
        task.finished_at = timezone.now()
        task.save()
        add_event(task, "task.failed", task.error)
    finally:
        try:
            from django.db import close_old_connections
            close_old_connections()
        except Exception:
            pass
        content = str((task.result or {}).get("assistant") or "")
        estimated = max(1, (len(task.goal or "") + len(content)) // 4)
        AgentUsage.objects.create(
            task=task, duration_ms=int((time.time() - started) * 1000),
            prompt_chars=len(task.goal or ""), response_chars=len(content), estimated_tokens=estimated,
        )
    return task.status


def _auto_verify(page: Page, user, proposal: AgentProposal, before_schema: dict, publish: bool, verification: dict) -> dict:
    from django.conf import settings as django_settings

    if not bool(getattr(django_settings, "AGENT_AUTO_VERIFY", False)):
        return verification
    try:
        from ai.browser_verify import verify_page

        browser = verify_page(page, user, prefix=f"auto-proposal-{proposal.id}", draft=True)
    except Exception as exc:  # noqa: BLE001
        browser = {"available": False, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    verification["browser"] = browser
    if browser.get("available") and not browser.get("ok"):
        page, _, _ = save_draft(page, before_schema, user)
        if publish:
            try:
                publish_page(page, user, "Agent 自动验证失败回滚")
            except Exception:
                pass
        proposal.status = "failed"
        proposal.verification = verification
        proposal.save(update_fields=["status", "verification"])
        raise ValueError("自动验证失败，已回滚：" + "；".join(browser.get("errors") or [])[:300])
    return verification


def apply_agent_proposal(proposal: AgentProposal, user, publish: bool = False, allow_stale: bool = False) -> dict:
    if proposal.status not in ("pending", "failed"):
        raise ValueError("该提案不可应用")
    task = proposal.task
    page = Page.objects.filter(app=task.app, id=proposal.target_id).first() if proposal.target_id else None
    before_schema = copy.deepcopy(page.schema) if page else {}
    if page is not None and proposal.base_schema and not allow_stale:
        proposed_schema = proposal.schema or before_schema
        if proposal.ops:
            from ai.agent import apply_patch
            proposed_schema = apply_patch(proposal.base_schema, proposal.ops)
        diff = three_way_diff(proposal.base_schema, page.schema or {}, proposed_schema)
        if diff.get("conflicts"):
            proposal.diff = diff
            proposal.verification = {"schema": "conflict", "conflicts": diff["conflicts"]}
            proposal.save(update_fields=["diff", "verification"])
            raise ValueError("页面已被其他修改更新，请重新生成提案")
    if proposal.message_id and proposal.conversation_id:
        from ai.agent import apply_proposal

        result = apply_proposal(proposal.conversation, proposal.message, user)
        page = Page.objects.get(pk=result.get("page_id") or proposal.target_id)
        verification = {"schema": "passed"}
        if publish:
            pv, errors, warnings = publish_page(page, user, "Agent 提案发布")
            if errors:
                proposal.status = "failed"
                proposal.verification = {"schema": "failed", "errors": errors[:20]}
                proposal.save()
                raise ValueError("；".join(str(x) for x in errors[:5]))
            verification["publish"] = errors or "passed"
        verification = _auto_verify(page, user, proposal, before_schema, publish, verification)
        proposal.status = "applied"
        proposal.undo = {"kind": "page_schema", "page_id": page.id, "schema": before_schema}
        proposal.applied_by = user
        proposal.applied_at = timezone.now()
        proposal.verification = verification
        proposal.save()
        task.status = "applied"
        task.result = {**(task.result or {}), "applied_page_id": page.id}
        task.save()
        add_event(task, "proposal.applied", proposal.summary[:300], {"proposal_id": proposal.id})
        emit_agent_event(task, "agent.proposal.applied", {"proposal_id": proposal.id, "page_id": page.id})
        return {"ok": True, "page_id": page.id, "schema": page.schema, "verification": verification}

    if page is None:
        raise ValueError("提案没有绑定页面")
    from ai.agent import apply_patch
    from pages.services import save_draft

    schema = proposal.schema or apply_patch(page.schema or {}, proposal.ops or [])
    page, errors, warnings = save_draft(page, schema, user)
    if errors:
        proposal.status = "failed"
        proposal.verification = {"schema": "failed", "errors": errors[:20]}
        proposal.save()
        raise ValueError("；".join(str(x) for x in errors[:5]))
    verification = {"schema": "passed", "warnings": warnings[:20]}
    if publish:
        pv, errors, warnings = publish_page(page, user, "Agent 提案发布")
        if errors:
            proposal.status = "failed"
            proposal.verification = {"schema": "failed", "errors": errors[:20]}
            proposal.save()
            raise ValueError("；".join(str(x) for x in errors[:5]))
        verification["publish"] = "passed"
    verification = _auto_verify(page, user, proposal, before_schema, publish, verification)
    proposal.status = "applied"
    proposal.undo = {"kind": "page_schema", "page_id": page.id, "schema": before_schema}
    proposal.applied_by = user
    proposal.applied_at = timezone.now()
    proposal.verification = verification
    proposal.save()
    task.status = "applied"
    task.save(update_fields=["status", "updated_at"])
    add_event(task, "proposal.applied", proposal.summary[:300], {"proposal_id": proposal.id})
    emit_agent_event(task, "agent.proposal.applied", {"proposal_id": proposal.id, "page_id": page.id})
    return {"ok": True, "page_id": page.id, "schema": page.schema, "verification": verification}


def rollback_agent_proposal(proposal: AgentProposal, user) -> dict:
    if proposal.status != "applied":
        raise ValueError("只有已应用的提案可以回滚")
    undo = proposal.undo or {}
    page = Page.objects.filter(app=proposal.task.app, id=undo.get("page_id") or proposal.target_id).first()
    if page is None or not undo.get("schema"):
        raise ValueError("没有可回滚页面快照")
    page, errors, _ = save_draft(page, undo["schema"], user)
    if errors:
        raise ValueError("；".join(str(x) for x in errors[:5]))
    pv, errors, _ = publish_page(page, user, "Agent 回滚")
    if errors:
        raise ValueError("；".join(str(x) for x in errors[:5]))
    proposal.status = "rolled_back"
    proposal.save(update_fields=["status"])
    proposal.task.status = "failed"
    proposal.task.save(update_fields=["status", "updated_at"])
    add_event(proposal.task, "proposal.rolled_back", proposal.summary[:300], {"proposal_id": proposal.id})
    return {"ok": True, "page_id": page.id, "schema": page.schema}

def apply_agent_proposals(proposals: list[AgentProposal], user, publish: bool = False) -> dict:
    """跨页面多提案原子应用：任一页面失败，整体回滚。"""
    from django.db import transaction
    from ai.agent import apply_patch

    if not proposals:
        raise ValueError("没有可应用提案")
    if any(p.status != "pending" for p in proposals):
        raise ValueError("存在非待审批提案")
    groups: dict[int, list[AgentProposal]] = {}
    for item in proposals:
        if not item.target_id:
            raise ValueError("提案没有绑定页面")
        groups.setdefault(int(item.target_id), []).append(item)
    pages = {x.id: x for x in Page.objects.filter(id__in=list(groups))}
    if len(pages) != len(groups):
        raise ValueError("存在页面不存在")
    for page_id, items in groups.items():
        first = items[0]
        page = pages[page_id]
        if first.base_schema and page.version != first.base_version:
            proposed = first.schema or page.schema
            if first.ops:
                proposed = apply_patch(first.base_schema, first.ops)
            diff = three_way_diff(first.base_schema, page.schema or {}, proposed)
            if diff.get("conflicts"):
                raise ValueError(f"页面 {page_id} 已被其他修改更新，请重新生成提案")
    saved: list[tuple[Page, dict]] = []
    try:
        with transaction.atomic():
            for page_id, items in groups.items():
                page = pages[page_id]
                base = copy.deepcopy(page.schema or {})
                schema = base
                for item in items:
                    schema = item.schema or apply_patch(schema, item.ops or [])
                page, errors, warnings = save_draft(page, schema, user)
                if errors:
                    raise ValueError("；".join(str(x) for x in errors[:5]))
                if publish:
                    pv, errors, _ = publish_page(page, user, "Agent 跨页面批量提案发布")
                    if errors:
                        raise ValueError("；".join(str(x) for x in errors[:5]))
                page.verification = {"schema": "passed", "warnings": warnings[:20], "publish": "passed" if publish else "draft"}
                saved.append((page, base))
            now = timezone.now()
            for item in proposals:
                base = next((b for p, b in saved if p.id == item.target_id), {})
                item.status = "applied"
                item.applied_by = user
                item.applied_at = now
                item.undo = {"kind": "page_schema", "page_id": item.target_id, "schema": base}
                item.verification = {"schema": "passed", "publish": "passed" if publish else "draft"}
                item.save()
                add_event(item.task, "proposal.applied", item.summary[:300], {"proposal_id": item.id})
                emit_agent_event(item.task, "agent.proposal.applied", {"proposal_id": item.id, "page_id": item.target_id})
            task = proposals[0].task
            task.status = "applied"
            task.save(update_fields=["status", "updated_at"])
            return {"ok": True, "pages": [p.id for p, _ in saved], "schema": saved[0][0].schema if saved else {}}
    except Exception:
        raise
