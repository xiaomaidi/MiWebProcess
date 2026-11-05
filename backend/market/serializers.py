from rest_framework import serializers

from .models import MarketItem
from .signing import signing_metadata


class MarketItemSerializer(serializers.ModelSerializer):
    created_by = serializers.CharField(source="created_by.username", read_only=True)
    source_app_id = serializers.IntegerField(read_only=True)
    signer = serializers.SerializerMethodField()
    signed = serializers.SerializerMethodField()
    signature_valid = serializers.SerializerMethodField()
    signature_error = serializers.SerializerMethodField()

    class Meta:
        model = MarketItem
        fields = (
            "id", "kind", "name", "slug", "description", "category", "tags",
            "preview", "payload", "status", "visibility", "source_app_id",
            "created_by", "installs", "created_at", "updated_at",
            # 签名/沙箱元数据（绝不返回签名密钥）
            "code_hash", "signature", "signed_at", "signer",
            "sandboxed", "policy", "signed", "signature_valid", "signature_error",
        )

    def _meta(self, obj: MarketItem) -> dict:
        cache = self.context.setdefault("_signing_meta", {})
        if obj.pk not in cache:
            cache[obj.pk] = signing_metadata(obj)
        return cache[obj.pk]

    def get_signed(self, obj: MarketItem) -> bool:
        return bool(self._meta(obj)["signed"])

    def get_signer(self, obj: MarketItem) -> str:
        return str(self._meta(obj)["signer"] or "")

    def get_signature_valid(self, obj: MarketItem) -> bool:
        return bool(self._meta(obj)["signature_valid"])

    def get_signature_error(self, obj: MarketItem) -> str:
        return str(self._meta(obj)["signature_error"])
