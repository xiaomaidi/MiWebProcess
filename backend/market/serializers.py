from rest_framework import serializers

from .models import MarketItem


class MarketItemSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    source_app_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = MarketItem
        fields = (
            "id", "kind", "name", "slug", "description", "category", "tags",
            "preview", "payload", "status", "visibility", "source_app_id",
            "created_by", "installs", "created_at", "updated_at",
        )
