"""区块版本历史 + 市场发布 pipeline 测试。

运行：cd backend && python manage.py test pages.tests_block_versions -v 2 --noinput

覆盖：
- PageBlockVersion 自动创建（区块创建 / PATCH 更新）、唯一约束；
- 版本列表 / 详情 / 手动创建快照 / 权限；
- 回滚仅恢复草稿、已发布快照不受影响、回滚后生成新版本；
- 发布到市场：创建 / 幂等更新 / payload schema / 显式 slug 冲突 / market 不可用；
- 区块详情 latest_version / version_count。

本模块同时充当测试专用 ROOT_URLCONF（模块级 urlpatterns = pages.block_urls），
因此无需修改 config/urls.py 即可独立验证新增路由。
"""
from __future__ import annotations

import copy
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App, AppMember
from market.models import MarketItem
from pages.block_services import MarketUnavailable, create_block_version
from pages.block_urls import urlpatterns  # noqa: F401 - 作为测试 ROOT_URLCONF 的 urlpatterns
from pages.models import Page, PageBlock, PageBlockVersion, PageVersion

User = get_user_model()


def api_client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


def source_schema() -> dict:
    return {
        "schemaVersion": 2,
        "rootId": "root-1",
        "nodes": {
            "root-1": {
                "id": "root-1",
                "type": "wp-canvas",
                "componentVersion": "2.0.0",
                "props": {},
                "children": ["n-text", "n-card"],
            },
            "n-text": {
                "id": "n-text",
                "type": "wp-text",
                "componentVersion": "2.0.0",
                "props": {"text": "标题"},
                "children": [],
            },
            "n-card": {
                "id": "n-card",
                "type": "wp-container",
                "componentVersion": "2.0.0",
                "props": {},
                "children": ["n-inner"],
            },
            "n-inner": {
                "id": "n-inner",
                "type": "wp-text",
                "componentVersion": "2.0.0",
                "props": {"text": "内容"},
                "children": [],
            },
        },
        "variables": {},
        "meta": {"title": "首页", "lang": "zh-CN", "globalStyle": {"cssVars": {}}},
        "layout": {"mode": "flow", "width": 1200, "height": 800},
    }


def first_text_node(schema: dict) -> str:
    for node_id, node in schema["nodes"].items():
        if node.get("type") == "wp-text":
            return node_id
    raise AssertionError("schema 中没有 wp-text 节点")


