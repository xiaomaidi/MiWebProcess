"""设计器节点锁 WebSocket 消费者（服务端权威）。

连接: ``ws://host/ws/designer-lock/{page_id}/?token=<JWT>&session=<uuid>``

- ``token``：JWT access token；服务端据此解析用户与页面所属应用。
- ``session``：可选的浏览器会话 UUID（推荐）。同一 session 重连后仍持有
  未过期的锁；不传则服务端生成，客户端无法跨连接恢复自己的锁。

客户端 → 服务端::

    {"type": "acquire",   "nodeId": "node-1", "requestId": "r1", "timeoutMs": 30000}
    {"type": "release",   "nodeId": "node-1"}
    {"type": "cancel",    "nodeId": "node-1"}
    {"type": "heartbeat"}
    {"type": "selection", "ids": ["node-1", "node-2"]}
    {"type": "cursor",    "x": 120, "y": 40}
    {"type": "ping"}

服务端 → 客户端::

    {"type": "snapshot", "locks": [...], "self": {...}}
    {"type": "lock-granted", "nodeId": ..., "expiresAt": ..., "queued": false}
    {"type": "lock-denied",  "nodeId": ..., "owner": {...}, "reason": "locked|queue-full|queue-busy"}
    {"type": "lock-queued",  "nodeId": ..., "position": 1, "timeoutAt": ..., "owner": {...}}
    {"type": "queue",        "nodeId": ..., "position": 2, "timeoutAt": ..., "owner": {...},
                             "queueLength": 3, "waiters": [...]}
    {"type": "lock-timeout", "nodeId": ...}
    {"type": "lock", "action": "acquire"|"release", "nodeId": ..., "userId": ...}
    {"type": "heartbeat-ack", "count": 2, "expiresAt": ...}
    {"type": "selection", "userId": ..., "ids": [...]}
    {"type": "cursor", "userId": ..., "x": ..., "y": ...}
    {"type": "error", "code": "...", "message": "..."}
    {"type": "pong"}

等待队列（服务端权威，缓存实现、无数据库迁移）：

- acquire 被拒时进入 ``(page, node)`` 的 FIFO 队列，30s（可配置）内等待；
- 释放 / 过期 / 断线时由服务端把锁原子转交给队首，并通过 session 组推送
  ``lock-granted``；
- 客户端取消或断线会撤销等待项，后续等待者收到 ``queue`` 位置更新；
- 队列满（默认 50 人）时直接返回 ``lock-denied`` + ``reason:"queue-full"``。
"""
from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from contextlib import suppress
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from . import lock_service

GROUP_PREFIX = "designer_lock"


def group_for(page_id: int) -> str:
    return f"{GROUP_PREFIX}_{page_id}"


