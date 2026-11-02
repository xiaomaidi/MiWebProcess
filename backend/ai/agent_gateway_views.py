from __future__ import annotations

import json

import time

from django.conf import settings
from django.db import close_old_connections
from django.db.models import Sum
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ai.agent_gateway import add_event, apply_agent_proposal, apply_agent_proposals, enqueue_agent_task, rollback_agent_proposal, run_agent_task
from core.audit import write_audit_log
from ai.browser_verify import verify_page
from ai.sandbox import sandbox_status
from ai.models import AgentEvalCase, AgentEvalRun, AgentProposal, AgentTask, AgentUsage
from appcore.models import App
from pages.models import Page
from wp_utils import require_app_role


def _task_payload(task: AgentTask) -> dict:
    page = Page.objects.filter(app=task.app, id=task.page_id).first() if task.page_id else None
    return {
        "id": task.id, "app_id": task.app_id, "app_name": task.app.name, "app_code": task.app.code,
        "page_id": task.page_id, "page_name": page.name if page else "",
        "page_path": page.path if page else "", "mode": task.mode, "goal": task.goal,
        "status": task.status, "risk": task.risk, "provider": task.provider, "model": task.model,
        "result": task.result or {}, "error": task.error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


def _proposal_payload(item: AgentProposal) -> dict:
    return {
        "id": item.id, "task_id": item.task_id, "kind": item.kind,
        "target_type": item.target_type, "target_id": item.target_id,
        "base_version": item.base_version, "summary": item.summary,
        "ops": item.ops or [], "diff": item.diff or {}, "status": item.status,
        "risk": item.risk, "verification": item.verification or {},
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _task_or_404(request, pk: int, role: str = "viewer") -> AgentTask:
    task = get_object_or_404(AgentTask.objects.select_related("app", "user"), pk=pk)
    require_app_role(request.user, task.app, role)
    return task


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def tasks(request):
    if request.method == "GET":
        app_id = request.query_params.get("app_id")
        if not app_id:
            raise ValidationError({"detail": "app_id 必填"})
        app = get_object_or_404(App, pk=app_id)
        require_app_role(request.user, app, "viewer")
        rows = AgentTask.objects.filter(app=app).order_by("-id")[:100]
        return Response({"results": [_task_payload(x) for x in rows]})

    app_id = request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_object_or_404(App, pk=app_id)
    require_app_role(request.user, app, "editor")
    goal = str(request.data.get("goal") or "").strip()
    if not goal:
        raise ValidationError({"detail": "goal 必填"})
    page_id = request.data.get("page_id")
    if page_id:
        page = Page.objects.filter(app=app, id=int(page_id)).first()
        if page is None:
            raise ValidationError({"detail": "页面不存在"})
    else:
        page = None
    today = timezone.now().date()
    task_limit = int(getattr(settings, "AGENT_DAILY_TASK_LIMIT", 50))
    token_limit = int(getattr(settings, "AGENT_DAILY_TOKEN_LIMIT", 200000))
    if AgentTask.objects.filter(app=app, user=request.user, created_at__date=today).count() >= task_limit:
        raise ValidationError({"detail": "今日 Agent 任务配额已用完"})
    used_tokens = AgentUsage.objects.filter(task__app=app, task__created_at__date=today).aggregate(
        total=Sum("estimated_tokens")
    )["total"] or 0
    if used_tokens >= token_limit:
        raise ValidationError({"detail": "今日 Agent Token 配额已用完"})
    task = AgentTask.objects.create(
        app=app, user=request.user, page_id=int(page_id) if page_id else None,
        mode=str(request.data.get("mode") or "page_edit"),
        goal=goal[:4000],
        context={"page_path": page.path if page else ""},
    )
    add_event(task, "task.created", "任务已创建", {"mode": task.mode})
    write_audit_log(
        user=request.user, action="agent.task.create", object_type="agent_task", object_id=task.id,
        app_id=app.id, after={"goal": task.goal, "page_id": task.page_id, "mode": task.mode},
    )
    enqueue_agent_task(task)
    return Response(_task_payload(task), status=status.HTTP_201_CREATED)


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def task_detail(request, pk: int):
    task = _task_or_404(request, pk, "viewer" if request.method == "GET" else "editor")
    if request.method == "DELETE":
        if task.status == "running":
            task.cancel_requested = True
            task.status = "cancelled"
            task.finished_at = timezone.now()
            task.save()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response({
        "task": _task_payload(task),
        "events": [
            {"id": e.id, "type": e.type, "message": e.message, "payload": e.payload,
             "created_at": e.created_at.isoformat() if e.created_at else None}
            for e in task.events.all()[:200]
        ],
        "proposals": [_proposal_payload(x) for x in task.proposals.all()],
        "usage": [
            {"steps": u.steps, "duration_ms": u.duration_ms, "estimated_tokens": u.estimated_tokens,
             "created_at": u.created_at.isoformat() if u.created_at else None}
            for u in task.usage.all()
        ],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_stream(request, pk: int):
    task = _task_or_404(request, pk, "viewer")

    def event_stream():
        last_id = 0
        try:
            while True:
                events = list(task.events.filter(id__gt=last_id).order_by("id")[:50])
                for event in events:
                    last_id = event.id
                    payload = {
                        "id": event.id, "type": event.type, "message": event.message,
                        "payload": event.payload or {},
                        "created_at": event.created_at.isoformat() if event.created_at else None,
                    }
                    yield "data: " + json.dumps(payload, ensure_ascii=False, default=str) + "\n\n"
                task.refresh_from_db(fields=["status"])
                if task.status in ("waiting_approval", "applied", "failed", "cancelled") and not events:
                    yield "data: " + json.dumps({"type": "done", "status": task.status}, ensure_ascii=False) + "\n\n"
                    break
                time.sleep(0.8)
        finally:
            close_old_connections()

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_cancel(request, pk: int):
    task = _task_or_404(request, pk, "editor")
    task.cancel_requested = True
    if task.status in ("pending", "running"):
        task.status = "cancelled"
        task.finished_at = timezone.now()
        task.save()
        add_event(task, "task.cancelled", "用户取消任务")
    return Response(_task_payload(task))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_retry(request, pk: int):
    task = _task_or_404(request, pk, "editor")
    if task.status not in ("failed", "cancelled", "applied"):
        raise ValidationError({"detail": "只有失败/取消/已应用任务可以重跑"})
    task.status = "pending"
    task.cancel_requested = False
    task.error = ""
    task.result = {}
    task.save()
    add_event(task, "task.retry", "重新执行任务")
    enqueue_agent_task(task)
    return Response(_task_payload(task))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def proposal_reject(request, pk: int):
    item = get_object_or_404(AgentProposal.objects.select_related("task", "task__app"), pk=pk)
    require_app_role(request.user, item.task.app, "editor")
    if item.status != "pending":
        raise ValidationError({"detail": "该提案不在待审批状态"})
    item.status = "rejected"
    item.save(update_fields=["status"])
    item.task.status = "failed"
    item.task.error = "提案被拒绝"
    item.task.save(update_fields=["status", "error", "updated_at"])
    add_event(item.task, "proposal.rejected", item.summary[:300], {"proposal_id": item.id})
    return Response({"ok": True, "status": item.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_apply_all(request, pk: int):
    task = _task_or_404(request, pk, "editor")
    pending = list(task.proposals.filter(status="pending").order_by("id"))
    if not pending:
        raise ValidationError({"detail": "没有待审批提案"})
    try:
        result = apply_agent_proposals(pending, request.user, bool(request.data.get("publish")))
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    write_audit_log(
        user=request.user, action="agent.proposal.apply_all", object_type="agent_task", object_id=task.id,
        app_id=task.app_id, after={"count": len(pending), "publish": bool(request.data.get("publish"))},
    )
    return Response({"ok": True, **result})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def proposal_verify(request, pk: int):
    item = get_object_or_404(AgentProposal.objects.select_related("task", "task__app"), pk=pk)
    require_app_role(request.user, item.task.app, "viewer")
    page = Page.objects.filter(app=item.task.app, id=item.target_id).first() if item.target_id else None
    if page is None:
        raise ValidationError({"detail": "提案没有绑定页面"})
    result = verify_page(page, request.user, prefix=f"proposal-{item.id}")
    item.verification = {**(item.verification or {}), "browser": result}
    item.save(update_fields=["verification"])
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def proposal_apply(request, pk: int):
    item = get_object_or_404(AgentProposal.objects.select_related("task", "task__app"), pk=pk)
    require_app_role(request.user, item.task.app, "editor")
    try:
        result = apply_agent_proposal(item, request.user, bool(request.data.get("publish")))
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    write_audit_log(
        user=request.user, action="agent.proposal.apply", object_type="agent_proposal", object_id=item.id,
        app_id=item.task.app_id, after={"publish": bool(request.data.get("publish")), "page_id": result.get("page_id")},
    )
    return Response({"ok": True, **result, "proposal": _proposal_payload(item)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def proposal_rollback(request, pk: int):
    item = get_object_or_404(AgentProposal.objects.select_related("task", "task__app"), pk=pk)
    require_app_role(request.user, item.task.app, "editor")
    try:
        result = rollback_agent_proposal(item, request.user)
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    write_audit_log(
        user=request.user, action="agent.proposal.rollback", object_type="agent_proposal", object_id=item.id,
        app_id=item.task.app_id, after={"page_id": result.get("page_id")},
    )
    return Response({"ok": True, **result, "proposal": _proposal_payload(item)})

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sandbox_info(request):
    return Response(sandbox_status())


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def eval_cases(request):
    if request.method == "GET":
        app_id = request.query_params.get("app_id")
        app = get_object_or_404(App, pk=app_id)
        require_app_role(request.user, app, "viewer")
        rows = []
        for case in app.agent_eval_cases.all()[:100]:
            rows.append({
                "id": case.id, "name": case.name, "goal": case.goal, "page_id": case.page_id,
                "expected": case.expected, "enabled": case.enabled,
                "runs": [
                    {"id": r.id, "task_id": r.task_id, "status": r.status, "score": r.score,
                     "detail": r.detail, "created_at": r.created_at.isoformat()}
                    for r in case.runs.all()[:5]
                ],
            })
        return Response({"results": rows})
    app_id = request.data.get("app_id")
    app = get_object_or_404(App, pk=app_id)
    require_app_role(request.user, app, "editor")
    name = str(request.data.get("name") or "").strip()
    goal = str(request.data.get("goal") or "").strip()
    if not name or not goal:
        raise ValidationError({"detail": "name 和 goal 必填"})
    case = AgentEvalCase.objects.create(
        app=app, name=name[:200], goal=goal[:4000],
        page_id=int(request.data.get("page_id")) if request.data.get("page_id") else None,
        expected=str(request.data.get("expected") or "")[:500],
    )
    return Response({"id": case.id, "name": case.name}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def eval_run(request, pk: int):
    case = get_object_or_404(AgentEvalCase.objects.select_related("app"), pk=pk)
    require_app_role(request.user, case.app, "editor")
    task = AgentTask.objects.create(
        app=case.app, user=request.user, page_id=case.page_id, mode="page_edit", goal=case.goal,
        context={"eval_case_id": case.id},
    )
    run = AgentEvalRun.objects.create(case=case, task=task, status="running")
    enqueue_agent_task(task)
    return Response({"id": run.id, "task_id": task.id, "status": run.status})


def _score_eval_run(run: AgentEvalRun) -> None:
    if run.task is None:
        run.status = "failed"
        run.score = 0
        run.detail = {"error": "评估任务不存在"}
        run.save()
        return
    status_ok = run.task.status in ("waiting_approval", "applied")
    proposal = run.task.proposals.order_by("-id").first()
    keyword_ok = True
    if run.case.expected and proposal is not None:
        haystack = (proposal.summary or "") + json.dumps(proposal.diff or {}, ensure_ascii=False)
        keyword_ok = run.case.expected in haystack
    run.status = "passed" if status_ok and keyword_ok else "failed"
    run.score = 100 if status_ok and keyword_ok else (50 if status_ok else 0)
    run.detail = {"task_status": run.task.status, "proposal": proposal.id if proposal else None,
                  "keyword": keyword_ok, "expected": run.case.expected}
    run.save()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def eval_score(request, pk: int):
    run = get_object_or_404(AgentEvalRun.objects.select_related("case", "task"), pk=pk)
    require_app_role(request.user, run.case.app, "viewer")
    _score_eval_run(run)
    return Response({"id": run.id, "status": run.status, "score": run.score, "detail": run.detail})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def eval_case_detail(request, pk: int):
    case = get_object_or_404(AgentEvalCase.objects.select_related("app"), pk=pk)
    require_app_role(request.user, case.app, "editor")
    case.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def eval_run_all(request):
    app = get_object_or_404(App, pk=request.data.get("app_id") or request.query_params.get("app_id"))
    require_app_role(request.user, app, "editor")
    cases = list(app.agent_eval_cases.filter(enabled=True)[:30])
    if not cases:
        raise ValidationError({"detail": "没有启用的评估用例"})
    runs = []
    for case in cases:
        task = AgentTask.objects.create(
            app=app, user=request.user, page_id=case.page_id, mode="page_edit", goal=case.goal,
            context={"eval_case_id": case.id, "batch": True},
        )
        run = AgentEvalRun.objects.create(case=case, task=task, status="running")
        enqueue_agent_task(task)
        runs.append({"id": run.id, "case_id": case.id, "task_id": task.id})
    return Response({"count": len(runs), "runs": runs})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def eval_score_all(request):
    app = get_object_or_404(App, pk=request.data.get("app_id") or request.query_params.get("app_id"))
    require_app_role(request.user, app, "viewer")
    runs = AgentEvalRun.objects.filter(case__app=app).select_related("case", "task").order_by("-id")[:100]
    for run in runs:
        _score_eval_run(run)
    return Response({"count": len(runs), "results": [{"id": r.id, "score": r.score, "status": r.status} for r in runs]})

