"""企业 SSO API。

配置面（需要应用 editor/owner）：
    GET/POST   /api/apps/{app_id}/sso/providers/
    GET/PATCH/PUT/DELETE  /api/apps/{app_id}/sso/providers/{id}/

公开面（登录页使用，AllowAny + 速率限制）：
    GET /api/auth/sso/{app_code}/providers/
    GET /api/auth/sso/{app_code}/{provider_slug}/start/?redirect=/...
    GET /api/auth/sso/{app_code}/{provider_slug}/callback/?code=&state=

约定：
- 响应 JSON 中的令牌键名固定为 ``access`` / ``refresh``（与 accounts 登录一致），
  避免被 SensitiveDataMiddleware 当作 access_token/refresh_token 脱敏。
- 失败一律返回结构化错误码，或 302 到前端回调页的 #fragment；绝不返回堆栈。
"""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.html import escape
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.serializers import MeSerializer
from appcore.models import App, AppAuthConfig
from core.audit import write_audit_log
from enterprise_sso import oidc, services
from enterprise_sso.models import SsoProvider
from enterprise_sso.serializers import PublicSsoProviderSerializer, SsoProviderSerializer
from wp_utils import is_platform_admin_full, require_app_role

logger = logging.getLogger("enterprise_sso")

_REDIRECT_FALLBACK_SAFE_CHARS = ("\\", "\t", "\n", "\r")


# ---------------------------------------------------------------- 小工具


def _frontend_base() -> str:
    return str(getattr(settings, "FRONTEND_URL", "") or "").strip().rstrip("/")


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or "unknown"


def _rate_limit(request, scope: str, limit: int = 60, window: int = 300) -> None:
    key = f"sso_rl:{scope}:{_client_ip(request)}"
    try:
        count = int(cache.get(key) or 0)
    except Exception:
        return
    if count >= limit:
        raise PermissionDenied("操作过于频繁，请稍后再试")
    try:
        cache.set(key, count + 1, window)
    except Exception:
        pass


def _no_store(response):
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    response["Pragma"] = "no-cache"
    response["Referrer-Policy"] = "no-referrer"
    return response


def _role(user, app, minimum: str = "viewer") -> str:
    if is_platform_admin_full(user):
        return "owner"
    return require_app_role(user, app, minimum)


def _sanitize_redirect(raw, app) -> str:
    """只接受同源相对路径；任何疑似开放重定向的输入都回落到应用首页。"""
    fallback = f"/run/{app.code}"
    text = str(raw or "").strip()
    if not text or len(text) > 500:
        return fallback
    if any(ch in text for ch in _REDIRECT_FALLBACK_SAFE_CHARS):
        return fallback
    if not text.startswith("/") or text.startswith("//"):
        return fallback
    try:
        parsed = urlparse(text)
    except ValueError:
        return fallback
    if parsed.scheme or parsed.netloc:
        return fallback
    if not parsed.path.startswith("/"):
        return fallback
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def _callback_url(request, app_code: str, provider_slug: str) -> str:
    """回调地址：默认按请求 Host 推导；可用 settings.SSO_CALLBACK_BASE_URL 覆盖。"""
    path = reverse("sso_callback", kwargs={"app_code": app_code, "provider_slug": provider_slug})
    base = str(getattr(settings, "SSO_CALLBACK_BASE_URL", "") or "").strip().rstrip("/")
    if base:
        return f"{base}{path}"
    return request.build_absolute_uri(path)


def _fail(request, *, mode: str, code: str, http_status: int = 400, app=None, detail: str = ""):
    message = oidc.SsoFlowError.default_messages.get(code, "登录失败，请稍后再试")
    if mode == "redirect" and app is not None:
        fragment = urlencode(
            {"error": code, "error_description": message, "app_code": app.code}
        )
        return _no_store(HttpResponseRedirect(f"{_frontend_base()}/sso/callback#{fragment}"))
    payload = {"error": code, "error_description": message}
    if detail:
        payload["detail"] = detail
    return _no_store(Response(payload, status=http_status))


def _html_error(request, app_code: str, message: str) -> HttpResponse:
    """无法判定返回方式（例如 state 无效）时的安全错误页：无堆栈、无令牌、可返回登录。"""
    login_url = f"{_frontend_base()}/auth/{app_code}/login" if app_code else f"{_frontend_base()}/login"
    html = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>企业登录失败</title><style>"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b1220;"
        "font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#e2e8f0}"
        ".card{max-width:420px;padding:36px 32px;border-radius:16px;background:#111a2b;"
        "border:1px solid #1e2a44;box-shadow:0 24px 60px rgba(2,6,23,.5);text-align:center}"
        "h1{margin:0 0 12px;font-size:20px}p{margin:0 0 24px;color:#94a3b8;font-size:14px;line-height:1.7}"
        "a{display:inline-block;padding:10px 22px;border-radius:10px;background:#2563eb;color:#fff;"
        "text-decoration:none;font-size:14px}</style></head><body><main class=\"card\">"
        "<h1>企业登录失败</h1><p>{message}</p><a href=\"{url}\">返回登录</a>"
        "</main></body></html>"
    ).format(message=escape(message), url=escape(login_url))
    response = HttpResponse(html, content_type="text/html; charset=utf-8", status=400)
    return _no_store(response)


