from django.contrib import admin

from realtime.models import RealtimeChannel, RealtimeMessage


@admin.register(RealtimeChannel)
class RealtimeChannelAdmin(admin.ModelAdmin):
    list_display = ("id", "app", "name", "kind", "topic", "enabled")
    list_filter = ("kind", "enabled", "app")
    search_fields = ("name", "slug", "topic")


@admin.register(RealtimeMessage)
class RealtimeMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "app", "topic", "direction", "transport", "sender", "created_at")
    list_filter = ("direction", "transport", "app")
    search_fields = ("topic",)
