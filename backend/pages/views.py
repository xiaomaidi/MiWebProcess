"""页面 REST 端点（草稿 / 发布 / 版本 / 回滚 / 预览 / 资产）。"""
from __future__ import annotations

import re
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.modules import require_module
from core.permissions import is_platform_admin
from pages.block_publish import auto_publish_referenced_blocks, empty_block_report
from pages.models import Asset, Page, PageVersion
from pages.serializers import AssetSerializer, PageSerializer, PageVersionSerializer
from pages.services import default_page_schema, publish_page, save_draft
from wp_utils import broadcast_draft_saved, get_app, paginate_items, require_app_role


PAGE_PATH_SEGMENT = re.compile(r"^(?:[A-Za-z0-9_-]+|:[A-Za-z_]\w*|\*)$")


def _clean_page_path(raw: str) -> str:
    """允许 home、news/games、news/:category、article/:id、docs/*splat。"""
    path = str(raw or "").strip().strip("/")
    if not path or "//" in path:
        raise ValidationError({"detail": "path 不能为空或包含连续斜杠"})
    segments = path.split("/")
    for i, seg in enumerate(segments):
        if not PAGE_PATH_SEGMENT.match(seg):
            raise ValidationError({"detail": f"path 片段不合法: {seg}"})
        if seg == "*" and i != len(segments) - 1:
            raise ValidationError({"detail": "* 只能出现在路径末尾"})
    return path


def _page_or_404(page_id: int) -> Page:
    return get_object_or_404(Page.objects.select_related("app"), id=page_id)


def _check_app_access(request, app_id: int, role: str):
    app = get_app(app_id)
    require_app_role(request.user, app, role)
    return app


