from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.permissions import ROLE_ORDER, get_app_role, is_platform_admin
from datamodels.models import DataModel, DataRecord
from workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowTask


def _nodes(definition: WorkflowDefinition) -> list[dict]:
    return [n for n in (definition.nodes or []) if isinstance(n, dict)]


def _node_index(nodes: list[dict], node_id: str | None) -> int | None:
    if not node_id:
        return None
    for i, node in enumerate(nodes):
        if str(node.get("id") or "") == str(node_id):
            return i
    return None


def _condition_met(instance: WorkflowInstance, node: dict) -> bool:
    cond = node.get("condition")
    if isinstance(cond, str):
        # 兼容简单表达式：status == approved / status != draft
        import re

        m = re.match(r"^\s*([\w.]+)\s*(==|!=|>=|<=|>|<|contains)\s*(.+?)\s*$", cond)
        if not m:
            return True
        field, op, expected = m.group(1), m.group(2), m.group(3).strip("'\" ")
    elif isinstance(cond, dict):
        field = str(cond.get("field") or "")
        op = str(cond.get("operator") or "eq")
        expected = cond.get("value")
    else:
        field, op, expected = "", "eq", None
    if not field:
        return True
    actual = (instance.data or {}).get(field)
    if op in ("eq", "=="):
        return str(actual) == str(expected)
    if op in ("ne", "!="):
        return str(actual) != str(expected)
    if op == "contains":
        return str(expected) in str(actual or "")
    if op == "in":
        values = expected if isinstance(expected, list) else str(expected).split(",")
        return str(actual) in {str(x).strip() for x in values}
    try:
        a, b = float(actual), float(expected)
    except (TypeError, ValueError):
        a, b = str(actual), str(expected)
    if op == "gt":
        return a > b
    if op == "gte":
        return a >= b
    if op == "lt":
        return a < b
    if op == "lte":
        return a <= b
    return False


def _finish(instance: WorkflowInstance, approved: bool) -> None:
    instance.status = "approved" if approved else "rejected"
    instance.current_node_id = ""
    instance.save(update_fields=["status", "current_node_id", "updated_at"])
    _writeback(instance, approved)
    try:
        from appcore.events import emit_event

        emit_event(instance.app, "workflow.approved" if approved else "workflow.rejected", {
            "instance_id": instance.id, "title": instance.title, "status": instance.status,
            "business_model_id": instance.business_model_id, "business_record_id": instance.business_record_id,
        })
    except Exception:
        pass


def can_view_task(user, task: WorkflowTask) -> bool:
    if is_platform_admin(user):
        return True
    if task.assignee_id and task.assignee_id == user.id:
        return True
    if not task.assignee_id:
        role = get_app_role(user, task.instance.app)
        if role and (not task.assignee_role or ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(task.assignee_role, 0)):
            return True
    return False


def can_act_task(user, task: WorkflowTask) -> bool:
    return task.status == "pending" and can_view_task(user, task)


def _due_for(node: dict):
    try:
        hours = float(node.get("timeout_hours") or 0)
    except (TypeError, ValueError):
        hours = 0
    return timezone.now() + timedelta(hours=hours) if hours > 0 else None


def _dept_leader_ids(instance: WorkflowInstance, node: dict, entry: dict) -> list[int]:
    """解析「部门负责人」审批人：节点指定部门 → 数据字段部门 → 发起人主部门。"""
    from org.models import Department
    from org.services import primary_department

    raw = entry.get("department_id") or node.get("department_id")
    if not raw:
        field = str(node.get("dept_field") or entry.get("dept_field") or "dept")
        raw = (instance.data or {}).get(field)
    dept = None
    if raw not in (None, ""):
        text = str(raw).strip()
        if text.isdigit():
            dept = Department.objects.filter(pk=int(text)).first()
        if dept is None:
            dept = Department.objects.filter(code=text).first() or Department.objects.filter(name=text).first()
    if dept is None and instance.initiator_id:
        dept = primary_department(instance.initiator)
    if dept is None:
        return []
    ids = [dept.leader_id] if dept.leader_id else []
    if not ids:
        ids = list(dept.members.filter(role="leader").values_list("user_id", flat=True))
    return [uid for uid in ids if uid]


