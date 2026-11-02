from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.models import App
from appcore.modules import require_module
from workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowTask
from workflow.serializers import (
    WorkflowDefinitionSerializer,
    WorkflowInstanceSerializer,
    WorkflowTaskSerializer,
)
from workflow.services import (
    act_instance,
    act_task,
    add_sign,
    pending_tasks_for,
    remind_task,
    start_instance,
    transfer_task,
    withdraw_instance,
)
from wp_utils import get_app, require_app_role


def _definition(pk: int) -> WorkflowDefinition:
    return get_object_or_404(WorkflowDefinition.objects.select_related("app"), pk=pk)


def _instance(pk: int) -> WorkflowInstance:
    return get_object_or_404(
        WorkflowInstance.objects.select_related("app", "definition", "initiator").prefetch_related("tasks"),
        pk=pk,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def definition_list_create(request):
    if request.method == "GET":
        app_id = request.query_params.get("app_id")
        if not app_id:
            raise ValidationError({"detail": "app_id 必填"})
        app = get_app(app_id)
        require_app_role(request.user, app, "viewer")
        require_module(app, "workflow")
        qs = WorkflowDefinition.objects.filter(app=app)
        return Response(WorkflowDefinitionSerializer(qs, many=True).data)

    app_id = request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(app_id)
    require_app_role(request.user, app, "editor")
    require_module(app, "workflow")
    name = str(request.data.get("name") or "").strip()
    code = str(request.data.get("code") or "").strip()
    if not name or not code:
        raise ValidationError({"detail": "name 和 code 必填"})
    if WorkflowDefinition.objects.filter(app=app, code=code).exists():
        raise ValidationError({"detail": f"流程编码 {code} 已存在"})
    nodes = request.data.get("nodes") or []
    if not isinstance(nodes, list):
        raise ValidationError({"detail": "nodes 必须是数组"})
    definition = WorkflowDefinition.objects.create(
        app=app, name=name, code=code, description=str(request.data.get("description") or ""),
        nodes=nodes, created_by=request.user,
    )
    return Response(WorkflowDefinitionSerializer(definition).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def definition_detail(request, pk: int):
    definition = _definition(pk)
    require_app_role(request.user, definition.app, "viewer" if request.method == "GET" else "editor")
    require_module(definition.app, "workflow")
    if request.method == "GET":
        return Response(WorkflowDefinitionSerializer(definition).data)
    if request.method == "DELETE":
        definition.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if "name" in request.data:
        definition.name = str(request.data.get("name") or "").strip() or definition.name
    if "description" in request.data:
        definition.description = str(request.data.get("description") or "")[:500]
    if "nodes" in request.data:
        nodes = request.data.get("nodes")
        if not isinstance(nodes, list):
            raise ValidationError({"detail": "nodes 必须是数组"})
        definition.nodes = nodes
    definition.version += 1
    definition.save()
    return Response(WorkflowDefinitionSerializer(definition).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def definition_publish(request, pk: int):
    definition = _definition(pk)
    require_app_role(request.user, definition.app, "owner")
    approvals = [n for n in definition.nodes if isinstance(n, dict) and n.get("type") == "approval"]
    if not approvals:
        raise ValidationError({"detail": "至少需要一个审批节点"})
    definition.status = "published"
    definition.save(update_fields=["status", "updated_at"])
    return Response(WorkflowDefinitionSerializer(definition).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def definition_start(request, pk: int):
    definition = _definition(pk)
    require_app_role(request.user, definition.app, "editor")
    require_module(definition.app, "workflow")
    if definition.status != "published":
        raise ValidationError({"detail": "流程尚未发布"})
    instance = start_instance(
        definition,
        user=request.user,
        title=str(request.data.get("title") or definition.name),
        business_model_id=request.data.get("business_model_id") or None,
        business_record_id=request.data.get("business_record_id") or None,
        data=request.data.get("data") or {},
    )
    return Response(WorkflowInstanceSerializer(instance).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def definition_instance(request, pk: int):
    """按业务记录查最近一次流程实例（审批面板启动/刷新用）。"""
    definition = _definition(pk)
    require_app_role(request.user, definition.app, "viewer")
    qs = WorkflowInstance.objects.filter(definition=definition).select_related("definition", "initiator").prefetch_related("tasks")
    model_id = request.query_params.get("business_model_id")
    record_id = request.query_params.get("business_record_id")
    if model_id:
        qs = qs.filter(business_model_id=model_id)
    if record_id:
        qs = qs.filter(business_record_id=record_id)
    instance = qs.first()
    if instance is None:
        return Response({"instance": None})
    return Response({"instance": WorkflowInstanceSerializer(instance).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def instance_list(request):
    app_id = request.query_params.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(app_id)
    require_app_role(request.user, app, "viewer")
    require_module(app, "workflow")
    qs = WorkflowInstance.objects.filter(app=app).select_related("definition", "initiator").prefetch_related("tasks")
    if request.query_params.get("business_model_id"):
        qs = qs.filter(business_model_id=request.query_params["business_model_id"])
    if request.query_params.get("business_record_id"):
        qs = qs.filter(business_record_id=request.query_params["business_record_id"])
    if request.query_params.get("status"):
        qs = qs.filter(status=request.query_params["status"])
    return Response(WorkflowInstanceSerializer(qs[:200], many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def instance_detail(request, pk: int):
    instance = _instance(pk)
    require_app_role(request.user, instance.app, "viewer")
    return Response(WorkflowInstanceSerializer(instance).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def instance_action(request, pk: int):
    instance = _instance(pk)
    require_app_role(request.user, instance.app, "viewer")
    action = request.data.get("action")
    if action not in ("approve", "reject"):
        raise ValidationError({"detail": "action 必须是 approve/reject"})
    try:
        act_instance(
            instance, user=request.user, action=action,
            comment=str(request.data.get("comment") or ""),
            rollback_to=request.data.get("rollback_to") or None,
        )
    except PermissionError as exc:
        raise PermissionDenied(str(exc))
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    instance = _instance(pk)
    return Response(WorkflowInstanceSerializer(instance).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def instance_withdraw(request, pk: int):
    instance = _instance(pk)
    require_app_role(request.user, instance.app, "viewer")
    try:
        withdraw_instance(instance, user=request.user)
    except PermissionError as exc:
        raise PermissionDenied(str(exc))
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    return Response(WorkflowInstanceSerializer(_instance(pk)).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_transfer(request, pk: int):
    task = get_object_or_404(WorkflowTask.objects.select_related("instance", "instance__app"), pk=pk)
    assignee_id = request.data.get("assignee_user_id") or None
    role = str(request.data.get("assignee_role") or "")
    if not assignee_id and not role:
        raise ValidationError({"detail": "assignee_user_id 或 assignee_role 必填"})
    try:
        transfer_task(task, user=request.user, assignee_user_id=assignee_id, assignee_role=role)
    except PermissionError as exc:
        raise PermissionDenied(str(exc))
    return Response(WorkflowTaskSerializer(task.instance.tasks.all(), many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_add_sign(request, pk: int):
    task = get_object_or_404(WorkflowTask.objects.select_related("instance", "instance__app"), pk=pk)
    assignee_id = request.data.get("assignee_user_id") or None
    role = str(request.data.get("assignee_role") or "")
    if not assignee_id and not role:
        raise ValidationError({"detail": "assignee_user_id 或 assignee_role 必填"})
    try:
        add_sign(task, user=request.user, assignee_user_id=assignee_id, assignee_role=role)
    except PermissionError as exc:
        raise PermissionDenied(str(exc))
    return Response(WorkflowTaskSerializer(task.instance.tasks.all(), many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_remind(request, pk: int):
    task = get_object_or_404(WorkflowTask.objects.select_related("instance", "instance__app"), pk=pk)
    try:
        task = remind_task(task, user=request.user)
    except PermissionError as exc:
        raise PermissionDenied(str(exc))
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    return Response(WorkflowTaskSerializer(task).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_list(request):
    app_id = request.query_params.get("app_id")
    if app_id:
        app = get_app(int(app_id))
        require_module(app, "workflow")
    qs = pending_tasks_for(request.user, int(app_id) if app_id else None)
    return Response(WorkflowTaskSerializer(qs[:300], many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_action(request, pk: int):
    task = get_object_or_404(WorkflowTask.objects.select_related("instance", "instance__app"), pk=pk)
    require_module(task.instance.app, "workflow")
    action = request.data.get("action")
    if action not in ("approve", "reject"):
        raise ValidationError({"detail": "action 必须是 approve/reject"})
    try:
        act_task(
            task, user=request.user, action=action,
            comment=str(request.data.get("comment") or ""),
            rollback_to=request.data.get("rollback_to") or None,
        )
    except PermissionError as exc:
        raise PermissionDenied(str(exc))
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    instance = _instance(task.instance_id)
    return Response(WorkflowInstanceSerializer(instance).data)
