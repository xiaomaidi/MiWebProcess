from django.conf import settings
from django.db import models


FIELD_TYPES = (
    "string", "longtext", "richtext", "email", "phone", "url", "password",
    "select", "multiselect", "tags",
    "number", "integer", "decimal", "money", "percent",
    "boolean", "date", "datetime", "time", "duration",
    "json", "reference", "references",
    "image", "file", "attachments", "user", "department",
    "auto_number", "formula", "created_at", "updated_at",
    "geolocation", "signature", "barcode", "rating", "color",
)

# 数据范围：全部 / 仅本人 / 本部门 / 本部门及子部门
DATA_SCOPES = ("all", "owner", "dept", "dept_and_children")


class DataModel(models.Model):
    """数据模型：fields JSONB 描述字段结构。"""

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="datamodels")
    name = models.CharField(max_length=100)
    fields = models.JSONField(default=list, blank=True)
    indexes = models.JSONField(default=list, blank=True)
    # 允许运行时公开读取（内容门户 / 公开 API）；默认关闭，写操作始终需要成员权限。
    is_public = models.BooleanField(default=False)
    # 行级数据权限：指定字段后，非管理员只能看到该字段等于自己的记录。
    row_owner_field = models.CharField(max_length=80, blank=True, default="")
    workflow_definition_id = models.IntegerField(null=True, blank=True)
    data_scope = models.CharField(max_length=20, default="all")
    # 部门数据范围：记录中哪个字段保存部门（id / code / name 均可匹配）
    dept_field = models.CharField(max_length=80, blank=True, default="dept")
    action_roles = models.JSONField(default=dict, blank=True)
    # 内容审核：开启后编辑提交需审核人通过才能发布
    review_required = models.BooleanField(default=False)
    review_roles = models.JSONField(default=list, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_data_models"
        unique_together = (("app", "name"),)

    def __str__(self):
        return f"{self.app_id}/{self.name}"

    def field_map(self) -> dict:
        return {f.get("name"): f for f in (self.fields or []) if isinstance(f, dict)}


class ReportSubscription(models.Model):
    """报表订阅配置：保存分组/指标/筛选和频率；实际推送通道可后续接入。"""

    FREQUENCY_CHOICES = (
        ("daily", "每日"),
        ("weekly", "每周"),
        ("monthly", "每月"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="report_subscriptions")
    model = models.ForeignKey(DataModel, on_delete=models.CASCADE, related_name="report_subscriptions")
    name = models.CharField(max_length=160)
    config = models.JSONField(default=dict, blank=True)
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default="weekly")
    recipients = models.CharField(max_length=500, blank=True, default="")
    enabled = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_report_subscriptions"
        unique_together = (("app", "name"),)

    def __str__(self):
        return f"{self.app_id}/{self.name}"


class DataRecord(models.Model):
    """数据记录：data JSONB。"""

    model = models.ForeignKey(DataModel, on_delete=models.CASCADE, related_name="records")
    data = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # 公开编辑凭证吊销：吊销后旧签名 token 不能再改/删该记录。
    public_token_revoked = models.BooleanField(default=False)

    class Meta:
        db_table = "wp_data_records"
        ordering = ("-id",)

    def __str__(self):
        return f"{self.model_id}#{self.id}"
