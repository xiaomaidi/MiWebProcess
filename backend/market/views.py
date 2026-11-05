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
from .signing import (
    DEFAULT_COMPONENT_POLICY,
    SIGNING_SCHEMA,
    element_for,
    normalize_policy,
    sign_item,
    signing_metadata,
    validate_component_payload,
    validate_source_url,
    verify_item,
)

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


def _payload(item: MarketItem) -> dict:
    meta = signing_metadata(item)
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
        "sandboxed": item.sandboxed,
        "policy": item.policy or {},
        "code_hash": meta["code_hash"],
        "signature": meta["signature"],
        "signed_at": meta["signed_at"],
        "signer": meta["signer"],
        "signed": meta["signed"],
        "signature_valid": meta["signature_valid"],
        "signature_error": meta["signature_error"],
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _can_manage(user, item: MarketItem) -> bool:
    return bool(is_platform_admin(user) or (item.created_by_id and item.created_by_id == user.id))


def _validate(data, *, partial=False, kind: str | None = None) -> dict:
    out = {}
    if "kind" in data or not partial:
        kind_value = str(data.get("kind") or "block")
        if kind_value not in ("component", "block"):
            raise ValidationError({"kind": "kind 只能是 component 或 block"})
        out["kind"] = kind_value
    effective_kind = out.get("kind") or kind or "block"
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
        if effective_kind == "component":
            validate_component_payload(payload, require_source=False)
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
    # 沙箱：组件永久启用（sandboxed=True）；区块可显式关闭。
    if effective_kind == "component":
        if "sandboxed" in data and not bool(data.get("sandboxed")):
            raise ValidationError({"sandboxed": "组件必须启用沙箱"})
        out["sandboxed"] = True
    elif "sandboxed" in data:
        out["sandboxed"] = bool(data.get("sandboxed"))
    elif not partial:
        out["sandboxed"] = False
    # 策略：组件只允许 network/allowed_origins/timeout_ms 可调，其余强制收紧。
    if "policy" in data or (effective_kind == "component" and ("kind" in data or not partial)):
        raw_policy = data.get("policy")
        if raw_policy is None and effective_kind == "component":
            raw_policy = DEFAULT_COMPONENT_POLICY
        out["policy"] = normalize_policy(raw_policy, kind=effective_kind)
    elif effective_kind != "component" and not partial:
        out["policy"] = normalize_policy(data.get("policy"), kind=effective_kind)
    return out


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def market_items(request):
    if request.method == "GET":
        qs = MarketItem.objects.select_related("created_by", "source_app", "signer")
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
    item = get_object_or_404(MarketItem.objects.select_related("created_by", "source_app", "signer"), pk=pk)
    if request.method == "GET":
        if item.visibility == "private" and item.created_by_id != request.user.id and not is_platform_admin(request.user):
            raise PermissionDenied("无权查看该市场条目")
        return Response(_payload(item))
    if not _can_manage(request.user, item):
        raise PermissionDenied("只能管理自己创建的市场条目")
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = _validate(request.data, partial=True, kind=item.kind)
    if "slug" in data and MarketItem.objects.filter(kind=item.kind, slug=data["slug"]).exclude(pk=item.pk).exists():
        raise ValidationError({"slug": "该 kind 下 slug 已存在"})
    for key, value in data.items():
        setattr(item, key, value)
    item.save()
    return Response(_payload(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def market_sign(request, pk: int):
    """POST /api/market/items/{id}/sign/ — 条目所有者/平台管理员签名组件。

    签名对象是服务端存储的 canonical JSON（见 market/signing.py），客户端
    不能提交 code_hash/signature。可选 body.policy 会在签名前规范化并保存。
    """
    item = get_object_or_404(
        MarketItem.objects.select_related("created_by", "signer"), pk=pk,
    )
    if not _can_manage(request.user, item):
        raise PermissionDenied("只有条目创建者或平台管理员可以签名")

    if item.kind == "component":
        validate_component_payload(item.payload, require_source=True)
        item.sandboxed = True
        raw_policy = request.data.get("policy", item.policy)
        item.policy = normalize_policy(raw_policy, kind="component")
    elif "policy" in request.data:
        item.policy = normalize_policy(request.data.get("policy"), kind=item.kind)

    sign_item(item, request.user)
    item.save(update_fields=[
        "sandboxed", "policy", "code_hash", "signature", "signed_at", "signer", "updated_at",
    ])
    return Response(_payload(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def market_install(request, pk: int):
    try:
        app_id = int(request.data.get("app_id"))
    except (TypeError, ValueError):
        raise ValidationError({"app_id": "目标应用不存在"})

    with transaction.atomic():
        # PostgreSQL 不允许 FOR UPDATE 锁定外连接的可空侧，故不在锁定查询里
        # select_related("signer"/"created_by")；后续按需懒加载。
        item = get_object_or_404(
            MarketItem.objects.select_for_update(),
            pk=pk,
        )
        if item.status != "published" or item.visibility != "public":
            if not _can_manage(request.user, item):
                raise PermissionDenied("该市场条目未发布")
        try:
            app = App.objects.get(pk=app_id)
        except App.DoesNotExist:
            raise ValidationError({"app_id": "目标应用不存在"})
        require_app_role(request.user, app, "editor")

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

        # 组件：必须签名且签名覆盖的 payload 未被篡改/修改。
        valid, reason = verify_item(item)
        if not valid:
            raise ValidationError({"signature": reason})
        if not item.sandboxed:
            raise ValidationError({"signature": "组件必须启用沙箱后才能安装"})
        payload = item.payload
        validate_component_payload(payload, require_source=True)
        source_url = validate_source_url(payload.get("source_url"))
        element = element_for(payload, item.slug)

        requested_name = str(payload.get("name") or "").strip()
        name = requested_name if requested_name.startswith("wp-market-") else f"wp-market-{item.slug}"
        name = name[:128]
        existing = ComponentMeta.objects.select_for_update().filter(name=name).first()
        if existing is not None:
            marker = {}
            if isinstance(existing.payload_schema, dict):
                raw_marker = existing.payload_schema.get("x-wp-market")
                marker = raw_marker if isinstance(raw_marker, dict) else {}
            if existing.is_builtin:
                raise ValidationError({"name": "不能覆盖平台内置组件"})
            if existing.source != "custom-sandbox" or marker.get("market_item_id") != item.pk:
                raise ValidationError({"name": "组件名已被其他自定义组件占用，无法安装"})

        base_payload_schema = payload.get("payload_schema")
        if not isinstance(base_payload_schema, dict):
            base_payload_schema = {}
        marker = {
            "schema": SIGNING_SCHEMA,
            "market_item_id": item.pk,
            "kind": "component",
            "sandboxed": True,
            "source": "custom-sandbox",
            "source_url": source_url,
            "element": element,
            "policy": item.policy or {},
            "code_hash": item.code_hash,
            "signature": item.signature,
            "signed_at": item.signed_at.isoformat() if item.signed_at else None,
            "signed_by": item.signer.username if item.signer_id and item.signer else "",
        }
        defaults = {
            "label": str(payload.get("label") or item.name)[:128],
            "type": "custom",
            "category": str(payload.get("category") or "custom")[:64],
            "version": str(payload.get("version") or "1.0.0")[:32],
            "props_schema": payload.get("props_schema") if isinstance(payload.get("props_schema"), dict) else {},
            "style_schema": payload.get("style_schema") if isinstance(payload.get("style_schema"), dict) else {},
            "default_props": payload.get("default_props") if isinstance(payload.get("default_props"), dict) else {},
            "payload_schema": {**base_payload_schema, "x-wp-market": marker},
            "events": payload.get("events") if isinstance(payload.get("events"), list) else [],
            "accept_children": payload.get("accept_children") if isinstance(payload.get("accept_children"), list) else [],
            "is_container": bool(payload.get("is_container")),
            "is_form_field": bool(payload.get("is_form_field")),
            "icon": str(payload.get("icon") or "SetUp")[:64],
            "source": "custom-sandbox",
            "element": element,
            "source_url": source_url,
            "is_custom": True,
            "is_enabled": True,
        }
        if existing is None:
            meta = ComponentMeta.objects.create(name=name, **defaults)
            created = True
        else:
            for key, value in defaults.items():
                setattr(existing, key, value)
            existing.save()
            meta = existing
            created = False
        invalidate_registry_cache()
        MarketItem.objects.filter(pk=item.pk).update(installs=item.installs + 1)
        return Response({
            "kind": "component",
            "component": meta.name,
            "created": created,
            "sandboxed": True,
            "source": "custom-sandbox",
            "element": element,
            "code_hash": item.code_hash,
            "signature": item.signature,
            "policy": item.policy or {},
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
