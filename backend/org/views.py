"""组织架构 REST 端点。"""
from __future__ import annotations

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from core.audit import write_audit_log
from org.models import Department, DepartmentMember
from org.services import (
    add_member,
    can_manage_department,
    create_department,
    delete_department,
    department_payload,
    department_scope,
    managed_department_ids,
    member_payload,
    move_department,
    subtree_ids,
    visible_department_ids,
)
from wp_utils import is_platform_admin_full, paginate_items


def _audit(request, action: str, before=None, after=None, object_id=None):
    write_audit_log(
        user=request.user, action=action, object_type="department",
        object_id=object_id, before=before, after=after, request=request,
    )


def _require_manage(request, department: Department | None):
    if not can_manage_department(request.user, department):
        raise PermissionDenied("需要该部门或其上级部门的负责人权限")


def _department_qs():
    return Department.objects.select_related("parent", "leader").annotate(member_count=Count("members"))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def department_list_create(request):
    """GET/POST /api/org/departments/"""
    if request.method == "GET":
        qs = _department_qs()
        q = str(request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
        if request.query_params.get("include_inactive") not in ("1", "true", "yes"):
            qs = qs.filter(is_active=True)
        parent = request.query_params.get("parent_id")
        if parent not in (None, ""):
            if str(parent) == "root":
                qs = qs.filter(parent__isnull=True)
            else:
                qs = qs.filter(parent_id=int(parent))
        return paginate_items(request, qs.order_by("path"), department_payload)

    parent = None
    parent_id = request.data.get("parent_id")
    if parent_id not in (None, "", 0, "0"):
        parent = get_object_or_404(Department, pk=parent_id)
        _require_manage(request, parent)
    elif not is_platform_admin_full(request.user):
        raise PermissionDenied("仅平台管理员可创建根部门")

    leader = None
    leader_id = request.data.get("leader_id")
    if leader_id:
        leader = get_object_or_404(User, pk=leader_id)
    department = create_department(
        name=request.data.get("name") or "",
        parent=parent,
        code=request.data.get("code") or "",
        leader=leader,
        sort=request.data.get("sort") or 0,
        description=request.data.get("description") or "",
    )
    _audit(request, "department.create", after=department_payload(department), object_id=department.id)
    return Response(department_payload(department), status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def department_detail(request, pk: int):
    """GET/PUT/PATCH/DELETE /api/org/departments/{id}/"""
    department = get_object_or_404(_department_qs(), pk=pk)
    if request.method == "GET":
        return Response(department_payload(department))

    _require_manage(request, department)
    before = department_payload(department)
    if request.method == "DELETE":
        delete_department(department)
        _audit(request, "department.delete", before=before, object_id=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    if "name" in request.data:
        name = str(request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"detail": "部门名称不能为空"})
        department.name = name[:120]
    if "code" in request.data:
        code = str(request.data.get("code") or "").strip()[:64]
        if code and Department.objects.filter(code=code).exclude(id=department.id).exists():
            raise ValidationError({"detail": f"部门编码 {code} 已存在"})
        department.code = code
    if "sort" in request.data:
        try:
            department.sort = int(request.data.get("sort") or 0)
        except (TypeError, ValueError):
            raise ValidationError({"detail": "sort 必须是整数"})
    if "leader_id" in request.data:
        leader_id = request.data.get("leader_id")
        department.leader = get_object_or_404(User, pk=leader_id) if leader_id else None
    if "description" in request.data:
        department.description = str(request.data.get("description") or "")[:500]
    if "is_active" in request.data:
        department.is_active = bool(request.data.get("is_active"))
    department.save()
    after = department_payload(department)
    _audit(request, "department.update", before=before, after=after, object_id=pk)
    return Response(after)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def department_move(request, pk: int):
    """POST /api/org/departments/{id}/move/ {parent_id}"""
    department = get_object_or_404(_department_qs(), pk=pk)
    _require_manage(request, department)
    parent = None
    parent_id = request.data.get("parent_id")
    if parent_id not in (None, "", 0, "0"):
        parent = get_object_or_404(Department, pk=parent_id)
        if not can_manage_department(request.user, parent):
            raise PermissionDenied("需要目标部门或其上级部门的负责人权限")
    elif not is_platform_admin_full(request.user):
        raise PermissionDenied("仅平台管理员可移动到根")
    before = department_payload(department)
    move_department(department, parent)
    after = department_payload(department)
    _audit(request, "department.move", before=before, after=after, object_id=pk)
    return Response(after)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def department_members(request, pk: int):
    """GET/POST /api/org/departments/{id}/members/"""
    department = get_object_or_404(Department, pk=pk)
    if request.method == "GET":
        qs = department.members.select_related("user").order_by("role", "id")
        return paginate_items(request, qs, member_payload)

    _require_manage(request, department)
    user_id = request.data.get("user_id")
    username = request.data.get("username")
    if user_id:
        user = get_object_or_404(User, pk=user_id)
    elif username:
        user = get_object_or_404(User, username=username)
    else:
        raise ValidationError({"detail": "需要 user_id 或 username"})
    member = add_member(
        department, user,
        role=request.data.get("role") or "member",
        title=request.data.get("title") or "",
    )
    if member.role == "leader":
        department.leader = user
        department.save(update_fields=["leader", "updated_at"])
    _audit(request, "department.member.add", after=member_payload(member), object_id=department.id)
    return Response(member_payload(member), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def department_member_detail(request, pk: int, user_id: int):
    """PATCH/DELETE /api/org/departments/{id}/members/{user_id}/"""
    department = get_object_or_404(Department, pk=pk)
    _require_manage(request, department)
    member = get_object_or_404(DepartmentMember, department=department, user_id=user_id)
    if request.method == "DELETE":
        was_leader = member.role == "leader"
        member.delete()
        if was_leader and department.leader_id == user_id:
            department.leader = None
            department.save(update_fields=["leader", "updated_at"])
        _audit(request, "department.member.remove", object_id=department.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    role = request.data.get("role")
    if role not in dict(DepartmentMember.ROLE_CHOICES):
        raise ValidationError({"detail": "role 必须是 leader/member"})
    member.role = role
    if "title" in request.data:
        member.title = str(request.data.get("title") or "")[:80]
    member.save(update_fields=["role", "title"])
    if role == "leader":
        department.leader = member.user
        department.save(update_fields=["leader", "updated_at"])
    return Response(member_payload(member))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def department_tree(request):
    """GET /api/org/tree/ — 扁平节点 + parent_id，前端自行组树。"""
    qs = _department_qs().filter(is_active=True).order_by("path")
    nodes = [department_payload(d) for d in qs]
    return Response({"count": len(nodes), "nodes": nodes})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def department_me(request):
    """GET /api/org/me/ — 我的部门 / 可见部门 / 可管理部门。"""
    visible = visible_department_ids(request.user)
    managed = managed_department_ids(request.user)
    direct = list(
        DepartmentMember.objects.filter(user=request.user)
        .select_related("department")
        .order_by("role", "id")
    )
    depts = {
        d.id: department_payload(d)
        for d in Department.objects.filter(id__in=visible).select_related("leader", "parent")
    }
    scope = department_scope(request.user)
    return Response({
        "user_id": request.user.id,
        "departments": [
            {**member_payload(m), "department_name": m.department.name if m.department_id else ""}
            for m in direct
        ],
        "visible_department_ids": sorted(visible),
        "managed_department_ids": sorted(managed),
        "visible_departments": [depts[i] for i in sorted(depts)],
        "tokens": sorted(scope.tokens),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_directory(request):
    """GET /api/org/users/?q= — 成员选择器（负责人/平台管理员可用）。"""
    is_admin = is_platform_admin_full(request.user)
    is_leader = bool(managed_department_ids(request.user))
    if not (is_admin or is_leader):
        raise PermissionDenied("需要部门负责人或平台管理员权限")
    qs = User.objects.filter(is_active=True).order_by("username")
    q = str(request.query_params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    rows = [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.get_full_name() or u.username,
            "email": u.email,
            "is_platform_admin": bool(u.is_superuser or u.is_platform_admin),
        }
        for u in qs[:50]
    ]
    return Response({"count": len(rows), "results": rows})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def department_bulk_members(request, pk: int):
    """POST /api/org/departments/{id}/members/bulk/ {user_ids: [], role}"""
    department = get_object_or_404(Department, pk=pk)
    _require_manage(request, department)
    ids = request.data.get("user_ids")
    if not isinstance(ids, list) or not ids:
        raise ValidationError({"detail": "user_ids 必须是非空数组"})
    role = request.data.get("role") or "member"
    added = []
    for user in User.objects.filter(id__in=ids):
        added.append(member_payload(add_member(department, user, role=role)))
    _audit(request, "department.member.bulk", after={"ids": ids, "role": role}, object_id=department.id)
    return Response({"added": added})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def department_subtree(request, pk: int):
    """GET /api/org/departments/{id}/subtree/ — 供数据范围预览。"""
    department = get_object_or_404(Department, pk=pk)
    ids = subtree_ids(department)
    rows = _department_qs().filter(id__in=ids).order_by("path")
    return Response({"ids": sorted(ids), "nodes": [department_payload(d) for d in rows]})
