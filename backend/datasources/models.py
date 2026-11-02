from django.conf import settings
from django.db import models


class Datasource(models.Model):
    """数据源：rest / sql / static。secrets 以 base64+marker 存储。"""

    TYPE_CHOICES = (
        ("rest", "REST"),
        ("sql", "系统内置 SQL"),
        ("mysql", "MySQL"),
        ("postgres", "PostgreSQL"),
        ("sqlserver", "SQL Server"),
        ("static", "静态"),
        ("websocket", "WebSocket"),
    )
    STATUS_CHOICES = (
        ("active", "可用"),
        ("inactive", "停用"),
        ("error", "异常"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="datasources")
    name = models.CharField(max_length=200)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    config = models.JSONField(default=dict, blank=True)
    transform = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_datasources"
        unique_together = (("app", "name"),)

    def __str__(self):
        return f"{self.app_id}/{self.name}({self.type})"
