"""应用级登录/注册：平台统一账号 + 应用品牌与准入策略。"""
from __future__ import annotations

import secrets

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.serializers import MeSerializer, RegisterSerializer
from appcore.models import App, AppAuthConfig, AppMember, AppModule
from appcore.modules import default_modules, normalize_modules
from appcore.serializers import AppAuthConfigSerializer
from wp_utils import require_app_role


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR") or ""
    return (forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")) or "unknown"


def _rate_limit(request, scope: str, limit: int = 20, window: int = 3600) -> None:
    key = f"app_auth:{scope}:{_client_ip(request)}"
    count = int(cache.get(key) or 0)
    if count >= limit:
        raise PermissionDenied("操作过于频繁，请稍后再试")
    cache.set(key, count + 1, window)


def _defaults(app: App) -> dict:
    return {
        "login_title": app.name,
        "login_subtitle": "登录后进入应用",
        "theme_color": "#2563eb",
        "redirect_path": "",
    }


def _config_for(app: App) -> AppAuthConfig:
    config, _ = AppAuthConfig.objects.get_or_create(app=app, defaults=_defaults(app))
    return config


def _public_config(app: App, config: AppAuthConfig) -> dict:
    return {
        "app_id": app.id,
        "app_code": app.code,
        "app_name": app.name,
        "enabled": config.enabled,
        "require_login": config.require_login,
        "allow_register": config.allow_register,
        "auto_join": config.auto_join,
        "invite_required": config.invite_required,
        "login_title": config.login_title or app.name,
        "login_subtitle": config.login_subtitle or "登录后进入应用",
        "logo_url": config.logo_url,
        "theme_color": config.theme_color or "#2563eb",
        "redirect_path": config.redirect_path,
    }


def _tokens(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _membership(app: App, user, *, create: bool) -> AppMember | None:
    member = AppMember.objects.filter(app=app, user=user).first()
    if member is not None:
        return member
    if not create:
        return None
    config = _config_for(app)
    if not config.auto_join:
        return None
    return AppMember.objects.create(app=app, user=user, role=config.default_role or "viewer")


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def app_modules(request, app_id: int):
    app = get_object_or_404(App.objects.select_related("owner"), pk=app_id)
    require_app_role(request.user, app, "viewer" if request.method == "GET" else "owner")
    existing = {item.key: item for item in AppModule.objects.filter(app=app)}
    if request.method == "GET":
        rows = []
        for item in default_modules():
            row = existing.get(item["key"])
            rows.append({
                **item,
                "enabled": row.enabled if row is not None else item["enabled"],
                "config": row.config if row is not None else {},
            })
        return Response({"modules": rows})

    rows = normalize_modules(request.data.get("modules", request.data))
    for item in rows:
        AppModule.objects.update_or_create(
            app=app, key=item["key"],
            defaults={"enabled": bool(item["enabled"]), "sort": rows.index(item)},
        )
    return Response({"modules": rows})


@api_view(["GET", "PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def app_auth_config(request, app_id: int):
    app = get_object_or_404(App.objects.select_related("owner"), pk=app_id)
    config = _config_for(app)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        return Response(AppAuthConfigSerializer(config).data)
    require_app_role(request.user, app, "owner")
    serializer = AppAuthConfigSerializer(config, data=request.data, partial=request.method == "PATCH")
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_auth_config(request, app_code: str):
    app = get_object_or_404(App, code=app_code)
    return Response(_public_config(app, _config_for(app)))


@api_view(["POST"])
@permission_classes([AllowAny])
def runtime_auth_login(request, app_code: str):
    _rate_limit(request, "login", limit=40)
    app = get_object_or_404(App, code=app_code)
    config = _config_for(app)
    if not config.enabled:
        raise PermissionDenied("该应用已关闭登录")
    username = str(request.data.get("username") or "").strip()
    password = str(request.data.get("password") or "")
    if not username or not password:
        raise ValidationError({"detail": "请输入账号和密码"})
    user = authenticate(request, username=username, password=password)
    if user is None or not user.is_active:
        raise PermissionDenied("账号或密码错误")
    with transaction.atomic():
        member = _membership(app, user, create=config.auto_join)
        if member is None:
            raise PermissionDenied("你没有该应用的访问权限")
    return Response({
        **_tokens(user),
        "user": MeSerializer(user).data,
        "app": {"id": app.id, "code": app.code, "name": app.name},
        "role": member.role,
        "config": _public_config(app, config),
    })


@api_view(["POST"])
@permission_classes([AllowAny])
def runtime_auth_register(request, app_code: str):
    _rate_limit(request, "register", limit=10)
    app = get_object_or_404(App, code=app_code)
    config = _config_for(app)
    if not config.enabled:
        raise PermissionDenied("该应用已关闭登录")
    if not config.allow_register:
        raise PermissionDenied("该应用未开放注册")
    if config.invite_required:
        supplied = str(request.data.get("invite_code") or "")
        if not config.invite_code or not secrets.compare_digest(supplied, config.invite_code):
            raise ValidationError({"invite_code": "邀请码不正确"})
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        user = serializer.save()
        AppMember.objects.create(app=app, user=user, role=config.default_role or "viewer")
    return Response({
        **_tokens(user),
        "user": MeSerializer(user).data,
        "app": {"id": app.id, "code": app.code, "name": app.name},
        "role": config.default_role or "viewer",
        "config": _public_config(app, config),
    }, status=status.HTTP_201_CREATED)
