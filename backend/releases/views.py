"""发布 REST 端点。"""
from __future__ import annotations

from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.models import App, AppMember
from core.audit import write_audit_log
from releases.models import Release, ReleaseTask
from releases.serializers import ReleaseSerializer
from releases.services import activate_release, get_active_release, rollback_release, run_compile_pipeline, schedule_release_for_app
from wp_utils import get_app, is_platform_admin_full, paginate_items, require_app_role


class ReleaseOut:
    """序列化输出。"""

    @staticmethod
    def of(release: Release, include_bundle: bool = False) -> dict:
        task = release.tasks.order_by("-created_at").first()
        out = {
            "id": release.id,
            "app": release.app.id,
            "app_code": release.app.code,
            "version": release.version,
            "status": release.status,
            "traffic_ratio": release.traffic_ratio,
            "previous_release_id": release.previous_release_id,
            "bundle_url": release.bundle_url,
            "error": release.error,
            "changelog": release.changelog,
            "task": {"status": task.status, "log": task.log} if task else None,
            "created_at": release.created_at,
        }
        return out


def _can_manage(request, app: App) -> bool:
    if is_platform_admin_full(request.user):
        return True
    return app.owner_id == request.user.id


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def release_create(request):
    """POST /api/releases/  body: {app, changelog?}"""
    app_id = request.data.get("app")
    if not app_id:
        raise ValidationError({"detail": "app 必填"})
    app = get_app(app_id)
    if not _can_manage(request, app):
        raise PermissionDenied("仅应用 owner / 平台管理员可发布")
    changelog = str(request.data.get("changelog") or "")
    release, mode = schedule_release_for_app(app, changelog=changelog, trigger="manual", user=request.user)
    write_audit_log(
        user=request.user,
        action="release.create",
        object_type="release",
        object_id=release.id,
        app_id=app.id,
        after={"version": release.version, "mode": mode},
        request=request,
    )
    return Response({"id": release.id, "status": release.status, "scheduled": mode}, status=status.HTTP_201_CREATED)


def _resolve_app_for_list(request, app_id_param):
    try:
        app = get_app(int(app_id_param))
    except (ValueError, TypeError):
        raise ValidationError({"detail": "app 必须是数字 id"})
    require_app_role(request.user, app, "viewer")
    return app


def _release_list_response(request, app_id: int | None = None) -> Response:
    qs = Release.objects.select_related("app").all()
    if app_id is not None:
        app = _resolve_app_for_list(request, app_id)
        qs = qs.filter(app=app)
    else:
        app_id_param = request.query_params.get("app")
        if app_id_param:
            app = _resolve_app_for_list(request, app_id_param)
            qs = qs.filter(app=app)
        else:
            ids = set(AppMember.objects.filter(user=request.user).values_list("app_id", flat=True))
            if not is_platform_admin_full(request.user):
                qs = qs.filter(app_id__in=ids)
    return paginate_items(request, qs, ReleaseSerializer)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def release_list(request, app_id: int | None = None):
    """GET /api/releases/?app=<id> 或 /api/apps/{app_id}/releases/"""
    return _release_list_response(request, app_id=app_id)