def session_group_for(page_id: int, session_id) -> str:
    """同一浏览器会话（可能多连接）的定向推送组。"""
    return f"{GROUP_PREFIX}_sess_{page_id}_{session_id}"


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
        self.session_group_name = ""
        self.is_editor = False
        self._last_cursor_at = 0.0
        self._conn_key = ""
        self._closed = False
        self._queued_nodes: set[str] = set()
        self._last_queue_positions: dict[str, int] = {}
        self._queue_task: asyncio.Task | None = None

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
        self.session_group_name = session_group_for(self.page_id, self.session_id)
        self._conn_key = lock_service.connection_key(self.page_id, self.session_id)

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.channel_layer.group_add(self.session_group_name, self.channel_name)
        await self.accept()
        # 同一 session 只允许「最新连接」在断开时释放锁/撤销排队，避免重连竞态。
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
        self._closed = True
        await self._stop_queue_task()
        for group in (self.group_name, self.session_group_name):
            if not group:
                continue
            try:
                await self.channel_layer.group_discard(group, self.channel_name)
            except Exception:
                pass
        try:
            outcome = await self._release_on_disconnect()
        except Exception:
            outcome = None
        if outcome:
            await self._emit_disconnect_outcome(outcome)

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
            elif msg_type == "cancel":
                await self._on_cancel(data)
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
        user = await self._get_user()
        # 公平性：节点已有等待者时，新请求不得越过队首直接抢锁（即使锁刚空出来）。
        try:
            waiters = await database_sync_to_async(lock_service.queue_snapshot)(
                self.page_id, node_id
            )
            waiting = await database_sync_to_async(lock_service.waiter_state)(
                self.page_id, self.user_id, self.session_id, node_id
            )
        except Exception:
            waiters = []
            waiting = {}
        if waiters:
            position = int(waiting.get("position") or 0)
            current_owner = await database_sync_to_async(lock_service.node_owner)(
                self.page_id, node_id
            )
            same_owner = bool(
                current_owner
                and int(current_owner.get("userId") or 0) == self.user_id
                and str(current_owner.get("sessionId") or "") == str(self.session_id)
            )
            if position != 1 and not same_owner:
                await self._enqueue_and_reply(
                    node_id, user, request_id, data, current_owner
                )
                return

        result = await database_sync_to_async(lock_service.acquire_lock)(
            self.page_id, user, self.session_id, node_id
        )
        if not result["granted"]:
            await self._enqueue_and_reply(
                node_id, user, request_id, data, result.get("owner")
            )
            return
        lock = result["lock"]
        # 可能此前已在队列中（例如重复 acquire）；成功后同步清理。
        removed = await database_sync_to_async(lock_service.cancel_waiter)(
            self.page_id, self.user_id, self.session_id, node_id
        )
        self._queued_nodes.discard(node_id)
        self._last_queue_positions.pop(node_id, None)
        await self._send(
            {
                "type": "lock-granted",
                "nodeId": lock["nodeId"],
                "expiresAt": lock["expiresAt"],
                "requestId": request_id,
                "queued": False,
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
        if removed.get("removed"):
            await self._push_queue(node_id, owner=lock)

    async def _enqueue_and_reply(self, node_id, user, request_id, data, owner) -> bool:
        """把请求放入队列并返回 lock-queued / lock-denied；返回是否已排队。"""
        queued = await database_sync_to_async(lock_service.enqueue_waiter)(
            self.page_id,
            user,
            self.session_id,
            node_id,
            str(request_id or ""),
            self._requested_timeout_seconds(data),
        )
        if queued.get("queued"):
            self._queued_nodes.add(node_id)
            self._last_queue_positions[node_id] = int(queued.get("position") or 0)
            self._ensure_queue_task()
            await self._expire_notify(queued.get("expired") or [])
            await self._send(
                {
                    "type": "lock-queued",
                    "nodeId": node_id,
                    "position": int(queued.get("position") or 0),
                    "timeoutAt": queued.get("timeoutAt") or "",
                    "owner": owner,
                    "requestId": request_id,
                    "queueLength": int(queued.get("queueLength") or 0),
                }
            )
            await self._push_queue(node_id, owner=owner)
            return True
        reason = str(queued.get("reason") or "denied")
        if reason == "full":
            reason = "queue-full"
        elif reason == "busy":
            reason = "queue-busy"
        await self._expire_notify(queued.get("expired") or [])
        await self._send(
            {
                "type": "lock-denied",
                "nodeId": node_id,
                "requestId": request_id,
                "owner": owner,
                "reason": reason,
                "queueLength": int(queued.get("queueLength") or 0),
            }
        )
        return False

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
        outcome = await database_sync_to_async(lock_service.release_lock_and_grant_next)(
            self.page_id, self.user_id, self.session_id, node_id, self.username
        )
        if outcome is None:
            return
        await self._broadcast({"type": "lock", "action": "release", **outcome["released"]})
        if outcome.get("granted"):
            await self._notify_granted(outcome.get("waiter") or {}, outcome["granted"])
            await self._broadcast({"type": "lock", "action": "acquire", **outcome["granted"]})
        await self._expire_notify(outcome.get("expired") or [])
        if outcome.get("granted") or outcome.get("expired") or outcome.get("queueLength"):
            await self._push_queue(node_id, owner=outcome.get("granted"))

    async def _on_cancel(self, data):
        node_id = lock_service.normalize_node_id(data.get("nodeId"))
        if node_id is None:
            await self._error("invalid-node", "nodeId 非法")
            return
        result = await database_sync_to_async(lock_service.cancel_waiter)(
            self.page_id, self.user_id, self.session_id, node_id
        )
        self._queued_nodes.discard(node_id)
        self._last_queue_positions.pop(node_id, None)
        await self._expire_notify(result.get("expired") or [])
        if result.get("removed"):
            await self._send(
                {
                    "type": "queue",
                    "nodeId": node_id,
                    "position": 0,
                    "timeoutAt": "",
                    "owner": await database_sync_to_async(lock_service.node_owner)(
                        self.page_id, node_id
                    ),
                    "queueLength": int(result.get("queueLength") or 0),
                }
            )
            await self._push_queue(node_id)

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

    def _requested_timeout_seconds(self, data: dict) -> float | None:
        raw = data.get("timeoutMs", data.get("timeout_ms"))
        if raw is None:
            return None
        try:
            return max(0.1, float(raw) / 1000.0)
        except (TypeError, ValueError):
            return None

    def _ensure_queue_task(self) -> None:
        """有等待项时确保巡检任务在跑（超时通知 + 过期锁接管 + 位置刷新）。"""
        if self._closed or not self._queued_nodes:
            return
        if self._queue_task is not None and not self._queue_task.done():
            return
        self._queue_task = asyncio.create_task(self._queue_loop())

    async def _stop_queue_task(self) -> None:
        task = self._queue_task
        self._queue_task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task

    async def _queue_loop(self) -> None:
        try:
            while not self._closed and self._queued_nodes:
                await asyncio.sleep(lock_service.queue_poll_seconds())
                for node_id in list(self._queued_nodes):
                    if self._closed:
                        break
                    try:
                        await self._poll_queued_node(node_id)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # 单节点异常（如 socket 正在关闭）不应让整条巡检任务退出。
                        await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        finally:
            self._queue_task = None

    async def _poll_queued_node(self, node_id: str) -> None:
        # 必须先检查超时：take_expired_waiter 会原子摘除并返回本会话条目，
        # 这样才能保证客户端收到且只收到一次 lock-timeout。
        try:
            expired = await database_sync_to_async(lock_service.take_expired_waiter)(
                self.page_id, self.user_id, self.session_id, node_id
            )
        except Exception:
            expired = None
        if expired is not None:
            self._queued_nodes.discard(node_id)
            self._last_queue_positions.pop(node_id, None)
            await self._send(
                {
                    "type": "lock-timeout",
                    "nodeId": node_id,
                    "requestId": str(expired.get("requestId") or ""),
                    "reason": "timeout",
                }
            )
            await self._push_queue(node_id)
            return

        try:
            state = await database_sync_to_async(lock_service.waiter_state)(
                self.page_id, self.user_id, self.session_id, node_id
            )
        except Exception:
            return
        if not state.get("queued"):
            self._queued_nodes.discard(node_id)
            self._last_queue_positions.pop(node_id, None)
            return

        if int(state.get("position") or 0) == 1:
            try:
                user = await self._get_user()
                claim = await database_sync_to_async(lock_service.claim_head_lock)(
                    self.page_id, user, self.session_id, node_id
                )
            except Exception:
                return
            await self._expire_notify(claim.get("expired") or [])
            if claim.get("granted"):
                lock = claim["lock"]
                self._queued_nodes.discard(node_id)
                self._last_queue_positions.pop(node_id, None)
                await self._send(
                    {
                        "type": "lock-granted",
                        "nodeId": lock["nodeId"],
                        "expiresAt": lock["expiresAt"],
                        "requestId": str(claim.get("requestId") or ""),
                        "queued": True,
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
                await self._push_queue(node_id, owner=lock)
                return
            if claim.get("reason") == "not-queued":
                self._queued_nodes.discard(node_id)
                self._last_queue_positions.pop(node_id, None)
                return

        position = int(state.get("position") or 0)
        if position and self._last_queue_positions.get(node_id) != position:
            self._last_queue_positions[node_id] = position
            await self._push_queue(node_id)

    async def _push_queue(self, node_id: str, owner: dict | None = None) -> None:
        """把最新排队位置推给每个等待者（定向），并向页面广播聚合队列。"""
        if not self.page_id or not self.group_name:
            return
        try:
            waiters = await database_sync_to_async(lock_service.queue_snapshot)(
                self.page_id, node_id
            )
            if owner is None:
                owner = await database_sync_to_async(lock_service.node_owner)(
                    self.page_id, node_id
                )
        except Exception:
            return
        for index, waiter in enumerate(waiters):
            await self._send_to_session(
                waiter.get("sessionId"),
                {
                    "type": "queue",
                    "nodeId": node_id,
                    "position": index + 1,
                    "timeoutAt": waiter.get("timeoutAt") or "",
                    "owner": owner,
                    "requestId": waiter.get("requestId") or "",
                    "queueLength": len(waiters),
                },
            )
        await self._broadcast(
            {
                "type": "queue",
                "nodeId": node_id,
                "position": 0,
                "timeoutAt": "",
                "owner": owner,
                "queueLength": len(waiters),
                "waiters": [
                    {
                        "position": index + 1,
                        "userId": waiter.get("userId") or 0,
                        "username": waiter.get("username") or "",
                        "sessionId": waiter.get("sessionId") or "",
                        "timeoutAt": waiter.get("timeoutAt") or "",
                    }
                    for index, waiter in enumerate(waiters)
                ],
            }
        )

    async def _send_to_session(self, session_id, payload: dict) -> None:
        if not session_id or not self.page_id:
            return
        try:
            await self.channel_layer.group_send(
                session_group_for(self.page_id, session_id),
                {"type": "designer_lock", "message": payload},
            )
        except Exception:
            pass

    async def _notify_granted(self, waiter: dict, lock: dict) -> None:
        await self._send_to_session(
            waiter.get("sessionId"),
            {
                "type": "lock-granted",
                "nodeId": lock["nodeId"],
                "expiresAt": lock["expiresAt"],
                "requestId": str(waiter.get("requestId") or ""),
                "queued": True,
            },
        )

    async def _expire_notify(self, expired: list[dict]) -> None:
        for entry in expired:
            await self._send_to_session(
                entry.get("sessionId"),
                {
                    "type": "lock-timeout",
                    "nodeId": str(entry.get("node") or ""),
                    "requestId": str(entry.get("requestId") or ""),
                    "reason": "timeout",
                },
            )

    async def _emit_disconnect_outcome(self, outcome: dict) -> None:
        for node_id in outcome.get("cancelled") or []:
            await self._push_queue(node_id)
        for item in outcome.get("results") or []:
            node_id = str(item.get("nodeId") or "")
            released = item.get("released")
            if released:
                await self._broadcast({"type": "lock", "action": "release", **released})
            granted = item.get("granted")
            if granted:
                await self._notify_granted(item.get("waiter") or {}, granted)
                await self._broadcast({"type": "lock", "action": "acquire", **granted})
            await self._expire_notify(item.get("expired") or [])
            if granted or item.get("expired") or item.get("queueLength"):
                await self._push_queue(node_id, owner=granted)

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
    def _release_on_disconnect(self) -> dict | None:
        from django.core.cache import cache

        owner = cache.get(self._conn_key)
        if owner not in (None, self.channel_name):
            # 同 session 已有更新的连接：旧连接断开时不得释放新连接的锁/排队。
            return None
        cache.delete(self._conn_key)
        cancelled = lock_service.cancel_session_waiters(
            self.page_id, self.user_id, self.session_id
        )
        results = lock_service.release_session_locks_with_queue(
            self.page_id, self.user_id, self.session_id, self.username
        )
        return {"cancelled": cancelled, "results": results}

    def _raw_query(self) -> str:
        raw = self.scope.get("query_string", b"")
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", "ignore")
        return str(raw or "")


def _now_ms() -> int:
    return int(time.time() * 1000)
