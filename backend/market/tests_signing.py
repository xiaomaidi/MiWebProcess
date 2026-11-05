"""市场组件签名 / 沙箱策略 / 安装权限测试。

运行：cd backend && python manage.py test market.tests_signing -v 2 --noinput
"""
from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import App, AppMember
from components.models import ComponentMeta
from market.models import MarketItem
from market.signing import (
    DEFAULT_COMPONENT_POLICY,
    canonical_json,
    compute_hash_and_signature,
    normalize_policy,
    signing_key,
)
from pages.models import PageBlock

User = get_user_model()
SIGNING_KEY = "unit-test-market-signing-key-0123456789abcdef"


def api_client(user=None) -> APIClient:
    client = APIClient()
    if user is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


def component_payload(**overrides) -> dict:
    payload = {
        "name": "wp-market-hello-world",
        "label": "Hello World",
        "type": "custom",
        "category": "custom",
        "version": "1.2.0",
        "source_url": "/media/custom-components/hello/1.2.0/index.js",
        "element": "wp-widget-hello-world",
        "props_schema": {
            "type": "object",
            "properties": {"title": {"type": "string", "title": "标题"}},
        },
        "default_props": {"title": "Hello"},
        "events": ["click"],
    }
    payload.update(overrides)
    return payload


def block_payload() -> dict:
    return {
        "rootId": "root",
        "nodes": {
            "root": {"id": "root", "type": "wp-canvas", "props": {}, "children": []},
        },
    }