def _create_release_for(request, app: App):
    if not _can_manage(request, app):
        raise PermissionDenied("仅应用 owner / 平台管理员可发布")
    changelog = str(request.data.get("changelog") or "")
    release, mode = schedule_release_for_app(app, changelog=changelog, trigger="manual", user=request.user)
    write_audit_log(
        user=request.user,
        action="release.create",
        object_type="release",
        object_id=release.id,
        app_id=app.id,
        after={"version": release.version, "mode": mode},
        request=request,
    )
    return Response({"id": release.id, "status": release.status, "scheduled": mode}, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def release_root(request):
    """GET/POST /api/releases/"""
    if request.method == "POST":
        app_id = request.data.get("app")
        if not app_id:
            raise ValidationError({"detail": "app 必填"})
        app = get_app(app_id)
        return _create_release_for(request, app)
    return _release_list_response(request)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_release_root(request, app_id: int):
    """GET/POST /api/apps/{app_id}/releases/"""
    app = get_app(app_id)
    if request.method == "POST":
        return _create_release_for(request, app)
    require_app_role(request.user, app, "viewer")
    return _release_list_response(request, app_id=app.id)


def _get_release_for_user(request, release_id: int, need_manage: bool) -> Release:
    release = get_object_or_404(Release.objects.select_related("app"), id=release_id)
    if need_manage:
        if not _can_manage(request, release.app):
            raise PermissionDenied("仅应用 owner / 平台管理员可操作")
    else:
        from appcore.models import AppMember

        if not is_platform_admin_full(request.user) and not AppMember.objects.filter(app=release.app, user=request.user).exists():
            raise PermissionDenied("无权限")
    return release


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def release_detail(request, pk):
    release = _get_release_for_user(request, pk, need_manage=False)
    return Response(ReleaseOut.of(release))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def release_activate(request, pk):
    release = _get_release_for_user(request, pk, need_manage=True)
    if release.status == "pending" or release.status == "releasing":
        # 尚未编译完成：直接内联执行流水线
        run_compile_pipeline(release.id)
        release.refresh_from_db()
    if not release.bundle_url:
        raise ValidationError({"detail": "该发布没有 bundle"})
    activate_release(release)
    write_audit_log(user=request.user, action="release.activate", object_type="release", object_id=release.id, app_id=release.app_id, request=request)
    return Response(ReleaseOut.of(release))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def release_rollback(request, pk):
    release = _get_release_for_user(request, pk, need_manage=True)
    if release.status != "active":
        raise ValidationError({"detail": "只能回滚当前生效的发布"})
    try:
        target = rollback_release(release)
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)})
    write_audit_log(user=request.user, action="release.rollback", object_type="release", object_id=release.id, app_id=release.app_id, after={"active_release": target.id}, request=request)
    return Response(ReleaseOut.of(target))


@api_view(["PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def release_traffic(request, pk):
    release = _get_release_for_user(request, pk, need_manage=True)
    ratio = request.data.get("traffic_ratio")
    if not isinstance(ratio, int) or not (0 <= ratio <= 100):
        raise ValidationError({"detail": "traffic_ratio 必须是 0-100 的整数"})
    release.traffic_ratio = ratio
    release.save(update_fields=["traffic_ratio", "updated_at"])
    write_audit_log(user=request.user, action="release.traffic", object_type="release", object_id=release.id, app_id=release.app_id, after={"traffic_ratio": ratio}, request=request)
    return Response(ReleaseOut.of(release))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def active_release(request, app_code: str):
    """GET /api/releases/active/<app_code>/ — 供前端/运维查看当前生效发布。"""
    app = get_app_by_code(app_code)
    from appcore.models import AppMember

    if not is_platform_admin_full(request.user) and not AppMember.objects.filter(app=app, user=request.user).exists():
        raise PermissionDenied("无权限")
    release = get_active_release(app)
    return Response(ReleaseOut.of(release) if release else None)


def get_app_by_code(code: str) -> App:
    return get_object_or_404(App, code=code)


def _task_out(task: ReleaseTask) -> dict:
    status = "success" if task.status == "done" else task.status
    return {"id": task.id, "status": status, "log": task.log, "created_at": task.created_at}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def release_task_list(request, pk):
    """GET /api/releases/{id}/tasks/ — 任务列表（新→旧）。"""
    release = _get_release_for_user(request, pk, need_manage=False)
    tasks = release.tasks.order_by("-created_at")
    return Response([_task_out(t) for t in tasks])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def release_task_detail(request, task_id):
    """GET /api/releases/tasks/{task_id}/ — 单个任务。"""
    task = get_object_or_404(ReleaseTask.objects.select_related("release__app"), id=task_id)
    if not _can_manage(request, task.release.app):
        if not AppMember.objects.filter(app=task.release.app, user=request.user).exists():
            raise PermissionDenied("无权限")
    return Response(_task_out(task))
