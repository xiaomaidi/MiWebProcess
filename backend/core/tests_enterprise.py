"""企业运维控制台 API 测试（新增文件）。

运行：cd backend && python manage.py test core.tests_enterprise -v 2 --noinput

说明：本模块同时充当测试专用 ROOT_URLCONF（模块级 urlpatterns），
因此无需修改 config/urls.py 即可独立验证 /api/enterprise/ 路由。
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import include, path
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from appcore.models import (
    App,
    NotificationLog,
    ScheduledJob,
    WebhookDelivery,
    WebhookEndpoint,
)
from audit.models import AuditLog

User = get_user_model()

urlpatterns = [
    path("api/enterprise/", include("core.enterprise_urls")),
]

OVERVIEW_URL = "/api/enterprise/overview/"
BACKUPS_URL = "/api/enterprise/backups/"


def admin_client(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")
    return client


def make_zip(path: Path, payload: bytes = b"demo-backup") -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", '{"demo": true}')
        zf.writestr("db.dump", payload)


@override_settings(ROOT_URLCONF="core.tests_enterprise")
class EnterprisePermissionTests(SimpleTestCase):
    """未认证/非管理员必须被拒绝（SimpleTestCase 不发数据库查询）。"""

    def test_anonymous_rejected(self):
        response = APIClient().get(OVERVIEW_URL)
        self.assertIn(response.status_code, (401, 403))
        response = APIClient().get(BACKUPS_URL)
        self.assertIn(response.status_code, (401, 403))


@override_settings(ROOT_URLCONF="core.tests_enterprise")
class EnterpriseOverviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser("ent-admin", "admin@example.com", "pass-12345")
        cls.staff = User.objects.create_user("ent-staff", password="pass-12345", is_staff=True)
        cls.regular = User.objects.create_user("ent-regular", password="pass-12345")

        app = App.objects.create(
            name="运维示例应用", code="ent-demo", owner=cls.admin, status="published"
        )
        cls.app = app
        ScheduledJob.objects.create(
            app=app, name="每晚同步", code="nightly-sync", handler="noop",
            last_status="failed", last_error="连接超时",
        )
        endpoint = WebhookEndpoint.objects.create(
            app=app, name="CRM 回调", url="https://example.com/hook", last_status="failed"
        )
        WebhookDelivery.objects.create(
            endpoint=endpoint, event="record.created", status_code=500, ok=False, error="HTTP 500"
        )
        NotificationLog.objects.create(app=app, channel="inapp", status="failed", subject="告警")
        AuditLog.objects.create(user=cls.admin, username=cls.admin.username, object_type="app",
                                object_id=str(app.id), action="create")

    def test_non_admin_forbidden(self):
        response = admin_client(self.regular).get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 403)

    def test_staff_allowed(self):
        response = admin_client(self.staff).get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 200)

    def test_overview_shape(self):
        response = admin_client(self.admin).get(OVERVIEW_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        for key in (
            "generated_at", "environment", "health", "apps", "users", "data", "storage",
            "audit", "jobs", "webhooks", "notifications", "releases", "backups",
        ):
            self.assertIn(key, data)

        self.assertEqual(data["apps"]["total"], 1)
        self.assertEqual(data["apps"]["by_status"], {"draft": 0, "published": 1, "archived": 0})
        self.assertEqual(data["users"]["total"], 3)
        self.assertEqual(data["users"]["active"], 3)
        self.assertEqual(data["users"]["staff"], 2)
        self.assertEqual(data["users"]["superuser"], 1)
        self.assertEqual(data["data"]["models"], 0)
        self.assertEqual(data["data"]["records"], 0)

        self.assertEqual(data["audit"]["total"], 1)
        self.assertEqual(data["audit"]["last_24h"], 1)
        self.assertLessEqual(len(data["audit"]["recent"]), 10)
        recent = data["audit"]["recent"][0]
        for field in ("id", "username", "action", "object_type", "object_id", "app_id", "ip", "created_at"):
            self.assertIn(field, recent)

        self.assertEqual(data["jobs"]["total"], 1)
        self.assertEqual(data["jobs"]["failed"], 1)
        self.assertEqual(len(data["jobs"]["recent_failures"]), 1)
        self.assertEqual(data["jobs"]["recent_failures"][0]["code"], "nightly-sync")

        self.assertEqual(data["webhooks"]["endpoints"], 1)
        self.assertEqual(data["webhooks"]["failing"], 1)
        self.assertEqual(data["webhooks"]["failed_deliveries"], 1)
        self.assertEqual(len(data["webhooks"]["recent_failures"]), 1)

        self.assertEqual(data["notifications"]["failed"], 1)
        self.assertEqual(data["releases"]["total"], 0)

        health = data["health"]
        self.assertIn(health["database"]["status"], ("ok", "error"))
        self.assertIn(health["overall"], ("ok", "degraded", "down"))
        self.assertIn(health["cache"]["status"], ("ok", "degraded", "error"))
        self.assertIn(health["celery_broker"]["status"], ("ok", "error", "unknown", "not_configured"))
        self.assertIn("configured_engine", health["database"])
        self.assertIn("backend", health["cache"])

        self.assertIn("count", data["backups"])
        self.assertIsInstance(data["storage"]["media_bytes"], int)

    def test_overview_does_not_leak_absolute_paths(self):
        response = admin_client(self.admin).get(OVERVIEW_URL)
        body = response.content.decode("utf-8")
        self.assertNotIn(str(settings.BASE_DIR), body)
        self.assertNotIn(str(settings.MEDIA_ROOT), body)


@override_settings(ROOT_URLCONF="core.tests_enterprise")
class EnterpriseBackupTests(TransactionTestCase):
    """备份用例用 TransactionTestCase：备份需要读取已提交的数据库状态。"""

    def setUp(self):
        self.admin = User.objects.create_superuser("ent-backup-admin", "backup@example.com", "pass-12345")
        self.regular = User.objects.create_user("ent-backup-user", password="pass-12345")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.backup_dir = Path(self.tmp.name)
        make_zip(self.backup_dir / "webprocess-20260101-000000.zip")
        (self.backup_dir / "demo-app-export.json").write_text("{}", encoding="utf-8")
        (self.backup_dir / "notes.txt").write_text("ignored", encoding="utf-8")
        (self.backup_dir / "evil.exe").write_bytes(b"nope")
        (self.backup_dir / ".hidden.zip").write_bytes(b"hidden")
        override = override_settings(ENTERPRISE_BACKUP_DIR=str(self.backup_dir))
        override.enable()
        self.addCleanup(override.disable)

    def _names(self) -> set[str]:
        return {entry.name for entry in self.backup_dir.iterdir()}

    def test_list_backups(self):
        response = admin_client(self.admin).get(BACKUPS_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 2)
        names = {item["name"] for item in data["results"]}
        self.assertEqual(names, {"webprocess-20260101-000000.zip", "demo-app-export.json"})
        self.assertNotIn("evil.exe", names)
        self.assertNotIn("notes.txt", names)
        self.assertNotIn(".hidden.zip", names)
        for item in data["results"]:
            self.assertNotIn("/", item["name"])
            self.assertNotIn("\\", item["name"])
            self.assertGreaterEqual(item["size"], 0)
            self.assertIn(item["kind"], ("system_backup", "app_export"))
            self.assertIn("created_at", item)
        self.assertEqual(data["directory"]["name"], self.backup_dir.name)
        self.assertIn("instructions", data)
        self.assertTrue(data["capabilities"]["create"])
        self.assertFalse(data["capabilities"]["download"])

    def test_non_admin_cannot_list_or_create(self):
        client = admin_client(self.regular)
        response = client.get(BACKUPS_URL)
        self.assertEqual(response.status_code, 403)
        before = self._names()
        response = client.post(BACKUPS_URL, {}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._names(), before)

    def test_create_backup(self):
        before = self._names()
        response = admin_client(self.admin).post(BACKUPS_URL, {}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertFalse(data["include_media"])
        self.assertTrue(data["filename"].startswith("webprocess-enterprise-"))
        self.assertTrue(data["filename"].endswith((".zip", ".sqlite3")))
        self.assertGreater(data["size"], 0)
        self.assertIn(data["backup"]["kind"], ("system_backup",))
        created = self.backup_dir / data["filename"]
        self.assertTrue(created.is_file())
        self.assertGreater(created.stat().st_size, 0)
        self.assertEqual(self._names() - before, {data["filename"]})
        self.assertFalse(data["filename"].endswith(".part"))
        # 审计日志记录备份动作
        self.assertTrue(AuditLog.objects.filter(action="backup.create", object_id=data["filename"]).exists())

    def test_create_ignores_client_supplied_paths(self):
        response = admin_client(self.admin).post(
            BACKUPS_URL,
            {"filename": "../../evil.zip", "output": "C:\\Windows\\evil.zip", "path": "/tmp/evil.zip"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertTrue(data["filename"].startswith("webprocess-enterprise-"))
        self.assertFalse((self.backup_dir.parent / "evil.zip").exists())
        self.assertFalse((self.backup_dir / "evil.zip").exists())

    def test_create_requires_authentication(self):
        before = self._names()
        response = APIClient().post(BACKUPS_URL, {}, format="json")
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self._names(), before)