@override_settings(MARKET_SIGNING_KEY=SIGNING_KEY)
class MarketSigningTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="market-owner", password="pw-test-123")
        self.other = User.objects.create_user(username="market-other", password="pw-test-123")
        self.admin = User.objects.create_user(
            username="market-admin", password="pw-test-123", is_superuser=True,
        )
        self.viewer = User.objects.create_user(username="market-viewer", password="pw-test-123")
        self.app = App.objects.create(name="Market Test App", code="market-test-app", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.viewer, role="viewer")
        self.client_owner = api_client(self.owner)
        self.client_other = api_client(self.other)
        self.client_admin = api_client(self.admin)
        self.client_viewer = api_client(self.viewer)

    # ---------------------------------------------------------------- helpers
    def create_item(self, *, kind="component", payload=None, status="published", client=None, slug="hello-world"):
        response = (client or self.client_owner).post(
            "/api/market/items/",
            {
                "kind": kind,
                "name": "Hello World" if kind == "component" else "Hero Block",
                "slug": slug,
                "description": "test item",
                "payload": payload if payload is not None else (
                    component_payload() if kind == "component" else block_payload()
                ),
                "status": status,
                "visibility": "public",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return MarketItem.objects.get(pk=response.data["id"])

    def sign(self, item, *, client=None, policy=None):
        body = {"policy": policy} if policy is not None else {}
        return (client or self.client_owner).post(
            f"/api/market/items/{item.pk}/sign/", body, format="json",
        )

    def install(self, item, *, client=None):
        return (client or self.client_owner).post(
            f"/api/market/items/{item.pk}/install/", {"app_id": self.app.pk}, format="json",
        )

    # ---------------------------------------------------------------- signing
    def test_owner_can_sign_and_response_has_metadata_but_not_key(self):
        item = self.create_item()
        response = self.sign(item)
        self.assertEqual(response.status_code, 200, response.data)
        data = response.data
        self.assertEqual(len(data["code_hash"]), 64)
        self.assertEqual(len(data["signature"]), 64)
        self.assertTrue(data["signed"])
        self.assertTrue(data["signature_valid"])
        self.assertEqual(data["signer"], self.owner.username)
        self.assertIsNotNone(data["signed_at"])
        self.assertEqual(data["sandboxed"], True)
        self.assertEqual(data["policy"]["allow_same_origin"], False)
        self.assertEqual(data["policy"]["allow_scripts"], True)

        dumped = json.dumps(data, ensure_ascii=False)
        self.assertNotIn(SIGNING_KEY, dumped)
        self.assertNotIn("signing_key", dumped)
        self.assertNotIn("MARKET_SIGNING_KEY", dumped)

        item.refresh_from_db()
        expected_hash, expected_signature = compute_hash_and_signature(item)
        self.assertEqual(item.code_hash, expected_hash)
        self.assertEqual(item.signature, expected_signature)
        self.assertFalse(item.sandboxed is False)

    def test_signing_is_deterministic_for_unchanged_item(self):
        item = self.create_item()
        first = self.sign(item)
        self.assertEqual(first.status_code, 200)
        item.refresh_from_db()
        hash_once, signature_once = item.code_hash, item.signature
        second = self.sign(item)
        self.assertEqual(second.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.code_hash, hash_once)
        self.assertEqual(item.signature, signature_once)

    def test_list_endpoint_exposes_signature_metadata(self):
        unsigned = self.create_item(payload=component_payload(name="wp-market-unsigned"))
        signed = self.create_item(
            slug="hello-signed",
            payload=component_payload(name="wp-market-signed", element="wp-widget-signed"),
        )
        self.assertEqual(self.sign(signed).status_code, 200)
        response = self.client_owner.get("/api/market/items/")
        self.assertEqual(response.status_code, 200, response.data)
        rows = {row["id"]: row for row in response.data["results"]}
        self.assertFalse(rows[unsigned.pk]["signature_valid"])
        self.assertEqual(rows[unsigned.pk]["signer"], "")
        self.assertTrue(rows[signed.pk]["signature_valid"])
        self.assertEqual(rows[signed.pk]["signer"], self.owner.username)
        self.assertNotIn(SIGNING_KEY, json.dumps(response.data, ensure_ascii=False))

    def test_non_owner_cannot_sign(self):
        item = self.create_item()
        response = self.sign(item, client=self.client_other)
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.signature, "")

    def test_platform_admin_can_sign_another_users_item(self):
        item = self.create_item()
        response = self.sign(item, client=self.client_admin)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["signer"], self.admin.username)

    def test_signing_forces_safe_policy_and_clamps_timeout(self):
        item = self.create_item()
        response = self.sign(item, policy={
            "allow_same_origin": True,
            "allow_forms": True,
            "sandbox": False,
            "network": "allowlist",
            "allowed_origins": ["https://cdn.example.com"],
            "timeout_ms": 999999,
        })
        self.assertEqual(response.status_code, 200, response.data)
        item.refresh_from_db()
        self.assertEqual(item.policy["allow_same_origin"], False)
        self.assertEqual(item.policy["allow_forms"], False)
        self.assertEqual(item.policy["sandbox"], True)
        self.assertEqual(item.policy["network"], "allowlist")
        self.assertEqual(item.policy["allowed_origins"], ["https://cdn.example.com"])
        self.assertEqual(item.policy["timeout_ms"], 30000)

    def test_component_without_source_url_cannot_be_signed(self):
        item = self.create_item(payload=component_payload(source_url=""))
        response = self.sign(item)
        self.assertEqual(response.status_code, 400)
        item.refresh_from_db()
        self.assertEqual(item.signature, "")

    def test_javascript_source_url_rejected(self):
        response = self.client_owner.post(
            "/api/market/items/",
            {
                "kind": "component",
                "name": "Bad URL",
                "slug": "bad-url",
                "payload": component_payload(source_url="javascript:alert(1)"),
                "status": "published",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_source_url_with_backslash_or_credentials_rejected(self):
        for index, source_url in enumerate((
            "/\\evil.example.com/widget.js",
            "https://user:pass@example.com/widget.js",
        )):
            response = self.client_owner.post(
                "/api/market/items/",
                {
                    "kind": "component",
                    "name": f"Bad URL {index}",
                    "slug": f"bad-url-{index}",
                    "payload": component_payload(source_url=source_url),
                    "status": "published",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400, source_url)

    def test_component_cannot_disable_sandbox(self):
        response = self.client_owner.post(
            "/api/market/items/",
            {
                "kind": "component",
                "name": "No Sandbox",
                "slug": "no-sandbox",
                "payload": component_payload(),
                "sandboxed": False,
                "status": "published",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_signing_falls_back_to_secret_key_when_market_key_empty(self):
        with override_settings(MARKET_SIGNING_KEY="", SECRET_KEY="fallback-secret-key"):
            self.assertEqual(signing_key(), b"fallback-secret-key")
            item = self.create_item()
            response = self.sign(item)
            self.assertEqual(response.status_code, 200, response.data)
            self.assertTrue(response.data["signature_valid"])

    # ---------------------------------------------------------------- tamper
    def test_tampered_payload_is_reported_invalid_and_install_rejected(self):
        item = self.create_item()
        self.assertEqual(self.sign(item).status_code, 200)
        MarketItem.objects.filter(pk=item.pk).update(
            payload=component_payload(default_props={"title": "tampered"}),
        )
        response = self.client_owner.get(f"/api/market/items/{item.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["signature_valid"])
        self.assertIn("code_hash", response.data["signature_error"])

        install = self.install(item)
        self.assertEqual(install.status_code, 400)
        self.assertIn("signature", install.data)
        self.assertEqual(ComponentMeta.objects.count(), 0)

    def test_changing_signed_field_via_patch_invalidates_signature(self):
        item = self.create_item()
        self.assertEqual(self.sign(item).status_code, 200)
        response = self.client_owner.patch(
            f"/api/market/items/{item.pk}/",
            {"name": "Hello World Renamed"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(response.data["signature_valid"])
        self.assertEqual(self.install(item).status_code, 400)

    # ---------------------------------------------------------------- install
    def test_unsigned_component_install_rejected(self):
        item = self.create_item()
        response = self.install(item)
        self.assertEqual(response.status_code, 400)
        self.assertIn("signature", response.data)
        self.assertIn("未签名", str(response.data))
        self.assertEqual(ComponentMeta.objects.count(), 0)

    def test_signed_component_install_creates_sandboxed_meta_and_marker(self):
        item = self.create_item()
        self.assertEqual(self.sign(item).status_code, 200)
        response = self.install(item)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertTrue(response.data["sandboxed"])
        self.assertEqual(response.data["source"], "custom-sandbox")
        self.assertEqual(response.data["element"], "wp-widget-hello-world")

        meta = ComponentMeta.objects.get(name="wp-market-hello-world")
        self.assertEqual(meta.source, "custom-sandbox")
        self.assertEqual(meta.element, "wp-widget-hello-world")
        self.assertEqual(meta.source_url, "/media/custom-components/hello/1.2.0/index.js")
        self.assertTrue(meta.is_custom)
        self.assertEqual(meta.version, "1.2.0")
        marker = meta.payload_schema["x-wp-market"]
        self.assertEqual(marker["market_item_id"], item.pk)
        self.assertTrue(marker["sandboxed"])
        self.assertEqual(marker["code_hash"], response.data["code_hash"])
        self.assertEqual(marker["signature"], response.data["signature"])
        self.assertEqual(marker["policy"]["allow_same_origin"], False)
        item.refresh_from_db()
        self.assertEqual(item.installs, 1)

        registry = self.client_owner.get("/api/components/registry/")
        self.assertEqual(registry.status_code, 200)
        row = next(c for c in registry.data["components"] if c["name"] == meta.name)
        self.assertEqual(row["source"], "custom-sandbox")
        self.assertEqual(row["payload_schema"]["x-wp-market"]["signature"], marker["signature"])

    def test_reinstall_same_item_updates_marker_not_duplicate(self):
        item = self.create_item()
        self.assertEqual(self.sign(item).status_code, 200)
        self.assertEqual(self.install(item).status_code, 201)
        self.assertEqual(self.install(item).status_code, 201)
        self.assertEqual(ComponentMeta.objects.filter(name="wp-market-hello-world").count(), 1)
        item.refresh_from_db()
        self.assertEqual(item.installs, 2)

    def test_install_without_app_editor_role_rejected(self):
        item = self.create_item()
        self.assertEqual(self.sign(item).status_code, 200)
        response = self.install(item, client=self.client_viewer)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ComponentMeta.objects.count(), 0)

    def test_install_requires_published_public_for_non_owner(self):
        item = self.create_item(status="draft")
        self.assertEqual(self.sign(item).status_code, 200)
        response = self.install(item, client=self.client_other)
        # other 不是条目所有者，且没有 app 角色，先被“未发布”拦截。
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ComponentMeta.objects.count(), 0)

    def test_block_install_does_not_require_signature(self):
        item = self.create_item(kind="block", payload=block_payload())
        self.assertEqual(item.signature, "")
        response = self.install(item)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["kind"], "block")
        self.assertEqual(PageBlock.objects.filter(pk=response.data["block_id"]).count(), 1)
        item.refresh_from_db()
        self.assertEqual(item.installs, 1)

    def test_install_cannot_overwrite_builtin_component(self):
        ComponentMeta.objects.create(
            name="wp-market-hello-world", label="Builtin", is_builtin=True, source="element-plus",
        )
        item = self.create_item()
        self.assertEqual(self.sign(item).status_code, 200)
        response = self.install(item)
        self.assertEqual(response.status_code, 400)
        self.assertIn("内置", str(response.data))
        self.assertEqual(ComponentMeta.objects.get(name="wp-market-hello-world").is_builtin, True)

    # ---------------------------------------------------------------- policy utils
    def test_policy_rejects_bad_origin_and_network(self):
        with self.assertRaises(Exception):
            normalize_policy({"network": "wide-open"}, kind="component")
        with self.assertRaises(Exception):
            normalize_policy({"allowed_origins": ["javascript:alert(1)"]}, kind="component")
        normalized = normalize_policy({}, kind="component")
        self.assertEqual(normalized, DEFAULT_COMPONENT_POLICY)

    def test_canonical_json_is_order_independent(self):
        self.assertEqual(
            canonical_json({"b": 1, "a": [2, {"d": 4, "c": 3}]}),
            canonical_json({"a": [2, {"c": 3, "d": 4}], "b": 1}),
        )
