from django.conf import settings
from django.db import models


class SecuritySetting(models.Model):
    """平台级安全设置（单例 id=1）。环境变量作为默认值，界面保存后覆盖。"""

    ssrf_allowed_hosts = models.JSONField(default=list, blank=True)
    ssrf_allow_private = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_security_settings"
