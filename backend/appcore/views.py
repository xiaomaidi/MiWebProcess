"""应用 / 成员 REST 端点。"""
from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from appcore.models import App, AppMember
from appcore.serializers import AppMemberSerializer, AppSerializer
from core.audit import snapshot_instance, write_audit_log
from wp_utils import get_app, is_platform_admin_full, paginate_items, require_app_role

CODE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,63}$")


def _audit(request, action: str, object_type: str, before=None, after=None, app_id=None, object_id=None):
    write_audit_log(
        user=request.user,
        action=action,
        object_type=object_type,
        object_id=object_id,
        app_id=app_id,
        before=before,
        after=after,
        request=request,
    )


def _department_id(value):
    """应用归属部门：空值 → None；否则必须是存在的部门。"""
    if value in (None, "", 0, "0"):
        return None
    from org.models import Department

    return get_object_or_404(Department, pk=value).id


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_list(request):
    """GET /api/apps/  ?scope=owned|member|all  ?search=  ?status=

    默认 scope=owned（owner=me）；scope=all 仅平台管理员。
    """
    if request.method == "GET":
        qs = App.objects.all().select_related("owner")
        scope = request.query_params.get("scope", "owned")
        if scope == "all":
            if not is_platform_admin_full(request.user):
                raise PermissionDenied("仅平台管理员可查看全部应用")
        elif scope == "member":
            from org.services import visible_department_ids

            dept_ids = visible_department_ids(request.user)
            qs = qs.filter(
                Q(members__user=request.user)
                | Q(department_id__in=dept_ids, department_visible=True)
            ).distinct()
        else:
            qs = qs.filter(owner=request.user)
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        return paginate_items(request, qs.order_by("-created_at"), AppSerializer)

    # POST 创建应用
    name = (request.data.get("name") or "").strip()
    code = (request.data.get("code") or "").strip()
    description = (request.data.get("description") or "").strip()
    if not name:
        raise ValidationError({"detail": "name 必填"})
    if not CODE_RE.match(code):
        raise ValidationError({"detail": "code 需 2-64 位，字母开头，仅允许字母/数字/_/-"})
    if App.objects.filter(code=code).exists():
        raise ValidationError({"detail": f"code {code} 已存在"})
    with transaction.atomic():
        app = App.objects.create(
            name=name, code=code, description=description, owner=request.user, status="draft",
            department_id=_department_id(request.data.get("department_id")),
            department_visible=bool(request.data.get("department_visible", False)),
        )
        AppMember.objects.create(app=app, user=request.user, role="owner")
    _audit(request, "app.create", "app", after=snapshot_instance(app), app_id=app.id, object_id=app.id)
    return Response(AppSerializer(app).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def app_detail(request, app_id):
    app = get_app(app_id)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        return Response(AppSerializer(app).data)
    role = require_app_role(request.user, app, "owner")
    before = snapshot_instance(app)
    if request.method == "DELETE":
        app.delete()
        _audit(request, "app.delete", "app", before=before, app_id=None, object_id=app_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    name = request.data.get("name")
    description = request.data.get("description")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValidationError({"detail": "name 不能为空"})
        app.name = name
    if description is not None:
        app.description = str(description)
    if "department_id" in request.data:
        app.department_id = _department_id(request.data.get("department_id"))
    if "department_visible" in request.data:
        app.department_visible = bool(request.data.get("department_visible"))
    if "design_tokens" in request.data:
        tokens = request.data.get("design_tokens")
        if not isinstance(tokens, dict):
            raise ValidationError({"detail": "design_tokens 必须是对象"})
        previous = app.design_tokens or {}
        if previous and previous != tokens:
            history = list(app.design_tokens_history or [])
            history.insert(0, {
                "tokens": previous,
                "saved_at": timezone.now().isoformat(),
                "username": request.user.username,
            })
            app.design_tokens_history = history[:20]
        app.design_tokens = tokens
    app.save()
    _audit(request, "app.update", "app", before=before, after=snapshot_instance(app), app_id=app_id, object_id=app.id)
    return Response(AppSerializer(app).data)


def _trigger_release(app: App, changelog: str, trigger: str):
    """触发应用级发布（celery 不可用时同步内联）。"""
    from releases.services import schedule_release_for_app

    schedule_release_for_app(app, changelog=changelog, trigger=trigger)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_design_token_versions(request, app_id):
    """GET 版本列表；POST {index} 或 {tokens} 回滚应用级 Token。"""
    app = get_app(app_id)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        return Response({
            "tokens": app.design_tokens or {},
            "history": app.design_tokens_history or [],
        })
    require_app_role(request.user, app, "owner")
    history = list(app.design_tokens_history or [])
    target = request.data.get("tokens")
    if target is None and "index" in request.data:
        try:
            index = int(request.data.get("index"))
        except (TypeError, ValueError):
            raise ValidationError({"detail": "index 不正确"})
        if index < 0 or index >= len(history):
            raise ValidationError({"detail": "版本不存在"})
        target = history[index].get("tokens") or {}
    if not isinstance(target, dict):
        raise ValidationError({"detail": "tokens 必须是对象"})
    previous = app.design_tokens or {}
    if previous and previous != target:
        history.insert(0, {
            "tokens": previous,
            "saved_at": timezone.now().isoformat(),
            "username": request.user.username,
        })
    app.design_tokens_history = history[:20]
    app.design_tokens = target
    app.save(update_fields=["design_tokens", "design_tokens_history", "updated_at"])
    _audit(request, "app.design_tokens.rollback", "app", after=snapshot_instance(app), app_id=app.id, object_id=app.id)
    return Response({"tokens": app.design_tokens, "history": app.design_tokens_history})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def app_publish(request, app_id):
    """POST /api/apps/{app_id}/publish/  owner"""
    app = get_app(app_id)
    require_app_role(request.user, app, "owner")
    before = snapshot_instance(app)
    app.status = "published"
    app.save(update_fields=["status", "updated_at"])
    _audit(request, "app.publish", "app", before=before, after=snapshot_instance(app), app_id=app_id, object_id=app.id)
    _trigger_release(app, request.data.get("changelog") or "publish app", "app_publish")
    return Response(AppSerializer(app).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def app_archive(request, app_id):
    """POST /api/apps/{app_id}/archive/  owner"""
    app = get_app(app_id)
    require_app_role(request.user, app, "owner")
    before = snapshot_instance(app)
    app.status = "archived"
    app.save(update_fields=["status", "updated_at"])
    _audit(request, "app.archive", "app", before=before, after=snapshot_instance(app), app_id=app_id, object_id=app.id)
    return Response(AppSerializer(app).data)


def _resolve_member_user(request, data: dict) -> User:
    user_id = data.get("user_id") or data.get("user")
    username = data.get("username")
    user = None
    if user_id:
        user = get_object_or_404(User, id=user_id)
    elif username:
        user = get_object_or_404(User, username=username)
    else:
        raise ValidationError({"detail": "需要 user_id 或 username"})
    return user


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def member_list_create(request, app_id):
    """GET/POST /api/apps/{app_id}/members/"""
    app = get_app(app_id)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        return paginate_items(request, app.members.all().select_related("user"), AppMemberSerializer)
    # POST
    require_app_role(request.user, app, "owner")
    user = _resolve_member_user(request, request.data)
    role = request.data.get("role", "viewer")
    if role not in dict(AppMember.ROLE_CHOICES):
        raise ValidationError({"detail": f"role 必须是 {dict(AppMember.ROLE_CHOICES).keys()}"})
    if app.members.filter(user=user).exists():
        raise ValidationError({"detail": "该用户已是成员，请用 PUT 修改角色"})
    member = AppMember.objects.create(app=app, user=user, role=role)
    _audit(
        request,
        "member.add",
        "app_member",
        after=snapshot_instance(member),
        app_id=app.id,
        object_id=member.id,
    )
    return Response(AppMemberSerializer(member).data, status=status.HTTP_201_CREATED)


@api_view(["PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def member_update_delete(request, app_id, user_id):
    """PUT/PATCH/DELETE /api/apps/{app_id}/members/{user_id}/"""
    app = get_app(app_id)
    require_app_role(request.user, app, "owner")
    member = get_object_or_404(AppMember, app=app, user_id=user_id)
    if request.method == "DELETE":
        if member.user_id == app.owner_id:
            raise ValidationError({"detail": "不能移除应用所有者的成员身份"})
        before = snapshot_instance(member)
        member.delete()
        _audit(request, "member.remove", "app_member", before=before, app_id=app.id, object_id=member.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    role = request.data.get("role")
    if role not in dict(AppMember.ROLE_CHOICES):
        raise ValidationError({"detail": f"role 必须是 {dict(AppMember.ROLE_CHOICES).keys()}"})
    if member.user_id == app.owner_id and role != "owner":
        raise ValidationError({"detail": "不能降级应用所有者的角色"})
    before = snapshot_instance(member)
    member.role = role
    member.save(update_fields=["role"])
    _audit(request, "member.update", "app_member", before=before, after=snapshot_instance(member), app_id=app.id, object_id=member.id)
    return Response(AppMemberSerializer(member).data)
