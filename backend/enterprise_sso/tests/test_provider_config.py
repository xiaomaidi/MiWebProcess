"""Provider 模型校验 + 配置 API（权限、secret 脱敏、加密落库）。"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from rest_framework.test import APIClient

from appcore.models import App, AppMember, AppAuthConfig
from enterprise_sso.models import SsoProvider

User = get_user_model()

SECRET_PLAINTEXT = "super-secret-value"


def provider_payload(**overrides) -> dict:
    payload = {
        "name": "Corp IdP",
        "slug": "corp",
        "protocol": "oidc",
        "enabled": True,
        "issuer": "https://idp.example.com",
        "client_id": "webprocess",
        "client_secret": SECRET_PLAINTEXT,
        "authorization_endpoint": "https://idp.example.com/oauth2/authorize",
        "token_endpoint": "https://idp.example.com/oauth2/token",
        "userinfo_endpoint": "https://idp.example.com/oauth2/userinfo",
        "scopes": "openid profile email",
        "auto_create_user": True,
        "default_role": "viewer",
        "allowed_email_domains": ["example.com"],
    }
    payload.update(overrides)
    return payload


def create_provider(app: App, **overrides) -> SsoProvider:
    return SsoProvider.objects.create(app=app, **provider_payload(**overrides))


class SsoProviderModelTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw-12345678")
        self.app = App.objects.create(name="Demo", code="demo", owner=self.owner)

    def test_defaults_are_safe(self):
        provider = SsoProvider(app=self.app, name="Corp", slug="corp")
        self.assertEqual(provider.protocol, "oidc")
        self.assertEqual(provider.scopes, "openid profile email")
        self.assertEqual(provider.default_role, "viewer")
        self.assertTrue(provider.auto_create_user)
        self.assertEqual(provider.allowed_email_domains, [])
        self.assertFalse(provider.enabled)
        self.assertFalse(provider.is_usable)

    def test_url_must_be_https_or_localhost(self):
        provider = SsoProvider(
            app=self.app,
            name="Corp",
            slug="corp",
            issuer="http://idp.example.com",
        )
        with self.assertRaises(ValidationError) as ctx:
            provider.full_clean()
        self.assertIn("issuer", ctx.exception.message_dict)

        for issuer in (
            "https://idp.example.com",
            "http://localhost:8080/realms/corp",
            "http://127.0.0.1:9000/oidc",
        ):
            candidate = SsoProvider(app=self.app, name="Corp", slug="corp", issuer=issuer)
            candidate.full_clean()  # 不应抛异常

    def test_rejects_credentials_and_fragments_in_url(self):
        for issuer in (
            "https://user:pass@idp.example.com",
            "https://idp.example.com/#frag",
            "ftp://idp.example.com",
        ):
            with self.assertRaises(ValidationError):
                SsoProvider(app=self.app, name="Corp", slug="corp", issuer=issuer).full_clean()

    def test_enabled_requires_fields(self):
        provider = SsoProvider(app=self.app, name="Corp", slug="corp", enabled=True, issuer="https://idp.example.com")
        with self.assertRaises(ValidationError) as ctx:
            provider.full_clean()
        errors = ctx.exception.message_dict
        for field in ("client_id", "client_secret", "authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
            self.assertIn(field, errors)

    def test_unique_app_slug(self):
        create_provider(self.app)
        with self.assertRaises(ValidationError) as ctx:
            SsoProvider(app=self.app, name="Dup", slug="corp", enabled=False).full_clean()
        self.assertIn("slug", ctx.exception.message_dict)

    def test_scope_and_domain_normalization(self):
        provider = SsoProvider(
            app=self.app,
            name="Corp",
            slug="Corp_1",
            scopes="profile, email",
            allowed_email_domains=["Example.COM", "@corp.example.com"],
        )
        provider.full_clean()
        self.assertEqual(provider.slug, "corp_1")
        self.assertEqual(provider.scopes, "openid profile email")
        self.assertEqual(provider.allowed_email_domains, ["example.com", "corp.example.com"])

        with self.assertRaises(ValidationError):
            SsoProvider(
                app=self.app, name="Corp", slug="corp", allowed_email_domains=["*.example.com"]
            ).full_clean()

    def test_client_secret_encrypted_at_rest(self):
        provider = create_provider(self.app)
        with connection.cursor() as cursor:
            cursor.execute("SELECT client_secret FROM wp_sso_providers WHERE id = %s", [provider.id])
            stored = cursor.fetchone()[0]
        self.assertTrue(stored.startswith("enc:v1:"), stored[:20])
        self.assertNotIn(SECRET_PLAINTEXT, stored)

        provider.refresh_from_db()
        self.assertEqual(provider.client_secret, SECRET_PLAINTEXT)
        self.assertTrue(provider.has_client_secret)
        self.assertTrue(provider.is_usable)


class SsoProviderApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw-12345678")
        self.editor = User.objects.create_user(username="editor", password="pw-12345678")
        self.viewer = User.objects.create_user(username="viewer", password="pw-12345678")
        self.outsider = User.objects.create_user(username="outsider", password="pw-12345678")
        self.app = App.objects.create(name="Demo", code="demo", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.editor, role="editor")
        AppMember.objects.create(app=self.app, user=self.viewer, role="viewer")
        self.client = APIClient()
        self.list_url = f"/api/apps/{self.app.id}/sso/providers/"

    def _as(self, user):
        self.client.force_authenticate(user=user)

    def test_owner_can_create_and_secret_is_never_exposed(self):
        self._as(self.owner)
        resp = self.client.post(self.list_url, provider_payload(), format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertNotIn("client_secret", body)
        self.assertTrue(body["has_client_secret"])
        self.assertEqual(body["slug"], "corp")
        self.assertNotIn(SECRET_PLAINTEXT, resp.content.decode())

        listing = self.client.get(self.list_url)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["count"], 1)
        self.assertNotIn("client_secret", listing.json()["results"][0])
        self.assertNotIn(SECRET_PLAINTEXT, listing.content.decode())

        detail = self.client.get(f"{self.list_url}{body['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn("client_secret", detail.json())
        self.assertNotIn(SECRET_PLAINTEXT, detail.content.decode())

    def test_patch_updates_secret_and_blank_keeps_it(self):
        provider = create_provider(self.app)
        self._as(self.owner)
        detail_url = f"{self.list_url}{provider.id}/"

        resp = self.client.patch(detail_url, {"client_secret": "rotated-secret"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertNotIn("rotated-secret", resp.content.decode())
        provider.refresh_from_db()
        self.assertEqual(provider.client_secret, "rotated-secret")

        resp = self.client.patch(detail_url, {"client_secret": "", "name": "Renamed"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        provider.refresh_from_db()
        self.assertEqual(provider.client_secret, "rotated-secret")
        self.assertEqual(provider.name, "Renamed")

    def test_permissions_editor_owner_only(self):
        provider = create_provider(self.app)
        detail_url = f"{self.list_url}{provider.id}/"

        self._as(self.outsider)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)
        self.assertEqual(self.client.post(self.list_url, provider_payload(slug="x"), format="json").status_code, 403)

        self._as(self.viewer)
        self.assertEqual(self.client.get(self.list_url).status_code, 403)

        self._as(self.editor)
        self.assertEqual(self.client.get(self.list_url).status_code, 200)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.assertEqual(
            self.client.post(self.list_url, provider_payload(slug="editor-corp"), format="json").status_code,
            403,
        )
        self.assertEqual(self.client.delete(detail_url).status_code, 403)

        self._as(self.owner)
        self.assertEqual(self.client.delete(detail_url).status_code, 204)
        self.assertFalse(SsoProvider.objects.filter(pk=provider.pk).exists())

    def test_enabled_provider_requires_endpoints(self):
        self._as(self.owner)
        payload = provider_payload()
        payload.pop("token_endpoint")
        resp = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("token_endpoint", resp.json())

    def test_plain_http_endpoint_rejected(self):
        self._as(self.owner)
        resp = self.client.post(
            self.list_url,
            provider_payload(token_endpoint="http://idp.example.com/token"),
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("token_endpoint", resp.json())

    def test_can_create_disabled_stub_then_enable(self):
        self._as(self.owner)
        resp = self.client.post(self.list_url, {"name": "Draft", "slug": "draft"}, format="json")
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertFalse(resp.json()["enabled"])
        self.assertFalse(resp.json()["has_client_secret"])

        provider_id = resp.json()["id"]
        resp = self.client.patch(f"{self.list_url}{provider_id}/", {"enabled": True}, format="json")
        self.assertEqual(resp.status_code, 400)  # 启用但缺必填项
        self.assertIn("client_id", resp.json())

    def test_duplicate_slug_rejected(self):
        create_provider(self.app)
        self._as(self.owner)
        resp = self.client.post(self.list_url, provider_payload(), format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("slug", resp.json())


class PublicProviderApiTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw-12345678")
        self.app = App.objects.create(name="Demo", code="demo", owner=self.owner)
        self.client = APIClient()

    def test_returns_only_enabled_minimal_fields(self):
        enabled = create_provider(self.app, slug="corp")
        create_provider(self.app, slug="disabled", enabled=False)
        create_provider(self.app, slug="broken", enabled=True, userinfo_endpoint="")

        resp = self.client.get("/api/auth/sso/demo/providers/")
        self.assertEqual(resp.status_code, 200)
        results = resp.json()["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(set(results[0].keys()), {"id", "name", "slug"})
        self.assertEqual(results[0]["slug"], enabled.slug)
        self.assertNotIn("client_secret", resp.content.decode())

    def test_hidden_when_app_login_disabled(self):
        create_provider(self.app)
        AppAuthConfig.objects.create(app=self.app, enabled=False)
        resp = self.client.get("/api/auth/sso/demo/providers/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])
