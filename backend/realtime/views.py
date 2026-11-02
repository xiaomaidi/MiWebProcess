"""实时通道 REST 端点（MQTT + WebSocket）。"""
from __future__ import annotations

from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import write_audit_log
from realtime.models import RealtimeChannel, RealtimeMessage
from realtime.mqtt import broker_config, get_bridge, is_available
from realtime.serializers import RealtimeChannelSerializer, RealtimeMessageSerializer
from realtime.services import cleanup_messages, presence_count, publish_message
from wp_utils import get_app, require_app_role


def _app_from(request):
    app_id = request.query_params.get("app_id") or (request.data.get("app_id") if hasattr(request, "data") else None)
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    return get_app(int(app_id))


def _validate_topic(topic: str) -> str:
    text = str(topic or "").strip()
    if not text:
        raise ValidationError({"detail": "topic 必填"})
    if " " in text:
        raise ValidationError({"detail": "topic 不能包含空格"})
    if len(text) > 200:
        raise ValidationError({"detail": "topic 过长（最多 200 字符）"})
    return text


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def channel_list_create(request):
    """GET/POST /api/realtime/channels/?app_id="""
    app = _app_from(request)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        qs = (
            RealtimeChannel.objects.filter(app=app)
            .annotate(message_count=Count("messages"))
            .order_by("id")
        )
        return Response({"count": qs.count(), "results": RealtimeChannelSerializer(qs, many=True).data})

    require_app_role(request.user, app, "editor")
    name = str(request.data.get("name") or "").strip()
    if not name:
        raise ValidationError({"detail": "name 必填"})
    kind = str(request.data.get("kind") or "both")
    if kind not in dict(RealtimeChannel.KIND_CHOICES):
        raise ValidationError({"detail": "kind 必须是 mqtt/ws/both"})
    channel = RealtimeChannel.objects.create(
        app=app,
        name=name[:120],
        slug=str(request.data.get("slug") or "")[:80],
        kind=kind,
        topic=_validate_topic(request.data.get("topic")),
        description=str(request.data.get("description") or "")[:300],
        qos=int(request.data.get("qos") or 0),
        retain=bool(request.data.get("retain", False)),
        enabled=bool(request.data.get("enabled", True)),
        created_by=request.user,
    )
    write_audit_log(
        user=request.user, action="realtime.channel.create", object_type="realtime_channel",
        object_id=channel.id, app_id=app.id, after=RealtimeChannelSerializer(channel).data, request=request,
    )
    return Response(RealtimeChannelSerializer(channel).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def channel_detail(request, pk: int):
    channel = get_object_or_404(RealtimeChannel.objects.select_related("app"), pk=pk)
    require_app_role(request.user, channel.app, "viewer")
    if request.method == "GET":
        return Response(RealtimeChannelSerializer(channel).data)
    require_app_role(request.user, channel.app, "editor")
    if request.method == "DELETE":
        channel.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    for field in ("name", "description"):
        if field in request.data:
            setattr(channel, field, str(request.data.get(field) or "")[:300])
    if "topic" in request.data:
        channel.topic = _validate_topic(request.data.get("topic"))
    if "kind" in request.data:
        kind = str(request.data.get("kind"))
        if kind not in dict(RealtimeChannel.KIND_CHOICES):
            raise ValidationError({"detail": "kind 必须是 mqtt/ws/both"})
        channel.kind = kind
    if "qos" in request.data:
        channel.qos = max(0, min(2, int(request.data.get("qos") or 0)))
    if "retain" in request.data:
        channel.retain = bool(request.data.get("retain"))
    if "enabled" in request.data:
        channel.enabled = bool(request.data.get("enabled"))
    channel.save()
    return Response(RealtimeChannelSerializer(channel).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def channel_publish(request, pk: int):
    """POST /api/realtime/channels/{id}/publish/ {payload, qos?, retain?}"""
    channel = get_object_or_404(RealtimeChannel.objects.select_related("app"), pk=pk)
    require_app_role(request.user, channel.app, "editor")
    if not channel.enabled:
        raise ValidationError({"detail": "通道已停用"})
    payload = request.data.get("payload")
    if payload is None:
        payload = request.data.get("message")
    if payload is None:
        raise ValidationError({"detail": "payload 必填"})
    result = publish_message(
        channel.app, topic=channel.topic, payload=payload, channel=channel,
        user=request.user, qos=request.data.get("qos"), retain=request.data.get("retain"),
    )
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def publish_by_topic(request):
    """POST /api/realtime/publish/ {app_id, topic, payload, channel_id?}"""
    app = _app_from(request)
    require_app_role(request.user, app, "editor")
    topic = _validate_topic(request.data.get("topic"))
    payload = request.data.get("payload")
    channel = None
    if request.data.get("channel_id"):
        channel = get_object_or_404(RealtimeChannel, pk=request.data.get("channel_id"), app=app)
    result = publish_message(app, topic=topic, payload=payload, channel=channel, user=request.user)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def channel_messages(request, pk: int):
    """GET /api/realtime/channels/{id}/messages/?limit=50"""
    channel = get_object_or_404(RealtimeChannel.objects.select_related("app"), pk=pk)
    require_app_role(request.user, channel.app, "viewer")
    limit = min(200, max(1, int(request.query_params.get("limit") or 50)))
    qs = RealtimeMessage.objects.filter(channel=channel).order_by("-created_at")[:limit]
    return Response({"count": len(qs), "results": RealtimeMessageSerializer(qs, many=True).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def app_messages(request):
    """GET /api/realtime/messages/?app_id=&limit=100"""
    app = _app_from(request)
    require_app_role(request.user, app, "viewer")
    limit = min(500, max(1, int(request.query_params.get("limit") or 100)))
    qs = RealtimeMessage.objects.filter(app=app).select_related("channel").order_by("-created_at")[:limit]
    return Response({"count": len(qs), "results": RealtimeMessageSerializer(qs, many=True).data})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def realtime_status(request):
    """GET /api/realtime/status/ — MQTT 桥接状态 + 在线人数。"""
    app_id = request.query_params.get("app_id")
    bridge = get_bridge()
    payload = {
        **bridge.status(),
        "paho_installed": is_available(),
        "ws_path": "/ws/{app_id}/?token=<JWT>",
        "presence": presence_count(int(app_id)) if app_id else 0,
    }
    cfg = broker_config()
    payload["broker_configured"] = bool(cfg["url"] and cfg["enabled"])
    return Response(payload)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def realtime_cleanup(request):
    """POST /api/realtime/cleanup/ {app_id?, keep=500} — 平台管理员。"""
    from wp_utils import is_platform_admin_full

    if not is_platform_admin_full(request.user):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("仅平台管理员可清理消息")
    app = _app_from(request) if (request.data.get("app_id")) else None
    keep = min(5000, max(10, int(request.data.get("keep") or 500)))
    deleted = cleanup_messages(app, keep=keep)
    return Response({"ok": True, "deleted": deleted, "keep": keep})
