"""设计器 schema 操作日志：模型 / REST / WebSocket 测试。

运行：``python manage.py test pages.tests_schema_ops -v 2``
"""
from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App, AppMember
from pages.models import Page, PageSchemaOperation
from pages.schema_ops import append_operations, broadcast_operations
from pages.schema_ops_consumer import websocket_urlpatterns

User = get_user_model()


def make_schema(text: str = "base") -> dict:
    return {
        "schemaVersion": 2,
        "rootId": "root-1",
        "nodes": {
            "root-1": {
                "id": "root-1",
                "type": "wp-canvas",
                "componentVersion": "2.0.0",
                "props": {},
                "children": ["text-1"],
            },
            "text-1": {
                "id": "text-1",
                "type": "text",
                "componentVersion": "1.0.0",
                "props": {"text": text},
                "children": [],
            },
        },
        "variables": {},
        "meta": {"title": "", "lang": "zh-CN"},
        "layout": {"mode": "flow", "width": 1200, "height": 800},
    }


def upsert_op(
    node_id: str = "text-1",
    text: str = "hello",
    counter: int = 1,
    client_id: str = "tab-a",
) -> dict:
    return {
        "kind": "node.upsert",
        "nodeId": node_id,
        "node": {
            "id": node_id,
            "type": "text",
            "componentVersion": "1.0.0",
            "props": {"text": text},
            "children": [],
        },
        "clock": {"counter": counter, "clientId": client_id},
    }


def delete_op(node_id: str = "text-1", counter: int = 1, client_id: str = "tab-a") -> dict:
    return {
        "kind": "node.delete",
        "nodeId": node_id,
        "clock": {"counter": counter, "clientId": client_id},
    }


def meta_op(title: str = "t", counter: int = 1, client_id: str = "tab-a") -> dict:
    return {
        "kind": "schema.meta",
        "meta": {"title": title, "lang": "zh-CN"},
        "clock": {"counter": counter, "clientId": client_id},
    }


def bearer(user) -> str:
    return f"Bearer {AccessToken.for_user(user)}"


def make_fixtures():
    owner = User.objects.create_user(username="ops-owner", password="pw-12345678")
    editor = User.objects.create_user(username="ops-editor", password="pw-12345678")
    viewer = User.objects.create_user(username="ops-viewer", password="pw-12345678")
    outsider = User.objects.create_user(username="ops-outsider", password="pw-12345678")
    app = App.objects.create(name="Ops Demo", code="ops-demo", owner=owner)
    AppMember.objects.create(app=app, user=editor, role="editor")
    AppMember.objects.create(app=app, user=viewer, role="viewer")
    page = Page.objects.create(
        app=app,
        name="Home",
        path="home",
        type="page",
        status="draft",
        schema=make_schema("base"),
    )
    other = Page.objects.create(
        app=app,
        name="Other",
        path="other",
        type="page",
        status="draft",
        schema=make_schema("other"),
    )
    return owner, editor, viewer, outsider, app, page, other


class PageSchemaOperationModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        (
            cls.owner,
            cls.editor,
            cls.viewer,
            cls.outsider,
            cls.app,
            cls.page,
            cls.other,
        ) = make_fixtures()

    def test_append_assigns_per_page_sequence(self):
        first = append_operations(
            self.page.id,
            client_id="tab-a",
            ops=[upsert_op(text="one"), meta_op("one")],
            user=self.owner,
        )
        self.assertEqual([row.seq for row in first], [1, 2])
        second = append_operations(
            self.page.id,
            client_id="tab-a",
            ops=[delete_op(counter=3)],
            user=self.owner,
        )
        self.assertEqual([row.seq for row in second], [3])
        other = append_operations(
            self.other.id,
            client_id="tab-b",
            ops=[upsert_op(text="other", client_id="tab-b")],
            user=self.owner,
        )
        self.assertEqual([row.seq for row in other], [1])
        self.assertEqual(PageSchemaOperation.objects.filter(page=self.page).count(), 3)
        self.assertEqual(
            list(
                PageSchemaOperation.objects.filter(page=self.page)
                .order_by("seq")
                .values_list("seq", flat=True)
            ),
            [1, 2, 3],
        )

    def test_append_does_not_modify_page_schema_or_revision(self):
        before = Page.objects.get(pk=self.page.id)
        append_operations(
            self.page.id,
            client_id="tab-a",
            ops=[upsert_op(text="only-in-op-log")],
            user=self.owner,
        )
        after = Page.objects.get(pk=self.page.id)
        self.assertEqual(after.schema, before.schema)
        self.assertEqual(after.schema_revision, before.schema_revision)

    def test_unique_page_seq_constraint(self):
        PageSchemaOperation.objects.create(
            page=self.page,
            seq=1,
            client_id="tab-a",
            user=self.owner,
            base_revision=1,
            op=upsert_op(),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PageSchemaOperation.objects.create(
                    page=self.page,
                    seq=1,
                    client_id="tab-a",
                    user=self.owner,
                    base_revision=1,
                    op=upsert_op(text="dup"),
                )

    def test_log_is_append_only(self):
        append_operations(
            self.page.id,
            client_id="tab-a",
            ops=[upsert_op()],
            user=self.owner,
        )
        row = PageSchemaOperation.objects.get(page=self.page, seq=1)
        row.op = meta_op()
        with self.assertRaises(RuntimeError):
            row.save()
        with self.assertRaises(RuntimeError):
            row.delete()
        with self.assertRaises(RuntimeError):
            PageSchemaOperation.objects.filter(pk=row.pk).update(op=meta_op())
        with self.assertRaises(RuntimeError):
            PageSchemaOperation.objects.filter(pk=row.pk).delete()
        self.assertEqual(PageSchemaOperation.objects.count(), 1)

    def test_invalid_batch_is_rejected_without_writing(self):
        with self.assertRaises(Exception):
            append_operations(
                self.page.id,
                client_id="tab-a",
                ops=[upsert_op(), {"kind": "node.delete"}],
                user=self.owner,
            )
        self.assertEqual(PageSchemaOperation.objects.count(), 0)

    def test_clock_client_must_match_batch_client(self):
        with self.assertRaises(Exception):
            append_operations(
                self.page.id,
                client_id="tab-a",
                ops=[upsert_op(client_id="tab-b")],
                user=self.owner,
            )
        self.assertEqual(PageSchemaOperation.objects.count(), 0)

    def test_too_many_operations_in_one_batch_is_rejected(self):
        many = [upsert_op(text=f"n{i}", counter=i + 1) for i in range(201)]
        with self.assertRaises(Exception):
            append_operations(
                self.page.id, client_id="tab-a", ops=many, user=self.owner
            )
        self.assertEqual(PageSchemaOperation.objects.count(), 0)


class PageSchemaOpsApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        (
            cls.owner,
            cls.editor,
            cls.viewer,
            cls.outsider,
            cls.app,
            cls.page,
            cls.other,
        ) = make_fixtures()

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.owner))

    def url(self, page_id: int | None = None) -> str:
        return f"/api/pages/{page_id or self.page.id}/schema/ops/"

    def _append(self, count: int = 3, page_id: int | None = None):
        return append_operations(
            page_id or self.page.id,
            client_id="tab-a",
            ops=[
                upsert_op(text=f"v{i}", counter=i + 1) for i in range(count)
            ],
            user=self.owner,
        )

    # ---------------------------------------------------------------- 写
    def test_editor_appends_batch_and_gets_sequences(self):
        resp = self.client.post(
            self.url(),
            {
                "client_id": "tab-editor",
                "base_revision": 1,
                "ops": [
                    upsert_op(counter=1, client_id="tab-editor"),
                    meta_op("next", counter=2, client_id="tab-editor"),
                ],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["seqs"], [1, 2])
        self.assertEqual(resp.data["last_seq"], 2)
        self.assertEqual([item["seq"] for item in resp.data["ops"]], [1, 2])
        self.assertEqual(resp.data["ops"][0]["client_id"], "tab-editor")
        self.assertEqual(resp.data["ops"][0]["user_id"], self.owner.id)
        self.assertEqual(resp.data["ops"][0]["username"], self.owner.username)
        self.assertEqual(resp.data["ops"][0]["op"]["kind"], "node.upsert")
        self.assertIsNotNone(resp.data["ops"][0]["created_at"])
        self.assertEqual(PageSchemaOperation.objects.filter(page=self.page).count(), 2)

    def test_editor_can_append_many_batches(self):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.editor))
        first = self.client.post(
            self.url(),
            {"client_id": "tab-editor", "ops": [upsert_op(client_id="tab-editor")]},
            format="json",
        )
        second = self.client.post(
            self.url(),
            {
                "client_id": "tab-editor",
                "ops": [meta_op(counter=2, client_id="tab-editor")],
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data["seqs"], [1])
        self.assertEqual(second.data["seqs"], [2])

    def test_base_revision_defaults_to_page_schema_revision(self):
        resp = self.client.post(
            self.url(),
            {"client_id": "tab-a", "ops": [upsert_op()]},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        row = PageSchemaOperation.objects.get(page=self.page, seq=1)
        self.assertEqual(row.base_revision, self.page.schema_revision)

    def test_viewer_cannot_append(self):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.viewer))
        resp = self.client.post(
            self.url(),
            {"client_id": "tab-viewer", "ops": [upsert_op()]},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(PageSchemaOperation.objects.count(), 0)

    def test_invalid_batch_returns_400_and_writes_nothing(self):
        resp = self.client.post(
            self.url(),
            {
                "client_id": "tab-a",
                "ops": [upsert_op(), {"kind": "node.delete", "nodeId": "x"}],
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PageSchemaOperation.objects.count(), 0)

    def test_clock_client_mismatch_returns_400(self):
        resp = self.client.post(
            self.url(),
            {"client_id": "tab-a", "ops": [upsert_op(client_id="tab-b")]},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_batch_over_limit_returns_400(self):
        ops = [upsert_op(counter=i + 1) for i in range(201)]
        resp = self.client.post(
            self.url(), {"client_id": "tab-a", "ops": ops}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(PageSchemaOperation.objects.count(), 0)

    # ---------------------------------------------------------------- 读
    def test_viewer_can_list_operations(self):
        self._append(3)
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.viewer))
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["page_id"], self.page.id)
        self.assertEqual(resp.data["seq"], 3)
        self.assertEqual([item["seq"] for item in resp.data["ops"]], [1, 2, 3])
        self.assertFalse(resp.data["has_more"])

    def test_after_filter_and_pagination(self):
        self._append(5)
        resp = self.client.get(self.url(), {"after": 2, "limit": 2})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["after"], 2)
        self.assertEqual([item["seq"] for item in resp.data["ops"]], [3, 4])
        self.assertTrue(resp.data["has_more"])
        self.assertEqual(resp.data["seq"], 5)

        tail = self.client.get(self.url(), {"after": 4, "limit": 2})
        self.assertEqual([item["seq"] for item in tail.data["ops"]], [5])
        self.assertFalse(tail.data["has_more"])

        empty = self.client.get(self.url(), {"after": 5})
        self.assertEqual(empty.data["ops"], [])
        self.assertFalse(empty.data["has_more"])

    def test_invalid_cursor_is_rejected(self):
        bad_after = self.client.get(self.url(), {"after": "abc"})
        self.assertEqual(bad_after.status_code, 400)
        negative = self.client.get(self.url(), {"after": -1})
        self.assertEqual(negative.status_code, 400)
        bad_limit = self.client.get(self.url(), {"limit": "x"})
        self.assertEqual(bad_limit.status_code, 400)

    def test_operations_are_scoped_to_page(self):
        self._append(2, page_id=self.page.id)
        self._append(1, page_id=self.other.id)
        resp = self.client.get(self.url(self.other.id))
        self.assertEqual([item["seq"] for item in resp.data["ops"]], [1])

    def test_outsider_cannot_list(self):
        self._append(1)
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.outsider))
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 403)

    def test_missing_page_is_404(self):
        resp = self.client.get(self.url(999999))
        self.assertEqual(resp.status_code, 404)


class PageSchemaOpsWebsocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        (
            self.owner,
            self.editor,
            self.viewer,
            self.outsider,
            self.app,
            self.page,
            self.other,
        ) = make_fixtures()

    def _url(self, user, page_id: int | None = None, after: int | None = None) -> str:
        token = str(AccessToken.for_user(user))
        query = f"?token={token}"
        if after is not None:
            query += f"&after={after}"
        return f"/ws/designer-ops/{page_id or self.page.id}/{query}"

    async def _connect(self, user, page_id: int | None = None, after: int | None = None):
        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns), self._url(user, page_id, after)
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        snapshot = await communicator.receive_json_from(timeout=2)
        return communicator, snapshot

    @database_sync_to_async
    def _rows(self, page_id: int | None = None):
        return list(
            PageSchemaOperation.objects.filter(page_id=page_id or self.page.id)
            .order_by("seq")
            .values("seq", "client_id", "op")
        )

    def _seed(self, count: int = 2):
        append_operations(
            self.page.id,
            client_id="tab-seed",
            ops=[
                upsert_op(
                    text=f"v{i}", counter=i + 1, client_id="tab-seed"
                )
                for i in range(count)
            ],
            user=self.owner,
        )

    # ---------------------------------------------------------------- snapshot
    def test_snapshot_replays_ops_after_cursor(self):
        self._seed(3)

        async def scenario():
            ws, snap = await self._connect(self.viewer, after=1)
            await ws.disconnect()
            return snap

        snap = async_to_sync(scenario)()
        self.assertEqual(snap["type"], "snapshot")
        self.assertEqual(snap["page_id"], self.page.id)
        self.assertEqual(snap["after"], 1)
        self.assertEqual(snap["seq"], 3)
        self.assertEqual([item["seq"] for item in snap["ops"]], [2, 3])
        self.assertFalse(snap["has_more"])
        self.assertNotIn("schema", snap)
        self.assertEqual(snap["schema_revision"], 1)

    def test_snapshot_from_zero_is_paginated(self):
        self._seed(3)

        async def scenario():
            token = str(AccessToken.for_user(self.viewer))
            url = f"/ws/designer-ops/{self.page.id}/?token={token}&after=0&limit=2"
            communicator = WebsocketCommunicator(
                URLRouter(websocket_urlpatterns), url
            )
            connected, _ = await communicator.connect()
            snap = await communicator.receive_json_from(timeout=2)
            await communicator.disconnect()
            return connected, snap

        connected, snap = async_to_sync(scenario)()
        self.assertTrue(connected)
        self.assertEqual([item["seq"] for item in snap["ops"]], [1, 2])
        self.assertEqual(snap["seq"], 3)
        self.assertTrue(snap["has_more"])

    def test_invalid_token_outsider_and_missing_page_are_rejected(self):
        async def connect_raw(url):
            communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), url)
            connected, _ = await communicator.connect()
            if connected:
                await communicator.disconnect()
            return connected

        async def scenario():
            bad = await connect_raw(
                f"/ws/designer-ops/{self.page.id}/?token=not-a-token"
            )
            missing = await connect_raw(f"/ws/designer-ops/{self.page.id}/")
            outsider = await connect_raw(self._url(self.outsider))
            missing_page = await connect_raw(self._url(self.owner, page_id=999999))
            return bad, missing, outsider, missing_page

        self.assertEqual(async_to_sync(scenario)(), (False, False, False, False))

    # ---------------------------------------------------------------- append / broadcast
    def test_editor_append_persists_acks_and_broadcasts_to_peer(self):
        async def scenario():
            owner_ws, _ = await self._connect(self.owner)
            editor_ws, _ = await self._connect(self.editor)
            await editor_ws.send_json_to(
                {
                    "type": "ops",
                    "client_id": "tab-editor",
                    "base_revision": 1,
                    "ops": [upsert_op(text="remote", counter=4, client_id="tab-editor")],
                }
            )
            ack = await editor_ws.receive_json_from(timeout=2)
            peer = await owner_ws.receive_json_from(timeout=2)
            sender_extra = await editor_ws.receive_nothing(timeout=0.2)
            rows = await self._rows()
            await owner_ws.disconnect()
            await editor_ws.disconnect()
            return ack, peer, sender_extra, rows

        ack, peer, sender_extra, rows = async_to_sync(scenario)()
        self.assertTrue(sender_extra, "发送方不应收到重复的 ops 广播")
        self.assertEqual(ack["type"], "appended")
        self.assertEqual(ack["seqs"], [1])
        self.assertEqual(ack["last_seq"], 1)
        self.assertEqual(ack["client_id"], "tab-editor")
        self.assertEqual(peer["type"], "ops")
        self.assertEqual(peer["last_seq"], 1)
        self.assertEqual(peer["from"], self.editor.username)
        self.assertEqual(peer["ops"][0]["op"]["node"]["props"]["text"], "remote")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seq"], 1)
        self.assertEqual(rows[0]["client_id"], "tab-editor")

    def test_rest_style_append_broadcasts_to_ws_clients(self):
        def append_and_broadcast():
            rows = append_operations(
                self.page.id,
                client_id="tab-rest",
                ops=[upsert_op(text="rest", counter=1, client_id="tab-rest")],
                user=self.owner,
            )
            broadcast_operations(self.page.id, rows, sender=self.owner.username)
            return [row.seq for row in rows]

        async def scenario():
            peer_ws, _ = await self._connect(self.viewer)
            seqs = await database_sync_to_async(append_and_broadcast)()
            event = await peer_ws.receive_json_from(timeout=2)
            await peer_ws.disconnect()
            return seqs, event

        seqs, event = async_to_sync(scenario)()
        self.assertEqual(seqs, [1])
        self.assertEqual(event["type"], "ops")
        self.assertEqual(event["last_seq"], 1)
        self.assertEqual(event["from"], self.owner.username)
        self.assertEqual(event["ops"][0]["op"]["node"]["props"]["text"], "rest")

    def test_viewer_cannot_append(self):
        async def scenario():
            viewer_ws, _ = await self._connect(self.viewer)
            editor_ws, _ = await self._connect(self.editor)
            await viewer_ws.send_json_to(
                {
                    "type": "ops",
                    "client_id": "tab-viewer",
                    "ops": [upsert_op()],
                }
            )
            error = await viewer_ws.receive_json_from(timeout=2)
            peer_silent = await editor_ws.receive_nothing(timeout=0.2)
            await viewer_ws.disconnect()
            await editor_ws.disconnect()
            return error, peer_silent

        error, peer_silent = async_to_sync(scenario)()
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "forbidden")
        self.assertTrue(peer_silent)

    def test_invalid_op_is_rejected_without_persisting(self):
        async def scenario():
            ws, _ = await self._connect(self.editor)
            await ws.send_json_to(
                {
                    "type": "ops",
                    "client_id": "tab-editor",
                    "ops": [{"kind": "node.delete", "nodeId": "x"}],
                }
            )
            error = await ws.receive_json_from(timeout=2)
            rows = await self._rows()
            await ws.disconnect()
            return error, rows

        error, rows = async_to_sync(scenario)()
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "invalid-ops")
        self.assertEqual(rows, [])

    def test_asgi_application_exposes_designer_ops_route(self):
        from config.asgi import application

        self._seed(1)

        async def scenario():
            communicator = WebsocketCommunicator(
                application, self._url(self.owner, after=0)
            )
            connected, _ = await communicator.connect()
            snap = (
                await communicator.receive_json_from(timeout=2) if connected else None
            )
            if connected:
                await communicator.disconnect()
            return connected, snap

        connected, snap = async_to_sync(scenario)()
        self.assertTrue(connected)
        self.assertEqual(snap["type"], "snapshot")
        self.assertEqual([item["seq"] for item in snap["ops"]], [1])
