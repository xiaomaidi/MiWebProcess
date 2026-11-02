"""RBAC 权限工具。

角色层级：viewer < editor < owner；平台管理员（is_superuser）恒通过。
- require_role(request_or_user, app, min_role)：不满足则 PermissionDenied。
- get_app_role(user, app)：用户在应用内的角色，或 None。
"""
from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

ROLE_ORDER = {"viewer": 1, "editor": 2, "owner": 3}

ROLES = ("viewer", "editor", "owner")


def is_platform_admin(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and bool(getattr(user, "is_superuser", False))


def get_app_role(user, app) -> str | None:
    """应用角色：显式成员优先；其次应用归属部门（含子部门）成员获得 viewer。

    部门可见性是「组织/部门层级权限」的入口：应用开启 ``department_visible`` 后，
    部门负责人可查看整棵子树的应用，普通成员只看本部门。
    """
    if app is None:
        return None
    if is_platform_admin(user):
        return "owner"
    member = getattr(app, "members", None)
    if member is not None:
        m = member.filter(user=user).first()
        if m is not None:
            return m.role
    dept_id = getattr(app, "department_id", None)
    if dept_id and getattr(app, "department_visible", False):
        cache = getattr(user, "_wp_dept_role_cache", None)
        if cache is None:
            cache = {}
            try:
                user._wp_dept_role_cache = cache
            except Exception:
                pass
        if not cache:
            try:
                from org.services import visible_department_ids

                cache["ids"] = visible_department_ids(user)
            except Exception:
                cache["ids"] = set()
        if dept_id in cache.get("ids", set()):
            return "viewer"
    return None


def require_role(user, app, min_role: str = "viewer"):
    if app is None:
        raise PermissionDenied("应用不存在")
    if is_platform_admin(user):
        return
    role = get_app_role(user, app)
    if role is None or ROLE_ORDER[role] < ROLE_ORDER[min_role]:
        raise PermissionDenied("没有该应用的编辑权限")


def check_role_ok(user, app, min_role: str) -> bool:
    if app is None:
        return False
    if is_platform_admin(user):
        return True
    role = get_app_role(user, app)
    return role is not None and ROLE_ORDER[role] >= ROLE_ORDER[min_role]
