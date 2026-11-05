from django.conf import settings
from django.db import models


class MarketItem(models.Model):
    KIND_CHOICES = (("component", "组件"), ("block", "区块"))
    STATUS_CHOICES = (("draft", "草稿"), ("published", "已发布"), ("archived", "已归档"))
    VISIBILITY_CHOICES = (("public", "公开"), ("private", "私有"))

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="block")
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=100)
    description = models.TextField(blank=True, default="")
    category = models.CharField(max_length=60, blank=True, default="")
    tags = models.JSONField(default=list, blank=True)
    preview = models.JSONField(default=dict, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="public")
    source_app = models.ForeignKey(
        "appcore.App", null=True, blank=True, on_delete=models.SET_NULL, related_name="market_items",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="market_items",
    )
    installs = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_market_items"
        ordering = ("-updated_at", "-id")
        constraints = (
            models.UniqueConstraint(fields=["kind", "slug"], name="uniq_market_kind_slug"),
        )

    def __str__(self):
        return f"{self.kind}:{self.slug}"
