"""实时通道服务：消息发布、落库、广播与清理。"""
from __future__ import annotations

from realtime.models import RealtimeChannel, RealtimeMessage
from wp_utils import broadcast_to_app


def channel_matches(channel: RealtimeChannel, topic: str) -> bool:
    from realtime.mqtt import topic_matches

    return topic_matches(channel.topic, topic)


def publish_message(
    app, *, topic: str, payload, channel: RealtimeChannel | None = None,
    user=None, qos: int | None = None, retain: bool | None = None,
) -> dict:
    """发送一条实时消息：落库 → WS 房间广播 → （可选）MQTT publish。"""
    sender = getattr(user, "username", "") if user is not None else ""
    topic = str(topic or "").strip()
    if not topic:
        topic = channel.topic if channel is not None else "app"
    record_message = RealtimeMessage.objects.create(
        app=app, channel=channel, topic=topic,
        payload=payload if isinstance(payload, (dict, list)) else {"value": payload},
        direction="out", transport="ws", sender=sender,
    )
    broadcast_to_app(
        app.id,
        {
            "type": "realtime",
            "payload": payload,
            "extra": {"topic": topic, "direction": "out", "sender": sender, "channel": channel.slug if channel else ""},
        },
        sender=sender,
    )

    transport = "ws"
    if channel is not None and channel.kind in ("mqtt", "both"):
        from realtime.mqtt import get_bridge

        bridge = get_bridge()
        if bridge.publish(topic, payload, qos=qos if qos is not None else channel.qos, retain=bool(retain if retain is not None else channel.retain)):
            transport = "mqtt+ws"
            RealtimeMessage.objects.filter(id=record_message.id).update(transport=transport)
    return {
        "ok": True,
        "id": record_message.id,
        "topic": topic,
        "transport": transport,
        "channel_id": channel.id if channel else None,
        "created_at": record_message.created_at,
    }


def cleanup_messages(app=None, keep: int = 500) -> int:
    """只保留每个应用最近 N 条消息。"""
    qs = RealtimeMessage.objects.all()
    if app is not None:
        qs = qs.filter(app=app)
    ids = list(qs.values_list("id", flat=True))
    if len(ids) <= keep:
        return 0
    extra = ids[keep:]
    deleted, _ = RealtimeMessage.objects.filter(id__in=extra).delete()
    return deleted


def presence_count(app_id: int) -> int:
    from django.core.cache import cache

    try:
        return int(cache.get(f"ws:presence:{app_id}") or 0)
    except (TypeError, ValueError):
        return 0


def bump_presence(app_id: int, delta: int) -> int:
    from django.core.cache import cache

    key = f"ws:presence:{app_id}"
    try:
        cache.add(key, 0, 86400)
        if delta > 0:
            count = cache.incr(key, delta)
        else:
            current = int(cache.get(key) or 0)
            count = max(0, current + delta)
            cache.set(key, count, 86400)
        return count
    except Exception:
        return 0
