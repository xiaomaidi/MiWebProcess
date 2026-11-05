"""页面发布时自动发布引用区块（PageBlock / fragment Page）的测试。

运行：cd backend && python manage.py test pages.tests_block_publish -v 2 --noinput

覆盖：
- 宿主页面发布 → 引用区块页面生成 PageVersion；
- 第二次发布未变更区块 → 不产生重复 PageVersion；
- 缺失区块 / 空区块 / 无承载页面 / 非 fragment → 仅 warning，宿主发布成功；
- 嵌套引用、深度上限、引用环安全；
- blockId 兜底解析；
- service 层 ``publish_page`` 默认自动发布，管理命令可补发。
"""
from __future__ import annotations

import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App
from components.models import ComponentMeta
from components.services import invalidate_registry_cache
from pages.models import Page, PageBlock, PageVersion
from pages.services import publish_page, save_draft
from releases.services import compile_bundle

User = get_user_model()

PUBLISH_URL = "/api/pages/{page_id}/publish/"
TEXT_COMPONENT_VERSION = "1.0.0"
BLOCK_COMPONENT_VERSION = "1.0.0"


def api_client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


def text_node(node_id: str, text: str = "hello") -> dict:
    return {
        "id": node_id,
        "type": "wp-text",
        "componentVersion": TEXT_COMPONENT_VERSION,
        "props": {"text": text},
        "children": [],
    }


def block_node(node_id: str, *, code: str = "", block_id: int | None = None) -> dict:
    props = {}
    if code:
        props["blockCode"] = code
    if block_id:
        props["blockId"] = block_id
    return {
        "id": node_id,
        "type": "wp-block",
        "componentVersion": BLOCK_COMPONENT_VERSION,
        "props": props,
        "children": [],
    }


def page_schema(nodes: dict, root_children: list[str], *, title: str = "") -> dict:
    root_id = "root"
    merged = {
        root_id: {
            "id": root_id,
            "type": "wp-canvas",
            "componentVersion": "2.0.0",
            "props": {},
            "children": list(root_children),
        }
    }
    merged.update(nodes)
    return {
        "schemaVersion": 2,
        "rootId": root_id,
        "nodes": merged,
        "variables": {},
        "meta": {"title": title, "lang": "zh-CN", "globalStyle": {"cssVars": {}}},
        "layout": {"mode": "flow", "width": 1200, "height": 800},
    }


def empty_schema() -> dict:
    return page_schema({}, [])


def text_schema(text: str = "content") -> dict:
    return page_schema({"txt": text_node("txt", text)}, ["txt"])


class BlockAutoPublishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("auto-owner", password="pass-12345")
        cls.app = App.objects.create(name="自动区块发布", code="auto-blocks", owner=cls.owner, status="draft")
        cls.host = Page.objects.create(
            app=cls.app,
            name="首页",
            path="home",
            type="page",
            schema=empty_schema(),
            schema_version=2,
            status="draft",
        )
        cls.fragment = Page.objects.create(
            app=cls.app,
            name="Hero 区块",
            path="__blocks__/hero",
            type="fragment",
            schema=text_schema("hero content"),
            schema_version=2,
            status="draft",
        )
        cls.block = PageBlock.objects.create(
            app=cls.app,
            name="Hero 区块",
            code="hero",
            page=cls.fragment,
            schema=text_schema("hero content"),
            version=1,
            created_by=cls.owner,
        )
        cls.host.schema = page_schema(
            {"blk": block_node("blk", code="hero", block_id=cls.block.id)},
            ["blk"],
        )
        cls.host.save(update_fields=["schema"])
        cls.host_id = cls.host.id
        cls.fragment_id = cls.fragment.id
        cls.block_id = cls.block.id

        for name, label, ctype in (
            ("wp-block", "复用区块", "layout"),
            ("wp-text", "文本", "basic"),
        ):
            ComponentMeta.objects.update_or_create(
                name=name,
                defaults={
                    "label": label,
                    "type": ctype,
                    "category": "test",
                    "version": "1.0.0",
                    "is_enabled": True,
                    "is_builtin": True,
                },
            )

    def setUp(self):
        invalidate_registry_cache()
        self.app = App.objects.get(pk=self.app.pk)
        self.host = Page.objects.get(pk=self.host_id)
        self.fragment = Page.objects.get(pk=self.fragment_id)
        self.block = PageBlock.objects.select_related("page").get(pk=self.block_id)
        self.client = api_client(self.owner)

    # -- helpers ---------------------------------------------------------
    def publish_view(self, page: Page, changelog: str = ""):
        with patch("releases.services.schedule_release_for_app", return_value=(None, "queued")):
            return self.client.post(
                PUBLISH_URL.format(page_id=page.id),
                {"changelog": changelog},
                format="json",
            )

    def make_block(self, code: str, schema: dict, *, page_type: str = "fragment", path: str = ""):
        page = Page.objects.create(
            app=self.app,
            name=code,
            path=path or f"__blocks__/{code}",
            type=page_type,
            schema=schema,
            schema_version=2,
            status="draft",
        )
        block = PageBlock.objects.create(
            app=self.app,
            name=code,
            code=code,
            page=page,
            schema=schema,
            version=1,
            created_by=self.owner,
        )
        return block, page

    def point_host_at(self, *refs: dict) -> Page:
        nodes = {}
        children = []
        for index, ref in enumerate(refs):
            node_id = f"ref-{index}"
            nodes[node_id] = block_node(node_id, **ref)
            children.append(node_id)
        self.host.schema = page_schema(nodes, children)
        self.host.save(update_fields=["schema"])
        self.host.refresh_from_db()
        return self.host

    # -- tests -----------------------------------------------------------
    def test_host_publish_publishes_referenced_block(self):
        response = self.publish_view(self.host, "host publish")
        self.assertEqual(response.status_code, 200, response.data)

        self.fragment.refresh_from_db()
        self.assertEqual(self.fragment.status, "published")
        self.assertIsNotNone(self.fragment.current_version_id)
        versions = list(PageVersion.objects.filter(page=self.fragment).order_by("version"))
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].version, 1)
        self.assertEqual(versions[0].changelog, "auto: block hero for page home")
        self.assertEqual(versions[0].publisher_id, self.owner.id)

        published = response.data["blocks"]["published"]
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["code"], "hero")
        self.assertEqual(published[0]["page_id"], self.fragment.id)
        self.assertEqual(len(response.data["published_blocks"]), 1)
        self.assertEqual(response.data["missing_blocks"], [])
        self.assertEqual(response.data["cycles"], [])
        self.assertEqual(PageVersion.objects.filter(page=self.host).count(), 1)

    def test_second_publish_does_not_duplicate_block_version(self):
        first = self.publish_view(self.host, "first")
        self.assertEqual(first.status_code, 200, first.data)
        second = self.publish_view(self.host, "second")
        self.assertEqual(second.status_code, 200, second.data)

        self.assertEqual(PageVersion.objects.filter(page=self.fragment).count(), 1)
        skipped = second.data["blocks"]["skipped"]
        self.assertTrue(any(item["code"] == "hero" and item["reason"] == "unchanged" for item in skipped))
        self.assertEqual(PageVersion.objects.filter(page=self.host).count(), 2)

    def test_missing_block_warns_but_host_publishes(self):
        self.point_host_at({"code": "ghost"})
        response = self.publish_view(self.host, "missing")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PageVersion.objects.filter(page=self.host).count(), 1)
        missing = response.data["blocks"]["missing"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["code"], "ghost")
        self.assertEqual(missing[0]["reason"], "missing")
        self.assertTrue(any("missing block" in warning for warning in response.data["warnings"]))
        self.assertEqual(response.data["missing_blocks"][0]["code"], "ghost")

    def test_cycle_is_safe(self):
        block_b, page_b = self.make_block("cycle-b", empty_schema())
        block_a, page_a = self.make_block(
            "cycle-a",
            page_schema({"ref-b": block_node("ref-b", code="cycle-b")}, ["ref-b"]),
        )
        page_b.schema = page_schema({"ref-a": block_node("ref-a", code="cycle-a")}, ["ref-a"])
        page_b.save(update_fields=["schema"])
        self.point_host_at({"code": "cycle-a"})

        response = self.publish_view(self.host, "cycle")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PageVersion.objects.filter(page=self.host).count(), 1)
        cycles = response.data["blocks"]["cycles"]
        self.assertEqual(len(cycles), 1)
        self.assertIn("cycle-a", cycles[0]["path"])
        self.assertIn("cycle-b", cycles[0]["path"])
        self.assertTrue(any("cycle" in warning for warning in response.data["warnings"]))
        # 环上的区块本身仍可各自发布，且不会无限递归。
        self.assertEqual(PageVersion.objects.filter(page=page_a).count(), 1)
        self.assertEqual(PageVersion.objects.filter(page=page_b).count(), 1)

    def test_transitive_blocks_are_published_child_first(self):
        inner_block, inner_page = self.make_block("inner", text_schema("inner"))
        outer_block, outer_page = self.make_block(
            "outer",
            page_schema({"inner-ref": block_node("inner-ref", code="inner")}, ["inner-ref"]),
        )
        self.point_host_at({"code": "outer"})

        response = self.publish_view(self.host, "nested")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PageVersion.objects.filter(page=inner_page).count(), 1)
        self.assertEqual(PageVersion.objects.filter(page=outer_page).count(), 1)
        published = response.data["blocks"]["published"]
        self.assertEqual([item["code"] for item in published], ["inner", "outer"])
        for item in published:
            self.assertEqual(item["changelog"], f"auto: block {item['code']} for page home")

    def test_depth_limit_skips_too_deep_block(self):
        depth = 9
        pages = {}
        blocks = {}
        for index in range(1, depth + 1):
            page = Page.objects.create(
                app=self.app,
                name=f"deep-{index}",
                path=f"__blocks__/deep-{index}",
                type="fragment",
                schema=empty_schema(),
                schema_version=2,
                status="draft",
            )
            block = PageBlock.objects.create(
                app=self.app,
                name=f"deep-{index}",
                code=f"deep-{index}",
                page=page,
                schema=empty_schema(),
                version=1,
                created_by=self.owner,
            )
            pages[index] = page
            blocks[index] = block
        for index in range(1, depth):
            pages[index].schema = page_schema(
                {"next": block_node("next", code=f"deep-{index + 1}")},
                ["next"],
            )
            pages[index].save(update_fields=["schema"])
        pages[depth].schema = text_schema("bottom")
        pages[depth].save(update_fields=["schema"])
        self.point_host_at({"code": "deep-1"})

        response = self.publish_view(self.host, "deep")
        self.assertEqual(response.status_code, 200, response.data)
        depth_limited = response.data["blocks"]["depth_limited"]
        self.assertEqual(len(depth_limited), 1)
        self.assertEqual(depth_limited[0]["code"], "deep-9")
        self.assertEqual(depth_limited[0]["depth"], 9)
        for index in range(1, depth):
            self.assertEqual(PageVersion.objects.filter(page=pages[index]).count(), 1, index)
        self.assertEqual(PageVersion.objects.filter(page=pages[depth]).count(), 0)

    def test_empty_block_draft_is_skipped(self):
        empty_block, empty_page = self.make_block("empty", empty_schema())
        self.point_host_at({"code": "empty"})

        response = self.publish_view(self.host, "empty")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PageVersion.objects.filter(page=empty_page).count(), 0)
        skipped = response.data["blocks"]["skipped"]
        self.assertTrue(any(item["code"] == "empty" and item["reason"] == "empty" for item in skipped))
        self.assertTrue(any("empty draft" in warning for warning in response.data["warnings"]))

    def test_block_validation_failure_does_not_fail_host(self):
        _block, broken_page = self.make_block(
            "broken",
            page_schema(
                {
                    "bad": {
                        "id": "bad",
                        "type": "wp-unknown-test-component",
                        "componentVersion": "1.0.0",
                        "props": {},
                        "children": [],
                    }
                },
                ["bad"],
            ),
        )
        self.point_host_at({"code": "broken"})

        response = self.publish_view(self.host, "broken block")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PageVersion.objects.filter(page=self.host).count(), 1)
        self.assertEqual(PageVersion.objects.filter(page=broken_page).count(), 0)
        skipped = response.data["blocks"]["skipped"]
        self.assertTrue(
            any(item["code"] == "broken" and item["reason"] == "validation_failed" for item in skipped)
        )
        self.assertTrue(any("validation_failed" in warning for warning in response.data["warnings"]))

    def test_block_without_backing_page_is_skipped(self):
        PageBlock.objects.create(
            app=self.app,
            name="无页面区块",
            code="detached",
            page=None,
            schema=text_schema("fallback"),
            version=1,
            created_by=self.owner,
        )
        self.point_host_at({"code": "detached"})

        response = self.publish_view(self.host, "detached")
        self.assertEqual(response.status_code, 200, response.data)
        skipped = response.data["blocks"]["skipped"]
        self.assertTrue(any(item["code"] == "detached" and item["reason"] == "no_page" for item in skipped))
        self.assertTrue(any("no backing page" in warning for warning in response.data["warnings"]))

    def test_non_fragment_block_page_is_skipped(self):
        block, page = self.make_block("normal-page", text_schema(), page_type="page", path="normal-page")
        self.point_host_at({"code": "normal-page"})

        response = self.publish_view(self.host, "normal")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(PageVersion.objects.filter(page=page).count(), 0)
        skipped = response.data["blocks"]["skipped"]
        self.assertTrue(any(item["code"] == "normal-page" and item["reason"] == "not_fragment" for item in skipped))

    def test_block_id_fallback_resolves_block(self):
        self.point_host_at({"block_id": self.block.id})
        response = self.publish_view(self.host, "by id")
        self.assertEqual(response.status_code, 200, response.data)
        published = response.data["blocks"]["published"]
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["code"], "hero")

    def test_snake_case_block_code_is_resolved(self):
        self.host.schema = page_schema(
            {
                "blk": {
                    "id": "blk",
                    "type": "wp-block",
                    "componentVersion": BLOCK_COMPONENT_VERSION,
                    "props": {"block_code": "hero"},
                    "children": [],
                }
            },
            ["blk"],
        )
        self.host.save(update_fields=["schema"])
        response = self.publish_view(self.host, "snake case")
        self.assertEqual(response.status_code, 200, response.data)
        published = response.data["blocks"]["published"]
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["code"], "hero")


    def test_service_publish_auto_publishes_blocks(self):
        pv, errors, warnings = publish_page(self.host, self.owner, "service publish")
        self.assertIsNotNone(pv, errors)
        self.assertEqual(errors, [])
        self.fragment.refresh_from_db()
        self.assertEqual(self.fragment.status, "published")
        self.assertEqual(PageVersion.objects.filter(page=self.fragment).count(), 1)
        self.assertFalse(any("失败" in warning for warning in warnings))

    def test_management_command_republishes_changed_block(self):
        publish_page(self.host, self.owner, "initial")
        self.assertEqual(PageVersion.objects.filter(page=self.fragment).count(), 1)

        fragment = Page.objects.get(pk=self.fragment_id)
        save_draft(fragment, text_schema("updated content"), self.owner)

        out = io.StringIO()
        call_command(
            "republish_referenced_blocks",
            app=self.app.code,
            include_drafts=True,
            stdout=out,
        )
        self.assertEqual(PageVersion.objects.filter(page=self.fragment).count(), 2)
        self.assertIn("republish done", out.getvalue())
        self.assertIn("hero", out.getvalue())

    def test_management_command_dry_run_creates_no_version(self):
        publish_page(self.host, self.owner, "initial")
        fragment = Page.objects.get(pk=self.fragment_id)
        save_draft(fragment, text_schema("updated content"), self.owner)

        out = io.StringIO()
        call_command(
            "republish_referenced_blocks",
            app=self.app.code,
            include_drafts=True,
            dry_run=True,
            stdout=out,
        )
        self.assertEqual(PageVersion.objects.filter(page=self.fragment).count(), 1)
        self.assertIn("dry-run done", out.getvalue())

    def test_release_bundle_excludes_block_carrier_pages(self):
        publish_page(self.host, self.owner, "bundle")
        # 旧数据：承载页被误标为 page，也应从 release bundle 中排除。
        legacy_page = Page.objects.create(
            app=self.app,
            name="旧区块承载页",
            path="__blocks__/legacy",
            type="page",
            schema=text_schema("legacy"),
            schema_version=2,
            status="published",
        )
        legacy_version = PageVersion.objects.create(
            page=legacy_page,
            version=1,
            schema=legacy_page.schema,
            schema_version=2,
            publisher=self.owner,
        )
        legacy_page.current_version = legacy_version
        legacy_page.save(update_fields=["current_version"])
        PageBlock.objects.create(
            app=self.app,
            name="旧区块",
            code="legacy",
            page=legacy_page,
            schema=text_schema("legacy"),
            version=1,
            created_by=self.owner,
        )

        bundle = compile_bundle(self.app)
        self.assertIn("home", bundle["pages"])
        self.assertNotIn("__blocks__/hero", bundle["pages"])
        self.assertNotIn("__blocks__/legacy", bundle["pages"])

