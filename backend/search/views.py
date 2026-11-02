"""搜索索引 REST 端点（登录用户，按应用权限）。"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.models import App
from core.audit import write_audit_log
from search.services import rebuild_app, search_documents, stats, suggest
from wp_utils import require_app_role


def _app(request) -> App:
    app_id = request.query_params.get("app_id") or request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    return get_object_or_404(App, pk=app_id)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search(request):
    """GET /api/search/?app_id=&q=&model_id=&page=&size="""
    app = _app(request)
    require_app_role(request.user, app, "viewer")
    try:
        page = max(1, int(request.query_params.get("page") or 1))
        size = min(50, max(1, int(request.query_params.get("size") or 20)))
    except (TypeError, ValueError):
        page, size = 1, 20
    model_id = request.query_params.get("model_id")
    result = search_documents(
        app, request.query_params.get("q") or "",
        model_id=int(model_id) if model_id else None,
        limit=size, offset=(page - 1) * size, include_private=True,
    )
    result.update({"page": page, "size": size})
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_stats(request):
    app = _app(request)
    require_app_role(request.user, app, "viewer")
    return Response(stats(app))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def search_suggest(request):
    app = _app(request)
    require_app_role(request.user, app, "viewer")
    return Response({"results": suggest(app, request.query_params.get("q") or "")})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def search_rebuild(request):
    """POST /api/search/rebuild/ {app_id} — 仅 owner / 平台管理员。"""
    app = _app(request)
    require_app_role(request.user, app, "owner")
    result = rebuild_app(app)
    write_audit_log(
        user=request.user, action="search.rebuild", object_type="search_index",
        app_id=app.id, object_id=app.id, after=result, request=request,
    )
    return Response({"ok": True, **result, "stats": stats(app)})