def _create_tasks(instance: WorkflowInstance, node: dict, index: int) -> list[WorkflowTask]:
    approvers = node.get("approvers")
    entries: list[dict] = []
    if isinstance(approvers, list) and approvers:
        entries = [a for a in approvers if isinstance(a, dict)]
    if not entries:
        entries = [{
            "assignee_role": node.get("assignee_role") or "editor",
            "assignee_user_id": node.get("assignee_user_id") or None,
        }]
    tasks = []
    seen = set()
    for entry in entries:
        role = str(entry.get("assignee_role") or node.get("assignee_role") or "editor")
        user_id = entry.get("assignee_user_id") or None
        assignee_type = str(entry.get("assignee_type") or node.get("assignee_type") or "")
        if assignee_type == "initiator":
            user_id = instance.initiator_id
            role = ""
        if assignee_type == "dept_leader":
            leader_ids = _dept_leader_ids(instance, node, entry)
            if leader_ids:
                for uid in leader_ids:
                    key = ("", uid)
                    if key in seen:
                        continue
                    seen.add(key)
                    tasks.append(WorkflowTask.objects.create(
                        instance=instance,
                        node_id=str(node.get("id") or f"approval-{index + 1}"),
                        node_name=str(node.get("name") or f"审批 {index + 1}"),
                        assignee_id=uid,
                        assignee_role="dept_leader",
                        due_at=_due_for(node),
                    ))
                continue
            # 无法解析部门负责人时回退到角色审批，避免流程卡死。
            role = "editor"
        if not user_id and not role:
            role = "editor"
        key = (role, user_id)
        if key in seen:
            continue
        seen.add(key)
        tasks.append(WorkflowTask.objects.create(
            instance=instance,
            node_id=str(node.get("id") or f"approval-{index + 1}"),
            node_name=str(node.get("name") or f"审批 {index + 1}"),
            assignee_id=user_id,
            assignee_role=role,
            due_at=_due_for(node),
        ))
    instance.current_index = index
    instance.current_node_id = str(node.get("id") or f"approval-{index + 1}")
    instance.save(update_fields=["current_index", "current_node_id", "updated_at"])
    return tasks


def _activate_from(instance: WorkflowInstance, start_index: int) -> bool:
    """从 start_index 向后激活节点；返回是否停在审批节点。"""
    nodes = _nodes(instance.definition)
    index = start_index
    guard = 0
    while 0 <= index < len(nodes) and guard < 100:
        guard += 1
        node = nodes[index]
        ntype = str(node.get("type") or "approval")
        if ntype in ("start",):
            index += 1
            continue
        if ntype == "end":
            _finish(instance, True)
            return False
        if ntype == "condition":
            matched = _condition_met(instance, node)
            target = node.get("true_next" if matched else "false_next")
            next_index = _node_index(nodes, target) if target else None
            index = next_index if next_index is not None else index + 1
            continue
        if ntype in ("approval", "parallel"):
            _create_tasks(instance, node, index)
            return True
        index += 1
    _finish(instance, True)
    return False


def _writeback(instance: WorkflowInstance, approved: bool) -> None:
    if not instance.business_model_id or not instance.business_record_id:
        return
    model = DataModel.objects.filter(app=instance.app, id=instance.business_model_id).first()
    if model is None:
        return
    record = DataRecord.objects.filter(model=model, id=instance.business_record_id).first()
    if record is None:
        return
    data = dict(record.data or {})
    action_map = (instance.definition.nodes or [])
    # 流程级配置：on_approve / on_reject（可选），默认只改 status。
    config = {}
    for node in action_map:
        if isinstance(node, dict) and node.get("type") == "end":
            config = node
            break
    target = config.get("on_approve" if approved else "on_reject") or {"status": "已审批" if approved else "已驳回"}
    if isinstance(target, dict):
        data.update(target)
        record.data = data
        record.save(update_fields=["data", "updated_at"])


def start_instance(
    definition: WorkflowDefinition,
    *,
    user,
    title: str = "",
    business_model_id: int | None = None,
    business_record_id: int | None = None,
    data: dict | None = None,
) -> WorkflowInstance:
    with transaction.atomic():
        existing = WorkflowInstance.objects.filter(
            definition=definition,
            business_model_id=business_model_id or None,
            business_record_id=business_record_id or None,
            status="running",
        ).first()
        if existing is not None:
            return existing
        if not data and business_model_id and business_record_id:
            model = DataModel.objects.filter(app=definition.app, id=business_model_id).first()
            record = DataRecord.objects.filter(model=model, id=business_record_id).first() if model else None
            data = dict(record.data or {}) if record else {}
        instance = WorkflowInstance.objects.create(
            definition=definition,
            app=definition.app,
            title=title or definition.name,
            business_model_id=business_model_id or None,
            business_record_id=business_record_id or None,
            data=data or {},
            initiator=user,
            status="running",
        )
        _activate_from(instance, 0)
        return instance