def _check_page_access(request, page: Page, role: str):
    require_app_role(request.user, page.app, role)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_page_list_create(request, app_id):
    """GET /api/apps/{app_id}/pages/  或  POST {name, path, type}"""
    app = _check_app_access(request, app_id, "viewer" if request.method == "GET" else "editor")
    if request.method == "GET":
        pages = app.pages.all().order_by("id")
        return paginate_items(request, pages, PageSerializer)
    # POST
    name = (request.data.get("name") or "").strip()
    path = _clean_page_path(request.data.get("path") or "")
    ptype = (request.data.get("type") or "page").strip()
    if not name or not path:
        raise ValidationError({"detail": "name 和 path 必填"})
    if ptype not in dict(Page.TYPE_CHOICES):
        raise ValidationError({"detail": f"type 必须是 {dict(Page.TYPE_CHOICES).keys()}"})
    if app.pages.filter(path=path).exists():
        raise ValidationError({"detail": f"path {path} 已存在"})
    page = Page.objects.create(app=app, name=name, path=path, type=ptype, schema=default_page_schema(), status="draft")
    return Response(PageSerializer(page).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def page_detail(request, pk):
    """GET/PUT/PATCH/DELETE /api/pages/{id}/"""
    page = _page_or_404(pk)
    if request.method == "GET":
        _check_page_access(request, page, "viewer")
        return Response(PageSerializer(page).data)
    _check_page_access(request, page, "editor")
    if request.method == "DELETE":
        page.delete()
        return Response({"detail": "deleted"})
    data = request.data
    errors = {}
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            errors["name"] = "name 不能为空"
        else:
            page.name = name
    if "type" in data:
        ptype = str(data.get("type") or "").strip()
        if ptype not in dict(Page.TYPE_CHOICES):
            errors["type"] = "type 不合法"
        else:
            page.type = ptype
    if "thumbnail_url" in data:
        page.thumbnail_url = str(data.get("thumbnail_url") or "")
    if "path" in data:
        try:
            new_path = _clean_page_path(data.get("path") or "")
        except ValidationError as exc:
            errors["path"] = exc.detail
            new_path = ""
        if not new_path:
            errors.setdefault("path", "path 不能为空")
        elif page.app.pages.exclude(id=page.id).filter(path=new_path).exists():
            errors["path"] = f"path {new_path} 已存在"
        else:
            page.path = new_path
    if errors:
        raise ValidationError(errors)
    page.save()
    return Response(PageSerializer(page).data)


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def page_schema(request, pk):
    """GET/PUT /api/pages/{id}/schema/"""
    page = _page_or_404(pk)
    if request.method == "GET":
        _check_page_access(request, page, "viewer")
        return Response({"schema": page.schema or {}})
    _check_page_access(request, page, "editor")
    schema = request.data.get("schema")
    if not isinstance(schema, dict):
        raise ValidationError({"detail": "schema 必须是对象"})
    base_version = request.data.get("base_version")
    if base_version not in (None, ""):
        try:
            expected = int(base_version)
        except (TypeError, ValueError):
            raise ValidationError({"detail": "base_version 必须是整数"})
        if expected != page.version:
            return Response(
                {
                    "detail": "页面已被其他人保存，请刷新后再编辑",
                    "current_version": page.version,
                },
                status=status.HTTP_409_CONFLICT,
            )
    page, errors, warnings = save_draft(page, schema, request.user)
    if errors:
        # 草稿宽松：结构性错误仍提示，但按契约仅警告不阻塞
        warnings = list(errors) + list(warnings)
    broadcast_draft_saved(page.app_id, page.id, page.version, request.user.username)
    return Response({"page": PageSerializer(page).data, "warnings": warnings})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def page_publish(request, pk):
    """POST /api/pages/{id}/publish/ {changelog?} → 严格校验 → PageVersion → 自动发布引用区块 → 触发应用发布"""
    page = _page_or_404(pk)
    _check_page_access(request, page, "owner")
    changelog = str(request.data.get("changelog") or "")
    with transaction.atomic():
        # 宿主页面在事务内发布；区块自动发布放到事务提交后，避免单个区块失败污染宿主事务。
        pv, errors, warnings = publish_page(page, request.user, changelog, auto_blocks=False)
        if pv is None:
            raise ValidationError({"detail": errors or "schema 校验失败"})
        app = page.app
        if app.status != "archived":
            app.status = "published"
            app.save(update_fields=["status", "updated_at"])
    # 自动发布引用区块（递归、限深、环安全）；失败只作为 warning 返回。
    block_report = empty_block_report()
    try:
        block_report = auto_publish_referenced_blocks(page, request.user, changelog)
        warnings = list(warnings or []) + list(block_report.get("warnings") or [])
    except Exception as exc:  # noqa: BLE001 - 区块失败不能阻塞宿主页面发布
        warnings = list(warnings or []) + [
            f"自动发布引用区块失败: {type(exc).__name__}: {exc}"
        ]
    # 触发（或更新）应用级发布：celery 不可用时同步内联执行
    from releases.services import schedule_release_for_app

    schedule_release_for_app(app, changelog=changelog, trigger="page_publish")
    payload = {
        "page_version": PageVersionSerializer(pv).data,
        "warnings": warnings,
        "blocks": block_report,
    }
    # 兼容/便利：同时提供顶层字段，前端或脚本可不必展开 blocks。
    payload.update(
        {
            "published_blocks": block_report.get("published") or [],
            "skipped_blocks": block_report.get("skipped") or [],
            "missing_blocks": block_report.get("missing") or [],
            "cycles": block_report.get("cycles") or [],
            "depth_limited_blocks": block_report.get("depth_limited") or [],
            "info": block_report.get("info") or [],
        }
    )
    return Response(payload)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def page_versions(request, pk):
    """GET /api/pages/{id}/versions/"""
    page = _page_or_404(pk)
    _check_page_access(request, page, "viewer")
    return paginate_items(request, page.versions.all().order_by("-version"), PageVersionSerializer)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def page_version_rollback(request, pk, version):
    """POST /api/pages/{id}/versions/{version}/rollback/ → 快照载入草稿"""
    page = _page_or_404(pk)
    _check_page_access(request, page, "editor")
    pv = get_object_or_404(PageVersion, page=page, version=int(version))
    page.schema = pv.schema
    page.schema_version = pv.schema_version
    page.version += 1
    page.status = "draft"
    page.save(update_fields=["schema", "schema_version", "version", "status", "updated_at"])
    broadcast_draft_saved(page.app_id, page.id, page.version, request.user.username)
    return Response({"page": PageSerializer(page).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def page_preview(request, pk):
    """POST /api/pages/{id}/preview/ → 草稿 schema（JWT 有效即可，不做成员校验）"""
    page = _page_or_404(pk)
    return Response(
        {
            "schema": page.schema or {},
            "page": {
                "id": page.id,
                "name": page.name,
                "path": page.path,
                "type": page.type,
                "version": page.version,
                "schemaVersion": page.schema_version,
            },
        }
    )


def _asset_type(name: str) -> str:
    ext = PurePosixPath(name).suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico"):
        return "image"
    if ext in (".ttf", ".otf", ".woff", ".woff2", ".eot"):
        return "font"
    return "file"


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def asset_list_create(request):
    """GET/POST /api/assets/"""
    if request.method == "GET":
        app_id = request.query_params.get("app_id")
        qs = Asset.objects.all().order_by("-id")
        if app_id:
            _check_app_access(request, int(app_id), "viewer")
            qs = qs.filter(app_id=app_id)
        else:
            qs = qs.filter(uploaded_by=request.user)
        return paginate_items(request, qs, AssetSerializer)
    # POST：multipart 上传
    file = request.FILES.get("file")
    if file is None:
        raise ValidationError({"detail": "缺少 file 字段"})
    app = None
    app_id = request.query_params.get("app_id")
    if app_id:
        app = _check_app_access(request, int(app_id), "editor")
        require_module(app, "files")
    else:
        _check_role_any_app(request)
    if request.data.get("name"):
        name = str(request.data.get("name"))[:300]
    else:
        name = file.name[:300]
    folder = str(app.id) if app else "common"
    rel = f"assets/{folder}/{uuid.uuid4().hex[:12]}-{uuid.uuid4().hex[:4]}-{PurePosixPath(name).name}"
    from django.core.files.storage import default_storage

    url = default_storage.save(rel, file)
    asset = Asset.objects.create(
        app=app,
        name=name,
        url="/" + str(settings.MEDIA_URL).lstrip("/") + str(url).replace("\\", "/"),
        type=_asset_type(name),
        uploaded_by=request.user,
    )
    return Response(AssetSerializer(asset).data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def asset_detail(request, pk):
    """DELETE /api/assets/{pk}/"""
    asset = get_object_or_404(Asset, id=pk)
    if asset.app_id:
        _check_app_access(request, asset.app_id, "editor")
        require_module(asset.app, "files")
    else:
        _check_role_any_app(request)
    try:
        from django.core.files.storage import default_storage

        default_storage.delete(str(asset.url).lstrip("/"))
    except Exception:
        pass
    asset.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def _check_role_any_app(request):
    """无 app_id 时要求用户是某应用 owner/editor 或平台管理员（防止匿名上传）。"""
    if is_platform_admin(request.user):
        return
    from appcore.models import AppMember

    if AppMember.objects.filter(user=request.user, role__in=("owner", "editor")).exists():
        return
    raise PermissionDenied("需要应用编辑权限")
