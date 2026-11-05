from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from appcore.models import App, AppMember, NotificationLog
from pages.models import Page

from .models import MAX_COMMENT_DEPTH, PageComment

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

    def test_delete_soft_deletes_and_broadcasts_update(self):
        comment_id = self._create("delete me").json()["id"]
        with patch("collab.views.broadcast_to_app") as broadcast:
            response = client_for(self.owner).delete(f"/api/collab/comments/{comment_id}/")
        self.assertEqual(response.status_code, 204)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["type"], "comment_updated")
        self.assertEqual(message["payload"]["comment_id"], comment_id)
        self.assertEqual(message["payload"]["comment"]["body"], "[已删除]")
        self.assertTrue(message["payload"]["comment"]["deleted"])
        self.assertTrue(
            message["payload"]["event_key"].startswith(f"comment_updated:{comment_id}:")
        )
        self.assertTrue(PageComment.objects.filter(pk=comment_id, deleted=True).exists())

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

    # 线程与通知中心测试见下方 PageCommentThreadTests / NotificationCenterTests。


class PageCommentThreadTests(TestCase):
    """评论回复线程：parent/root/depth、软删除保留回复、@ 提及通知。"""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw-12345678")
        self.viewer = User.objects.create_user(
            username="viewer", password="pw-12345678",
            first_name="View", last_name="Er",
        )
        self.other = User.objects.create_user(username="other", password="pw-12345678")
        self.app = App.objects.create(name="Thread Demo", code="thread-demo", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.viewer, role="viewer")
        AppMember.objects.create(app=self.app, user=self.other, role="viewer")
        self.page = Page.objects.create(
            app=self.app, name="Home", path="home", type="page", status="draft",
        )
        self.other_page = Page.objects.create(
            app=self.app, name="Other", path="other", type="page", status="draft",
        )

    def _create(self, body, user=None, page=None, **extra):
        page = page or self.page
        return client_for(user or self.owner).post(
            f"/api/collab/pages/{page.id}/comments/",
            {"body": body, **extra},
            format="json",
        )

    def _rows(self, user=None, page=None):
        page = page or self.page
        listed = client_for(user or self.owner).get(
            f"/api/collab/pages/{page.id}/comments/"
        )
        self.assertEqual(listed.status_code, 200)
        return {row["id"]: row for row in listed.json()["results"]}

    def test_reply_sets_parent_root_and_depth(self):
        root = self._create("根评论").json()
        self.assertEqual(root["depth"], 0)
        self.assertIsNone(root["parent_id"])
        self.assertEqual(root["root_id"], root["id"])
        self.assertFalse(root["is_reply"])
        self.assertFalse(root["deleted"])

        reply = self._create("回复", parent_id=root["id"]).json()
        self.assertEqual(reply["parent_id"], root["id"])
        self.assertEqual(reply["root_id"], root["id"])
        self.assertEqual(reply["depth"], 1)
        self.assertTrue(reply["is_reply"])

    def test_second_level_reply_shares_thread_root(self):
        root = self._create("根").json()
        first = self._create("一级回复", parent_id=root["id"]).json()
        second = self._create("二级回复", parent_id=first["id"]).json()
        self.assertEqual(second["parent_id"], first["id"])
        self.assertEqual(second["root_id"], root["id"])
        self.assertEqual(second["depth"], 2)

        rows = self._rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[second["id"]]["root_id"], root["id"])

    def test_reply_depth_is_limited(self):
        root = self._create("根").json()
        parent_id = root["id"]
        for depth in range(1, MAX_COMMENT_DEPTH):
            created = self._create(f"第 {depth} 层", parent_id=parent_id)
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["depth"], depth)
            parent_id = created.json()["id"]
        too_deep = self._create("超过层级", parent_id=parent_id)
        self.assertEqual(too_deep.status_code, 400)
        self.assertIn("层级", str(too_deep.json()))

    def test_reply_parent_must_belong_to_same_page(self):
        foreign = self._create("别的页面", page=self.other_page).json()
        response = self._create("串页回复", parent_id=foreign["id"])
        self.assertEqual(response.status_code, 400)
        self.assertIn("不属于当前页面", str(response.json()))

    def test_reply_to_unknown_parent_is_rejected(self):
        response = self._create("幽灵父评论", parent_id=999999)
        self.assertEqual(response.status_code, 400)
        self.assertIn("不存在", str(response.json()))

    def test_reply_inherits_node_id_when_omitted(self):
        root = self._create("节点评论", node_id="node-1").json()
        reply = self._create("回复节点", parent_id=root["id"]).json()
        self.assertEqual(reply["node_id"], "node-1")
        explicit = self._create("显式节点", parent_id=root["id"], node_id="node-2").json()
        self.assertEqual(explicit["node_id"], "node-2")

    def test_delete_parent_soft_deletes_and_keeps_replies(self):
        root = self._create("父评论 @viewer").json()
        reply = self._create("子回复", parent_id=root["id"]).json()
        grandchild = self._create("孙回复", parent_id=reply["id"]).json()
        self.assertEqual(
            NotificationLog.objects.filter(recipient="viewer").count(), 1,
        )

        with patch("collab.views.broadcast_to_app") as broadcast:
            response = client_for(self.owner).delete(f"/api/collab/comments/{root['id']}/")
        self.assertEqual(response.status_code, 204)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["type"], "comment_updated")
        self.assertTrue(message["payload"]["comment"]["deleted"])

        root_row = PageComment.objects.get(pk=root["id"])
        self.assertTrue(root_row.deleted)
        self.assertEqual(root_row.body, "[已删除]")
        self.assertEqual(root_row.mentions, [])
        self.assertTrue(PageComment.objects.filter(pk=reply["id"], deleted=False).exists())
        self.assertTrue(PageComment.objects.filter(pk=grandchild["id"], deleted=False).exists())

        rows = self._rows()
        self.assertTrue(rows[root["id"]]["deleted"])
        self.assertEqual(rows[root["id"]]["body"], "[已删除]")
        self.assertEqual(rows[root["id"]]["mentions"], [])
        self.assertFalse(rows[reply["id"]]["deleted"])
        self.assertEqual(rows[reply["id"]]["parent_id"], root["id"])

    def test_delete_parent_is_idempotent_and_broadcasts_once(self):
        root = self._create("删两次").json()
        client = client_for(self.owner)
        self.assertEqual(client.delete(f"/api/collab/comments/{root['id']}/").status_code, 204)
        with patch("collab.views.broadcast_to_app") as broadcast:
            again = client.delete(f"/api/collab/comments/{root['id']}/")
        self.assertEqual(again.status_code, 204)
        broadcast.assert_not_called()

    def test_deleted_comment_cannot_be_replied_or_edited(self):
        root = self._create("将被删除").json()
        PageComment.objects.filter(pk=root["id"]).update(
            deleted=True, body="[已删除]",
        )
        self.assertEqual(self._create("回复已删除", parent_id=root["id"]).status_code, 400)
        patched = client_for(self.owner).patch(
            f"/api/collab/comments/{root['id']}/",
            {"body": "偷偷改回来"},
            format="json",
        )
        self.assertEqual(patched.status_code, 400)
        self.assertFalse(PageComment.objects.get(pk=root["id"]).body == "偷偷改回来")

    def test_reply_mention_creates_notification_with_thread_metadata(self):
        root = self._create("父评论").json()
        reply = self._create("请看下 @viewer", parent_id=root["id"])
        self.assertEqual(reply.status_code, 201)
        data = reply.json()
        self.assertEqual(data["mention_usernames"], ["viewer"])
        self.assertEqual(data["notified_count"], 1)
        self.assertEqual(data["parent_id"], root["id"])

        log = NotificationLog.objects.get(recipient="viewer")
        self.assertIn("回复", log.subject)
        self.assertEqual(log.payload["comment_id"], data["id"])
        self.assertEqual(log.payload["parent_id"], root["id"])
        self.assertEqual(log.payload["root_id"], root["id"])
        self.assertTrue(log.payload["is_reply"])

    def test_duplicate_reply_mentions_collapse_to_one_notification(self):
        root = self._create("父评论").json()
        response = self._create("@viewer @viewer 回复", parent_id=root["id"])
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            NotificationLog.objects.filter(recipient="viewer").count(), 1,
        )

    def test_reply_broadcast_carries_thread_fields(self):
        root = self._create("父").json()
        with patch("collab.views.broadcast_to_app") as broadcast:
            reply = self._create("子", parent_id=root["id"])
        self.assertEqual(reply.status_code, 201)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["type"], "comment_created")
        comment = message["payload"]["comment"]
        self.assertEqual(comment["parent_id"], root["id"])
        self.assertEqual(comment["root_id"], root["id"])
        self.assertEqual(comment["depth"], 1)
        self.assertEqual(message["extra"]["topic"], f"designer-comments/{self.page.id}")

    def test_resolve_root_resolves_whole_thread(self):
        root = self._create("父").json()
        first = self._create("一级", parent_id=root["id"]).json()
        second = self._create("二级", parent_id=first["id"]).json()

        with patch("collab.views.broadcast_to_app") as broadcast:
            response = client_for(self.owner).patch(
                f"/api/collab/comments/{root['id']}/", {"resolved": True}, format="json",
            )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["resolved"])
        self.assertEqual(set(data["resolved_reply_ids"]), {first["id"], second["id"]})
        for pk in (first["id"], second["id"]):
            self.assertTrue(PageComment.objects.get(pk=pk).resolved)
        message = broadcast.call_args.args[1]
        self.assertEqual(message["type"], "comment_resolved")
        self.assertEqual(
            set(message["payload"]["comment"]["resolved_reply_ids"]),
            {first["id"], second["id"]},
        )

        reopened = client_for(self.owner).patch(
            f"/api/collab/comments/{root['id']}/", {"resolved": False}, format="json",
        )
        self.assertEqual(reopened.status_code, 200)
        self.assertEqual(
            set(reopened.json()["resolved_reply_ids"]), {first["id"], second["id"]},
        )
        for pk in (first["id"], second["id"]):
            self.assertFalse(PageComment.objects.get(pk=pk).resolved)

    def test_parent_id_cannot_be_changed(self):
        root = self._create("父").json()
        reply = self._create("子", parent_id=root["id"]).json()
        response = client_for(self.owner).patch(
            f"/api/collab/comments/{reply['id']}/",
            {"parent_id": None},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(PageComment.objects.get(pk=reply["id"]).parent_id, root["id"])

    def test_page_delete_cascades_whole_thread(self):
        root = self._create("父").json()
        self._create("子", parent_id=root["id"])
        self.page.delete()
        self.assertFalse(PageComment.objects.filter(app_id=self.app.id).exists())


class NotificationCenterTests(TestCase):
    """通知中心：只读自己的、已读、全部已读、分页与元数据。"""

    def setUp(self):
        self.owner = User.objects.create_user(username="owner", password="pw-12345678")
        self.viewer = User.objects.create_user(username="viewer", password="pw-12345678")
        self.other = User.objects.create_user(username="other", password="pw-12345678")
        self.app = App.objects.create(name="Notify Demo", code="notify-demo", owner=self.owner)
        AppMember.objects.create(app=self.app, user=self.viewer, role="viewer")
        self.page = Page.objects.create(
            app=self.app, name="收件箱页", path="inbox", type="page", status="draft",
        )
        self.list_url = reverse("notifications-list")
        self.read_all_url = reverse("notifications-read-all")

    def make_log(self, recipient, *, read=False, payload=None, subject=None):
        return NotificationLog.objects.create(
            app=self.app,
            channel="inapp",
            recipient=recipient,
            subject=subject or f"给 {recipient} 的通知",
            content="通知内容",
            status="sent",
            read_at=timezone.now() if read else None,
            payload=payload or {
                "kind": "comment_mention",
                "page_id": self.page.id,
                "page_name": self.page.name,
                "comment_id": 321,
                "author": "owner",
            },
        )

    def test_feed_only_returns_current_user_notifications(self):
        mine = self.make_log("viewer")
        self.make_log("other")
        self.make_log("")
        response = client_for(self.viewer).get(self.list_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual([row["id"] for row in data["results"]], [mine.id])
        self.assertNotIn("recipient", data["results"][0])

    def test_feed_unread_filter_and_counts(self):
        unread = self.make_log("viewer")
        self.make_log("viewer", read=True)
        response = client_for(self.viewer).get(self.list_url + "?unread=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual([row["id"] for row in data["results"]], [unread.id])
        self.assertEqual(data["unread_count"], 1)
        self.assertFalse(data["results"][0]["is_read"])

        all_rows = client_for(self.viewer).get(self.list_url).json()
        self.assertEqual(all_rows["count"], 2)
        self.assertEqual(all_rows["unread_count"], 1)

    def test_feed_pagination(self):
        for index in range(25):
            self.make_log("viewer", subject=f"第 {index} 条")
        response = client_for(self.viewer).get(
            self.list_url + "?page=2&size=10"
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 25)
        self.assertEqual(data["page"], 2)
        self.assertEqual(data["size"], 10)
        self.assertEqual(len(data["results"]), 10)
        self.assertEqual(data["unread_count"], 25)

    def test_feed_includes_app_page_and_comment_metadata(self):
        log = self.make_log("viewer")
        response = client_for(self.viewer).get(self.list_url)
        row = response.json()["results"][0]
        self.assertEqual(row["id"], log.id)
        self.assertEqual(row["app_id"], self.app.id)
        self.assertEqual(row["app_name"], "Notify Demo")
        self.assertEqual(row["page_id"], self.page.id)
        self.assertEqual(row["page_name"], "收件箱页")
        self.assertEqual(row["comment_id"], 321)
        self.assertEqual(row["kind"], "comment_mention")
        self.assertEqual(row["author"], "owner")
        self.assertTrue(row["subject"])

    def test_feed_kind_filter(self):
        mention = self.make_log("viewer")
        self.make_log("viewer", payload={"kind": "workflow_todo", "page_id": None})
        response = client_for(self.viewer).get(self.list_url + "?kind=comment_mention")
        self.assertEqual(response.status_code, 200)
        rows = response.json()["results"]
        self.assertEqual([row["id"] for row in rows], [mention.id])

    def test_mark_read_is_idempotent(self):
        log = self.make_log("viewer")
        client = client_for(self.viewer)
        first = client.post(reverse("notification-read", args=[log.id]))
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["is_read"])
        self.assertIsNotNone(first.json()["read_at"])
        log.refresh_from_db()
        self.assertIsNotNone(log.read_at)
        read_at = log.read_at

        second = client.post(reverse("notification-read", args=[log.id]))
        self.assertEqual(second.status_code, 200)
        log.refresh_from_db()
        self.assertEqual(log.read_at, read_at)

    def test_cannot_mark_read_other_users_notification(self):
        foreign = self.make_log("other")
        response = client_for(self.viewer).post(
            reverse("notification-read", args=[foreign.id])
        )
        self.assertEqual(response.status_code, 404)
        foreign.refresh_from_db()
        self.assertIsNone(foreign.read_at)

    def test_read_all_only_affects_current_user(self):
        for _ in range(3):
            self.make_log("viewer")
        self.make_log("viewer", read=True)
        untouched = self.make_log("other")
        response = client_for(self.viewer).post(self.read_all_url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["updated"], 3)
        self.assertEqual(data["unread_count"], 0)
        self.assertEqual(
            NotificationLog.objects.filter(recipient="viewer", read_at__isnull=True).count(),
            0,
        )
        untouched.refresh_from_db()
        self.assertIsNone(untouched.read_at)

    def test_feed_requires_authentication(self):
        response = APIClient().get(self.list_url)
        self.assertIn(response.status_code, (401, 403))

    def test_reply_mention_reaches_recipient_feed_and_can_be_read(self):
        root = client_for(self.owner).post(
            f"/api/collab/pages/{self.page.id}/comments/",
            {"body": "根评论"},
            format="json",
        ).json()
        reply = client_for(self.owner).post(
            f"/api/collab/pages/{self.page.id}/comments/",
            {"body": "回复里 @viewer 看一下", "parent_id": root["id"]},
            format="json",
        )
        self.assertEqual(reply.status_code, 201)
        reply_id = reply.json()["id"]

        client = client_for(self.viewer)
        feed = client.get(self.list_url + "?unread=1").json()
        self.assertEqual(feed["count"], 1)
        row = feed["results"][0]
        self.assertEqual(row["kind"], "comment_mention")
        self.assertEqual(row["page_id"], self.page.id)
        self.assertEqual(row["comment_id"], reply_id)
        self.assertEqual(row["parent_id"], root["id"])
        self.assertEqual(row["root_id"], root["id"])
        self.assertTrue(row["is_reply"])
        self.assertEqual(feed["unread_count"], 1)

        marked = client.post(reverse("notification-read", args=[row["id"]]))
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(client.get(self.list_url + "?unread=1").json()["count"], 0)
