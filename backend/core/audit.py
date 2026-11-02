"""审计日志写入与 ViewSet 混入。

用法（在 ViewSet 中）：
    class PageViewSet(AuditViewSetMixin, ModelViewSet):
        audit_type = "page"
        app_id_attr = "app_id"
        # 覆盖 perform_create/perform_update/perform_destroy 自动记录前后快照
"""
from __future__ import annotations

import json
from typing import Any

from .expr import json_safe


def client_ip(request) -> str:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def snapshot_instance(obj, fields: list[str] | None = None) -> dict[str, Any] | None:
    """模型实例 → 可 JSON 化的前后快照（None 表示对象不存在）。"""
    if obj is None:
        return None
    from django.db import models as dj_models

    if fields is None:
        fields = [f.name for f in obj._meta.fields if not isinstance(f, dj_models.FileField)]
    out: dict[str, Any] = {}
    for name in fields:
        try:
            v = getattr(obj, name)
        except Exception:
            continue
        if callable(v):
            continue
        out[name] = json_safe(v)
    return out


def write_audit_log(
    *,
    user,
    action: str,
    object_type: str,
    object_id: Any = None,
    app_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
    request=None,
) -> None:
    """写入审计日志（延迟导入避免循环依赖；无 user 时跳过）。"""
    if user is None or not getattr(user, "is_authenticated", False):
        return
    try:
        from audit.models import AuditLog

        AuditLog.objects.create(
            user_id=user.id,
            username=getattr(user, "username", ""),
            app_id=app_id,
            object_type=object_type,
            object_id=object_id,
            action=action,
            before=json_safe(before) if before is not None else None,
            after=json_safe(after) if after is not None else None,
            ip=client_ip(request) if request is not None else "",
        )
    except Exception:
        # 审计失败不阻塞业务
        import logging

        logging.getLogger("audit").exception("write_audit_log failed")


class AuditViewSetMixin:
    """为 ViewSet 提供 create/update/destroy 审计钩子。

    属性：
    - audit_type: 对象类型名（如 "page"）。
    - app_id_attr: 对象上取 app_id 的属性名（默认 "app_id"）。
    """

    audit_type: str = "object"
    app_id_attr: str = "app_id"

    def _resolve_app_id(self, obj=None) -> Any:
        if obj is not None:
            v = getattr(obj, self.app_id_attr, None)
            if v is not None:
                return v
        app = getattr(self, "app", None)
        if app is not None:
            return getattr(app, "id", app)
        return None

    def _audit(self, action: str, before: dict | None, after: dict | None, obj=None, object_id: Any = None):
        write_audit_log(
            user=getattr(self.request, "user", None),
            action=action,
            object_type=self.audit_type,
            object_id=object_id if object_id is not None else getattr(obj, "pk", None),
            app_id=self._resolve_app_id(obj),
            before=before,
            after=after,
            request=getattr(self, "request", None),
        )

    def perform_create(self, serializer):
        serializer.save()
        self._audit("create", None, snapshot_instance(serializer.instance), serializer.instance)

    def perform_update(self, serializer):
        before = snapshot_instance(serializer.instance)
        serializer.save()
        self._audit("update", before, snapshot_instance(serializer.instance), serializer.instance)

    def perform_destroy(self, serializer):
        obj = serializer.instance
        before = snapshot_instance(obj)
        obj_id = obj.pk
        obj.delete()
        self._audit("delete", before, None, object_id=obj_id)
