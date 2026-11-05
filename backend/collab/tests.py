from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from appcore.models import App, AppMember, NotificationLog
from pages.models import Page

from .models import PageComment

User = get_user_model()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


class PageCommentTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw-12345678")
        self.viewer = User.objects.create_user(
            username="viewer", password="pw-12345678",
            first_name="View", last_name="Er",
        )
        self.outsider = User.objects.create_user(username="outsider", password="pw-12345678")
        self.inactive = User.objects.create_user(
            username="inactive", password="pw-12345678", is_active=False,
        )
        self.app = App.objects.create(name="Demo", code="demo-collab", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.viewer, role="viewer")
        self.page = Page.objects.create(
            app=self.app, name="Home", path="home", type="page", status="draft",
        )

    def _create(self, body, user=None, **extra):
        return client_for(user or self.owner).post(
            f"/api/collab/pages/{self.page.id}/comments/",
            {"body": body, **extra},
            format="json",
        )

    def test_owner_can_create_list_and_resolve(self):
        client = client_for(self.owner)
        created = client.post(
            f"/api/collab/pages/{self.page.id}/comments/",
            {"body": "Please align this card", "node_id": "node-1"},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        comment_id = created.json()["id"]
        listed = client.get(f"/api/collab/pages/{self.page.id}/comments/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()["results"]), 1)

        resolved = client.patch(f"/api/collab/comments/{comment_id}/", {"resolved": True}, format="json")
        self.assertEqual(resolved.status_code, 200)
        self.assertTrue(resolved.json()["resolved"])
        self.assertEqual(PageComment.objects.get(pk=comment_id).resolved, True)

    def test_non_editor_cannot_create(self):
        client = client_for(self.viewer)
        response = client.post(
            f"/api/collab/pages/{self.page.id}/comments/",
            {"body": "should fail"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_empty_body_rejected(self):
        client = client_for(self.owner)
        response = client.post(
            f"/api/collab/pages/{self.page.id}/comments/",
            {"body": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    # ---------------------------------------------------------------- @ 提及
    def test_mention_parsed_and_notification_created(self):
        response = self._create("Please check @viewer. Thanks @ghost")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual([m["username"] for m in data["mentions"]], ["viewer"])
        self.assertEqual(data["mentions"][0]["display_name"], "View Er")
        self.assertEqual(data["mention_usernames"], ["viewer"])
        self.assertEqual(data["notified_count"], 1)
        # 邮箱绝不进入提及对象
        self.assertEqual(set(data["mentions"][0]), {"id", "username", "display_name"})
        self.assertNotIn("email", data["mentions"][0])
        # 无效提及只给警告，不通知
        self.assertEqual([w["token"] for w in data["warnings"]], ["@ghost"])
        self.assertEqual(data["warnings"][0]["code"], "unknown_user")

        log = NotificationLog.objects.get(app=self.app, recipient="viewer")
        self.assertEqual(log.channel, "inapp")
        self.assertEqual(log.created_by_id, self.owner.id)
        self.assertIn("owner", log.subject)
        self.assertIn("Home", log.subject)
        self.assertEqual(log.payload["comment_id"], data["id"])
        self.assertEqual(log.payload["page_id"], self.page.id)
        self.assertEqual(PageComment.objects.get(pk=data["id"]).body, "Please check @viewer. Thanks @ghost")

    def test_invalid_mention_keeps_text_without_notification(self):
        response = self._create("Hi @nobody, take a look")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["mentions"], [])
        self.assertEqual(data["mention_usernames"], [])
        self.assertEqual(data["warnings"][0]["code"], "unknown_user")
        self.assertEqual(PageComment.objects.get(pk=data["id"]).body, "Hi @nobody, take a look")
        self.assertFalse(NotificationLog.objects.filter(app=self.app).exists())

    def test_inactive_mention_is_rejected(self):
        response = self._create("Ping @inactive")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["mentions"], [])
        self.assertEqual(data["warnings"][0]["code"], "inactive_user")
        self.assertFalse(NotificationLog.objects.exists())

    def test_mention_without_app_access_is_rejected(self):
        response = self._create("Ping @outsider")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["mentions"], [])
        self.assertEqual(data["warnings"][0]["code"], "no_app_access")
        self.assertFalse(NotificationLog.objects.exists())

    def test_self_mention_is_stored_without_self_notification(self):
        response = self._create("Note to self @owner")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual([m["username"] for m in data["mentions"]], ["owner"])
        self.assertEqual(data.get("notified_count", 0), 0)
        self.assertFalse(NotificationLog.objects.exists())

    def test_duplicate_mentions_collapse_to_one_notification(self):
        response = self._create("@viewer @viewer @viewer.")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["mention_usernames"], ["viewer"])
        self.assertEqual(NotificationLog.objects.filter(recipient="viewer").count(), 1)
        self.assertNotIn("warnings", data)

    def test_mention_matching_is_case_insensitive(self):
        response = self._create("Hello @Viewer")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["mention_usernames"], ["viewer"])
        self.assertEqual(NotificationLog.objects.filter(recipient="viewer").count(), 1)

    def test_unicode_username_mention(self):
        zh = User.objects.create_user(username="张三", password="pw-12345678")
        AppMember.objects.create(app=self.app, user=zh, role="viewer")
        response = self._create("请 @张三 看一下这个卡片")
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["mention_usernames"], ["张三"])
        self.assertEqual(NotificationLog.objects.filter(recipient="张三").count(), 1)

    def test_mention_kept_in_list_serializer(self):
        created = self._create("cc @viewer")
        self.assertEqual(created.status_code, 201)
        listed = client_for(self.owner).get(f"/api/collab/pages/{self.page.id}/comments/")
        self.assertEqual(listed.status_code, 200)
        row = listed.json()["results"][0]
        self.assertEqual(row["mentions"][0]["username"], "viewer")
        self.assertNotIn("email", row["mentions"][0])

    def test_patch_body_refreshes_mentions_and_notifies_only_new(self):
        created = self._create("plain comment")
        comment_id = created.json()["id"]
        client = client_for(self.owner)
        with patch("collab.views.broadcast_to_app"):
            updated = client.patch(
                f"/api/collab/comments/{comment_id}/",
                {"body": "now mention @viewer"},
                format="json",
            )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["mention_usernames"], ["viewer"])
        self.assertEqual(updated.json()["notified_count"], 1)
        self.assertEqual(NotificationLog.objects.filter(recipient="viewer").count(), 1)
        # 同一提及再次保存不重复通知
        with patch("collab.views.broadcast_to_app"):
            again = client.patch(
                f"/api/collab/comments/{comment_id}/",
                {"body": "now mention @viewer again"},
                format="json",
            )
        self.assertEqual(again.status_code, 200)
        self.assertEqual(NotificationLog.objects.filter(recipient="viewer").count(), 1)

    # ---------------------------------------------------------------- 权限
    def test_outsider_cannot_read_or_write(self):
        client = client_for(self.outsider)
        self.assertEqual(client.get(f"/api/collab/pages/{self.page.id}/comments/").status_code, 403)
        self.assertEqual(
            client.post(
                f"/api/collab/pages/{self.page.id}/comments/",
                {"body": "nope"},
                format="json",
            ).status_code,
            403,
        )

    def test_viewer_can_read_resolve_but_not_create_or_edit_body(self):
        comment_id = self._create("owner comment").json()["id"]
        viewer = client_for(self.viewer)
        self.assertEqual(viewer.get(f"/api/collab/pages/{self.page.id}/comments/").status_code, 200)
        self.assertEqual(
            viewer.post(
                f"/api/collab/pages/{self.page.id}/comments/",
                {"body": "no"},
                format="json",
            ).status_code,
            403,
        )
        self.assertEqual(
            viewer.patch(
                f"/api/collab/comments/{comment_id}/",
                {"body": "rewritten"},
                format="json",
            ).status_code,
            403,
        )
        resolved = viewer.patch(
            f"/api/collab/comments/{comment_id}/", {"resolved": True}, format="json",
        )
        self.assertEqual(resolved.status_code, 200)
        # 删除他人的评论需要编辑权限
        self.assertEqual(viewer.delete(f"/api/collab/comments/{comment_id}/").status_code, 403)

    def test_platform_admin_can_comment_without_membership(self):
        admin = User.objects.create_superuser(
            username="admin", password="pw-12345678", email="admin@example.com",
        )
        response = self._create("admin note @viewer", user=admin)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(NotificationLog.objects.filter(recipient="viewer").count(), 1)

    # ---------------------------------------------------------------- WebSocket 中继
    def test_create_broadcasts_comment_created_event(self):
        with patch("collab.views.broadcast_to_app") as broadcast:
            response = self._create("broadcast me @viewer")
        self.assertEqual(response.status_code, 201)
        broadcast.assert_called_once()
        args, kwargs = broadcast.call_args
        self.assertEqual(args[0], self.app.id)
        message = args[1]
        comment = response.json()
        self.assertEqual(message["type"], "comment_created")
        self.assertEqual(message["extra"]["topic"], f"designer-comments/{self.page.id}")
        self.assertEqual(message["extra"]["page_id"], self.page.id)
        self.assertEqual(message["payload"]["page_id"], self.page.id)
        self.assertEqual(message["payload"]["comment_id"], comment["id"])
        self.assertEqual(message["payload"]["comment"]["id"], comment["id"])
        self.assertEqual(
            message["payload"]["event_key"],
            f"comment_created:{comment['id']}:{comment['updated_at']}",
        )
        self.assertEqual(kwargs["sender"], "owner")

    def test_resolve_broadcasts_comment_resolved_event(self):
        comment_id = self._create("resolve me").json()["id"]
        with patch("collab.views.broadcast_to_app") as broadcast:
            response = client_for(self.owner).patch(
                f"/api/collab/comments/{comment_id}/", {"resolved": True}, format="json",
            )
        self.assertEqual(response.status_code, 200)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["type"], "comment_resolved")
        self.assertTrue(message["payload"]["comment"]["resolved"])
        self.assertTrue(message["payload"]["event_key"].startswith(f"comment_resolved:{comment_id}:"))

    def test_delete_broadcasts_comment_deleted_event(self):
        comment_id = self._create("delete me").json()["id"]
        with patch("collab.views.broadcast_to_app") as broadcast:
            response = client_for(self.owner).delete(f"/api/collab/comments/{comment_id}/")
        self.assertEqual(response.status_code, 204)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["type"], "comment_deleted")
        self.assertEqual(message["payload"]["comment_id"], comment_id)
        self.assertEqual(message["payload"]["comment"]["body"], "delete me")
        self.assertEqual(message["payload"]["event_key"], f"comment_deleted:{comment_id}")

    def test_unrelated_page_topic_is_not_used(self):
        other = Page.objects.create(
            app=self.app, name="Other", path="other", type="page", status="draft",
        )
        with patch("collab.views.broadcast_to_app") as broadcast:
            response = client_for(self.owner).post(
                f"/api/collab/pages/{other.id}/comments/",
                {"body": "other page"},
                format="json",
            )
        self.assertEqual(response.status_code, 201)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["extra"]["topic"], f"designer-comments/{other.id}")
        self.assertEqual(message["payload"]["page_id"], other.id)
