from django.conf import settings
from django.db import models


class Page(models.Model):
    """页面：schema JSONB 为草稿；发布生成 PageVersion 不可变快照。"""

    TYPE_CHOICES = (
        ("page", "页面"),
        ("layout", "布局"),
        ("popup", "弹窗"),
        # 可复用区块的承载页面：不在运行时路由中直接访问，仅作为区块 schema 源。
        ("fragment", "区块片段"),
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


class PageBlock(models.Model):
    """可复用页面区块（共享布局的基础单元）。

    schema 源优先取 ``page``（type=fragment 的承载页面，路径 ``__blocks__/<code>``），
    这样区块可以直接在现有设计器中编辑；``schema`` 仅在没有承载页面时作为兜底源，
    保存格式为节点子树 ``{"rootId": str, "nodes": {id: node}}``。
    """

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="blocks")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=80)
    description = models.TextField(blank=True, default="")
    page = models.ForeignKey(
        Page,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="blocks",
        help_text="承载页面（type=fragment）；为空时使用 schema 字段",
    )
    schema = models.JSONField(default=dict, blank=True)
    version = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_page_blocks"
        ordering = ("-updated_at", "-id")
        unique_together = (("app", "code"),)
        indexes = [models.Index(fields=["app", "updated_at"])]

    def __str__(self):
        return f"{self.app_id}/{self.code}"


class PageBlockVersion(models.Model):
    """区块版本快照（不可变）。

    ``snapshot`` 只保存节点子树 ``{"rootId": str, "nodes": {id: node}}``；页面级
    ``meta`` / ``layout`` / ``variables`` 等不属于区块内容，回滚时以承载页面当前
    的同名元数据为基底合并，避免丢失页面设置。
    """

    block = models.ForeignKey(PageBlock, on_delete=models.CASCADE, related_name="versions")
    version = models.IntegerField()
    snapshot = models.JSONField(default=dict, blank=True)
    changelog = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_page_block_versions"
        ordering = ("-version",)
        unique_together = (("block", "version"),)

    def __str__(self):
        return f"{self.block_id} v{self.version}"


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
