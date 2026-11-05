from django.conf import settings
from django.db import models


class MarketItem(models.Model):
    """市场条目：组件（可执行远端 ESM）或页面区块。

    组件安装前必须通过 ``market.signing`` 的 HMAC 签名校验；区块保持可匿名安装。
    ``policy`` 为规范化后的沙箱策略，``sandboxed`` 对组件强制为 True。
    """

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
    # ---- 代码签名（组件安装门槛；区块可保持未签名） ----
    code_hash = models.CharField("代码摘要", max_length=64, blank=True, default="")
    signature = models.CharField("HMAC 签名", max_length=64, blank=True, default="")
    signed_at = models.DateTimeField("签名时间", null=True, blank=True)
    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="signed_market_items",
    )
    # ---- 沙箱策略 ----
    sandboxed = models.BooleanField("启用沙箱", default=True)
    policy = models.JSONField("沙箱策略", default=dict, blank=True)
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
