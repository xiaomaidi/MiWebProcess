"""认证 / 用户管理端点。"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError, Q
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.serializers import MeSerializer, MeUpdateSerializer, RegisterSerializer, UserAdminSerializer
from core.audit import write_audit_log
from wp_utils import paginate

User = get_user_model()


def _require_platform_admin(request):
    from wp_utils import is_platform_admin_full

    if not is_platform_admin_full(request.user):
        raise AuthenticationFailed("需要平台管理员权限")


# ---------------------------------------------------------------- 注册 / 登录

def _tokens_and_user(request, serializer) -> dict:
    from rest_framework_simplejwt.tokens import RefreshToken

    user = serializer.validated_data["user"]
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": {"id": user.id, "username": user.username, "is_superuser": user.is_superuser},
    }


def _client_ip(request):
    import ipaddress

    raw = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    raw = raw or request.META.get("REMOTE_ADDR") or ""
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def _record_login(request, user=None, success=False, reason=""):
    from accounts.models import LoginLog

    try:
        LoginLog.objects.create(
            user=user,
            username=(user.username if user else str(request.data.get("username") or ""))[:150],
            success=success,
            reason=str(reason or "")[:200],
            ip=_client_ip(request),
            user_agent=str(request.META.get("HTTP_USER_AGENT") or "")[:500],
        )
    except Exception:
        # 登录日志不能影响登录本身
        pass


def _login_response(request):
    from .serializers import TokenSerializer

    serializer = TokenSerializer(data=request.data)
    try:
        serializer.is_valid(raise_exception=True)
    except Exception as exc:
        _record_login(request, success=False, reason=str(exc))
        raise
    user = serializer.validated_data["user"]
    _record_login(request, user=user, success=True)
    return Response(_tokens_and_user(request, serializer))


@api_view(["POST"])
@permission_classes([AllowAny])
def token(request):
    """POST /api/auth/token/ {username, password} → {access, refresh, user}"""
    return _login_response(request)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """POST /api/auth/login/（token 的别名）"""
    return _login_response(request)


@api_view(["POST"])
@permission_classes([AllowAny])
def refresh(request):
    """POST /api/auth/refresh/ {refresh} → {access, refresh}"""
    from rest_framework_simplejwt.tokens import RefreshToken

    raw = request.data.get("refresh")
    if not raw:
        return Response({"detail": "refresh 必填"}, status=400)
    try:
        old = RefreshToken(raw)
    except Exception:
        return Response({"detail": "refresh 无效或已过期"}, status=401)
    uid = old.payload.get("user_id")
    user = User.objects.filter(id=uid, is_active=True).first()
    if user is None:
        return Response({"detail": "refresh 无效或用户已禁用"}, status=401)
    new = RefreshToken.for_user(user)
    return Response({"access": str(new.access_token), "refresh": str(new)})


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    """POST /api/auth/register/ — 公开注册。"""
    ser = RegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = ser.save()
    refresh = RefreshToken.for_user(user)
    return Response(
        {
            "id": user.id,
            "username": user.username,
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH", "PUT"])
@permission_classes([IsAuthenticated])
def me(request):
    """GET/PATCH/PUT /api/auth/me/（同 /api/auth/user/）"""
    if request.method == "GET":
        return Response(MeSerializer(request.user).data)
    ser = MeUpdateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = request.user
    for key, value in ser.validated_data.items():
        setattr(user, key, value)
    user.save()
    return Response(MeSerializer(user).data)


# ---------------------------------------------------------------- 用户管理（平台管理员）

def _user_list_response(request, queryset):
    from wp_utils import paginate_items

    return paginate_items(request, queryset, UserAdminSerializer)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def users_list_create(request):
    """GET/POST /api/auth/users/ — 平台管理员。"""
    _require_platform_admin(request)
    if request.method == "GET":
        qs = User.objects.all().order_by("id")
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(username__icontains=q)
                | Q(email__icontains=q)
                | Q(first_name__icontains=q)
                | Q(last_name__icontains=q)
            )
        active = request.query_params.get("is_active")
        if active in ("0", "false", "False"):
            qs = qs.filter(is_active=False)
        elif active in ("1", "true", "True"):
            qs = qs.filter(is_active=True)
        role = request.query_params.get("role")
        if role == "superuser":
            qs = qs.filter(is_superuser=True)
        elif role == "platform_admin":
            qs = qs.filter(is_platform_admin=True)
        elif role == "normal":
            qs = qs.filter(is_superuser=False, is_platform_admin=False)
        return _user_list_response(request, qs)
    ser = UserAdminSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    generated = not bool(request.data.get("password"))
    if generated:
        import secrets
        import string

        alphabet = string.ascii_letters + string.digits
        password = "".join(secrets.choice(alphabet) for _ in range(14))
    else:
        password = str(request.data.get("password"))
    try:
        user = User.objects.create_user(
            username=data["username"],
            email=data.get("email", ""),
            password=password,
            first_name=data.get("first_name", ""),
            last_name=data.get("last_name", ""),
            is_staff=bool(data.get("is_staff", False)),
            is_active=data.get("is_active", True),
        )
    except Exception as e:  # noqa: BLE001
        from rest_framework.exceptions import ValidationError

        raise ValidationError({"detail": str(e)})
    if data.get("is_platform_admin"):
        user.is_platform_admin = True
        user.save(update_fields=["is_platform_admin"])
    if data.get("is_superuser"):
        user.is_superuser = True
        user.save(update_fields=["is_superuser", "is_platform_admin"])
    write_audit_log(user=request.user, action="user.create", object_type="user", object_id=user.id, after={"username": user.username}, request=request)
    payload = UserAdminSerializer(user).data
    if generated:
        payload["temporary_password"] = password
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def user_detail(request, pk):
    """GET/PUT/PATCH/DELETE /api/auth/users/{id}/ — 平台管理员。"""
    _require_platform_admin(request)
    user = User.objects.filter(id=pk).first()
    if user is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return Response(UserAdminSerializer(user).data)
    if request.method == "DELETE":
        from rest_framework.exceptions import ValidationError

        if user.id == request.user.id:
            raise ValidationError({"detail": "不能删除当前登录账号"})
        if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
            raise ValidationError({"detail": "不能删除最后一个超级管理员"})
        username = user.username
        try:
            user.delete()
        except ProtectedError as exc:
            raise ValidationError({"detail": "该用户名下仍有应用，请先转移或删除应用"}) from exc
        write_audit_log(user=request.user, action="user.delete", object_type="user", object_id=pk, before={"username": username}, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = UserAdminSerializer(user, data=request.data, partial=(request.method == "PATCH"))
    ser.is_valid(raise_exception=True)
    before = {"username": user.username, "is_staff": user.is_staff, "is_platform_admin": user.is_platform_admin}
    data = ser.validated_data
    for key in ("email", "first_name", "last_name", "is_staff", "is_active"):
        if key in data:
            setattr(user, key, data[key])
    if "is_platform_admin" in data:
        user.is_platform_admin = bool(data["is_platform_admin"])
    if "is_superuser" in data:
        if not data["is_superuser"] and user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
            from rest_framework.exceptions import ValidationError

            raise ValidationError({"detail": "不能取消最后一个超级管理员"})
        user.is_superuser = bool(data["is_superuser"])
    if "is_superuser" in data:
        user.is_platform_admin = user.is_platform_admin or user.is_superuser
    user.save()
    write_audit_log(user=request.user, action="user.update", object_type="user", object_id=user.id, before=before, after={"username": user.username, "is_staff": user.is_staff, "is_platform_admin": user.is_platform_admin}, request=request)
    return Response(UserAdminSerializer(user).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_access(request, pk):
    """GET /api/auth/users/{id}/access/ — 应用角色、部门、平台角色。"""
    _require_platform_admin(request)
    user = User.objects.filter(id=pk).first()
    if user is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    from appcore.models import AppMember
    from org.models import DepartmentMember

    apps = []
    seen = set()
    for member in AppMember.objects.filter(user=user).select_related("app").order_by("app_id"):
        app = member.app
        seen.add(app.id)
        apps.append({
            "id": app.id,
            "name": app.name,
            "code": app.code,
            "role": member.role,
            "is_owner": app.owner_id == user.id,
        })
    for app in user.owned_apps.all().order_by("id"):
        if app.id not in seen:
            apps.append({
                "id": app.id,
                "name": app.name,
                "code": app.code,
                "role": "owner",
                "is_owner": True,
            })
    departments = [
        {
            "id": dm.department_id,
            "name": dm.department.name,
            "role": dm.role,
            "title": dm.title,
            "is_leader": dm.role == "leader" or dm.department.leader_id == user.id,
        }
        for dm in DepartmentMember.objects.filter(user=user).select_related("department")
    ]
    return Response({
        "user": UserAdminSerializer(user).data,
        "platform": {
            "is_superuser": user.is_superuser,
            "is_platform_admin": user.is_platform_admin,
            "is_staff": user.is_staff,
            "is_active": user.is_active,
        },
        "apps": apps,
        "departments": departments,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_reset_password(request, pk):
    """POST /api/auth/users/{id}/reset-password/ {password} — 平台管理员。"""
    _require_platform_admin(request)
    from rest_framework.exceptions import ValidationError

    user = User.objects.filter(id=pk).first()
    if user is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    password = str(request.data.get("password") or "")
    if len(password) < 8:
        raise ValidationError({"detail": "密码至少 8 位"})
    user.set_password(password)
    user.save(update_fields=["password"])
    write_audit_log(
        user=request.user,
        action="user.password.reset",
        object_type="user",
        object_id=user.id,
        after={"username": user.username},
        request=request,
    )
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def users_batch(request):
    """POST /api/auth/users/batch/ {action: enable|disable|delete, user_ids: []}"""
    _require_platform_admin(request)
    from rest_framework.exceptions import ValidationError

    action = str(request.data.get("action") or "")
    ids = request.data.get("user_ids")
    if action not in ("enable", "disable", "delete"):
        raise ValidationError({"detail": "action 必须是 enable / disable / delete"})
    if not isinstance(ids, list) or not ids:
        raise ValidationError({"detail": "user_ids 必须是非空数组"})
    updated, skipped, errors = 0, [], []
    for user in User.objects.filter(id__in=ids):
        if user.id == request.user.id:
            skipped.append({"id": user.id, "username": user.username, "reason": "当前登录账号"})
            continue
        if action == "delete":
            if user.is_superuser and User.objects.filter(is_superuser=True).count() <= 1:
                skipped.append({"id": user.id, "username": user.username, "reason": "最后一个超级管理员"})
                continue
            try:
                user.delete()
                updated += 1
            except ProtectedError:
                errors.append({"id": user.id, "username": user.username, "reason": "名下仍有应用"})
        else:
            user.is_active = action == "enable"
            user.save(update_fields=["is_active"])
            updated += 1
    write_audit_log(
        user=request.user,
        action=f"user.batch_{action}",
        object_type="user",
        object_id=ids[0] if ids else 0,
        after={"user_ids": ids, "updated": updated},
        request=request,
    )
    return Response({"updated": updated, "skipped": skipped, "errors": errors})


def _serialize_login(log):
    return {
        "id": log.id,
        "user_id": log.user_id,
        "username": log.username,
        "success": log.success,
        "reason": log.reason,
        "ip": log.ip,
        "user_agent": log.user_agent,
        "created_at": log.created_at,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def login_logs(request):
    """GET /api/auth/login-logs/ — 平台管理员查看登录记录。"""
    _require_platform_admin(request)
    from accounts.models import LoginLog
    from wp_utils import paginate_items

    qs = LoginLog.objects.select_related("user").all()
    user_id = request.query_params.get("user_id")
    if user_id:
        qs = qs.filter(user_id=user_id)
    username = request.query_params.get("username") or request.query_params.get("q")
    if username:
        qs = qs.filter(username__icontains=username)
    success = request.query_params.get("success")
    if success in ("0", "false", "False"):
        qs = qs.filter(success=False)
    elif success in ("1", "true", "True"):
        qs = qs.filter(success=True)
    return paginate_items(request, qs.order_by("-created_at"), _serialize_login)
