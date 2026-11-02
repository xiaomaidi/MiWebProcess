"""MQTT 桥接：可选依赖 paho-mqtt。

设计原则：
- 未安装 paho 或未配置 ``MQTT_BROKER_URL`` 时，整个模块降级为「仅 WebSocket」，
  发布消息仍然进入平台房间并落库，不会报错；
- 桥接进程通过 ``python manage.py mqtt_bridge`` 单独运行（避免每个 web worker 都连 broker）；
- broker 收到的消息按 ``RealtimeChannel.topic`` 过滤器匹配到应用后广播到 ``app_{id}`` 房间。
"""
from __future__ import annotations

import json
import logging
import threading
import time

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from realtime.models import RealtimeChannel, RealtimeMessage

logger = logging.getLogger("realtime.mqtt")

try:  # pragma: no cover - 可选依赖
    import paho.mqtt.client as mqtt  # type: ignore
except Exception:  # noqa: BLE001
    mqtt = None


def broker_config() -> dict:
    return {
        "url": str(getattr(settings, "MQTT_BROKER_URL", "") or ""),
        "username": str(getattr(settings, "MQTT_USERNAME", "") or ""),
        "password": str(getattr(settings, "MQTT_PASSWORD", "") or ""),
        "client_id": str(getattr(settings, "MQTT_CLIENT_ID", "") or f"webprocess-{int(time.time())}"),
        "enabled": bool(getattr(settings, "MQTT_ENABLED", False)),
    }


def is_available() -> bool:
    return mqtt is not None


def parse_broker(url: str) -> tuple[str, int]:
    text = str(url or "").strip()
    if "://" in text:
        text = text.split("://", 1)[1]
    text = text.rstrip("/")
    if ":" in text:
        host, port = text.rsplit(":", 1)
        try:
            return host, int(port)
        except ValueError:
            return text, 1883
    return text or "127.0.0.1", 1883


def topic_matches(topic_filter: str, topic: str) -> bool:
    """MQTT 通配符匹配：+ 单层，# 多层。"""
    if not topic_filter:
        return False
    if topic_filter == topic:
        return True
    f_parts = topic_filter.split("/")
    t_parts = str(topic or "").split("/")
    for i, part in enumerate(f_parts):
        if part == "#":
            return True
        if i >= len(t_parts):
            return False
        if part != "+" and part != t_parts[i]:
            return False
    return len(f_parts) == len(t_parts)


def _broadcast(app_id: int, topic: str, payload, *, direction: str, sender: str = "mqtt") -> None:
    from wp_utils import broadcast_to_app

    broadcast_to_app(
        app_id,
        {
            "type": "realtime",
            "payload": payload,
            "extra": {"topic": topic, "direction": direction, "sender": sender},
        },
        sender=sender,
    )


def record_message(
    *, app, channel: RealtimeChannel | None, topic: str, payload, direction: str,
    transport: str = "ws", sender: str = "",
) -> RealtimeMessage:
    try:
        return RealtimeMessage.objects.create(
            app=app, channel=channel, topic=topic, payload=payload if isinstance(payload, (dict, list)) else {"value": payload},
            direction=direction, transport=transport, sender=sender,
        )
    except Exception:
        logger.exception("record_message failed")
        return RealtimeMessage(app=app, topic=topic, payload={}, direction=direction)


class MqttBridge:
    """单例 MQTT 客户端（管理命令内运行）。"""

    def __init__(self):
        self.client = None
        self.connected = False
        self.last_error = ""
        self.started_at = None
        self._lock = threading.Lock()

    def start(self) -> bool:
        cfg = broker_config()
        if not cfg["enabled"] or not cfg["url"]:
            self.last_error = "未启用 MQTT（MQTT_ENABLED=1 + MQTT_BROKER_URL）"
            return False
        if mqtt is None:
            self.last_error = "未安装 paho-mqtt（pip install paho-mqtt）"
            return False
        host, port = parse_broker(cfg["url"])
        try:
            with self._lock:
                self.client = mqtt.Client(client_id=cfg["client_id"], clean_session=True)
                if cfg["username"]:
                    self.client.username_pw_set(cfg["username"], cfg["password"])
                self.client.on_connect = self._on_connect
                self.client.on_disconnect = self._on_disconnect
                self.client.on_message = self._on_message
                self.client.connect(host, port, keepalive=30)
                self.client.loop_start()
            self.started_at = timezone.now()
            cache.set("mqtt:bridge:status", {"connected": True, "at": str(self.started_at)}, 300)
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)[:300]
            logger.exception("mqtt connect failed")
            return False

    def stop(self) -> None:
        with self._lock:
            if self.client is not None:
                try:
                    self.client.loop_stop()
                    self.client.disconnect()
                except Exception:
                    pass
            self.client = None
            self.connected = False
        cache.delete("mqtt:bridge:status")

    def _on_connect(self, client, userdata, flags, rc):  # noqa: ANN001
        self.connected = rc == 0
        if not self.connected:
            self.last_error = f"connect rc={rc}"
            return
        topics = set(
            RealtimeChannel.objects.filter(enabled=True, kind__in=("mqtt", "both"))
            .values_list("topic", flat=True)
        )
        for topic in topics:
            if topic:
                client.subscribe(topic, qos=1)
        logger.info("mqtt connected, subscribed %s topics", len(topics))

    def _on_disconnect(self, client, userdata, rc):  # noqa: ANN001
        self.connected = False
        self.last_error = f"disconnected rc={rc}"

    def _on_message(self, client, userdata, msg):  # noqa: ANN001
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            payload = {"value": msg.payload.decode("utf-8", errors="replace")}
        channels = list(
            RealtimeChannel.objects.filter(enabled=True, kind__in=("mqtt", "both")).select_related("app")
        )
        seen_apps = set()
        for channel in channels:
            if not topic_matches(channel.topic, topic):
                continue
            seen_apps.add(channel.app_id)
            record_message(
                app=channel.app, channel=channel, topic=topic, payload=payload,
                direction="in", transport="mqtt", sender="mqtt",
            )
            _broadcast(channel.app_id, topic, payload, direction="in", sender="mqtt")
        logger.debug("mqtt message %s -> %s apps", topic, len(seen_apps))

    def publish(self, topic: str, payload, qos: int = 0, retain: bool = False) -> bool:
        if self.client is None or not self.connected:
            return False
        body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        info = self.client.publish(topic, body, qos=qos, retain=retain)
        return info.rc == 0

    def status(self) -> dict:
        cfg = broker_config()
        return {
            "available": is_available(),
            "enabled": cfg["enabled"],
            "broker": cfg["url"],
            "connected": bool(self.connected),
            "client_id": cfg["client_id"],
            "last_error": self.last_error,
            "started_at": self.started_at,
        }


_bridge: MqttBridge | None = None


def get_bridge() -> MqttBridge:
    global _bridge
    if _bridge is None:
        _bridge = MqttBridge()
    return _bridge
