from django.conf import settings
from django.db import models


class Release(models.Model):
    """发布：app 的 bundle 快照版本。"""

    STATUS_CHOICES = (
        ("pending", "待发布"),
        ("releasing", "发布中"),
        ("active", "生效"),
        ("rollback", "已回滚"),
        ("failed", "失败"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="releases")
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    traffic_ratio = models.PositiveIntegerField(default=100)
    previous_release = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="next_releases",
    )
    bundle_url = models.CharField(max_length=500, blank=True, default="")
    page_versions = models.JSONField(default=dict, help_text="{page_id: page_version_id}")
    error = models.TextField(blank=True, default="")
    changelog = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_releases"
        unique_together = (("app", "version"),)
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.app.code} v{self.version}({self.status})"


class ReleaseTask(models.Model):
    """发布任务执行记录。"""

    STATUS_CHOICES = (
        ("pending", "待执行"),
        ("running", "执行中"),
        ("done", "完成"),
        ("failed", "失败"),
    )

    release = models.ForeignKey(Release, on_delete=models.CASCADE, related_name="tasks")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    log = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_release_tasks"

    def __str__(self):
        return f"release {self.release_id} {self.status}"
