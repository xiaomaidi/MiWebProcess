from django.conf import settings
from django.db import models


class Page(models.Model):
    """页面：schema JSONB 为草稿；发布生成 PageVersion 不可变快照。"""

    TYPE_CHOICES = (
        ("page", "页面"),
        ("layout", "布局"),
        ("popup", "弹窗"),
    )
    STATUS_CHOICES = (
        ("draft", "草稿"),
        ("published", "已发布"),
        ("archived", "已归档"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="pages")
    name = models.CharField(max_length=200)
    path = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default="page")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    schema = models.JSONField(default=dict, blank=True)
    version = models.IntegerField(default=0)  # 草稿修订号，每次保存 schema +1
    schema_version = models.IntegerField(default=1)  # schema.schemaVersion
    thumbnail_url = models.CharField(max_length=500, blank=True, default="")
    current_version = models.ForeignKey(
        "pages.PageVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_pages"
        unique_together = (("app", "path"),)
        indexes = [models.Index(fields=["app", "status"])]

    def __str__(self):
        return f"{self.name}({self.path})"


class PageVersion(models.Model):
    """页面发布快照（不可变）。"""

    page = models.ForeignKey(Page, on_delete=models.CASCADE, related_name="versions")
    version = models.IntegerField()
    schema = models.JSONField()
    schema_version = models.IntegerField(default=1)
    publisher = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    published_at = models.DateTimeField(auto_now_add=True)
    changelog = models.TextField(blank=True, default="")

    class Meta:
        db_table = "wp_page_versions"
        ordering = ("-version",)
        unique_together = (("page", "version"),)

    def __str__(self):
        return f"{self.page_id} v{self.version}"


class Asset(models.Model):
    """页面资产（图片/文件/字体上传）。"""

    app = models.ForeignKey("appcore.App", null=True, blank=True, on_delete=models.SET_NULL, related_name="assets")
    name = models.CharField(max_length=300)
    url = models.CharField(max_length=500)
    type = models.CharField(max_length=20, default="file")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_assets"

    def __str__(self):
        return self.name
