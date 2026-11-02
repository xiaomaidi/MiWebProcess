"""实时通道：MQTT 主题 ↔ 应用 WebSocket 房间的映射与消息留存。"""
from django.conf import settings
from django.db import models


class RealtimeChannel(models.Model):
    """应用内的一条实时通道。

    - ``mqtt``：消息经 MQTT Broker 收发（需要 paho-mqtt 与 MQTT_BROKER_URL）；
    - ``ws``：仅走平台 WebSocket 房间；
    - ``both``：同时走 MQTT 与 WebSocket。
    """

    KIND_CHOICES = (
        ("mqtt", "MQTT"),
        ("ws", "WebSocket"),
        ("both", "MQTT + WebSocket"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="realtime_channels")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, default="")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default="both")
    topic = models.CharField(max_length=200, help_text="MQTT 主题过滤器，如 devices/+/telemetry")
    description = models.CharField(max_length=300, blank=True, default="")
    qos = models.IntegerField(default=0)
    retain = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_realtime_channels"
        unique_together = (("app", "slug"),)
        ordering = ("id",)
        indexes = [models.Index(fields=["app", "enabled"])]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = str(self.name or "channel").strip().lower()
            self.slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in base)[:80] or f"channel-{self.pk or ''}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.app_id}/{self.slug}({self.topic})"


class RealtimeMessage(models.Model):
    """最近消息（默认保留 500 条/应用，由清理命令裁剪）。"""

    DIRECTION_CHOICES = (
        ("in", "接收"),
        ("out", "发送"),
    )

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="realtime_messages")
    channel = models.ForeignKey(
        RealtimeChannel, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    topic = models.CharField(max_length=200, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    direction = models.CharField(max_length=8, choices=DIRECTION_CHOICES, default="out")
    transport = models.CharField(max_length=10, default="ws")
    sender = models.CharField(max_length=120, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_realtime_messages"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["app", "-created_at"]), models.Index(fields=["channel", "-created_at"])]

    def __str__(self):
        return f"{self.topic} {self.direction}"
