from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """审计日志：谁在何时对哪个对象做了什么。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    username = models.CharField(max_length=150, blank=True, default="")
    app = models.ForeignKey("appcore.App", on_delete=models.SET_NULL, null=True, blank=True, related_name="audit_logs")
    object_type = models.CharField(max_length=100)
    object_id = models.CharField(max_length=100, blank=True, default="")
    action = models.CharField(max_length=50)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_audit_logs"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["app", "object_type", "object_id"]),
            models.Index(fields=["user", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.username} {self.action} {self.object_type}:{self.object_id}"