def _assert_app_login_enabled(app) -> None:
    config = AppAuthConfig.objects.filter(app=app).first()
    if config is not None and not config.enabled:
        raise oidc.SsoFlowError("app_login_disabled", http_status=403)


def _active_provider(app_code: str, provider_slug: str):
    app = get_object_or_404(App, code=app_code)
    provider = get_object_or_404(SsoProvider, app=app, slug=provider_slug)
    _assert_app_login_enabled(app)
    if not provider.enabled or provider.protocol != "oidc":
        raise oidc.SsoFlowError("provider_disabled", http_status=403)
    if not provider.is_usable:
        raise oidc.SsoFlowError("config_invalid")
    return app, provider


def _audit(request, app, action: str, provider, *, before=None, after=None) -> None:
    write_audit_log(
        user=request.user,
        action=action,
        object_type="sso_provider",
        object_id=provider.pk,
        app_id=app.id,
        before=before,
        after=after,
        request=request,
    )


# ---------------------------------------------------------------- 配置 API


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def provider_list_create(request, app_id: int):
    """GET/POST /api/apps/{app_id}/sso/providers/"""
    app = get_object_or_404(App, pk=app_id)
    if request.method == "GET":
        _role(request.user, app, "editor")
        items = list(app.sso_providers.all().order_by("id"))
        return Response(
            {"count": len(items), "results": SsoProviderSerializer(items, many=True).data}
        )

    _role(request.user, app, "owner")
    serializer = SsoProviderSerializer(
        data=request.data, context={"app": app, "request": request}
    )
    serializer.is_valid(raise_exception=True)
    provider = serializer.save(app=app)
    _audit(request, app, "sso.provider.create", provider, after=services.safe_provider_snapshot(provider))
    response = Response(SsoProviderSerializer(provider).data, status=status.HTTP_201_CREATED)
    return _no_store(response)


