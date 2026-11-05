from __future__ import annotations

import re

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.models import App
from components.models import ComponentMeta
from components.services import invalidate_registry_cache
from core.permissions import is_platform_admin
from pages.block_services import create_block
from wp_utils import paginate_items, require_app_role

from .models import MarketItem

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


def _payload(item: MarketItem) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "category": item.category,
        "tags": item.tags or [],
        "preview": item.preview or {},
        "payload": item.payload or {},
        "status": item.status,
        "visibility": item.visibility,
        "source_app_id": item.source_app_id,
        "created_by": item.created_by.username if item.created_by else "",
        "installs": item.installs,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _can_manage(user, item: MarketItem) -> bool:
    return bool(is_platform_admin(user) or (item.created_by_id and item.created_by_id == user.id))


def _validate(data, *, partial=False) -> dict:
    out = {}
    if "kind" in data or not partial:
        kind = str(data.get("kind") or "block")
        if kind not in ("component", "block"):
            raise ValidationError({"kind": "kind 只能是 component 或 block"})
        out["kind"] = kind
    if "name" in data or not partial:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": "name 必填"})
        out["name"] = name[:160]
    if "slug" in data or not partial:
        slug = str(data.get("slug") or "").strip().lower()
        if not SLUG_RE.match(slug):
            raise ValidationError({"slug": "slug 只能包含小写字母、数字和连字符"})
        out["slug"] = slug
    if "description" in data:
        out["description"] = str(data.get("description") or "")[:4000]
    if "category" in data:
        out["category"] = str(data.get("category") or "")[:60]
    if "tags" in data:
        tags = data.get("tags")
        if not isinstance(tags, list):
            raise ValidationError({"tags": "tags 必须是数组"})
        out["tags"] = [str(tag)[:40] for tag in tags if str(tag).strip()][:20]
    if "preview" in data:
        if not isinstance(data.get("preview"), dict):
            raise ValidationError({"preview": "preview 必须是对象"})
        out["preview"] = data["preview"]
    if "payload" in data or not partial:
        payload = data.get("payload")
        if not isinstance(payload, dict):
            raise ValidationError({"payload": "payload 必须是对象"})
        out["payload"] = payload
    if "status" in data:
        status_value = str(data.get("status") or "draft")
        if status_value not in ("draft", "published", "archived"):
            raise ValidationError({"status": "status 非法"})
        out["status"] = status_value
    if "visibility" in data:
        visibility = str(data.get("visibility") or "public")
        if visibility not in ("public", "private"):
            raise ValidationError({"visibility": "visibility 非法"})
        out["visibility"] = visibility
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def market_items(request):
    if request.method == "GET":
        qs = MarketItem.objects.select_related("created_by", "source_app")
        if not is_platform_admin(request.user):
            qs = qs.filter(status="published", visibility="public") | qs.filter(created_by=request.user)
            qs = qs.distinct()
        kind = str(request.query_params.get("kind") or "").strip()
        category = str(request.query_params.get("category") or "").strip()
        query = str(request.query_params.get("q") or "").strip()
        if kind:
            qs = qs.filter(kind=kind)
        if category:
            qs = qs.filter(category=category)
        if query:
            from django.db.models import Q
            qs = qs.filter(Q(name__icontains=query) | Q(description__icontains=query) | Q(slug__icontains=query))
        return paginate_items(request, qs, MarketItemSerializer)
    data = _validate(request.data)
    if MarketItem.objects.filter(kind=data["kind"], slug=data["slug"]).exists():
        raise ValidationError({"slug": "该 kind 下 slug 已存在"})
    item = MarketItem.objects.create(
        created_by=request.user,
        source_app=App.objects.filter(pk=request.data.get("source_app_id")).first(),
        **data,
    )
    return Response(_payload(item), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def market_item_detail(request, pk: int):
    item = get_object_or_404(MarketItem.objects.select_related("created_by", "source_app"), pk=pk)
    if request.method == "GET":
        if item.visibility == "private" and item.created_by_id != request.user.id and not is_platform_admin(request.user):
            raise PermissionDenied("无权查看该市场条目")
        return Response(_payload(item))
    if not _can_manage(request.user, item):
        raise PermissionDenied("只能管理自己创建的市场条目")
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = _validate(request.data, partial=True)
    if "slug" in data and MarketItem.objects.filter(kind=item.kind, slug=data["slug"]).exclude(pk=item.pk).exists():
        raise ValidationError({"slug": "该 kind 下 slug 已存在"})
    for key, value in data.items():
        setattr(item, key, value)
    item.save()
    return Response(_payload(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def market_install(request, pk: int):
    item = get_object_or_404(MarketItem.objects.select_related("created_by"), pk=pk)
    if item.status != "published" or item.visibility != "public":
        if not _can_manage(request.user, item):
            raise PermissionDenied("该市场条目未发布")
    app_id = request.data.get("app_id")
    try:
        app = App.objects.get(pk=int(app_id))
    except (TypeError, ValueError, App.DoesNotExist):
        raise ValidationError({"app_id": "目标应用不存在"})
    require_app_role(request.user, app, "editor")
    with transaction.atomic():
        if item.kind == "block":
            subtree = item.payload.get("schema") if isinstance(item.payload.get("schema"), dict) else item.payload
            if not isinstance(subtree, dict) or not subtree.get("rootId"):
                raise ValidationError({"payload": "区块 payload 必须是 {rootId, nodes}"})
            block, page, warnings = create_block(
                app, request.user, name=item.name, code=item.slug,
                description=item.description, source_schema=subtree,
            )
            MarketItem.objects.filter(pk=item.pk).update(installs=item.installs + 1)
            return Response({
                "kind": "block", "block_id": block.id, "page_id": page.id,
                "code": block.code, "warnings": warnings,
            }, status=status.HTTP_201_CREATED)
        payload = item.payload
        name = str(payload.get("name") or f"market-{item.slug}")
        if not name.startswith("wp-market-"):
            name = f"wp-market-{item.slug}"
        defaults = {
            "label": str(payload.get("label") or item.name)[:128],
            "type": str(payload.get("type") or "custom"),
            "category": str(payload.get("category") or "custom"),
            "version": str(payload.get("version") or "1.0.0"),
            "props_schema": payload.get("props_schema") or {},
            "style_schema": payload.get("style_schema") or {},
            "default_props": payload.get("default_props") or {},
            "events": payload.get("events") or [],
            "accept_children": payload.get("accept_children") or [],
            "is_container": bool(payload.get("is_container")),
            "is_form_field": bool(payload.get("is_form_field")),
            "icon": str(payload.get("icon") or "SetUp"),
            "source": "custom",
            "source_url": str(payload.get("source_url") or ""),
            "is_custom": True,
            "is_enabled": True,
        }
        meta, created = ComponentMeta.objects.update_or_create(name=name, defaults=defaults)
        invalidate_registry_cache()
        MarketItem.objects.filter(pk=item.pk).update(installs=item.installs + 1)
        return Response({
            "kind": "component", "component": meta.name, "created": created,
        }, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def market_categories(request):
    rows = MarketItem.objects.filter(status="published", visibility="public").values_list("kind", "category")
    seen = []
    for kind, category in rows:
        value = {"kind": kind, "category": category or "other"}
        if value not in seen:
            seen.append(value)
    return Response({"results": seen})


from .serializers import MarketItemSerializer  # noqa: E402
