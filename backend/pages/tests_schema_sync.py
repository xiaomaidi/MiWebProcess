"""设计器 schema 持久化 revision / 保存冲突 / 实时同步 WebSocket 测试。

运行：``python manage.py test pages.tests_schema_sync -v 2``
"""
from __future__ import annotations

import json

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App, AppMember
from pages.models import Page, PageVersion
from pages.schema_consumer import websocket_urlpatterns
from pages.schema_sync import compute_schema_hash, revision_cache_key

User = get_user_model()


def make_schema(text: str = "hello") -> dict:
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


def bearer(user) -> str:
    return f"Bearer {AccessToken.for_user(user)}"


def make_fixtures():
    owner = User.objects.create_user(username="sync-owner", password="pw-12345678")
    editor = User.objects.create_user(username="sync-editor", password="pw-12345678")
    viewer = User.objects.create_user(username="sync-viewer", password="pw-12345678")
    outsider = User.objects.create_user(username="sync-outsider", password="pw-12345678")
    app = App.objects.create(name="Sync Demo", code="sync-demo", owner=owner)
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
    return owner, editor, viewer, outsider, app, page


class SchemaHashTests(SimpleTestCase):
    def test_hash_is_stable_across_key_order(self):
        a = {"rootId": "r", "nodes": {"r": {"id": "r", "type": "wp-canvas"}}, "schemaVersion": 2}
        b = {"schemaVersion": 2, "nodes": {"r": {"type": "wp-canvas", "id": "r"}}, "rootId": "r"}
        self.assertEqual(compute_schema_hash(a), compute_schema_hash(b))
        self.assertEqual(len(compute_schema_hash(a)), 64)

    def test_hash_changes_when_schema_changes(self):
        self.assertNotEqual(
            compute_schema_hash(make_schema("a")),
            compute_schema_hash(make_schema("b")),
        )


class SchemaRevisionApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner, cls.editor, cls.viewer, cls.outsider, cls.app, cls.page = make_fixtures()

    def setUp(self):
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.owner))

    def url(self) -> str:
        return f"/api/pages/{self.page.id}/schema/"

    def refresh(self) -> Page:
        return Page.objects.get(pk=self.page.id)

    # ---------------------------------------------------------------- 持久化修订号
    def test_get_schema_returns_revision_and_hash(self):
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["schema"], self.page.schema)
        self.assertEqual(resp.data["schema_revision"], 1)
        self.assertEqual(resp.data["schema_hash"], compute_schema_hash(self.page.schema))

    def test_page_detail_includes_schema_revision(self):
        resp = self.client.get(f"/api/pages/{self.page.id}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["schema_revision"], 1)

    def test_each_successful_put_increments_revision(self):
        first = self.client.put(self.url(), {"schema": make_schema("one")}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["schema_revision"], 2)
        self.assertEqual(first.data["schema_hash"], compute_schema_hash(make_schema("one")))
        self.assertEqual(first.data["page"]["schema_revision"], 2)

        second = self.client.put(
            self.url(), {"schema": make_schema("two"), "base_revision": 2}, format="json"
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.data["schema_revision"], 3)
        self.assertEqual(self.refresh().schema_revision, 3)
        self.assertEqual(self.refresh().schema, make_schema("two"))

    def test_put_without_base_revision_is_legacy_compatible(self):
        resp = self.client.put(self.url(), {"schema": make_schema("no-base")}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["schema_revision"], 2)

    # ---------------------------------------------------------------- 冲突检测
    def test_stale_base_revision_returns_409_without_writing(self):
        saved = self.client.put(self.url(), {"schema": make_schema("winner")}, format="json")
        self.assertEqual(saved.status_code, 200)
        current = self.refresh()
        self.assertEqual(current.schema_revision, 2)
        self.assertEqual(current.schema_updated_by, self.owner)

        # editor 仍基于旧 revision 保存 → 409
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.editor))
        conflict = self.client.put(
            self.url(), {"schema": make_schema("loser"), "base_revision": 1}, format="json"
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["code"], "schema_conflict")
        self.assertEqual(conflict.data["current_revision"], 2)
        self.assertEqual(conflict.data["current_hash"], compute_schema_hash(make_schema("winner")))
        self.assertEqual(conflict.data["schema"], make_schema("winner"))
        self.assertEqual(conflict.data["updated_by"], self.owner.username)
        self.assertIn("updated_at", conflict.data)
        self.assertIn("detail", conflict.data)

        latest = self.refresh()
        self.assertEqual(latest.schema_revision, 2)
        self.assertEqual(latest.schema, make_schema("winner"))

    def test_conflict_is_reported_against_latest_after_multiple_saves(self):
        self.client.put(self.url(), {"schema": make_schema("s1")}, format="json")
        self.client.put(
            self.url(), {"schema": make_schema("s2"), "base_revision": 2}, format="json"
        )
        conflict = self.client.put(
            self.url(), {"schema": make_schema("s3"), "base_revision": 1}, format="json"
        )
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.data["current_revision"], 3)
        self.assertEqual(conflict.data["schema"], make_schema("s2"))

    def test_invalid_base_revision_is_rejected(self):
        resp = self.client.put(
            self.url(), {"schema": make_schema("x"), "base_revision": "abc"}, format="json"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.refresh().schema_revision, 1)

    def test_legacy_base_version_conflict_still_detected(self):
        # page.version 初始 0，首次保存后变 1；旧前端继续用 0 保存 → 409。
        self.client.put(self.url(), {"schema": make_schema("v1"), "base_version": 0}, format="json")
        legacy = self.client.put(
            self.url(), {"schema": make_schema("v2"), "base_version": 0}, format="json"
        )
        self.assertEqual(legacy.status_code, 409)
        self.assertEqual(legacy.data["code"], "schema_conflict")
        self.assertEqual(legacy.data["current_revision"], 2)

    def test_viewer_cannot_save(self):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.viewer))
        resp = self.client.put(self.url(), {"schema": make_schema("nope")}, format="json")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.refresh().schema_revision, 1)

    def test_outsider_cannot_read_schema(self):
        self.client.credentials(HTTP_AUTHORIZATION=bearer(self.outsider))
        resp = self.client.get(self.url())
        self.assertEqual(resp.status_code, 403)

    # ---------------------------------------------------------------- 其它草稿写入
    def test_rollback_increments_revision(self):
        PageVersion.objects.create(
            page=self.page,
            version=1,
            schema=make_schema("published"),
            schema_version=2,
            publisher=self.owner,
        )
        resp = self.client.post(f"/api/pages/{self.page.id}/versions/1/rollback/")
        self.assertEqual(resp.status_code, 200)
        latest = self.refresh()
        self.assertEqual(latest.schema_revision, 2)
        self.assertEqual(latest.schema, make_schema("published"))
        self.assertEqual(latest.schema_updated_by, self.owner)


class SchemaSyncWebsocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner, self.editor, self.viewer, self.outsider, self.app, self.page = make_fixtures()
        cache.delete(revision_cache_key(self.page.id))

    # ---------------------------------------------------------------- helpers
    def _url(self, user, page_id: int | None = None) -> str:
        token = str(AccessToken.for_user(user))
        return f"/ws/designer-sync/{page_id or self.page.id}/?token={token}"

    async def _connect(self, user, page_id: int | None = None):
        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), self._url(user, page_id))
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        snapshot = await communicator.receive_json_from(timeout=2)
        return communicator, snapshot

    @database_sync_to_async
    def _page_row(self):
        page = Page.objects.get(pk=self.page.id)
        return page.schema, page.schema_revision

    # ---------------------------------------------------------------- snapshot / auth
    def test_snapshot_uses_db_schema_and_revision(self):
        async def scenario():
            ws, snap = await self._connect(self.viewer)
            await ws.disconnect()
            return snap

        snap = async_to_sync(scenario)()
        self.assertEqual(snap["type"], "snapshot")
        self.assertEqual(snap["revision"], 1)
        self.assertEqual(snap["schema"], self.page.schema)
        self.assertEqual(snap["hash"], compute_schema_hash(self.page.schema))
        self.assertEqual(snap["page_id"], self.page.id)

    def test_asgi_application_exposes_designer_sync_route(self):
        from config.asgi import application

        async def scenario():
            communicator = WebsocketCommunicator(application, self._url(self.owner))
            connected, _ = await communicator.connect()
            snap = await communicator.receive_json_from(timeout=2) if connected else None
            if connected:
                await communicator.disconnect()
            return connected, snap

        connected, snap = async_to_sync(scenario)()
        self.assertTrue(connected)
        self.assertEqual(snap["type"], "snapshot")

    def test_invalid_token_outsider_and_missing_page_are_rejected(self):
        async def connect_raw(url):
            communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), url)
            connected, _ = await communicator.connect()
            if connected:
                await communicator.disconnect()
            return connected

        async def scenario():
            bad = await connect_raw(f"/ws/designer-sync/{self.page.id}/?token=not-a-token")
            missing = await connect_raw(f"/ws/designer-sync/{self.page.id}/")
            outsider = await connect_raw(self._url(self.outsider))
            missing_page = await connect_raw(self._url(self.owner, page_id=999999))
            return bad, missing, outsider, missing_page

        self.assertEqual(async_to_sync(scenario)(), (False, False, False, False))

    # ---------------------------------------------------------------- 广播
    def test_editor_broadcast_reaches_peer_but_not_sender_and_does_not_persist(self):
        async def scenario():
            owner_ws, _ = await self._connect(self.owner)
            editor_ws, _ = await self._connect(self.editor)
            await owner_ws.send_json_to(
                {
                    "type": "schema",
                    "base_revision": 1,
                    "client_id": "client-owner",
                    "schema": make_schema("remote"),
                }
            )
            received = await editor_ws.receive_json_from(timeout=2)
            own_echo = await owner_ws.receive_nothing(timeout=0.2)
            row = await self._page_row()
            await owner_ws.disconnect()
            await editor_ws.disconnect()
            return received, own_echo, row

        received, own_echo, (schema, revision) = async_to_sync(scenario)()
        self.assertTrue(own_echo, "发送方连接不应收到自己的 schema 回声")
        self.assertEqual(received["type"], "schema")
        self.assertEqual(received["revision"], 2)
        self.assertEqual(received["client_id"], "client-owner")
        self.assertEqual(received["from"], self.owner.username)
        self.assertEqual(received["schema"], make_schema("remote"))
        self.assertEqual(received["hash"], compute_schema_hash(make_schema("remote")))
        # 实时广播不落库
        self.assertEqual(schema, self.page.schema)
        self.assertEqual(revision, 1)

    def test_ephemeral_revision_increments_per_message(self):
        async def scenario():
            owner_ws, _ = await self._connect(self.owner)
            editor_ws, _ = await self._connect(self.editor)
            await owner_ws.send_json_to(
                {"type": "schema", "base_revision": 1, "client_id": "c1", "schema": make_schema("a")}
            )
            first = await editor_ws.receive_json_from(timeout=2)
            await owner_ws.send_json_to(
                {"type": "schema", "base_revision": first["revision"], "client_id": "c2",
                 "schema": make_schema("b")}
            )
            second = await editor_ws.receive_json_from(timeout=2)
            await owner_ws.disconnect()
            await editor_ws.disconnect()
            return first, second

        first, second = async_to_sync(scenario)()
        self.assertEqual(first["revision"], 2)
        self.assertEqual(second["revision"], 3)
        self.assertEqual(second["client_id"], "c2")

    def test_snapshot_after_unsaved_broadcast_comes_from_db(self):
        """MVP 限制：临时广播不落库，新连接 snapshot 仍是数据库草稿。"""

        async def scenario():
            owner_ws, _ = await self._connect(self.owner)
            peer_ws, _ = await self._connect(self.editor)
            await owner_ws.send_json_to(
                {"type": "schema", "base_revision": 1, "client_id": "c1", "schema": make_schema("tmp")}
            )
            await peer_ws.receive_json_from(timeout=2)
            fresh_ws, snap = await self._connect(self.viewer)
            await fresh_ws.disconnect()
            await owner_ws.disconnect()
            await peer_ws.disconnect()
            return snap

        snap = async_to_sync(scenario)()
        self.assertEqual(snap["schema"], self.page.schema)
        self.assertEqual(snap["revision"], 1)

    def test_viewer_cannot_broadcast(self):
        async def scenario():
            viewer_ws, _ = await self._connect(self.viewer)
            editor_ws, _ = await self._connect(self.editor)
            await viewer_ws.send_json_to(
                {"type": "schema", "client_id": "v1", "schema": make_schema("hack")}
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

    # ---------------------------------------------------------------- 校验 / 限流
    def test_malformed_messages_are_rejected(self):
        async def scenario():
            ws, _ = await self._connect(self.owner)
            await ws.send_to(text_data="{not-json")
            invalid_json = await ws.receive_json_from(timeout=2)

            await ws.send_json_to({"type": "schema", "schema": make_schema("x")})
            missing_client = await ws.receive_json_from(timeout=2)

            await ws.send_json_to(
                {"type": "schema", "client_id": "c1", "base_revision": "1", "schema": make_schema("x")}
            )
            bad_revision = await ws.receive_json_from(timeout=2)

            await ws.send_json_to({"type": "schema", "client_id": "c1", "schema": "nope"})
            bad_schema = await ws.receive_json_from(timeout=2)

            await ws.send_json_to({"type": "schema", "client_id": "c1", "schema": {"rootId": "r"}})
            bad_nodes = await ws.receive_json_from(timeout=2)

            await ws.send_json_to({"type": "nope"})
            unknown = await ws.receive_json_from(timeout=2)
            await ws.disconnect()
            return invalid_json, missing_client, bad_revision, bad_schema, bad_nodes, unknown

        invalid_json, missing_client, bad_revision, bad_schema, bad_nodes, unknown = async_to_sync(
            scenario
        )()
        self.assertEqual(invalid_json["code"], "invalid-json")
        self.assertEqual(missing_client["code"], "invalid-client-id")
        self.assertEqual(bad_revision["code"], "invalid-revision")
        self.assertEqual(bad_schema["code"], "invalid-schema")
        self.assertEqual(bad_nodes["code"], "invalid-schema")
        self.assertEqual(unknown["code"], "unknown-type")

    def test_payload_over_two_megabytes_is_rejected(self):
        async def scenario():
            owner_ws, _ = await self._connect(self.owner)
            editor_ws, _ = await self._connect(self.editor)
            huge = make_schema("x" * (2 * 1024 * 1024))
            await owner_ws.send_json_to(
                {"type": "schema", "client_id": "big", "schema": huge}
            )
            error = await owner_ws.receive_json_from(timeout=5)
            silent = await editor_ws.receive_nothing(timeout=0.3)
            await owner_ws.disconnect()
            await editor_ws.disconnect()
            return error, silent

        error, silent = async_to_sync(scenario)()
        self.assertEqual(error["type"], "error")
        self.assertEqual(error["code"], "payload_too_large")
        self.assertTrue(silent)
