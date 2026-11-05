"""设计器节点锁 WebSocket 消费者（服务端权威）。

连接: ``ws://host/ws/designer-lock/{page_id}/?token=<JWT>&session=<uuid>``

- ``token``：JWT access token；服务端据此解析用户与页面所属应用。
- ``session``：可选的浏览器会话 UUID（推荐）。同一 session 重连后仍持有
  未过期的锁；不传则服务端生成，客户端无法跨连接恢复自己的锁。

客户端 → 服务端::

    {"type": "acquire",   "nodeId": "node-1", "requestId": "r1"}
    {"type": "release",   "nodeId": "node-1"}
    {"type": "heartbeat"}
    {"type": "selection", "ids": ["node-1", "node-2"]}
    {"type": "cursor",    "x": 120, "y": 40}
    {"type": "ping"}

服务端 → 客户端::

    {"type": "snapshot", "locks": [...], "self": {...}}
    {"type": "lock-granted", "nodeId": ..., "expiresAt": ...}
    {"type": "lock-denied",  "nodeId": ..., "owner": {...}}
    {"type": "lock", "action": "acquire"|"release", "nodeId": ..., "userId": ...}
    {"type": "heartbeat-ack", "count": 2, "expiresAt": ...}
    {"type": "selection", "userId": ..., "ids": [...]}
    {"type": "cursor", "userId": ..., "x": ..., "y": ...}
    {"type": "error", "code": "...", "message": "..."}
    {"type": "pong"}
"""
from __future__ import annotations

import json
import math
import time
import uuid
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import lock_service

GROUP_PREFIX = "designer_lock"


def group_for(page_id: int) -> str:
    return f"{GROUP_PREFIX}_{page_id}"


@database_sync_to_async
def resolve_page(token_str: str, page_id: int):
    """校验 JWT、页面所属应用与 viewer 权限；返回 (user, page, role)。"""
    from django.contrib.auth import get_user_model
    from rest_framework_simplejwt.tokens import AccessToken

    from pages.models import Page
    from wp_utils import require_app_role

    token = AccessToken(token_str)
    user = get_user_model().objects.filter(id=token.get("user_id"), is_active=True).first()
    if user is None:
        raise ValueError("user not found")
    page = Page.objects.select_related("app").filter(id=page_id).first()
    if page is None:
        raise LookupError("page not found")
    role = require_app_role(user, page.app, "viewer")
    return user, page, role


class DesignerLockConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.page_id = 0
        self.user_id = 0
        self.username = ""
        self.session_id: uuid.UUID | None = None
        self.group_name = ""
        self.is_editor = False
        self._last_cursor_at = 0.0
        self._conn_key = ""

        query = parse_qs(self._raw_query(), keep_blank_values=True)
        token_str = (query.get("token") or [""])[0].strip()
        session_raw = (query.get("session") or query.get("sessionId") or [""])[0]

        route = self.scope.get("url_route") or {}
        kwargs = getattr(route, "kwargs", None)
        if kwargs is None and isinstance(route, dict):
            kwargs = route.get("kwargs") or {}
        try:
            page_id = int((kwargs or {}).get("page_id", ""))
        except (TypeError, ValueError):
            await self.close(code=4400)
            return
        if not token_str:
            await self.close(code=4401)
            return

        try:
            user, page, role = await resolve_page(token_str, page_id)
        except LookupError:
            await self.close(code=4404)
            return
        except Exception:
            # JWT 无效 / 非应用成员 / 无 viewer 权限均按 4403 处理。
            await self.close(code=4403)
            return

        self.page_id = page.id
        self.user_id = user.id
        self.username = user.username
        self.is_editor = role in ("editor", "owner")
        self.session_id = lock_service.normalize_session_id(session_raw) or uuid.uuid4()
        self.group_name = group_for(self.page_id)
        self._conn_key = f"designer_lock:conn:{self.page_id}:{self.session_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        # 同一 session 只允许「最新连接」在断开时释放锁，避免重连竞态。
        await self._claim_session()
        snapshot = await self._snapshot()
        await self._send(
            {
                "type": "snapshot",
                "pageId": self.page_id,
                "self": {
                    "userId": self.user_id,
                    "username": self.username,
                    "sessionId": str(self.session_id),
                    "isEditor": self.is_editor,
                },
                "locks": snapshot["locks"],
                # 便于客户端直接识别“自己的锁”，与逐条 sessionId 比对等价。
                "ownedNodeIds": snapshot["ownedNodeIds"],
            }
        )

    async def disconnect(self, code: int):
        try:
            if self.group_name:
                await self.channel_layer.group_discard(self.group_name, self.channel_name)
        except Exception:
            pass
        try:
            released = await self._release_on_disconnect()
        except Exception:
            released = []
        for payload in released:
            await self._broadcast({"type": "lock", "action": "release", **payload})

    # ------------------------------------------------------------------ 消息分发
    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return
        try:
            data = json.loads(text_data)
        except (ValueError, TypeError):
            await self._error("invalid-json", "消息必须是 JSON")
            return
        if not isinstance(data, dict):
            await self._error("invalid-message", "消息必须是对象")
            return
        msg_type = str(data.get("type") or "").strip().lower()
        if not msg_type:
            await self._error("invalid-message", "缺少 type")
            return
        try:
            if msg_type == "ping":
                await self._send({"type": "pong", "ts": _now_ms()})
            elif msg_type == "acquire":
                await self._on_acquire(data)
            elif msg_type == "release":
                await self._on_release(data)
            elif msg_type == "heartbeat":
                await self._on_heartbeat()
            elif msg_type == "selection":
                await self._on_selection(data)
            elif msg_type == "cursor":
                await self._on_cursor(data)
            else:
                await self._error("unknown-type", f"未知消息类型: {msg_type}")
        except Exception:
            await self._error("internal-error", "服务端处理消息失败")

    async def _on_acquire(self, data):
        node_id = lock_service.normalize_node_id(data.get("nodeId"))
        request_id = data.get("requestId")
        if node_id is None:
            await self._send(
                {"type": "error", "code": "invalid-node", "nodeId": data.get("nodeId"), "message": "nodeId 非法"}
            )
            return
        if not self.is_editor:
            await self._send(
                {
                    "type": "error",
                    "code": "forbidden",
                    "nodeId": node_id,
                    "requestId": request_id,
                    "message": "仅编辑者可以获取锁",
                }
            )
            return
        result = await database_sync_to_async(lock_service.acquire_lock)(
            self.page_id, await self._get_user(), self.session_id, node_id
        )
        if not result["granted"]:
            await self._send(
                {
                    "type": "lock-denied",
                    "nodeId": node_id,
                    "requestId": request_id,
                    "owner": result.get("owner"),
                }
            )
            return
        lock = result["lock"]
        await self._send(
            {
                "type": "lock-granted",
                "nodeId": lock["nodeId"],
                "expiresAt": lock["expiresAt"],
                "requestId": request_id,
            }
        )
        await self._broadcast(
            {
                "type": "lock",
                "action": "acquire",
                "nodeId": lock["nodeId"],
                "userId": lock["userId"],
                "username": lock["username"],
                "sessionId": lock["sessionId"],
                "expiresAt": lock["expiresAt"],
            }
        )

    async def _on_release(self, data):
        node_id = lock_service.normalize_node_id(data.get("nodeId"))
        if node_id is None:
            await self._error("invalid-node", "nodeId 非法")
            return
        if not self.is_editor:
            await self._send(
                {"type": "error", "code": "forbidden", "nodeId": node_id, "message": "仅编辑者可以释放锁"}
            )
            return
        payload = await database_sync_to_async(lock_service.release_lock)(
            self.page_id, self.user_id, self.session_id, node_id, self.username
        )
        if payload is not None:
            await self._broadcast({"type": "lock", "action": "release", **payload})

    async def _on_heartbeat(self):
        result = await database_sync_to_async(lock_service.heartbeat)(
            self.page_id, self.user_id, self.session_id
        )
        await self._send(
            {
                "type": "heartbeat-ack",
                "count": result["count"],
                "expiresAt": result["expiresAt"],
            }
        )

    async def _on_selection(self, data):
        ids = lock_service.normalize_selection_ids(data.get("ids"))
        if ids is None:
            await self._error("invalid-selection", "ids 必须是字符串数组")
            return
        await self._broadcast(
            {
                "type": "selection",
                "userId": self.user_id,
                "username": self.username,
                "sessionId": str(self.session_id),
                "ids": ids,
            }
        )

    async def _on_cursor(self, data):
        # 每连接 50ms 限流；超频消息静默丢弃，避免拖垮群组广播。
        now = time.monotonic()
        if (now - self._last_cursor_at) * 1000.0 < lock_service.CURSOR_MIN_INTERVAL_MS:
            return
        try:
            x = float(data.get("x"))
            y = float(data.get("y"))
        except (TypeError, ValueError):
            return
        if not (math.isfinite(x) and math.isfinite(y)):
            return
        self._last_cursor_at = now
        await self._broadcast(
            {
                "type": "cursor",
                "userId": self.user_id,
                "username": self.username,
                "sessionId": str(self.session_id),
                "x": max(-1_000_000.0, min(1_000_000.0, x)),
                "y": max(-1_000_000.0, min(1_000_000.0, y)),
            }
        )

    # ------------------------------------------------------------------ 群组
    async def designer_lock(self, event):
        message = event.get("message")
        if message is not None:
            await self._send(message)

    async def _broadcast(self, payload: dict):
        if not self.group_name:
            return
        await self.channel_layer.group_send(
            self.group_name, {"type": "designer_lock", "message": payload}
        )

    # ------------------------------------------------------------------ 辅助
    async def _send(self, payload: dict):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, default=str))

    async def _error(self, code: str, message: str):
        await self._send({"type": "error", "code": code, "message": message})

    async def _snapshot(self) -> dict:
        return await database_sync_to_async(lock_service.snapshot_for_session)(
            self.page_id, self.user_id, self.session_id
        )

    @database_sync_to_async
    def _get_user(self):
        from django.contrib.auth import get_user_model

        return get_user_model().objects.filter(pk=self.user_id).first()

    @database_sync_to_async
    def _claim_session(self) -> None:
        from django.core.cache import cache

        cache.set(self._conn_key, self.channel_name, lock_service.LOCK_TTL_SECONDS + 120)

    @database_sync_to_async
    def _release_on_disconnect(self) -> list[dict]:
        from django.core.cache import cache

        owner = cache.get(self._conn_key)
        if owner not in (None, self.channel_name):
            # 同 session 已有更新的连接：旧连接断开时不得释放新连接的锁。
            return []
        cache.delete(self._conn_key)
        return lock_service.release_session_locks(
            self.page_id, self.user_id, self.session_id, self.username
        )

    def _raw_query(self) -> str:
        raw = self.scope.get("query_string", b"")
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", "ignore")
        return str(raw or "")


def _now_ms() -> int:
    return int(time.time() * 1000)
