"""审计日志查询端点。"""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from audit.models import AuditLog
from wp_utils import get_app, is_platform_admin_full, paginate_items


def _serialize(log: AuditLog) -> dict:
    return {
        "id": log.id,
        "user_id": log.user_id,
        "username": log.username,
        "app_id": log.app_id,
        "object_type": log.object_type,
        "object_id": log.object_id,
        "action": log.action,
        "before": log.before,
        "after": log.after,
        "ip": log.ip,
        "created_at": log.created_at,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def audit_list(request):
    """GET /api/audit/（= /api/audit-logs/）?app_id=&action=&user=&object_type=&start=&end=

    平台管理员可查全部；应用成员只能查所在应用的日志；无 app 过滤时非管理员仅见自己的操作。
    """
    qs = AuditLog.objects.select_related("user", "app").all()
    app_param = request.query_params.get("app_id") or request.query_params.get("app")
    if app_param:
        try:
            app = get_app(int(app_param))
        except (ValueError, TypeError):
            raise ValidationError({"detail": "app_id 必须是数字 id"})
        if not is_platform_admin_full(request.user):
            from core.permissions import get_app_role

            if get_app_role(request.user, app) is None:
                raise PermissionDenied("仅平台管理员或应用成员可查该应用审计")
        qs = qs.filter(app=app)
    else:
        if not is_platform_admin_full(request.user):
            # 无 app 过滤时仅允许查自己的操作
            qs = qs.filter(user=request.user)
    action = request.query_params.get("action")
    if action:
        qs = qs.filter(action=action)
    user_id_param = request.query_params.get("user_id")
    if user_id_param:
        qs = qs.filter(user_id=user_id_param)
    user = request.query_params.get("user") or request.query_params.get("username")
    if user:
        qs = qs.filter(username__icontains=user)
    object_type = request.query_params.get("object_type")
    if object_type:
        qs = qs.filter(object_type=object_type)
    object_id = request.query_params.get("object_id")
    if object_id:
        qs = qs.filter(object_id=object_id)
    start = request.query_params.get("start")
    if start:
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(start)
        if parsed is None:
            raise ValidationError({"detail": "start 格式应为 ISO 8601 或 YYYY-MM-DD"})
        qs = qs.filter(created_at__gte=parsed)
    end = request.query_params.get("end")
    if end:
        import re

        from datetime import datetime, time as dtime

        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(end)
        if parsed is None:
            raise ValidationError({"detail": "end 格式应为 ISO 8601 或 YYYY-MM-DD"})
        # 纯日期视为当天末尾
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end.strip()):
            parsed = datetime.combine(parsed.date(), dtime(23, 59, 59, 999999))
        qs = qs.filter(created_at__lte=parsed)
    return paginate_items(request, qs, lambda item: _serialize(item))
