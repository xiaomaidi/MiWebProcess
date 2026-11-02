"""WebSocket 消费者：应用房间广播 + 主题订阅 + 在线状态。

连接: ws://host/ws/{app_id}/?token=<JWT>
客户端 → 服务端:
  {"type": "subscribe", "topics": ["devices/+/telemetry", "chat/#"]}
  {"type": "unsubscribe", "topics": ["devices/+/telemetry"]}
  {"type": "ping"}
  {"type": "presence"}
  {"type": "<任意>", "payload": ..., "topic": "devices/1/telemetry"}
服务端 → 客户端:
  {"type": "joined" | "realtime" | "presence" | "pong" | "subscribed" | "error", ...}
"""
from __future__ import annotations

import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.tokens import AccessToken

DEFAULT_TOPICS = ["#"]


def _group_for(app_id: int) -> str:
    return f"app_{app_id}"


@database_sync_to_async
def _resolve_member(token_str: str, app_id: int):
    """校验 JWT 与 app 成员身份；返回 (user, app) 或抛异常。"""
    from django.contrib.auth import get_user_model

    from appcore.models import App
    from core.permissions import get_app_role

    token = AccessToken(token_str)  # 过期/无效会抛 TokenError
    user = get_user_model().objects.filter(id=token.get("user_id"), is_active=True).first()
    if user is None:
        raise ValueError("user not found")
    app = App.objects.filter(id=app_id).first()
    if app is None:
        raise ValueError("app not found")
    role = get_app_role(user, app)
    is_admin = bool(getattr(user, "is_superuser", False)) or bool(getattr(user, "is_platform_admin", False))
    if role is None and not is_admin:
        raise PermissionError("not a member")
    return user, app


def topic_matches(topic_filter: str, topic: str) -> bool:
    if not topic_filter:
        return False
    if topic_filter in ("#", "*"):
        return True
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


class AppWebSocket(AsyncWebsocketConsumer):
    async def connect(self):
        raw_query = self.scope.get("query_string", b"")
        query = raw_query.decode("utf-8") if isinstance(raw_query, (bytes, bytearray)) else str(raw_query or "")
        params = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
        token_str = params.get("token", "")

        route = self.scope.get("url_route") or {}
        route_kwargs = getattr(route, "kwargs", None)
        if route_kwargs is None and isinstance(route, dict):
            route_kwargs = route.get("kwargs") or {}
        app_id_raw = (route_kwargs or {}).get("app_id", "")
        try:
            app_id = int(app_id_raw)
        except (TypeError, ValueError):
            await self.close(code=4400)
            return
        if not token_str:
            await self.close(code=4401)  # 缺少 token
            return
        try:
            user, app = await _resolve_member(token_str, app_id)
        except Exception:
            await self.close(code=4403)  # 无效 token 或非成员
            return
        self._user_id = user.id
        self._username = user.username
        self._app_id = app.id
        self._topics = set(DEFAULT_TOPICS)
        group = _group_for(app.id)
        await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()
        count = await self._bump_presence(1)
        await self.send(
            text_data=json.dumps({
                "type": "joined",
                "payload": {"app_id": app.id, "user": user.username, "presence": count, "topics": sorted(self._topics)},
                "from": "server",
                "ts": _now(),
            }, ensure_ascii=False)
        )
        await self.channel_layer.group_send(
            group,
            {"type": "app_broadcast", "message": json.dumps(
                {"type": "presence", "payload": {"count": count, "event": "join", "user": user.username},
                 "from": "server", "ts": _now()}, ensure_ascii=False)},
        )

    async def disconnect(self, code: int):
        try:
            group = _group_for(self._app_id)
            await self.channel_layer.group_discard(group, self.channel_name)
        except Exception:
            pass
        try:
            count = await self._bump_presence(-1)
            await self.channel_layer.group_send(
                _group_for(self._app_id),
                {"type": "app_broadcast", "message": json.dumps(
                    {"type": "presence", "payload": {"count": count, "event": "leave"},
                     "from": "server", "ts": _now()}, ensure_ascii=False)},
            )
        except Exception:
            pass

    async def _bump_presence(self, delta: int) -> int:
        from realtime.services import bump_presence

        return await database_sync_to_async(bump_presence)(self._app_id, delta)

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return
        try:
            data = json.loads(text_data)
        except (ValueError, TypeError):
            await self._error("invalid JSON")
            return
        if not isinstance(data, dict) or "type" not in data:
            await self._error("需要 type 字段")
            return

        msg_type = str(data.get("type"))
        if msg_type == "ping":
            await self.send(text_data=json.dumps({"type": "pong", "payload": {"ts": _now()}, "from": "server", "ts": _now()}))
            return
        if msg_type == "presence":
            count = await self._bump_presence(0)
            await self.send(text_data=json.dumps({"type": "presence", "payload": {"count": count}, "from": "server", "ts": _now()}))
            return
        if msg_type in ("subscribe", "unsubscribe"):
            topics = data.get("topics") or ([data.get("topic")] if data.get("topic") else [])
            if not isinstance(topics, list):
                await self._error("topics 必须是数组")
                return
            cleaned = {str(t).strip() for t in topics if str(t).strip()}
            if msg_type == "subscribe":
                self._topics.update(cleaned)
            else:
                self._topics.difference_update(cleaned)
                if not self._topics:
                    self._topics = set(DEFAULT_TOPICS)
            await self.send(text_data=json.dumps({
                "type": "subscribed", "payload": {"topics": sorted(self._topics)}, "from": "server", "ts": _now(),
            }, ensure_ascii=False))
            return

        topic = str(data.get("topic") or "chat")
        message = {
            "type": msg_type,
            "payload": data.get("payload"),
            "from": self._username,
            "ts": _now(),
            "topic": topic,
        }
        group = _group_for(self._app_id)
        await self.channel_layer.group_send(
            group,
            {"type": "app_broadcast", "message": json.dumps(message, ensure_ascii=False)},
        )
        # 客户端消息落库（设备调试/图表可回放最近消息）。
        try:
            await database_sync_to_async(self._persist_message)(topic, message["payload"])
        except Exception:
            pass

    def _persist_message(self, topic: str, payload) -> None:
        from appcore.models import App
        from realtime.models import RealtimeMessage

        app = App.objects.filter(id=self._app_id).first()
        if app is None:
            return
        RealtimeMessage.objects.create(
            app=app, topic=topic,
            payload=payload if isinstance(payload, (dict, list)) else {"value": payload},
            direction="out", transport="ws", sender=self._username,
        )

    async def _error(self, message: str):
        await self.send(text_data=json.dumps({"type": "error", "payload": message, "from": "server", "ts": _now()}, ensure_ascii=False))

    async def app_broadcast(self, event):
        raw = event["message"]
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            await self.send(text_data=raw)
            return
        topic = data.get("topic")
        if topic and not any(topic_matches(f, topic) for f in self._topics):
            return
        await self.send(text_data=raw)


def _now() -> int:
    import time

    return int(time.time() * 1000)
