"""组织架构服务：树维护、可见范围、部门数据权限。"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from rest_framework.exceptions import ValidationError

from org.models import Department, DepartmentMember


# ---------------------------------------------------------------- 树与可见范围

def subtree_ids(department: Department | int) -> set[int]:
    """部门及其所有后代 id（基于物化路径，一次查询）。"""
    if isinstance(department, int):
        department = Department.objects.filter(id=department).first()
    if department is None:
        return set()
    prefix = department.path or f"/{department.id}/"
    ids = {department.id}
    ids.update(Department.objects.filter(path__startswith=prefix).values_list("id", flat=True))
    return ids


def ancestor_ids(department: Department) -> list[int]:
    return department.ancestor_ids


def membership_map(user) -> dict[int, str]:
    """{department_id: role} 直接成员关系。"""
    if not getattr(user, "is_authenticated", False):
        return {}
    rows = DepartmentMember.objects.filter(user=user).values_list("department_id", "role")
    return {int(dep_id): role for dep_id, role in rows}


def visible_department_ids(user) -> set[int]:
    """用户可见部门：直接加入的部门；作为负责人时额外包含整棵子树。"""
    mapping = membership_map(user)
    if not mapping:
        return set()
    ids: set[int] = set(mapping)
    leader_ids = [dep_id for dep_id, role in mapping.items() if role == "leader"]
    if leader_ids:
        depts = Department.objects.filter(id__in=leader_ids)
        for dept in depts:
            ids.update(subtree_ids(dept))
    return ids


def managed_department_ids(user) -> set[int]:
    """用户可管理的部门：负责人所在部门 + 子树（平台管理员由调用方特判）。"""
    from wp_utils import is_platform_admin_full

    if is_platform_admin_full(user):
        return set(Department.objects.values_list("id", flat=True))
    mapping = membership_map(user)
    ids: set[int] = set()
    for dep_id, role in mapping.items():
        if role == "leader":
            ids.update(subtree_ids(dep_id))
    return ids


def can_manage_department(user, department: Department | None) -> bool:
    from wp_utils import is_platform_admin_full

    if is_platform_admin_full(user):
        return True
    if department is None:
        return False
    return department.id in managed_department_ids(user)


def primary_department(user) -> Department | None:
    """主部门：优先负责人部门，其次最早加入的部门。"""
    rows = (
        DepartmentMember.objects.filter(user=user)
        .select_related("department")
        .order_by("role", "id")
    )
    for row in rows:
        if row.department and row.department.is_active:
            return row.department
    return None


@dataclass
class DepartmentScope:
    """一次请求内复用的部门范围，避免逐行查询。"""

    user_id: int | None = None
    direct_ids: set[int] = field(default_factory=set)
    visible_ids: set[int] = field(default_factory=set)
    leader_ids: set[int] = field(default_factory=set)
    tokens: set[str] = field(default_factory=set)

    @property
    def empty(self) -> bool:
        return not self.visible_ids

    def matches(self, value) -> bool:
        if value is None or value == "":
            return False
        if isinstance(value, bool):
            return False
        if isinstance(value, (int, float)):
            return int(value) in self.visible_ids
        text = str(value).strip()
        if not text:
            return False
        if text.isdigit():
            return int(text) in self.visible_ids
        return text in self.tokens


def department_scope(user) -> DepartmentScope:
    direct = membership_map(user)
    scope = DepartmentScope(user_id=getattr(user, "id", None), direct_ids=set(direct))
    if not direct:
        return scope
    scope.leader_ids = {dep_id for dep_id, role in direct.items() if role == "leader"}
    visible: set[int] = set(direct)
    if scope.leader_ids:
        for dept in Department.objects.filter(id__in=scope.leader_ids):
            visible.update(subtree_ids(dept))
    scope.visible_ids = visible
    if visible:
        for dept in Department.objects.filter(id__in=visible).only("id", "code", "name"):
            scope.tokens.add(str(dept.id))
            if dept.code:
                scope.tokens.add(dept.code)
            if dept.name:
                scope.tokens.add(dept.name)
    return scope


def record_in_scope(scope: DepartmentScope, data: dict, field_name: str) -> bool:
    if scope.empty:
        return False
    return scope.matches((data or {}).get(field_name))


# ---------------------------------------------------------------- 写操作

def _normalize_code(code: str) -> str:
    return str(code or "").strip()[:64]


def create_department(
    *, name: str, parent: Department | None = None, code: str = "", leader=None,
    sort: int = 0, description: str = "",
) -> Department:
    name = str(name or "").strip()
    if not name:
        raise ValidationError({"detail": "部门名称必填"})
    code = _normalize_code(code)
    if code and Department.objects.filter(code=code).exists():
        raise ValidationError({"detail": f"部门编码 {code} 已存在"})
    if parent is not None and not parent.is_active:
        raise ValidationError({"detail": "父部门已停用"})
    return Department.objects.create(
        name=name,
        code=code,
        parent=parent,
        leader=leader,
        sort=int(sort or 0),
        description=str(description or "")[:500],
    )


def _refresh_subtree_paths(department: Department) -> None:
    """部门移动后重算子孙的 path/level。"""
    prefix = department.path or f"/{department.id}/"
    descendants = list(Department.objects.filter(path__startswith=prefix).exclude(id=department.id))
    for node in descendants:
        node.save()  # save() 会按 parent 重算 path/level


@transaction.atomic
def move_department(department: Department, parent: Department | None) -> Department:
    if parent is not None:
        if parent.id == department.id:
            raise ValidationError({"detail": "不能把部门移动到自身"})
        if department.path and parent.path.startswith(department.path):
            raise ValidationError({"detail": "不能把部门移动到自己的子部门下"})
    department.parent = parent
    department.save()
    _refresh_subtree_paths(department)
    return department


@transaction.atomic
def delete_department(department: Department) -> None:
    """删除部门；子孙部门一并删除，成员关系级联。"""
    department.delete()


def add_member(department: Department, user, role: str = "member", title: str = "") -> DepartmentMember:
    if role not in dict(DepartmentMember.ROLE_CHOICES):
        raise ValidationError({"detail": "role 必须是 leader/member"})
    member, created = DepartmentMember.objects.get_or_create(
        department=department, user=user,
        defaults={"role": role, "title": str(title or "")[:80]},
    )
    if not created:
        member.role = role
        if title:
            member.title = str(title)[:80]
        member.save(update_fields=["role", "title"])
    return member


# ---------------------------------------------------------------- 序列化

def department_payload(department: Department) -> dict:
    return {
        "id": department.id,
        "name": department.name,
        "code": department.code,
        "parent_id": department.parent_id,
        "path": department.path,
        "level": department.level,
        "sort": department.sort,
        "leader_id": department.leader_id,
        "leader_name": department.leader.username if department.leader_id else "",
        "description": department.description,
        "is_active": department.is_active,
        "member_count": getattr(department, "member_count", None),
        "display_path": department.display_path(),
        "created_at": department.created_at,
        "updated_at": department.updated_at,
    }


def member_payload(member: DepartmentMember) -> dict:
    user = member.user
    return {
        "id": member.id,
        "department_id": member.department_id,
        "user_id": user.id,
        "username": user.username,
        "display_name": (user.get_full_name() or user.username),
        "email": user.email,
        "role": member.role,
        "title": member.title,
        "created_at": member.created_at,
    }