@api_view(["GET", "PATCH", "PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def provider_detail(request, app_id: int, pk: int):
    """GET/PATCH/PUT/DELETE /api/apps/{app_id}/sso/providers/{id}/"""
    app = get_object_or_404(App, pk=app_id)
    provider = get_object_or_404(SsoProvider, pk=pk, app=app)
    if request.method == "GET":
        _role(request.user, app, "editor")
        return _no_store(Response(SsoProviderSerializer(provider).data))

    _role(request.user, app, "owner")
    if request.method == "DELETE":
        before = services.safe_provider_snapshot(provider)
        provider_id = provider.pk
        provider.delete()
        write_audit_log(
            user=request.user,
            action="sso.provider.delete",
            object_type="sso_provider",
            object_id=provider_id,
            app_id=app.id,
            before=before,
            after=None,
            request=request,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    before = services.safe_provider_snapshot(provider)
    serializer = SsoProviderSerializer(
        provider,
        data=request.data,
        partial=request.method == "PATCH",
        context={"app": app, "request": request},
    )
    serializer.is_valid(raise_exception=True)
    # client_secret 为空表示「不修改」；非空则更新（落库自动加密）。
    serializer.save()
    provider.refresh_from_db()
    _audit(
        request,
        app,
        "sso.provider.update",
        provider,
        before=before,
        after=services.safe_provider_snapshot(provider),
    )
    return _no_store(Response(SsoProviderSerializer(provider).data))


# ---------------------------------------------------------------- 公开登录流程


@api_view(["GET"])
@permission_classes([AllowAny])
def public_providers(request, app_code: str):
    """GET /api/auth/sso/{app_code}/providers/ → 登录页可用的按钮数据。"""
    app = get_object_or_404(App, code=app_code)
    config = AppAuthConfig.objects.filter(app=app).first()
    if config is not None and not config.enabled:
        return _no_store(Response({"results": []}))
    items = [
        provider
        for provider in app.sso_providers.filter(enabled=True, protocol="oidc").order_by("id")
        if provider.is_usable
    ]
    return _no_store(
        Response({"results": PublicSsoProviderSerializer(items, many=True).data})
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def start(request, app_code: str, provider_slug: str):
    """GET .../start/?redirect=/xxx&mode=redirect → {authorize_url, state}"""
    _rate_limit(request, "start", limit=60)
    try:
        app, provider = _active_provider(app_code, provider_slug)
    except oidc.SsoFlowError as exc:
        return _fail(request, mode="json", code=exc.code, http_status=exc.http_status, detail=exc.detail)

    redirect_path = _sanitize_redirect(request.query_params.get("redirect"), app)
    mode = "redirect" if str(request.query_params.get("mode") or "").lower() in ("redirect", "fragment") else "json"
    redirect_uri = _callback_url(request, app.code, provider.slug)
    nonce = secrets.token_urlsafe(16)
    state = oidc.issue_state(
        {
            "a": app.id,
            "p": provider.id,
            "c": app.code,
            "s": provider.slug,
            "r": redirect_path,
            "m": mode,
            "ri": redirect_uri,
            "nc": nonce,
        }
    )
    try:
        authorize_url = oidc.build_authorize_url(
            provider,
            redirect_uri=redirect_uri,
            state=state,
            nonce=nonce,
            code_challenge=oidc.code_challenge_for(oidc.derive_code_verifier(state)),
        )
    except oidc.SsoFlowError as exc:
        return _fail(request, mode=mode, code=exc.code, http_status=exc.http_status, app=app, detail=exc.detail)

    return _no_store(
        Response(
            {
                "authorize_url": authorize_url,
                "state": state,
                "redirect_uri": redirect_uri,
                "mode": mode,
                "expires_in": oidc.STATE_MAX_AGE,
                "app": {"code": app.code, "name": app.name},
                "provider": {"id": provider.id, "name": provider.name, "slug": provider.slug},
            }
        )
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def callback(request, app_code: str, provider_slug: str):
    """GET .../callback/?code=&state= → 平台 JWT（JSON）或 302 到前端回调页。"""
    _rate_limit(request, "callback", limit=120)
    try:
        state_payload = oidc.consume_state(request.query_params.get("state"))
    except oidc.StateError as exc:
        logger.info("sso.state_rejected app_code=%s code=%s", app_code, exc.code)
        return _html_error(request, app_code, exc.message)

    mode = "redirect" if str(state_payload.get("m") or "") == "redirect" else "json"
    app = App.objects.filter(pk=state_payload.get("a")).first()
    if app is None or app.code != app_code:
        logger.warning("sso.state_app_mismatch app_code=%s", app_code)
        return _html_error(request, app_code, "登录状态与应用不匹配，请重新发起登录")

    provider = SsoProvider.objects.filter(pk=state_payload.get("p"), app=app).first()
    if provider is None or str(state_payload.get("s") or "") != provider.slug:
        logger.warning("sso.state_provider_mismatch app_code=%s", app_code)
        return _html_error(request, app_code, "登录状态与身份提供方不匹配，请重新发起登录")

    redirect_path = _sanitize_redirect(state_payload.get("r"), app)
    redirect_uri = str(state_payload.get("ri") or "") or _callback_url(request, app.code, provider.slug)

    try:
        _assert_app_login_enabled(app)
        if not provider.enabled or provider.protocol != "oidc":
            raise oidc.SsoFlowError("provider_disabled", http_status=403)
        if not provider.is_usable:
            raise oidc.SsoFlowError("config_invalid")
        idp_error = request.query_params.get("error")
        if idp_error:
            logger.warning(
                "sso.idp_error app=%s provider=%s error=%s",
                app.id,
                provider.slug,
                str(idp_error)[:80],
            )
            raise oidc.SsoFlowError("provider_error")

        code = str(request.query_params.get("code") or "").strip()
        if not code:
            raise oidc.SsoFlowError("missing_code")

        verifier = oidc.derive_code_verifier(str(request.query_params.get("state") or ""))
        token_payload = oidc.exchange_code(
            provider, code=code, redirect_uri=redirect_uri, code_verifier=verifier
        )
        id_token = str(token_payload.get("id_token") or "")
        if id_token:
            oidc.validate_id_token(provider, id_token, nonce=str(state_payload.get("nc") or ""))
        claims = oidc.fetch_userinfo(provider, token_payload["access_token"])
        oidc.assert_issuer(provider, claims)

        user, created_user = services.resolve_user(provider, claims)
        member, created_member = services.ensure_member(app, provider, user)
    except oidc.SsoFlowError as exc:
        logger.info(
            "sso.callback_failed app=%s provider=%s code=%s",
            app.id,
            provider.slug,
            exc.code,
        )
        return _fail(
            request,
            mode=mode,
            code=exc.code,
            http_status=exc.http_status,
            app=app,
            detail=exc.detail,
        )
    except PermissionDenied:
        return _fail(request, mode=mode, code="provider_disabled", http_status=403, app=app)
    except Exception:
        logger.exception("sso.callback_error app=%s provider=%s", app.id, provider.slug)
        return _fail(request, mode=mode, code="server_error", http_status=500, app=app)

    services.record_login(
        request,
        app=app,
        provider=provider,
        user=user,
        created_user=created_user,
        created_member=created_member,
    )

    body = {
        **services.issue_tokens(user),
        "token_type": "Bearer",
        "expires_in": services.access_token_expires_in(),
        "user": MeSerializer(user).data,
        "app": {"id": app.id, "code": app.code, "name": app.name},
        "role": member.role,
        "provider": {"id": provider.id, "name": provider.name, "slug": provider.slug},
        "redirect": redirect_path,
        "created_user": created_user,
    }

    if mode == "redirect":
        fragment = urlencode(
            {
                "access_token": body["access"],
                "refresh_token": body["refresh"],
                "token_type": "Bearer",
                "expires_in": body["expires_in"],
                "app_code": app.code,
                "app_name": app.name,
                "provider": provider.slug,
                "role": body["role"],
                "redirect": redirect_path,
            }
        )
        return _no_store(HttpResponseRedirect(f"{_frontend_base()}/sso/callback#{fragment}"))

    return _no_store(Response(body))
