"""设计器 schema 操作日志 WebSocket 消费者（独立于 collab 锁 / schema-sync）。

连接：``ws(s)://host/ws/designer-ops/{page_id}/?token=<JWT>&after=<seq>&limit=<n>``

鉴权：JWT access token；用户必须至少是页面所属应用的 ``viewer``。只有
``editor`` / ``owner`` 可以追加操作，viewer 仅接收。

服务端 → 客户端::

    {"type": "snapshot", "page_id": 1, "seq": 12, "after": 3,
     "ops": [{"seq": 4, ...}, ...], "has_more": false,
     "schema_revision": 3, "from": "server"}
    {"type": "ops", "page_id": 1, "ops": [...], "last_seq": 13, "from": "alice"}
    {"type": "appended", "page_id": 1, "seqs": [13], "last_seq": 13,
     "ops": [...], "client_id": "tab-x"}
    {"type": "pong", "ts": 1700000000000}
    {"type": "error", "code": "invalid-ops", "message": "..."}

客户端 → 服务端::

    {"type": "ops", "client_id": "tab-x", "base_revision": 3, "ops": [op, ...]}
    {"type": "ping"}

设计边界：

- 追加先落库（页面行锁 + seq 唯一约束），成功后才广播；发送方收到 ack，
  其他连接收到 ``ops``。不回传整页 schema。
- 连接时按 ``after`` 重放操作；默认从 0 开始（受 ``limit`` 上限约束，
  ``has_more`` 为 true 时客户端应继续用 REST ``GET .../schema/ops/?after=``
  分页）。
- 单条消息上限 2 MB；每连接 10s 内最多 120 条。
"""
from __future__ import annotations

import json
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import re_path

from pages.schema_ops import (
    MAX_BATCH_OPS,
    SchemaOpValidationError,
    append_operations,
    fetch_operations,
    group_for,
    latest_seq,
    normalize_client_id,
    operations_to_dict,
    parse_cursor,
)

MAX_MESSAGE_BYTES = 2 * 1024 * 1024  # 2 MB
RATE_WINDOW_SECONDS = 10.0
RATE_LIMIT_MESSAGES = 120  # 每连接 10s 内最多 120 条


@database_sync_to_async
def resolve_snapshot(token_str: str, page_id: int, after: int, limit: int):
    """校验 JWT / 页面 / viewer 权限，返回连接 snapshot（操作日志，不含 schema）。"""
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
    rows, has_more = fetch_operations(page_id, after=after, limit=limit)
    return {
        "user_id": user.id,
        "username": user.username,
        "role": role,
        "is_editor": role in ("editor", "owner"),
        "seq": latest_seq(page_id),
        "schema_revision": int(page.schema_revision or 1),
        "ops": operations_to_dict(rows),
        "has_more": has_more,
    }


@database_sync_to_async
def append_batch(page_id: int, client_id: str, base_revision, ops: list, user_id: int):
    """落库一批操作并返回可广播的普通 dict（跨线程后不再触碰 ORM 实例）。"""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(id=user_id).first()
    rows = append_operations(
        page_id,
        client_id=client_id,
        base_revision=base_revision,
        ops=ops,
        user=user,
    )
    return operations_to_dict(rows), int(rows[-1].seq)


class DesignerOpsConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self._page_id = 0
        self._user_id = 0
        self._username = ""
        self._group_name = ""
        self._is_editor = False
        self._message_times: list[float] = []

        route = self.scope.get("url_route") or {}
        kwargs = getattr(route, "kwargs", None)
        if kwargs is None and isinstance(route, dict):
            kwargs = route.get("kwargs") or {}
        try:
            page_id = int((kwargs or {}).get("page_id", ""))
        except (TypeError, ValueError):
            await self.close(code=4400)
            return

        query = parse_qs(self._raw_query(), keep_blank_values=True)
        token_str = (query.get("token") or [""])[0].strip()
        if not token_str:
            await self.close(code=4401)
            return
        try:
            after, limit = parse_cursor(
                (query.get("after") or [""])[0] or None,
                (query.get("limit") or [""])[0] or None,
            )
        except SchemaOpValidationError:
            await self.close(code=4400)
            return

        try:
            info = await resolve_snapshot(token_str, page_id, after, limit)
        except LookupError:
            await self.close(code=4404)
            return
        except Exception:
            # 无效 JWT / 非应用成员 / 无 viewer 权限统一按 4403。
            await self.close(code=4403)
            return

        self._page_id = page_id
        self._user_id = info["user_id"]
        self._username = info["username"]
        self._is_editor = bool(info["is_editor"])
        self._group_name = group_for(page_id)

        await self.channel_layer.group_add(self._group_name, self.channel_name)
        await self.accept()
        await self._send(
            {
                "type": "snapshot",
                "page_id": page_id,
                "seq": info["seq"],
                "after": after,
                "ops": info["ops"],
                "has_more": info["has_more"],
                "schema_revision": info["schema_revision"],
                "from": "server",
            }
        )

    async def disconnect(self, code: int):
        try:
            if self._group_name:
                await self.channel_layer.group_discard(
                    self._group_name, self.channel_name
                )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 消息分发
    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            if bytes_data is not None:
                await self._error("invalid-message", "只接受 JSON 文本消息")
            return
        if len(text_data.encode("utf-8")) >= MAX_MESSAGE_BYTES:
            await self._error("payload_too_large", "消息必须小于 2MB")
            return
        if not self._within_rate_limit():
            await self._error("rate_limited", "消息过于频繁，请稍后重试")
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
        if msg_type == "ping":
            await self._send({"type": "pong", "ts": _now_ms()})
            return
        if msg_type != "ops":
            await self._error(
                "unknown-type", f"未知或缺失的消息类型: {msg_type or '(empty)'}"
            )
            return
        await self._on_ops(data)

    async def _on_ops(self, data: dict):
        if not self._is_editor:
            await self._error("forbidden", "仅应用编辑者可以追加 schema 操作")
            return

        try:
            client_id = normalize_client_id(data.get("client_id"))
        except SchemaOpValidationError as exc:
            await self._error("invalid-client-id", str(exc))
            return

        ops = data.get("ops")
        if not isinstance(ops, list):
            await self._error("invalid-ops", "ops 必须是数组")
            return
        if len(ops) > MAX_BATCH_OPS:
            await self._error("invalid-ops", f"单批最多 {MAX_BATCH_OPS} 条操作")
            return

        try:
            stored, last_seq = await append_batch(
                self._page_id,
                client_id,
                data.get("base_revision"),
                ops,
                self._user_id,
            )
        except SchemaOpValidationError as exc:
            await self._error("invalid-ops", str(exc))
            return
        except Exception:  # noqa: BLE001 - 数据库错误不暴露内部细节
            await self._error("append-failed", "操作追加失败，请重试")
            return

        # 发送方 ack（包含服务端分配的 seq）；其他连接收到 ops 广播。
        await self._send(
            {
                "type": "appended",
                "page_id": self._page_id,
                "client_id": client_id,
                "seqs": [int(item["seq"]) for item in stored],
                "last_seq": last_seq,
                "ops": stored,
            }
        )
        await self.channel_layer.group_send(
            self._group_name,
            {
                "type": "designer_ops",
                "message": {
                    "type": "ops",
                    "page_id": self._page_id,
                    "ops": stored,
                    "last_seq": last_seq,
                    "from": self._username,
                },
                "sender_channel": self.channel_name,
            },
        )

    async def designer_ops(self, event):
        if event.get("sender_channel") == self.channel_name:
            return
        message = event.get("message")
        if message is not None:
            await self._send(message)

    # ------------------------------------------------------------------ 辅助
    async def _send(self, payload: dict):
        await self.send(text_data=json.dumps(payload, ensure_ascii=False, default=str))

    async def _error(self, code: str, message: str):
        await self._send({"type": "error", "code": code, "message": message})

    def _within_rate_limit(self) -> bool:
        now = time.monotonic()
        cutoff = now - RATE_WINDOW_SECONDS
        self._message_times = [ts for ts in self._message_times if ts >= cutoff]
        if len(self._message_times) >= RATE_LIMIT_MESSAGES:
            return False
        self._message_times.append(now)
        return True

    def _raw_query(self) -> str:
        raw = self.scope.get("query_string", b"")
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", "ignore")
        return str(raw or "")


def _now_ms() -> int:
    return int(time.time() * 1000)


websocket_urlpatterns = [
    re_path(
        r"^ws/designer-ops/(?P<page_id>\d+)/$", DesignerOpsConsumer.as_asgi()
    ),
]
