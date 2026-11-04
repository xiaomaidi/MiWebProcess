"""可复用区块（PageBlock）REST 端点。

路由（由 pages/block_urls.py 定义，需在 config/urls.py 中 include 到根路径）：

- GET/POST ``/api/apps/{app_id}/blocks/``
- GET/PATCH/DELETE ``/api/blocks/{id}/``
- GET ``/api/runtime/{app_code}/blocks/{code}/``

权限：viewer 可读；editor 可创建/修改；owner 可删除。运行时端点遵循应用登录策略：
``require_login`` 为真时仅应用成员可用；应用已发布且允许公开访问时，匿名可拿到
已发布快照（fragment 页面通常没有独立发布，回退到草稿 schema 且不缓存）。
"""
from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from appcore.models import App, AppAuthConfig
from core.permissions import get_app_role, is_platform_admin
from pages.block_services import (
    archive_block_page,
    block_schema,
    create_block,
    delete_block_page_if_safe,
    normalize_block_code,
    node_count,
    normalize_subtree,
    sync_block_page_path,
)
from pages.models import Page, PageBlock
from pages.serializers import PageBlockDetailSerializer, PageBlockSerializer
from wp_utils import get_app, paginate_items, require_app_role


def _block_or_404(pk: int) -> PageBlock:
    return get_object_or_404(PageBlock.objects.select_related("app", "page", "created_by"), pk=pk)


def _detail(block: PageBlock, **extra) -> dict:
    data = PageBlockDetailSerializer(block).data
    data.update(extra)
    return data


