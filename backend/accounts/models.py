from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """自定义用户：username + email + is_staff；superuser 蕴含平台管理员。"""

    is_platform_admin = models.BooleanField(default=False)

    class Meta:
        db_table = "wp_users"
        verbose_name = "user"
        verbose_name_plural = "users"

    def save(self, *args, **kwargs):
        if self.is_superuser and not self.is_platform_admin:
            self.is_platform_admin = True
        super().save(*args, **kwargs)

    @property
    def is_platform(self) -> bool:
        return bool(self.is_superuser or self.is_platform_admin)

    def __str__(self):
        return self.username


class LoginLog(models.Model):
    """登录成功/失败记录，供平台管理员审计。"""

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="login_logs")
    username = models.CharField(max_length=150, blank=True, default="")
    success = models.BooleanField(default=False)
    reason = models.CharField(max_length=200, blank=True, default="")
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "wp_login_logs"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "created_at"])]

