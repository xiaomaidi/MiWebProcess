"""服务端权威设计器锁：服务层 + WebSocket 协议测试。

运行：``python manage.py test collab.tests_locks -v 2``
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.db import IntegrityError, connection, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App, AppMember
from pages.models import Page

from . import lock_service
from .lock_models import DesignerLock
from .lock_routing import websocket_urlpatterns

User = get_user_model()


def sid() -> uuid.UUID:
    return uuid.uuid4()


def token_for(user) -> str:
    return str(AccessToken.for_user(user))


@database_sync_to_async
def lock_rows(page_id: int):
    return list(
        DesignerLock.objects.filter(page_id=page_id)
        .order_by("node_id")
        .values_list("node_id", "user_id", "session_id")
    )


class DesignerLockServiceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="lock-owner", password="pw-12345678")
        self.editor = User.objects.create_user(username="lock-editor", password="pw-12345678")
        self.app = App.objects.create(name="Lock Demo", code="lock-demo", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.editor, role="editor")
        self.page = Page.objects.create(
            app=self.app, name="Home", path="home", type="page", status="draft",
        )
        self.sid_a = sid()
        self.sid_b = sid()

    # ---------------------------------------------------------------- 原子获取
    def test_acquire_is_exclusive_across_sessions(self):
        first = lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        self.assertTrue(first["granted"])
        self.assertEqual(first["reason"], "created")
        self.assertEqual(first["lock"]["userId"], self.owner.id)

        second = lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "node-1")
        self.assertFalse(second["granted"])
        self.assertEqual(second["reason"], "locked")
        self.assertEqual(second["owner"]["userId"], self.owner.id)
        self.assertEqual(second["owner"]["sessionId"], str(self.sid_a))
        self.assertEqual(DesignerLock.objects.filter(page=self.page, node_id="node-1").count(), 1)

    def test_same_session_reacquire_refreshes_without_changing_owner(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        DesignerLock.objects.filter(page=self.page, node_id="node-1").update(
            expires_at=timezone.now() + timedelta(seconds=5)
        )
        again = lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        self.assertTrue(again["granted"])
        self.assertEqual(again["reason"], "refreshed")
        row = DesignerLock.objects.get(page=self.page, node_id="node-1")
        self.assertEqual(row.user_id, self.owner.id)
        self.assertEqual(row.session_id, self.sid_a)
        self.assertGreater(row.expires_at, timezone.now() + timedelta(seconds=60))

    def test_expired_lock_is_reclaimed_atomically(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        DesignerLock.objects.filter(page=self.page, node_id="node-1").update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        reclaimed = lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "node-1")
        self.assertTrue(reclaimed["granted"])
        self.assertEqual(reclaimed["reason"], "expired")
        row = DesignerLock.objects.get(page=self.page, node_id="node-1")
        self.assertEqual(row.user_id, self.editor.id)
        self.assertEqual(row.session_id, self.sid_b)
        self.assertEqual(DesignerLock.objects.filter(page=self.page, node_id="node-1").count(), 1)

    def test_unique_constraint_blocks_duplicate_row(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DesignerLock.objects.create(
                    page=self.page,
                    node_id="node-1",
                    user_id=self.editor.id,
                    session_id=self.sid_b,
                    expires_at=timezone.now() + lock_service.LOCK_TTL,
                )
        self.assertEqual(DesignerLock.objects.filter(page=self.page, node_id="node-1").count(), 1)

    def test_another_user_cannot_reuse_known_session_uuid(self):
        """sessionId 会出现在 snapshot 中，不能仅凭它续租/抢占他人锁。"""
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        attempted = lock_service.acquire_lock(self.page.id, self.editor, self.sid_a, "node-1")
        self.assertFalse(attempted["granted"])
        self.assertEqual(attempted["owner"]["userId"], self.owner.id)
        row = DesignerLock.objects.get(page=self.page, node_id="node-1")
        self.assertEqual(row.user_id, self.owner.id)

    def test_invalid_node_ids_are_rejected(self):
        self.assertFalse(
            lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "x" * 121)["granted"]
        )
        self.assertFalse(lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "   ")["granted"])
        self.assertFalse(lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, 123)["granted"])
        self.assertEqual(DesignerLock.objects.count(), 0)

    # ---------------------------------------------------------------- 过期 / 心跳
    def test_cleanup_expired_removes_only_expired(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "live")
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "stale")
        DesignerLock.objects.filter(page=self.page, node_id="stale").update(
            expires_at=timezone.now() - timedelta(seconds=30)
        )
        self.assertEqual(lock_service.cleanup_expired(self.page.id), 1)
        self.assertEqual(
            list(DesignerLock.objects.filter(page=self.page).values_list("node_id", flat=True)),
            ["live"],
        )

    def test_snapshot_cleans_expired_and_excludes_them(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "live")
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "stale")
        DesignerLock.objects.filter(page=self.page, node_id="stale").update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        snap = lock_service.snapshot_for_session(self.page.id, self.owner.id, self.sid_a)
        self.assertEqual([lock["nodeId"] for lock in snap["locks"]], ["live"])
        self.assertEqual(snap["ownedNodeIds"], ["live"])
        self.assertFalse(DesignerLock.objects.filter(page=self.page, node_id="stale").exists())

    def test_heartbeat_extends_only_own_session_locks(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-1")
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-2")
        lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "b-1")
        old = timezone.now() + timedelta(seconds=5)
        DesignerLock.objects.filter(page=self.page).update(expires_at=old)
        editor_expiry_before = DesignerLock.objects.get(page=self.page, node_id="b-1").expires_at

        result = lock_service.heartbeat(self.page.id, self.owner.id, self.sid_a)
        self.assertEqual(result["count"], 2)
        refreshed = DesignerLock.objects.filter(page=self.page, session_id=self.sid_a)
        self.assertEqual(refreshed.count(), 2)
        for row in refreshed:
            self.assertGreater(row.expires_at, timezone.now() + timedelta(seconds=60))
        other = DesignerLock.objects.get(page=self.page, node_id="b-1")
        self.assertEqual(other.expires_at, editor_expiry_before)

    # ---------------------------------------------------------------- 释放
    def test_release_lock_only_by_own_session(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        self.assertIsNone(
            lock_service.release_lock(self.page.id, self.editor.id, self.sid_b, "node-1")
        )
        self.assertTrue(DesignerLock.objects.filter(page=self.page, node_id="node-1").exists())

        payload = lock_service.release_lock(
            self.page.id, self.owner.id, self.sid_a, "node-1", self.owner.username
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload["nodeId"], "node-1")
        self.assertFalse(DesignerLock.objects.filter(page=self.page, node_id="node-1").exists())

    def test_release_session_locks_only_own_user_and_session(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-1")
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-2")
        lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "b-1")

        # 错误的 session / user 不得删除任何锁。
        self.assertEqual(
            lock_service.release_session_locks(self.page.id, self.owner.id, self.sid_b), []
        )
        self.assertEqual(
            lock_service.release_session_locks(self.page.id, self.editor.id, self.sid_a), []
        )
        self.assertEqual(DesignerLock.objects.filter(page=self.page).count(), 3)

        released = lock_service.release_session_locks(
            self.page.id, self.owner.id, self.sid_a, self.owner.username
        )
        self.assertEqual({item["nodeId"] for item in released}, {"a-1", "a-2"})
        self.assertEqual(
            list(DesignerLock.objects.filter(page=self.page).values_list("node_id", flat=True)),
            ["b-1"],
        )

    # ---------------------------------------------------------------- 会话恢复
    def test_snapshot_marks_own_locks_for_recovery(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-1")
        lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "b-1")
        own = lock_service.snapshot_for_session(self.page.id, self.owner.id, self.sid_a)
        self.assertEqual(own["ownedNodeIds"], ["a-1"])
        self.assertEqual({lock["nodeId"] for lock in own["locks"]}, {"a-1", "b-1"})

        other = lock_service.snapshot_for_session(self.page.id, self.editor.id, self.sid_b)
        self.assertEqual(other["ownedNodeIds"], ["b-1"])

    def test_recovery_plan_classifies_owned_recoverable_and_lost(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-1")
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "a-2")
        lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "b-1")

        plan = lock_service.recovery_plan(
            self.page.id, self.owner.id, self.sid_a, ["a-1", "a-2", "b-1", "free-1", "free-2"]
        )
        self.assertEqual(set(plan["owned"]), {"a-1", "a-2"})
        self.assertEqual(set(plan["recoverable"]), {"free-1", "free-2"})
        self.assertEqual([item["nodeId"] for item in plan["lost"]], ["b-1"])
        self.assertEqual(plan["lost"][0]["owner"]["userId"], self.editor.id)

    def test_session_recovery_after_disconnect_release(self):
        lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        released = lock_service.release_session_locks(
            self.page.id, self.owner.id, self.sid_a, self.owner.username
        )
        self.assertEqual([item["nodeId"] for item in released], ["node-1"])

        plan = lock_service.recovery_plan(self.page.id, self.owner.id, self.sid_a, ["node-1"])
        self.assertEqual(plan["recoverable"], ["node-1"])
        reacquired = lock_service.acquire_lock(self.page.id, self.owner, self.sid_a, "node-1")
        self.assertTrue(reacquired["granted"])

    def test_recovery_plan_expired_lock_becomes_recoverable(self):
        lock_service.acquire_lock(self.page.id, self.editor, self.sid_b, "node-1")
        DesignerLock.objects.filter(page=self.page, node_id="node-1").update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        plan = lock_service.recovery_plan(self.page.id, self.owner.id, self.sid_a, ["node-1"])
        self.assertEqual(plan["recoverable"], ["node-1"])
        self.assertEqual(plan["lost"], [])


class DesignerLockConcurrencyTests(TransactionTestCase):
    """真实并发：Postgres 行锁 + 唯一约束必须保证同一节点只有一个赢家。"""

    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user(username="cc-owner", password="pw-12345678")
        self.editor = User.objects.create_user(username="cc-editor", password="pw-12345678")
        self.app = App.objects.create(name="Lock CC", code="lock-cc", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.editor, role="editor")
        self.page = Page.objects.create(
            app=self.app, name="Home", path="home", type="page", status="draft",
        )

    def test_concurrent_acquire_has_exactly_one_winner(self):
        if connection.vendor != "postgresql":
            self.skipTest("并发锁语义在 PostgreSQL 上验证")
        users = [self.owner, self.editor]
        barrier = threading.Barrier(6)

        def worker(index: int) -> bool:
            try:
                barrier.wait(timeout=10)
                user = User.objects.get(pk=users[index % 2].pk)
                result = lock_service.acquire_lock(
                    self.page.id, user, uuid.uuid4(), "node-1"
                )
                return bool(result["granted"])
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(worker, range(6)))

        self.assertEqual(sum(1 for granted in results if granted), 1, results)
        self.assertEqual(DesignerLock.objects.filter(page_id=self.page.id).count(), 1)


class DesignerLockWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner = User.objects.create_user(username="ws-owner", password="pw-12345678")
        self.editor = User.objects.create_user(username="ws-editor", password="pw-12345678")
        self.viewer = User.objects.create_user(username="ws-viewer", password="pw-12345678")
        self.outsider = User.objects.create_user(username="ws-outsider", password="pw-12345678")
        self.app = App.objects.create(name="WS Lock Demo", code="ws-lock-demo", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.editor, role="editor")
        AppMember.objects.create(app=self.app, user=self.viewer, role="viewer")
        self.page = Page.objects.create(
            app=self.app, name="Home", path="home", type="page", status="draft",
        )
        self.sid_a = str(sid())
        self.sid_b = str(sid())

    def _url(self, user, session, page_id=None) -> str:
        page_id = page_id or self.page.id
        return (
            f"/ws/designer-lock/{page_id}/"
            f"?token={token_for(user)}&session={session}"
        )

    async def _connect(self, user, session):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), self._url(user, session)
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        snapshot = await communicator.receive_json_from(timeout=2)
        return communicator, snapshot

    def test_asgi_application_exposes_designer_lock_route(self):
        from config.asgi import application

        async def scenario():
            communicator = WebsocketCommunicator(
                application, self._url(self.owner, self.sid_a)
            )
            connected, _ = await communicator.connect()
            snapshot = await communicator.receive_json_from(timeout=2) if connected else None
            if connected:
                await communicator.disconnect()
            return connected, snapshot

        connected, snapshot = async_to_sync(scenario)()
        self.assertTrue(connected)
        self.assertEqual(snapshot["type"], "snapshot")

    # ---------------------------------------------------------------- 协议主流程
    def test_snapshot_acquire_deny_and_broadcast(self):
        async def scenario():
            owner_ws, owner_snap = await self._connect(self.owner, self.sid_a)
            editor_ws, editor_snap = await self._connect(self.editor, self.sid_b)

            await owner_ws.send_json_to(
                {"type": "acquire", "nodeId": "node-1", "requestId": "r1"}
            )
            granted = await owner_ws.receive_json_from()
            owner_broadcast = await owner_ws.receive_json_from()
            editor_broadcast = await editor_ws.receive_json_from()

            await editor_ws.send_json_to(
                {"type": "acquire", "nodeId": "node-1", "requestId": "r2"}
            )
            denied = await editor_ws.receive_json_from()

            rows = await lock_rows(self.page.id)
            await owner_ws.disconnect()
            await editor_ws.disconnect()
            return {
                "owner_snap": owner_snap,
                "editor_snap": editor_snap,
                "granted": granted,
                "owner_broadcast": owner_broadcast,
                "editor_broadcast": editor_broadcast,
                "denied": denied,
                "rows": rows,
            }

        data = async_to_sync(scenario)()
        self.assertEqual(data["owner_snap"]["type"], "snapshot")
        self.assertEqual(data["owner_snap"]["locks"], [])
        self.assertEqual(data["owner_snap"]["self"]["sessionId"], self.sid_a)
        self.assertTrue(data["owner_snap"]["self"]["isEditor"])
        self.assertTrue(data["editor_snap"]["self"]["isEditor"])

        self.assertEqual(data["granted"]["type"], "lock-granted")
        self.assertEqual(data["granted"]["nodeId"], "node-1")
        self.assertEqual(data["granted"]["requestId"], "r1")
        self.assertEqual(data["owner_broadcast"]["type"], "lock")
        self.assertEqual(data["owner_broadcast"]["action"], "acquire")
        self.assertEqual(data["owner_broadcast"]["userId"], self.owner.id)
        self.assertEqual(data["editor_broadcast"]["nodeId"], "node-1")

        self.assertEqual(data["denied"]["type"], "lock-denied")
        self.assertEqual(data["denied"]["owner"]["userId"], self.owner.id)
        self.assertEqual(data["denied"]["owner"]["sessionId"], self.sid_a)
        self.assertEqual(len(data["rows"]), 1)
        self.assertEqual(data["rows"][0][0], "node-1")
        self.assertEqual(data["rows"][0][1], self.owner.id)

    def test_heartbeat_acknowledges_and_extends(self):
        async def scenario():
            ws, _ = await self._connect(self.owner, self.sid_a)
            await ws.send_json_to({"type": "acquire", "nodeId": "node-1"})
            await ws.receive_json_from()  # lock-granted
            await ws.receive_json_from()  # broadcast
            await database_sync_to_async(
                lambda: DesignerLock.objects.filter(page_id=self.page.id, node_id="node-1").update(
                    expires_at=timezone.now() + timedelta(seconds=5)
                )
            )()
            await ws.send_json_to({"type": "heartbeat"})
            ack = await ws.receive_json_from()
            await ws.disconnect()
            return ack

        ack = async_to_sync(scenario)()
        self.assertEqual(ack["type"], "heartbeat-ack")
        self.assertEqual(ack["count"], 1)
        self.assertIsNotNone(ack["expiresAt"])

    def test_disconnect_releases_and_broadcasts(self):
        async def scenario():
            owner_ws, _ = await self._connect(self.owner, self.sid_a)
            await owner_ws.send_json_to({"type": "acquire", "nodeId": "node-1"})
            await owner_ws.receive_json_from()
            await owner_ws.receive_json_from()

            editor_ws, editor_snap = await self._connect(self.editor, self.sid_b)
            self.assertEqual([lock["nodeId"] for lock in editor_snap["locks"]], ["node-1"])

            await owner_ws.disconnect()
            release_event = await editor_ws.receive_json_from()
            rows_after_disconnect = await lock_rows(self.page.id)

            await editor_ws.send_json_to({"type": "acquire", "nodeId": "node-1"})
            granted = await editor_ws.receive_json_from()
            await editor_ws.receive_json_from()  # 自己的广播
            rows_after_reacquire = await lock_rows(self.page.id)
            await editor_ws.disconnect()
            rows_final = await lock_rows(self.page.id)
            return {
                "release_event": release_event,
                "rows_after_disconnect": rows_after_disconnect,
                "granted": granted,
                "rows_after_reacquire": rows_after_reacquire,
                "rows_final": rows_final,
            }

        data = async_to_sync(scenario)()
        self.assertEqual(data["release_event"]["type"], "lock")
        self.assertEqual(data["release_event"]["action"], "release")
        self.assertEqual(data["release_event"]["nodeId"], "node-1")
        self.assertEqual(data["rows_after_disconnect"], [])
        self.assertEqual(data["granted"]["type"], "lock-granted")
        self.assertEqual(data["rows_after_reacquire"][0][1], self.editor.id)
        self.assertEqual(data["rows_final"], [])

    def test_viewer_cannot_acquire(self):
        async def scenario():
            ws, snap = await self._connect(self.viewer, self.sid_a)
            await ws.send_json_to({"type": "acquire", "nodeId": "node-1"})
            reply = await ws.receive_json_from()
            rows = await lock_rows(self.page.id)
            await ws.disconnect()
            return snap, reply, rows

        snap, reply, rows = async_to_sync(scenario)()
        self.assertFalse(snap["self"]["isEditor"])
        self.assertEqual(reply["type"], "error")
        self.assertEqual(reply["code"], "forbidden")
        self.assertEqual(rows, [])

    def test_client_cannot_spoof_user_identity(self):
        async def scenario():
            ws, _ = await self._connect(self.owner, self.sid_a)
            await ws.send_json_to(
                {
                    "type": "acquire",
                    "nodeId": "node-1",
                    "userId": self.editor.id,
                    "username": self.editor.username,
                }
            )
            granted = await ws.receive_json_from()
            broadcast = await ws.receive_json_from()
            rows = await lock_rows(self.page.id)
            await ws.disconnect()
            return granted, broadcast, rows

        granted, broadcast, rows = async_to_sync(scenario)()
        self.assertEqual(granted["type"], "lock-granted")
        self.assertEqual(broadcast["userId"], self.owner.id)
        self.assertEqual(broadcast["username"], self.owner.username)
        self.assertEqual(rows[0][1], self.owner.id)

    def test_invalid_token_non_member_and_missing_page_are_rejected(self):
        async def connect_raw(url):
            communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), url)
            connected, code = await communicator.connect()
            if connected:
                await communicator.disconnect()
            return connected, code

        async def scenario():
            bad_token = await connect_raw(
                f"/ws/designer-lock/{self.page.id}/?token=not-a-token"
            )
            missing_token = await connect_raw(f"/ws/designer-lock/{self.page.id}/")
            non_member = await connect_raw(self._url(self.outsider, self.sid_a))
            missing_page = await connect_raw(self._url(self.owner, self.sid_a, page_id=999999))
            return bad_token, missing_token, non_member, missing_page

        bad_token, missing_token, non_member, missing_page = async_to_sync(scenario)()
        self.assertFalse(bad_token[0])
        self.assertFalse(missing_token[0])
        self.assertFalse(non_member[0])
        self.assertFalse(missing_page[0])

    # ---------------------------------------------------------------- 会话恢复
    def test_reconnect_with_same_session_can_reacquire_released_locks(self):
        async def scenario():
            ws1, _ = await self._connect(self.owner, self.sid_a)
            await ws1.send_json_to({"type": "acquire", "nodeId": "node-1"})
            await ws1.receive_json_from()
            await ws1.receive_json_from()
            await ws1.disconnect()  # 断线释放

            ws2, snap = await self._connect(self.owner, self.sid_a)
            await ws2.send_json_to({"type": "acquire", "nodeId": "node-1"})
            granted = await ws2.receive_json_from()
            await ws2.receive_json_from()
            rows = await lock_rows(self.page.id)
            await ws2.disconnect()
            return snap, granted, rows

        snap, granted, rows = async_to_sync(scenario)()
        self.assertEqual(snap["locks"], [])
        self.assertEqual(granted["type"], "lock-granted")
        self.assertEqual(rows[0][1], self.owner.id)

    def test_reconnected_session_relearns_own_live_lock_from_snapshot(self):
        async def scenario():
            holder, _ = await self._connect(self.owner, self.sid_a)
            await holder.send_json_to({"type": "acquire", "nodeId": "node-1"})
            await holder.receive_json_from()
            await holder.receive_json_from()

            # 模拟网络抖动：旧连接尚未被服务端判定断开时，新连接已建立（同 session）。
            reconnect, snap = await self._connect(self.owner, self.sid_a)
            self.assertEqual(snap["locks"][0]["sessionId"], self.sid_a)
            await holder.disconnect()
            rows_after_old_disconnect = await lock_rows(self.page.id)
            await reconnect.disconnect()
            rows_final = await lock_rows(self.page.id)
            return snap, rows_after_old_disconnect, rows_final

        snap, rows_after_old_disconnect, rows_final = async_to_sync(scenario)()
        self.assertEqual([lock["nodeId"] for lock in snap["locks"]], ["node-1"])
        # 旧连接断开不得释放新连接的锁。
        self.assertEqual(rows_after_old_disconnect[0][1], self.owner.id)
        self.assertEqual(rows_final, [])

    # ---------------------------------------------------------------- 校验 / 限流
    def test_invalid_node_id_rejected_over_websocket(self):
        async def scenario():
            ws, _ = await self._connect(self.owner, self.sid_a)
            await ws.send_json_to({"type": "acquire", "nodeId": "x" * 121})
            reply = await ws.receive_json_from()
            await ws.disconnect()
            return reply

        reply = async_to_sync(scenario)()
        self.assertEqual(reply["type"], "error")
        self.assertEqual(reply["code"], "invalid-node")

    def test_selection_and_cursor_broadcast(self):
        async def scenario():
            a, _ = await self._connect(self.owner, self.sid_a)
            b, _ = await self._connect(self.editor, self.sid_b)
            await a.send_json_to({"type": "selection", "ids": ["node-1", "node-2"]})
            selection = await b.receive_json_from()
            await a.send_json_to({"type": "cursor", "x": 12, "y": 34})
            cursor = await b.receive_json_from()
            await a.disconnect()
            await b.disconnect()
            return selection, cursor

        selection, cursor = async_to_sync(scenario)()
        self.assertEqual(selection["type"], "selection")
        self.assertEqual(selection["userId"], self.owner.id)
        self.assertEqual(selection["ids"], ["node-1", "node-2"])
        self.assertEqual(cursor["type"], "cursor")
        self.assertEqual(cursor["userId"], self.owner.id)
        self.assertEqual((cursor["x"], cursor["y"]), (12.0, 34.0))
