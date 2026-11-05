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
    # 草稿 schema 的持久化修订号：与实时通道的临时 revision 分离，专门用于保存冲突检测。
    schema_revision = models.PositiveIntegerField(default=1)
    schema_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="最近一次保存草稿 schema 的用户（冲突提示用）",
    )
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


class PageSchemaOperationQuerySet(models.QuerySet):
    """操作日志只允许追加：禁止 ORM 批量更新 / 删除。"""

    def update(self, **kwargs):
        raise RuntimeError("PageSchemaOperation 是只追加日志，禁止更新")

    def delete(self):
        raise RuntimeError("PageSchemaOperation 是只追加日志，禁止删除")


class PageSchemaOperation(models.Model):
    """设计器 schema 操作日志（append-only，按 page + seq 单调排序）。

    每条记录是客户端生成、服务端校验后落库的节点级 CRDT 操作。``seq`` 由
    服务端在页面行锁内分配，保证同一页面内严格递增且唯一；``op`` 保存操作
    本身（``node.upsert`` / ``node.delete`` / ``schema.meta``），包含 Lamport
    clock。日志用于断线重放与审计，页面 ``Page.schema`` 仍是整页草稿快照。
    """

    page = models.ForeignKey(
        Page, on_delete=models.CASCADE, related_name="schema_operations"
    )
    seq = models.PositiveIntegerField()
    client_id = models.CharField(max_length=128)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="提交该操作的用户",
    )
    base_revision = models.PositiveIntegerField(
        default=0, help_text="客户端生成操作时基于的 Page.schema_revision"
    )
    op = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = PageSchemaOperationQuerySet.as_manager()

    class Meta:
        db_table = "wp_page_schema_operations"
        ordering = ("page_id", "seq")
        constraints = [
            models.UniqueConstraint(
                fields=("page", "seq"), name="uniq_page_schema_op_seq"
            )
        ]
        indexes = [
            models.Index(
                fields=("page", "created_at"), name="wp_page_schema_op_created_idx"
            )
        ]

    def save(self, *args, **kwargs):
        # 更新已有行会破坏 seq 的不可变语义；只允许首次插入。
        if self.pk is not None:
            raise RuntimeError("PageSchemaOperation 是只追加日志，禁止更新")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError("PageSchemaOperation 是只追加日志，禁止删除")

    def __str__(self):
        return f"page={self.page_id} seq={self.seq} {self.op.get('kind', '')}"


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
