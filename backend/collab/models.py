from django.conf import settings
from django.db import models

# 评论线程的最大层级（根评论为第 1 层）。
# root depth=0，回复 depth=1，回复的回复 depth=2；depth=3 的第四层会被拒绝。
MAX_COMMENT_DEPTH = 3

# 软删除后的占位正文：保留回复树，不让父评论级联消失。
DELETED_COMMENT_BODY = "[已删除]"

MAX_COMMENT_BODY = 4000


class PageComment(models.Model):
    """Designer review comment anchored to a page or a schema node.

    支持两级以上回复（最多 ``MAX_COMMENT_DEPTH`` 层）：

    - ``parent``：直接父评论；根评论为 NULL。
    - ``root``：所属线程的根评论；根评论自身为 NULL（便于按线程聚合与鉴权）。
    - ``depth``：0 表示根评论，回复逐级 +1（冗余存储，避免逐级回溯）。
    - ``deleted``：软删除标记；删除父评论时只把正文替换为 ``[已删除]``，
      回复仍然保留（不会级联删除）。
    """

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="page_comments")
    page = models.ForeignKey("pages.Page", on_delete=models.CASCADE, related_name="comments")
    parent = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE, related_name="replies",
    )
    root = models.ForeignKey(
        "self", null=True, blank=True,
        on_delete=models.CASCADE, related_name="+",
    )
    depth = models.PositiveSmallIntegerField(default=0)
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
    deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_page_comments"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["page", "parent"], name="wp_comment_page_parent_idx"),
            models.Index(fields=["page", "created_at"], name="wp_comment_page_created_idx"),
            models.Index(fields=["root"], name="wp_comment_root_idx"),
        ]

    @property
    def thread_root_id(self) -> int:
        """线程根 id（根评论返回自身 id，回复返回所属根 id）。"""
        return self.root_id or self.id

    @property
    def is_reply(self) -> bool:
        return self.parent_id is not None

# Server-authoritative designer locks live in a separate module.
from .lock_models import DesignerLock  # noqa: E402,F401
