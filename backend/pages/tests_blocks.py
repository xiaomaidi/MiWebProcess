"""PageBlock（可复用区块）API / 权限 / 承载页面测试。

运行：cd backend && python manage.py test pages.tests_blocks -v 2 --noinput

本模块同时充当测试专用 ROOT_URLCONF（模块级 urlpatterns = pages.block_urls），
因此无需修改 config/urls.py 即可独立验证 /api/apps/.../blocks/ 与 /api/blocks/... 路由。
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import resolve
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App, AppAuthConfig, AppMember
from pages.block_services import (
    extract_subtree,
    normalize_subtree,
    prefix_subtree_ids,
    subtree_into_schema,
)
from pages.block_urls import urlpatterns
from pages.models import Page, PageBlock, PageVersion

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
            "root-1": {"id": "root-1", "type": "wp-canvas", "componentVersion": "2.0.0", "props": {}, "children": ["n-text", "n-card"]},
            "n-text": {"id": "n-text", "type": "wp-text", "componentVersion": "2.0.0", "props": {"text": "标题"}, "children": []},
            "n-card": {"id": "n-card", "type": "wp-container", "componentVersion": "2.0.0", "props": {}, "children": ["n-inner"]},
            "n-inner": {"id": "n-inner", "type": "wp-text", "componentVersion": "2.0.0", "props": {"text": "内容"}, "children": []},
        },
    }


class BlockServiceTests(SimpleTestCase):
    def test_normalize_subtree_drops_dangling_refs(self):
        raw = {
            "rootId": "a",
            "nodes": {
                "a": {"id": "a", "type": "wp-container", "props": {}, "children": ["b", "missing"]},
                "b": {"id": "b", "type": "wp-text", "props": {}, "children": ["ghost"]},
            },
        }
        out = normalize_subtree(raw)
        self.assertEqual(out["rootId"], "a")
        self.assertEqual(out["nodes"]["a"]["children"], ["b"])
        self.assertEqual(out["nodes"]["b"]["children"], [])

    def test_normalize_subtree_requires_root(self):
        from rest_framework.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            normalize_subtree({"rootId": "nope", "nodes": {}})

    def test_extract_subtree_keeps_selected_and_descendants(self):
        out = extract_subtree(source_schema(), ["n-card"])
        self.assertEqual(out["rootId"], "n-card")
        self.assertEqual(set(out["nodes"]), {"n-card", "n-inner"})

    def test_extract_subtree_filters_selected_ancestors(self):
        out = extract_subtree(source_schema(), ["n-card", "n-inner"])
        self.assertEqual(out["rootId"], "n-card")
        self.assertEqual(set(out["nodes"]), {"n-card", "n-inner"})

    def test_extract_subtree_multiple_roots_gets_wrapper(self):
        out = extract_subtree(source_schema(), ["n-text", "n-card"])
        root = out["nodes"][out["rootId"]]
        self.assertEqual(root["type"], "wp-container")
        self.assertEqual(root["children"], ["n-text", "n-card"])

    def test_prefix_subtree_ids_rewrites_references(self):
        out = prefix_subtree_ids(extract_subtree(source_schema(), ["n-card"]), "blk-demo-")
        self.assertEqual(out["rootId"], "blk-demo-n-card")
        self.assertEqual(out["nodes"]["blk-demo-n-card"]["children"], ["blk-demo-n-inner"])
        self.assertIn("blk-demo-n-inner", out["nodes"])

    def test_subtree_into_schema_attaches_to_canvas(self):
        subtree = prefix_subtree_ids(extract_subtree(source_schema(), ["n-text"]), "x-")
        schema = subtree_into_schema(subtree, name="标题块")
        self.assertEqual(schema["meta"]["title"], "标题块")
        self.assertEqual(schema["nodes"][schema["rootId"]]["children"], ["x-n-text"])
        self.assertIn("x-n-text", schema["nodes"])


class BlockUrlWiringTests(SimpleTestCase):
    """项目真实 ROOT_URLCONF 下的路由检查（防止被 runtime 兜底路由截获）。"""

    def test_block_urls_resolve_to_block_views(self):
        from pages import block_views

        cases = {
            "/api/apps/1/blocks/": block_views.app_block_list_create,
            "/api/blocks/1/": block_views.block_detail,
            "/api/runtime/demo/blocks/hero/": block_views.runtime_block,
        }
        for url, view in cases.items():
            self.assertEqual(resolve(url).func, view, url)

    def test_runtime_page_route_still_works(self):
        from runtime import views as runtime_views

        self.assertEqual(resolve("/api/runtime/demo/home/").func, runtime_views.runtime_page)


@override_settings(ROOT_URLCONF="pages.tests_blocks")
class BlockApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("blk-owner", password="pass-12345")
        cls.editor = User.objects.create_user("blk-editor", password="pass-12345")
        cls.viewer = User.objects.create_user("blk-viewer", password="pass-12345")
        cls.stranger = User.objects.create_user("blk-stranger", password="pass-12345")
        cls.app = App.objects.create(name="区块测试应用", code="blk-demo", owner=cls.owner, status="draft")
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


class BlockCreateTests(BlockApiBase):
    def test_create_block_from_selected_nodes(self):
        data = self.create_block()
        block = data["block"]
        self.assertEqual(block["name"], "产品卡片")
        # 中文名无法 slug 时回退为 block 前缀编码
        self.assertTrue(block["code"].startswith("block"))
        page = Page.objects.get(id=block["page_id"])
        self.assertEqual(page.type, "fragment")
        self.assertEqual(page.path, f"__blocks__/{block['code']}")
        self.assertEqual(page.status, "draft")
        root = page.schema["nodes"][page.schema["rootId"]]
        self.assertEqual(len(root["children"]), 1)
        prefixed = root["children"][0]
        self.assertTrue(prefixed.startswith(f"blk-{block['code']}-"))
        inner_ids = page.schema["nodes"][prefixed]["children"]
        self.assertEqual(len(inner_ids), 1)
        self.assertTrue(inner_ids[0].startswith(f"blk-{block['code']}-"))
        self.assertEqual(page.schema["nodes"][inner_ids[0]]["props"]["text"], "内容")
        self.assertEqual(block["node_count"], len(page.schema["nodes"]))
        self.assertEqual(block["backing_page"]["path"], page.path)

    def test_create_block_empty_when_no_source(self):
        response = api_client(self.editor).post(
            f"/api/apps/{self.app.id}/blocks/", {"name": "空区块", "code": "empty"}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["block"]["code"], "empty")
        page = Page.objects.get(id=response.data["block"]["page_id"])
        self.assertEqual(page.type, "fragment")
        self.assertEqual(page.schema["nodes"][page.schema["rootId"]]["children"], [])

    def test_create_block_duplicate_code_gets_suffix(self):
        self.create_block(code="hero")
        data = self.create_block(code="hero")
        self.assertEqual(data["block"]["code"], "hero-2")
        self.assertTrue(data["warnings"])

    def test_create_block_from_raw_subtree(self):
        subtree = extract_subtree(source_schema(), ["n-text"])
        response = api_client(self.editor).post(
            f"/api/apps/{self.app.id}/blocks/",
            {"name": "原始子树", "code": "raw-tree", "source_nodes": subtree},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        page = Page.objects.get(id=response.data["block"]["page_id"])
        root = page.schema["nodes"][page.schema["rootId"]]
        self.assertTrue(root["children"][0].startswith("blk-raw-tree-"))

    def test_create_block_invalid_code_rejected(self):
        response = api_client(self.editor).post(
            f"/api/apps/{self.app.id}/blocks/", {"name": "坏编码", "code": "bad code!"}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_create_block_source_page_must_belong_to_app(self):
        other_app = App.objects.create(name="别的应用", code="blk-other", owner=self.owner)
        other_page = Page.objects.create(app=other_app, name="别的页", path="home", schema=source_schema())
        response = api_client(self.editor).post(
            f"/api/apps/{self.app.id}/blocks/",
            {"name": "越权来源", "source_page_id": other_page.id},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_create(self):
        response = api_client(self.viewer).post(
            f"/api/apps/{self.app.id}/blocks/", {"name": "无权限"}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_anonymous_cannot_create(self):
        response = api_client().post(f"/api/apps/{self.app.id}/blocks/", {"name": "匿名"}, format="json")
        self.assertIn(response.status_code, (401, 403))

    def test_list_blocks_with_search(self):
        self.create_block(name="产品卡片", code="product-card")
        self.create_block(name="页脚", code="footer")
        response = api_client(self.viewer).get(f"/api/apps/{self.app.id}/blocks/", {"search": "footer"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["code"], "footer")


class BlockDetailTests(BlockApiBase):
    def test_get_detail_returns_schema(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.viewer).get(f"/api/blocks/{block_id}/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["block"]["schema"]["rootId"])
        self.assertEqual(
            response.data["block"]["schema"]["rootId"], response.data["block"]["root_id"]
        )
        self.assertEqual(response.data["page"]["type"], "fragment")

    def test_editor_can_rename(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).patch(
            f"/api/blocks/{block_id}/", {"name": "产品卡片 v2", "description": "说明"}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        block = PageBlock.objects.get(id=block_id)
        self.assertEqual(block.name, "产品卡片 v2")
        self.assertEqual(block.description, "说明")
        self.assertEqual(block.version, 2)

    def test_code_change_syncs_backing_page_path(self):
        block_id = self.create_block(code="hero")["block"]["id"]
        response = api_client(self.editor).patch(f"/api/blocks/{block_id}/", {"code": "hero-2"}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        block = PageBlock.objects.get(id=block_id)
        self.assertEqual(block.code, "hero-2")
        self.assertEqual(Page.objects.get(id=block.page_id).path, "__blocks__/hero-2")
        self.assertTrue(response.data["warnings"])

    def test_schema_patch_rejected_when_backing_page(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).patch(
            f"/api/blocks/{block_id}/", {"schema": {"rootId": "x", "nodes": {"x": {"id": "x"}}}}, format="json"
        )
        self.assertEqual(response.status_code, 400)

    def test_stranger_cannot_read(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.stranger).get(f"/api/blocks/{block_id}/")
        self.assertEqual(response.status_code, 403)

    def test_editor_cannot_delete(self):
        block_id = self.create_block()["block"]["id"]
        response = api_client(self.editor).delete(f"/api/blocks/{block_id}/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(PageBlock.objects.filter(id=block_id).exists())

    def test_owner_delete_archives_page_by_default(self):
        data = self.create_block()
        block_id, page_id = data["block"]["id"], data["block"]["page_id"]
        response = api_client(self.owner).delete(f"/api/blocks/{block_id}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(PageBlock.objects.filter(id=block_id).exists())
        self.assertTrue(response.data["page_archived"])
        self.assertEqual(Page.objects.get(id=page_id).status, "archived")

    def test_owner_delete_with_explicit_page_delete(self):
        data = self.create_block()
        block_id, page_id = data["block"]["id"], data["block"]["page_id"]
        response = api_client(self.owner).delete(f"/api/blocks/{block_id}/?delete_page=true")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["page_deleted"])
        self.assertFalse(Page.objects.filter(id=page_id).exists())


@override_settings(ROOT_URLCONF="pages.tests_blocks")
class BlockRuntimeTests(BlockApiBase):
    def setUp(self):
        self.block = PageBlock.objects.create(
            app=self.app,
            name="运行区块",
            code="runtime-hero",
            page=None,
            schema=extract_subtree(source_schema(), ["n-text"]),
            version=1,
            created_by=self.owner,
        )

    def test_member_gets_draft_schema(self):
        response = api_client(self.viewer).get(f"/api/runtime/{self.app.code}/blocks/{self.block.code}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["draft"])
        self.assertEqual(response.data["rootId"], "n-text")

    def test_anonymous_gets_404_for_unpublished(self):
        response = api_client().get(f"/api/runtime/{self.app.code}/blocks/{self.block.code}/")
        self.assertEqual(response.status_code, 404)

    def test_public_app_serves_draft_block_to_anonymous(self):
        self.app.status = "published"
        self.app.save(update_fields=["status"])
        response = api_client().get(f"/api/runtime/{self.app.code}/blocks/{self.block.code}/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["draft"])
        self.assertFalse(response.data["published"])

    def test_anonymous_gets_published_snapshot(self):
        page = Page.objects.create(
            app=self.app,
            name="已发布区块",
            path="__blocks__/published-hero",
            type="fragment",
            schema=source_schema(),
            status="published",
        )
        pv = PageVersion.objects.create(page=page, version=1, schema=source_schema(), schema_version=2, publisher=self.owner)
        page.current_version = pv
        page.save(update_fields=["current_version"])
        PageBlock.objects.create(
            app=self.app, name="已发布区块", code="published-hero", page=page, version=2, created_by=self.owner
        )
        response = api_client().get(f"/api/runtime/{self.app.code}/blocks/published-hero/")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["draft"])
        self.assertTrue(response.data["published"])
        self.assertEqual(response.data["rootId"], "root-1")

    def test_require_login_blocks_anonymous(self):
        config, _ = AppAuthConfig.objects.get_or_create(app=self.app)
        config.require_login = True
        config.save(update_fields=["require_login"])
        response = api_client().get(f"/api/runtime/{self.app.code}/blocks/{self.block.code}/")
        self.assertEqual(response.status_code, 403)
        response = api_client(self.viewer).get(f"/api/runtime/{self.app.code}/blocks/{self.block.code}/")
        self.assertEqual(response.status_code, 200)

    def test_unknown_code_returns_404(self):
        response = api_client(self.viewer).get(f"/api/runtime/{self.app.code}/blocks/nope/")
        self.assertEqual(response.status_code, 404)

    def test_anonymous_draft_param_rejected(self):
        response = api_client().get(f"/api/runtime/{self.app.code}/blocks/{self.block.code}/?draft=1")
        self.assertIn(response.status_code, (403, 404))
