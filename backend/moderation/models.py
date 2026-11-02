"""内容审核：记录级送审、审核队列与状态回写。

与工作流解耦：审核只关心「内容是否可公开」，节点少（提交 → 通过/驳回），
适合文章、商品、素材等需要编辑与发布分离的场景。每次重新送审生成新的
revision，历史审核记录保留，便于追溯。
"""
from django.conf import settings
from django.db import models


class ContentReview(models.Model):
    STATUS_CHOICES = (
        ("pending", "待审核"),
        ("approved", "已通过"),
        ("rejected", "已驳回"),
        ("cancelled", "已撤回"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="content_reviews")
    model = models.ForeignKey("datamodels.DataModel", on_delete=models.CASCADE, related_name="reviews")
    record = models.ForeignKey("datamodels.DataRecord", on_delete=models.CASCADE, related_name="reviews")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    revision = models.IntegerField(default=1)
    title = models.CharField(max_length=300, blank=True, default="")
    snapshot = models.JSONField(default=dict, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="submitted_reviews",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_content_reviews"
        ordering = ("-submitted_at",)
        indexes = [
            models.Index(fields=["app", "status"]),
            models.Index(fields=["record", "status"]),
            models.Index(fields=["model", "status"]),
        ]

    def __str__(self):
        return f"review#{self.id} {self.status}"


class ContentReviewEvent(models.Model):
    """审核轨迹：提交 / 通过 / 驳回 / 撤回 / 重新送审。"""

    review = models.ForeignKey(ContentReview, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=20)
    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20, blank=True, default="")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_content_review_events"
        ordering = ("id",)
