from rest_framework import serializers

from realtime.models import RealtimeChannel, RealtimeMessage


class RealtimeChannelSerializer(serializers.ModelSerializer):
    app_id = serializers.IntegerField(source="app.id", read_only=True)
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = RealtimeChannel
        fields = (
            "id", "app_id", "name", "slug", "kind", "topic", "description",
            "qos", "retain", "enabled", "message_count", "created_at", "updated_at",
        )
        read_only_fields = ("id", "app_id", "slug", "message_count", "created_at", "updated_at")

    def get_message_count(self, obj) -> int:
        return getattr(obj, "message_count", 0) or 0


class RealtimeMessageSerializer(serializers.ModelSerializer):
    channel_slug = serializers.CharField(source="channel.slug", read_only=True, default="")

    class Meta:
        model = RealtimeMessage
        fields = (
            "id", "app_id", "channel_id", "channel_slug", "topic", "payload",
            "direction", "transport", "sender", "created_at",
        )
        read_only_fields = fields
