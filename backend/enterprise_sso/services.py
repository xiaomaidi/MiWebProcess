"""SSO 登录的业务编排：账号关联 / 自动建号 / 应用成员 / 平台 JWT / 登录审计。

账号关联策略（防接管）：
- 只按 **邮箱**（大小写不敏感）关联既有账号，绝不按用户名关联；
- 邮箱域名白名单优先校验；``email_verified == false`` 直接拒绝；
- 未命中且 ``auto_create_user`` 关闭时拒绝登录，绝不隐式创建。
"""
from __future__ import annotations

import ipaddress
import logging
import re
import secrets

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from appcore.models import AppMember
from enterprise_sso.oidc import SsoFlowError, map_claims
from enterprise_sso.validators import email_domain_allowed

logger = logging.getLogger("enterprise_sso")

_USERNAME_SAFE = re.compile(r"[^a-zA-Z0-9._@+-]+")


def _normalize_username(hint: str) -> str:
    base = _USERNAME_SAFE.sub("-", str(hint or "").strip()).strip("-._")
    base = base[:120]
    return base or "sso-user"


def unique_username(hint: str) -> str:
    User = get_user_model()
    base = _normalize_username(hint)
    candidate = base
    for _ in range(5):
        if not User.objects.filter(username__iexact=candidate).exists():
            return candidate
        candidate = f"{base}-{secrets.token_hex(2)}"
    return f"{base}-{secrets.token_hex(6)}"


def resolve_user(provider, claims: dict) -> tuple[object, bool]:
    """userinfo 声明 → 平台用户；返回 (user, created)。"""
    data = map_claims(claims)
    email = data["email"]
    domains = list(provider.allowed_email_domains or [])

    if domains and email and not email_domain_allowed(email, domains):
        raise SsoFlowError("email_domain_not_allowed", http_status=403)
    if not email:
        raise SsoFlowError("email_missing", http_status=403)
    if data["email_verified"] is False:
        raise SsoFlowError("email_unverified", http_status=403)

    User = get_user_model()
    user = User.objects.filter(email__iexact=email).order_by("id").first()
    created = False
    if user is None:
        if not provider.auto_create_user:
            raise SsoFlowError("account_not_found", http_status=403)
        first_name, _, last_name = data["name"].partition(" ")
        if not first_name:
            first_name = data["given_name"]
        if not last_name:
            last_name = data["family_name"]
        with transaction.atomic():
            user = User.objects.create_user(
                username=unique_username(data["username_hint"] or email),
                email=email,
                password=None,  # create_user → set_unusable_password()
                first_name=str(first_name or "")[:150],
                last_name=str(last_name or "")[:150],
            )
        created = True

    if not user.is_active:
        raise SsoFlowError("account_disabled", http_status=403)
    return user, created


def ensure_member(app, provider, user):
    """保证 AppMember 存在（默认角色来自 provider.default_role）；不降级既有角色。"""
    role = provider.default_role if provider.default_role in ("viewer", "editor") else "viewer"
    member, created = AppMember.objects.get_or_create(
        app=app,
        user=user,
        defaults={"role": role},
    )
    return member, created


def issue_tokens(user) -> dict:
    """与 accounts 登录一致的 JWT 结构：{"access", "refresh"}。

    注意：响应里不能使用 access_token / refresh_token 作为键名，
    否则会被 core.middleware.SensitiveDataMiddleware 脱敏成 "***"。
    """
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def access_token_expires_in() -> int:
    from django.conf import settings

    lifetime = getattr(settings, "SIMPLE_JWT", {}).get("ACCESS_TOKEN_LIFETIME")
    try:
        return int(lifetime.total_seconds())
    except Exception:
        return 0


def _client_ip(request) -> str | None:
    raw = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    raw = raw or (request.META.get("REMOTE_ADDR") or "")
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def record_login(request, *, app, provider, user, created_user: bool, created_member: bool) -> None:
    """写平台登录日志（复用 accounts.LoginLog，仅新增记录，不修改 accounts 模型）。"""
    try:
        from accounts.models import LoginLog

        LoginLog.objects.create(
            user=user,
            username=str(user.username)[:150],
            success=True,
            reason=f"sso:{provider.slug}:{'create' if created_user else 'login'}"[:200],
            ip=_client_ip(request),
            user_agent=str(request.META.get("HTTP_USER_AGENT") or "")[:500],
        )
    except Exception:
        logger.debug("sso.login_log_failed app=%s provider=%s", getattr(app, "id", None), provider.slug)


def safe_provider_snapshot(provider) -> dict:
    """审计快照：显式白名单字段，永不含 client_secret 明文/密文。"""
    return {
        "id": provider.pk,
        "name": provider.name,
        "slug": provider.slug,
        "protocol": provider.protocol,
        "enabled": provider.enabled,
        "issuer": provider.issuer,
        "client_id": provider.client_id,
        "has_client_secret": bool(provider.client_secret),
        "authorization_endpoint": provider.authorization_endpoint,
        "token_endpoint": provider.token_endpoint,
        "userinfo_endpoint": provider.userinfo_endpoint,
        "scopes": provider.scopes,
        "auto_create_user": provider.auto_create_user,
        "default_role": provider.default_role,
        "allowed_email_domains": list(provider.allowed_email_domains or []),
        "updated_at": timezone.now().isoformat(timespec="seconds"),
    }
