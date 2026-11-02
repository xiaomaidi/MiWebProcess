"""安全设置界面 API（平台管理员）。"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import SecuritySetting
from core.security import clear_security_cache, get_security_config
from wp_utils import is_platform_admin_full, validate_outbound_url


def _require_admin(request):
    if not is_platform_admin_full(request.user):
        raise PermissionDenied("需要平台管理员权限")


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def security_settings(request):
    """GET/PUT /api/security/settings/ — SSRF 白名单与私网开关。"""
    _require_admin(request)
    if request.method == "GET":
        config = get_security_config()
        return Response({
            **config,
            "env_defaults": {
                "ssrf_allowed_hosts": list(getattr(settings, "SSRF_ALLOWED_HOSTS", []) or []),
                "ssrf_allow_private": bool(getattr(settings, "SSRF_ALLOW_PRIVATE", False)),
            },
        })
    hosts = request.data.get("ssrf_allowed_hosts")
    if isinstance(hosts, str):
        hosts = [item.strip() for item in hosts.replace("\n", ",").split(",") if item.strip()]
    if not isinstance(hosts, list):
        raise ValidationError({"detail": "ssrf_allowed_hosts 必须是数组或逗号分隔字符串"})
    cleaned = []
    for item in hosts:
        host = str(item or "").strip().lower().lstrip(".")
        if not host:
            continue
        if any(ch in host for ch in ("/", ":", " ")):
            raise ValidationError({"detail": f"主机名不合法（只写主机名，不要带协议/端口）：{item}"})
        cleaned.append(host)
    allow_private = bool(request.data.get("ssrf_allow_private", False))
    row = SecuritySetting.objects.order_by("id").first() or SecuritySetting()
    row.ssrf_allowed_hosts = cleaned
    row.ssrf_allow_private = allow_private
    row.updated_by = request.user
    try:
        row.save()
    except DjangoValidationError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    clear_security_cache()
    return Response(get_security_config())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def security_test_url(request):
    """POST /api/security/test-url/ {url} — 用当前规则测试出站地址。"""
    _require_admin(request)
    url = str(request.data.get("url") or "").strip()
    if not url:
        raise ValidationError({"detail": "url 必填"})
    try:
        validate_outbound_url(url)
    except Exception as exc:  # noqa: BLE001
        message = getattr(exc, "detail", None) or str(exc)
        return Response({"allowed": False, "detail": message})
    return Response({"allowed": True, "detail": "允许访问"})