def act_instance(
    instance: WorkflowInstance, *, user, action: str, comment: str = "", rollback_to: str | None = None,
) -> WorkflowInstance:
    if instance.status != "running":
        raise ValueError("流程已结束")
    node_id = instance.current_node_id
    pending = list(instance.tasks.filter(status="pending", node_id=node_id).order_by("id"))
    task = next((t for t in pending if can_act_task(user, t)), None)
    if task is None:
        raise ValueError("没有可处理的待办任务")
    if not can_act_task(user, task):
        raise PermissionError("无权处理该任务")
    node = next((n for n in _nodes(instance.definition) if str(n.get("id")) == str(node_id)), {})
    with transaction.atomic():
        task.status = "approved" if action == "approve" else "rejected"
        task.action_by = user
        task.comment = comment or ""
        task.save(update_fields=["status", "action_by", "comment", "updated_at"])
        if action != "approve":
            if rollback_to:
                nodes = _nodes(instance.definition)
                target_index = _node_index(nodes, rollback_to)
                target = nodes[target_index] if target_index is not None else None
                if target is None or target.get("type") not in ("approval", "condition"):
                    raise ValueError("回退节点不存在或不是审批/条件节点")
                instance.tasks.filter(status="pending").update(status="cancelled", updated_at=timezone.now())
                instance.status = "running"
                instance.current_index = target_index
                instance.current_node_id = ""
                instance.save(update_fields=["status", "current_index", "current_node_id", "updated_at"])
                if target.get("type") == "condition":
                    _activate_from(instance, target_index)
                else:
                    _create_tasks(instance, target, target_index)
                return instance
            instance.tasks.filter(status="pending").update(status="cancelled", updated_at=timezone.now())
            instance.status = "rejected"
            instance.current_node_id = ""
            instance.save(update_fields=["status", "current_node_id", "updated_at"])
            _writeback(instance, False)
            return instance

        mode = str(node.get("mode") or "all")
        remaining = instance.tasks.filter(status="pending", node_id=node_id)
        if mode == "any":
            remaining.update(status="cancelled", updated_at=timezone.now())
        elif remaining.exists():
            # 会签/并行：还有其他人未处理，停留在当前节点
            return instance
        _activate_from(instance, instance.current_index + 1)
        return instance


def act_task(task: WorkflowTask, *, user, action: str, comment: str = "", rollback_to: str | None = None) -> WorkflowInstance:
    if not can_act_task(user, task):
        raise PermissionError("无权处理该任务")
    return act_instance(task.instance, user=user, action=action, comment=comment, rollback_to=rollback_to)


def remind_task(task: WorkflowTask, *, user) -> WorkflowTask:
    if task.status != "pending":
        raise ValueError("任务已结束")
    if not can_view_task(user, task):
        raise PermissionError("无权催办该任务")
    task.remind_count += 1
    task.last_reminded_at = timezone.now()
    task.save(update_fields=["remind_count", "last_reminded_at", "updated_at"])
    return task


def transfer_task(task: WorkflowTask, *, user, assignee_user_id: int | None = None, assignee_role: str = "") -> WorkflowTask:
    if not can_act_task(user, task):
        raise PermissionError("无权转办该任务")
    with transaction.atomic():
        task.status = "transferred"
        task.action_by = user
        task.comment = (task.comment + " " if task.comment else "") + f"转办给 {assignee_user_id or assignee_role}"
        task.save(update_fields=["status", "action_by", "comment", "updated_at"])
        new_task = WorkflowTask.objects.create(
            instance=task.instance,
            node_id=task.node_id,
            node_name=task.node_name,
            assignee_id=assignee_user_id or None,
            assignee_role=assignee_role or task.assignee_role or "editor",
            due_at=task.due_at,
        )
        return new_task


def add_sign(task: WorkflowTask, *, user, assignee_user_id: int | None = None, assignee_role: str = "") -> WorkflowTask:
    if not can_act_task(user, task):
        raise PermissionError("无权加签该任务")
    return WorkflowTask.objects.create(
        instance=task.instance,
        node_id=task.node_id,
        node_name=task.node_name,
        assignee_id=assignee_user_id or None,
        assignee_role=assignee_role or "editor",
        due_at=task.due_at,
    )


def withdraw_instance(instance: WorkflowInstance, *, user) -> WorkflowInstance:
    if instance.status != "running":
        raise ValueError("流程已结束")
    if not is_platform_admin(user) and instance.initiator_id != user.id:
        raise PermissionError("只有发起人可以撤回")
    with transaction.atomic():
        instance.tasks.filter(status="pending").update(status="cancelled", updated_at=timezone.now())
        instance.status = "cancelled"
        instance.current_node_id = ""
        instance.save(update_fields=["status", "current_node_id", "updated_at"])
    return instance


def pending_tasks_for(user, app_id: int | None = None):
    from appcore.models import App

    qs = WorkflowTask.objects.select_related("instance", "instance__app", "instance__definition").filter(status="pending")
    if app_id:
        qs = qs.filter(instance__app_id=app_id)
    if is_platform_admin(user):
        return qs
    from django.db.models import Q

    member_apps = App.objects.filter(members__user=user).values_list("id", flat=True)
    candidate = Q(assignee=user) | Q(assignee__isnull=True, instance__app_id__in=member_apps)
    return qs.filter(candidate)


def dashboard_counts(user, app_id: int | None = None) -> dict:
    qs = pending_tasks_for(user, app_id)
    return {"pending": qs.count()}
