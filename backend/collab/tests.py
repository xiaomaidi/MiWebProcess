from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from appcore.models import App
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
        self.viewer = User.objects.create_user(username="viewer", password="pw-12345678")
        self.app = App.objects.create(name="Demo", code="demo-collab", owner=self.owner)
        self.page = Page.objects.create(
            app=self.app, name="Home", path="home", type="page", status="draft",
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
