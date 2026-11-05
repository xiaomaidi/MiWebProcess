from django.conf import settings
from django.db import models


class PageComment(models.Model):
    """Designer review comment anchored to a page or a schema node."""

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="page_comments")
    page = models.ForeignKey("pages.Page", on_delete=models.CASCADE, related_name="comments")
    node_id = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField()
    # 已解析且通过校验的 @ 提及：[{id, username, display_name}]（不存邮箱）。
    mentions = models.JSONField(default=list, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="page_comments",
    )
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_page_comments"
        ordering = ("-created_at",)

# Server-authoritative designer locks live in a separate module.
from .lock_models import DesignerLock  # noqa: E402,F401