def _page_brief(page: Page | None) -> dict | None:
    if page is None:
        return None
    return {
        "id": page.id,
        "name": page.name,
        "path": page.path,
        "type": page.type,
        "status": page.status,
        "version": page.version,
    }


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_block_list_create(request, app_id: int):
    """GET /api/apps/{app_id}/blocks/   POST {name, code?, description?, source_page_id?, node_ids?}"""
    app = get_app(app_id)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        qs = PageBlock.objects.filter(app=app).select_related("page", "created_by")
        search = str(request.query_params.get("search") or request.query_params.get("q") or "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        qs = qs.order_by("-updated_at", "-id")
        return paginate_items(request, qs, PageBlockSerializer)

    require_app_role(request.user, app, "editor")
    data = request.data
    name = str(data.get("name") or "").strip()
    if not name:
        raise ValidationError({"name": "name 必填"})
    code = str(data.get("code") or "").strip()
    description = str(data.get("description") or "")

    source_page = None
    source_page_id = data.get("source_page_id")
    if source_page_id not in (None, ""):
        try:
            source_page = Page.objects.select_related("app").get(pk=int(source_page_id), app=app)
        except (TypeError, ValueError):
            raise ValidationError({"source_page_id": "source_page_id 必须是整数"})
        except Page.DoesNotExist:
            raise ValidationError({"source_page_id": "来源页面不存在"})

    node_ids = data.get("node_ids")
    if node_ids is not None and not isinstance(node_ids, list):
        raise ValidationError({"node_ids": "node_ids 必须是字符串数组"})
    if node_ids:
        node_ids = [str(n) for n in node_ids if str(n or "").strip()]

    source_nodes = data.get("source_nodes")
    if source_nodes is not None and not isinstance(source_nodes, dict):
        raise ValidationError({"source_nodes": "source_nodes 必须是 {rootId, nodes} 对象"})
    if source_nodes is None and isinstance(data.get("schema"), dict):
        source_nodes = data.get("schema")

    block, page, warnings = create_block(
        app,
        request.user,
        name=name,
        code=code,
        description=description,
        source_page=source_page,
        node_ids=node_ids or None,
        source_schema=source_nodes,
    )
    return Response(
        {
            "block": _detail(block),
            "page": _page_brief(page),
            "warnings": warnings,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def block_detail(request, pk: int):
    """GET/PATCH/DELETE /api/blocks/{id}/"""
    block = _block_or_404(pk)
    app = block.app
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        return Response(
            {
                "block": _detail(block),
                "page": _page_brief(block.page if block.page_id else None),
            }
        )

    if request.method == "DELETE":
        require_app_role(request.user, app, "owner")
        delete_page = _parse_bool(
            request.query_params.get("delete_page")
            if request.query_params.get("delete_page") is not None
            else request.data.get("delete_page")
        )
        page = block.page if block.page_id else None
        page_id = page.id if page else None
        page_archived = False
        page_deleted = False
        if delete_page:
            page_deleted = delete_block_page_if_safe(block)
        elif page is not None:
            archive_block_page(block)
            page_archived = True
        block.delete()
        return Response(
            {
                "detail": "deleted",
                "page_id": page_id,
                "page_archived": page_archived,
                "page_deleted": page_deleted,
            }
        )

    # PATCH
    require_app_role(request.user, app, "editor")
    data = request.data
    warnings: list[str] = []
    errors: dict[str, str] = {}
    new_code = None
    if "name" in data:
        name = str(data.get("name") or "").strip()
        if not name:
            errors["name"] = "name 不能为空"
        else:
            block.name = name
    if "code" in data:
        try:
            new_code = normalize_block_code(data.get("code"))
        except ValidationError as exc:
            errors["code"] = str(exc.detail)
        if not new_code:
            errors.setdefault("code", "code 不能为空")
        elif PageBlock.objects.filter(app=app, code=new_code).exclude(id=block.id).exists():
            errors["code"] = f"code {new_code} 已存在"
    if "description" in data:
        block.description = str(data.get("description") or "")
    schema = data.get("schema")
    if schema is not None:
        if block.page_id:
            errors["schema"] = "该区块使用承载页面，请在页面设计器中修改 schema"
        else:
            try:
                block.schema = normalize_subtree(schema)
            except ValidationError as exc:
                errors["schema"] = str(exc.detail)
    if errors:
        raise ValidationError(errors)

    if new_code and new_code != block.code:
        old_code = block.code
        try:
            sync_block_page_path(block, new_code)
        except ValidationError as exc:
            raise ValidationError({"code": exc.detail})
        block.code = new_code
        from .block_services import rewrite_block_references
        changed = rewrite_block_references(app, old_code, new_code)
        if changed:
            warnings.append(f"已同步更新 {changed} 个页面中的区块引用")
    block.version += 1
    block.save()
    return Response({"block": _detail(block), "warnings": warnings})


def _runtime_block_schema(block: PageBlock, *, draft_ok: bool, prefer_draft: bool = False) -> tuple[dict, bool]:
    """返回 (schema, draft)。默认已发布快照优先；``prefer_draft`` 时直接取草稿。"""
    page = block.page if block.page_id else None
    if not prefer_draft and page is not None and page.status == "published":
        pv = page.current_version if page.current_version_id else None
        if pv is not None and isinstance(pv.schema, dict) and pv.schema.get("rootId"):
            return pv.schema, False
    if not draft_ok:
        return {}, True
    schema = page.schema if page is not None else block_schema(block)
    return (schema or {}), True


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_block(request, app_code: str, code: str):
    """GET /api/runtime/{app_code}/blocks/{code}/ — 区块 schema（公开发布/草稿按权限）。"""
    app = get_object_or_404(App.objects.select_related("owner"), code=app_code)
    if app.status == "archived":
        raise NotFound("应用已归档")
    block = PageBlock.objects.select_related("page").filter(app=app, code=code).first()
    if block is None:
        raise NotFound(f"区块 {code} 不存在")

    user = request.user
    member = bool(getattr(user, "is_authenticated", False)) and (
        is_platform_admin(user) or get_app_role(user, app) is not None
    )
    config = AppAuthConfig.objects.filter(app=app).first()
    require_login = bool(config.require_login) if config is not None else False
    if require_login and not member:
        raise PermissionDenied("该应用需要登录后访问")

    want_draft = _parse_bool(request.query_params.get("draft"))
    if want_draft and not member:
        raise PermissionDenied("draft 模式需要应用成员权限")
    # 已发布应用 + 允许公开访问时，区块作为页面内容的一部分公开渲染；
    # fragment 承载页面通常不单独发布，因此允许回退草稿 schema（不缓存）。
    public_ok = not require_login and app.status == "published"
    draft_ok = bool(member) or public_ok
    prefer_draft = want_draft
    schema, is_draft = _runtime_block_schema(block, draft_ok=draft_ok, prefer_draft=prefer_draft)
    if not schema or not schema.get("rootId"):
        if is_draft and not draft_ok:
            raise NotFound("区块尚未发布")
        raise NotFound("区块还没有内容")

    payload = {
        "code": block.code,
        "name": block.name,
        "version": block.version,
        "app": {"id": app.id, "code": app.code, "name": app.name},
        "rootId": schema.get("rootId") or "",
        "nodes": schema.get("nodes") or {},
        "schema": schema,
        "draft": bool(is_draft),
        "published": not is_draft,
        "node_count": node_count(schema),
        "updated_at": block.updated_at,
    }
    response = Response(payload)
    if is_draft:
        response["Cache-Control"] = "no-store"
    else:
        response["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    return response