@override_settings(ROOT_URLCONF="pages.tests_block_versions")
class BlockVersionBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("ver-owner", password="pass-12345")
        cls.editor = User.objects.create_user("ver-editor", password="pass-12345")
        cls.viewer = User.objects.create_user("ver-viewer", password="pass-12345")
        cls.stranger = User.objects.create_user("ver-stranger", password="pass-12345")
        cls.app = App.objects.create(name="版本测试应用", code="ver-demo", owner=cls.owner, status="draft")
        AppMember.objects.create(app=cls.app, user=cls.editor, role="editor")
        AppMember.objects.create(app=cls.app, user=cls.viewer, role="viewer")
        cls.page = Page.objects.create(
            app=cls.app,
            name="首页",
            path="home",
            type="page",
            schema=source_schema(),
            status="draft",
        )

    def create_block(self, client=None, **payload) -> dict:
        body = {"name": "产品卡片", "source_page_id": self.page.id, "node_ids": ["n-card"]}
        body.update(payload)
        response = (client or api_client(self.editor)).post(
            f"/api/apps/{self.app.id}/blocks/", body, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def block(self, block_id: int) -> PageBlock:
        return PageBlock.objects.select_related("page").get(id=block_id)

    def version_url(self, block_id: int, suffix: str = "") -> str:
        return f"/api/blocks/{block_id}/versions/{suffix}"

    def publish_url(self, block_id: int) -> str:
        return f"/api/blocks/{block_id}/publish-market/"


class BlockVersionAutoTests(BlockVersionBase):
    def test_create_block_creates_version_one(self):
        data = self.create_block()
        block = self.block(data["block"]["id"])
        self.assertEqual(block.versions.count(), 1)
        version = block.versions.get()
        self.assertEqual(version.version, 1)
        self.assertEqual(version.created_by_id, self.editor.id)
        self.assertIn("创建", version.changelog)
        self.assertEqual(version.snapshot["rootId"], block.page.schema["rootId"])
        self.assertEqual(set(version.snapshot["nodes"]), set(block.page.schema["nodes"]))
        self.assertEqual(data["block"]["latest_version"], 1)
        self.assertEqual(data["block"]["version_count"], 1)

    def test_patch_block_creates_next_version(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).patch(
            f"/api/blocks/{block_id}/", {"name": "产品卡片 v2"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["block"]["version_count"], 2)
        self.assertEqual(response.data["block"]["latest_version"], 2)
        self.assertTrue(any("版本快照" in w for w in response.data["warnings"]))
        versions = list(PageBlockVersion.objects.filter(block_id=block_id).order_by("version"))
        self.assertEqual([v.version for v in versions], [1, 2])
        self.assertIn("name", versions[1].changelog)

    def test_block_version_is_unique_per_block(self):
        block_id = self.create_block()["block"]["id"]
        block = self.block(block_id)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PageBlockVersion.objects.create(block=block, version=1, snapshot={"rootId": "", "nodes": {}})

    def test_same_version_number_allowed_for_other_block(self):
        self.create_block(code="one")
        self.create_block(code="two")
        self.assertEqual(PageBlockVersion.objects.filter(version=1).count(), 2)


class BlockVersionApiTests(BlockVersionBase):
    def test_list_versions_as_viewer(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).get(self.version_url(block_id))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["version"], 1)
        self.assertIn("snapshot", row)
        self.assertIn("changelog", row)

    def test_version_detail_returns_snapshot(self):
        data = self.create_block()
        block_id = data["block"]["id"]
        response = api_client(self.viewer).get(self.version_url(block_id, "1/"))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["version"], 1)
        self.assertEqual(response.data["block_id"], block_id)
        self.assertTrue(response.data["snapshot"]["rootId"])
        self.assertTrue(response.data["snapshot"]["nodes"])

    def test_unknown_version_returns_404(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).get(self.version_url(block_id, "99/"))
        self.assertEqual(response.status_code, 404)

    def test_editor_can_create_manual_snapshot(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).post(
            self.version_url(block_id), {"changelog": "发布前留档"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["created"])
        self.assertEqual(response.data["version"]["version"], 2)
        self.assertEqual(response.data["version"]["changelog"], "发布前留档")
        self.assertEqual(response.data["block"]["version_count"], 2)

    def test_manual_snapshot_can_skip_unchanged(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).post(
            self.version_url(block_id), {"skip_if_unchanged": True}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["created"])
        self.assertEqual(response.data["reason"], "unchanged")
        self.assertEqual(response.data["version"]["version"], 1)
        self.assertEqual(PageBlockVersion.objects.filter(block_id=block_id).count(), 1)

    def test_viewer_cannot_create_snapshot(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).post(self.version_url(block_id), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_stranger_cannot_list_versions(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.stranger).get(self.version_url(block_id))
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_list_versions(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client().get(self.version_url(block_id))
        self.assertIn(response.status_code, (401, 403))


class BlockVersionRollbackTests(BlockVersionBase):
    def _backing_page(self, block_id: int) -> Page:
        return Page.objects.get(id=self.block(block_id).page_id)

    def _edit_draft(self, page_id: int, text: str) -> None:
        page = Page.objects.get(id=page_id)
        schema = page.schema
        schema["nodes"][first_text_node(schema)]["props"]["text"] = text
        page.schema = schema
        page.version += 1
        page.save(update_fields=["schema", "version", "updated_at"])

    def test_rollback_restores_backing_page_draft(self):
        data = self.create_block()
        block_id = data["block"]["id"]
        page_id = self.block(block_id).page_id
        page_before = Page.objects.get(id=page_id)
        text_id = first_text_node(page_before.schema)
        original_text = page_before.schema["nodes"][text_id]["props"]["text"]

        self._edit_draft(page_id, "改后草稿")
        created = api_client(self.editor).post(self.version_url(block_id), {"changelog": "v2"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertEqual(created.data["version"]["version"], 2)

        response = api_client(self.editor).post(self.version_url(block_id, "1/rollback/"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["rolled_back_to"], 1)
        self.assertFalse(response.data["was_published"])
        page = Page.objects.get(id=page_id)
        restored_node = page.schema["nodes"][first_text_node(page.schema)]
        self.assertEqual(restored_node["props"]["text"], original_text)
        # 回滚后 page.version +1，并生成新的快照版本
        self.assertEqual(response.data["new_version"]["version"], 3)
        self.assertEqual(response.data["block"]["latest_version"], 3)
        self.assertEqual(response.data["block"]["version_count"], 3)
        # 页面级 meta 不应被快照覆盖丢失
        self.assertEqual(page.schema["meta"]["title"], page_before.schema["meta"]["title"])

    def test_rollback_published_page_keeps_published_snapshot(self):
        data = self.create_block()
        block_id = data["block"]["id"]
        block = self.block(block_id)
        page = Page.objects.get(id=block.page_id)

        published_schema = copy.deepcopy(page.schema)
        page_version = PageVersion.objects.create(
            page=page, version=1, schema=published_schema, schema_version=2, publisher=self.owner
        )
        page.status = "published"
        page.current_version = page_version
        page.save(update_fields=["status", "current_version", "updated_at"])

        self._edit_draft(page.id, "已发布后的草稿")
        self.assertEqual(
            api_client(self.editor).post(self.version_url(block_id), {}, format="json").status_code, 201
        )

        response = api_client(self.editor).post(self.version_url(block_id, "1/rollback/"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["was_published"])
        self.assertTrue(response.data["published_intact"])
        self.assertEqual(response.data["published_version"], 1)
        self.assertTrue(response.data["warnings"])
        self.assertIn("已发布", response.data["warnings"][0])

        page.refresh_from_db()
        page_version.refresh_from_db()
        # 已发布快照与页面状态均保持不变，只有草稿被回滚
        self.assertEqual(page.status, "published")
        self.assertEqual(page_version.schema, published_schema)
        self.assertEqual(
            page.schema["nodes"][first_text_node(page.schema)]["props"]["text"],
            published_schema["nodes"][first_text_node(published_schema)]["props"]["text"],
        )

    def test_rollback_fallback_block_without_page(self):
        expected = {"rootId": "c1", "nodes": {"c1": {"id": "c1", "type": "wp-container", "props": {}, "children": []}}}
        block = PageBlock.objects.create(
            app=self.app,
            name="兜底区块",
            code="fallback",
            page=None,
            schema=copy.deepcopy(expected),
            version=1,
            created_by=self.editor,
        )
        self.assertTrue(create_block_version(block, self.editor, "init", force=True)["created"])
        changed = {
            "rootId": "c2",
            "nodes": {"c2": {"id": "c2", "type": "wp-text", "props": {"text": "改后"}, "children": []}},
        }
        block.schema = changed
        block.save(update_fields=["schema", "updated_at"])
        api_client(self.editor).post(self.version_url(block.id), {"changelog": "changed"}, format="json")

        response = api_client(self.editor).post(self.version_url(block.id, "1/rollback/"), {}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        block.refresh_from_db()
        self.assertEqual(block.schema["rootId"], expected["rootId"])
        self.assertEqual(set(block.schema["nodes"]), set(expected["nodes"]))
        self.assertEqual(block.schema["nodes"]["c1"]["props"], {})
        self.assertIsNone(response.data["page"])
        self.assertFalse(response.data["was_published"])

    def test_rollback_unknown_version_returns_404(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).post(self.version_url(block_id, "99/rollback/"), {}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_viewer_cannot_rollback(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).post(self.version_url(block_id, "1/rollback/"), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_stranger_cannot_rollback(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.stranger).post(self.version_url(block_id, "1/rollback/"), {}, format="json")
        self.assertEqual(response.status_code, 403)


class BlockMarketPublishTests(BlockVersionBase):
    def test_publish_market_creates_item(self):
        data = self.create_block(code="hero")
        block_id = data["block"]["id"]
        response = api_client(self.editor).post(self.publish_url(block_id), {}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["created"])
        item_id = response.data["item_id"]
        item = MarketItem.objects.get(id=item_id)
        self.assertEqual(item.kind, "block")
        self.assertEqual(item.slug, "hero")
        self.assertEqual(item.status, "draft")
        self.assertEqual(item.source_app_id, self.app.id)
        self.assertEqual(item.created_by_id, self.editor.id)
        self.assertEqual(item.payload["code"], "hero")
        self.assertEqual(item.payload["name"], item.name)
        self.assertEqual(item.payload["block"]["id"], block_id)
        self.assertEqual(item.payload["block"]["app_id"], self.app.id)
        self.assertTrue(item.payload["schema"]["rootId"])
        self.assertTrue(item.payload["schema"]["nodes"])
        # 市场安装用 schema 应为内容子树（根不是页面画布）
        root = item.payload["schema"]["nodes"][item.payload["schema"]["rootId"]]
        self.assertNotEqual(root["type"], "wp-canvas")
        self.assertEqual(item.payload["version"], 1)
        self.assertEqual(response.data["version"], 1)

    def test_publish_market_updates_existing_item(self):
        block_id = self.create_block(code="hero")["block"]["id"]
        first = api_client(self.editor).post(self.publish_url(block_id), {}, format="json")
        self.assertEqual(first.status_code, 201)
        second = api_client(self.editor).post(
            self.publish_url(block_id),
            {"status": "published", "name": "市场英雄区块", "category": "hero", "tags": ["营销"]},
            format="json",
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertFalse(second.data["created"])
        self.assertTrue(second.data["updated"])
        self.assertEqual(second.data["item_id"], first.data["item_id"])
        self.assertEqual(MarketItem.objects.filter(kind="block", slug="hero").count(), 1)
        item = MarketItem.objects.get(id=first.data["item_id"])
        self.assertEqual(item.status, "published")
        self.assertEqual(item.name, "市场英雄区块")
        self.assertEqual(item.category, "hero")
        self.assertEqual(item.tags, ["营销"])

    def test_publish_market_explicit_slug_and_status(self):
        block_id = self.create_block(code="hero")["block"]["id"]
        response = api_client(self.editor).post(
            self.publish_url(block_id),
            {"slug": "My_Hero Block", "status": "published", "visibility": "private"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        item = MarketItem.objects.get(id=response.data["item_id"])
        self.assertEqual(item.slug, "my-hero-block")
        self.assertEqual(item.status, "published")
        self.assertEqual(item.visibility, "private")

    def test_publish_market_invalid_status_rejected(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).post(
            self.publish_url(block_id), {"status": "archived"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_publish_market_explicit_slug_conflict_rejected(self):
        first_block = self.create_block(code="hero")["block"]["id"]
        second_block = self.create_block(code="footer")["block"]["id"]
        self.assertEqual(
            api_client(self.editor).post(self.publish_url(first_block), {"slug": "shared"}, format="json").status_code,
            201,
        )
        response = api_client(self.editor).post(
            self.publish_url(second_block), {"slug": "shared"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("slug", response.data)

    def test_publish_market_derived_slug_collision_gets_suffix(self):
        second_app = App.objects.create(name="第二应用", code="ver-other", owner=self.owner)
        second_page = Page.objects.create(
            app=second_app, name="首页2", path="home", type="page", schema=source_schema()
        )
        first_block = self.create_block(code="hero")["block"]["id"]
        response = api_client(self.owner).post(
            f"/api/apps/{second_app.id}/blocks/",
            {"name": "另一英雄", "code": "hero", "source_page_id": second_page.id, "node_ids": ["n-text"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        second_block = response.data["block"]["id"]
        self.assertEqual(
            api_client(self.editor).post(self.publish_url(first_block), {}, format="json").status_code, 201
        )
        second = api_client(self.owner).post(self.publish_url(second_block), {}, format="json")
        self.assertEqual(second.status_code, 201, second.data)
        self.assertEqual(second.data["slug"], "hero-2")

    def test_published_payload_is_installable(self):
        from pages.block_services import create_block

        data = self.create_block(code="hero")
        block_id = data["block"]["id"]
        response = api_client(self.editor).post(self.publish_url(block_id), {}, format="json")
        item = MarketItem.objects.get(id=response.data["item_id"])
        installed, installed_page, _ = create_block(
            self.app,
            self.owner,
            name="从市场安装",
            code="from-market",
            source_schema=item.payload["schema"],
        )
        self.assertNotEqual(installed.id, block_id)
        self.assertGreater(len(installed_page.schema["nodes"]), 1)
        texts = [
            node.get("props", {}).get("text")
            for node in installed_page.schema["nodes"].values()
            if node.get("type") == "wp-text"
        ]
        self.assertIn("内容", texts)

    def test_publish_market_snapshots_changed_schema(self):
        block_id = self.create_block(code="hero")["block"]["id"]
        first = api_client(self.editor).post(self.publish_url(block_id), {}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["version"], 1)

        block = self.block(block_id)
        page = Page.objects.get(id=block.page_id)
        schema = page.schema
        schema["nodes"][first_text_node(schema)]["props"]["text"] = "市场新版内容"
        page.schema = schema
        page.version += 1
        page.save(update_fields=["schema", "version", "updated_at"])

        second = api_client(self.editor).post(
            self.publish_url(block_id), {"status": "published"}, format="json"
        )
        self.assertEqual(second.status_code, 200, second.data)
        self.assertEqual(second.data["item_id"], first.data["item_id"])
        self.assertEqual(second.data["version"], 2)
        item = MarketItem.objects.get(id=first.data["item_id"])
        self.assertEqual(item.payload["version"], 2)
        installed_schema = item.payload["schema"]
        texts = [
            node.get("props", {}).get("text")
            for node in installed_schema["nodes"].values()
            if node.get("type") == "wp-text"
        ]
        self.assertIn("市场新版内容", texts)

    def test_publish_market_requires_editor(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).post(self.publish_url(block_id), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_publish_market_stranger_forbidden(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.stranger).post(self.publish_url(block_id), {}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_publish_market_anonymous_forbidden(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client().post(self.publish_url(block_id), {}, format="json")
        self.assertIn(response.status_code, (401, 403))

    def test_publish_market_unavailable_returns_clear_error(self):
        block_id = self.create_block()["block"]["id"]
        with patch(
            "pages.block_services._load_market_item_model",
            side_effect=MarketUnavailable("market 应用不可用（测试注入）"),
        ):
            response = api_client(self.editor).post(self.publish_url(block_id), {}, format="json")
        self.assertEqual(response.status_code, 503, response.data)
        self.assertEqual(response.data["code"], "market_unavailable")
        self.assertIn("market 应用不可用", response.data["detail"])
        self.assertFalse(MarketItem.objects.exists())


class BlockDetailVersionMetaTests(BlockVersionBase):
    def test_detail_includes_latest_version_and_count(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).get(f"/api/blocks/{block_id}/")
        self.assertEqual(response.status_code, 200, response.data)
        detail = response.data["block"]
        self.assertEqual(detail["latest_version"], 1)
        self.assertEqual(detail["version_count"], 1)
        self.assertEqual(detail["latest_version_detail"]["version"], 1)

        api_client(self.editor).post(self.version_url(block_id), {"changelog": "v2"}, format="json")
        response = api_client(self.viewer).get(f"/api/blocks/{block_id}/")
        detail = response.data["block"]
        self.assertEqual(detail["latest_version"], 2)
        self.assertEqual(detail["version_count"], 2)
        self.assertEqual(detail["latest_version_detail"]["changelog"], "v2")


class BlockVersionUrlWiringTests(TestCase):
    def test_new_routes_resolve(self):
        from django.urls import resolve

        from pages import block_views

        cases = {
            "/api/blocks/1/versions/": block_views.block_version_list_create,
            "/api/blocks/1/versions/2/": block_views.block_version_detail,
            "/api/blocks/1/versions/2/rollback/": block_views.block_version_rollback,
            "/api/blocks/1/publish-market/": block_views.block_publish_market,
            "/api/blocks/1/": block_views.block_detail,
        }
        for url, view in cases.items():
            self.assertEqual(resolve(url).func, view, url)
