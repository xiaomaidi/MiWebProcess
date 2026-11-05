"""设计器 schema 实时同步 WebSocket 消费者（独立于 collab 锁通道）。

连接: ``ws://host/ws/designer-sync/{page_id}/?token=<JWT>``

鉴权：JWT access token；用户必须至少是页面所属应用的 ``viewer``。只有
``editor`` / ``owner`` 可以发送 schema，viewer 仅接收。

客户端 → 服务端::

    {"type": "schema", "base_revision": 3, "client_id": "tab-...", "schema": {...}}
    {"type": "ping"}

服务端 → 客户端::

    {"type": "snapshot", "page_id": 1, "revision": 3, "schema": {...}, "hash": "..."}
    {"type": "schema", "revision": 4, "client_id": "tab-...", "from": "alice",
     "schema": {...}, "hash": "..."}
    {"type": "pong", "ts": 1700000000000}
    {"type": "error", "code": "...", "message": "..."}

设计边界（MVP）：

- 广播 revision 由缓存原子递增，**不落库**；真正的持久化修订号是
  ``Page.schema_revision``，由 REST ``PUT /api/pages/{id}/schema/`` 维护。
- 发送方的连接不会收到自己消息的回声（按 ``channel_name`` 排除）；其他标签页
  通过 ``client_id`` 再自行去重。
- 新连接/重连的 snapshot 来自数据库（权威草稿），未通过 API 落库的远端临时
  修改会丢失，需要靠冲突检测与显式保存收敛。
- 单条消息上限 2 MB；超限、非 JSON、缺字段、schema 结构非法均返回 error。
"""
from __future__ import annotations

import json
import time
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.urls import re_path

from pages.schema_sync import compute_schema_hash, next_ephemeral_revision

GROUP_PREFIX = "designer_sync"
MAX_MESSAGE_BYTES = 2 * 1024 * 1024  # 2 MB
MAX_CLIENT_ID_LENGTH = 128
RATE_WINDOW_SECONDS = 10.0
RATE_LIMIT_MESSAGES = 120  # 每连接 10s 内最多 120 条（客户端另有节流）


def group_for(page_id: int) -> str:
    return f"{GROUP_PREFIX}_{page_id}"


@database_sync_to_async
def resolve_page(token_str: str, page_id: int):
    """校验 JWT / 页面 / viewer 权限，返回构建 snapshot 所需的普通数据。"""
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
    schema = page.schema or {}
    return {
        "user_id": user.id,
        "username": user.username,
        "role": role,
        "is_editor": role in ("editor", "owner"),
        "schema": schema,
        "revision": int(page.schema_revision or 1),
        "hash": compute_schema_hash(schema),
    }


@database_sync_to_async
def _next_revision(page_id: int) -> int:
    """基于当前持久化 revision 递增缓存中的临时 revision（只读 DB）。"""
    from pages.models import Page
    from pages.schema_sync import raise_revision_floor

    db_revision = (
        Page.objects.filter(id=page_id).values_list("schema_revision", flat=True).first()
    )
    db_revision = int(db_revision or 1)
    # 保存接口可能已经抬高了缓存 floor；先对齐 DB 再原子递增。
    raise_revision_floor(page_id, db_revision)
    return next_ephemeral_revision(page_id, db_revision)


def _validate_schema(schema) -> str | None:
    """基础结构校验；返回错误文案，None 表示通过。"""
    if not isinstance(schema, dict):
        return "schema 必须是对象"
    nodes = schema.get("nodes")
    if not isinstance(nodes, dict):
        return "schema.nodes 必须是对象"
    if not isinstance(schema.get("rootId"), str):
        return "schema.rootId 必须是字符串"
    try:
        compute_schema_hash(schema)
    except Exception:  # noqa: BLE001 - 不可序列化的值
        return "schema 无法序列化"
    return None


class DesignerSchemaConsumer(AsyncWebsocketConsumer):
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
            info = await resolve_page(token_str, page_id)
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
                "revision": info["revision"],
                "schema": info["schema"],
                "hash": info["hash"],
                "from": "server",
            }
        )

    async def disconnect(self, code: int):
        try:
            if self._group_name:
                await self.channel_layer.group_discard(self._group_name, self.channel_name)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 消息分发
    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            if bytes_data is not None:
                await self._error("invalid-message", "只接受 JSON 文本消息")
            return
        # 先按 UTF-8 字节数限流，避免超大 payload 进入 JSON 解析。
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
        if msg_type != "schema":
            await self._error("unknown-type", f"未知或缺失的消息类型: {msg_type or '(empty)'}")
            return
        await self._on_schema(data)

    async def _on_schema(self, data: dict):
        if not self._is_editor:
            await self._error("forbidden", "仅应用编辑者可以广播 schema")
            return

        client_id = data.get("client_id")
        if not isinstance(client_id, str) or not client_id.strip():
            await self._error("invalid-client-id", "client_id 必须是非空字符串")
            return
        client_id = client_id.strip()
        if len(client_id) > MAX_CLIENT_ID_LENGTH:
            await self._error("invalid-client-id", "client_id 过长")
            return

        base_revision = data.get("base_revision")
        if base_revision is not None:
            if isinstance(base_revision, bool) or not isinstance(base_revision, int):
                await self._error("invalid-revision", "base_revision 必须是整数")
                return
            if base_revision < 0:
                await self._error("invalid-revision", "base_revision 不能为负数")
                return

        schema = data.get("schema")
        schema_error = _validate_schema(schema)
        if schema_error:
            await self._error("invalid-schema", schema_error)
            return

        revision = await _next_revision(self._page_id)
        payload = {
            "type": "schema",
            "revision": revision,
            "client_id": client_id,
            "from": self._username,
            "schema": schema,
            "hash": compute_schema_hash(schema),
        }
        # 广播给同页其他连接（发送方 channel 在事件处理时排除），不写数据库。
        await self.channel_layer.group_send(
            self._group_name,
            {
                "type": "designer_schema",
                "message": payload,
                "sender_channel": self.channel_name,
            },
        )

    async def designer_schema(self, event):
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
    re_path(r"^ws/designer-sync/(?P<page_id>\d+)/$", DesignerSchemaConsumer.as_asgi()),
]
