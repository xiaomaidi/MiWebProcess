from datasources.executor import SECRET_PREFIX
from datasources.models import Datasource
from rest_framework import serializers


def _mask_config(config: dict) -> dict:
    """把编码后的密钥值替换为 `***` 占位。"""
    if not isinstance(config, dict):
        return config

    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, str) and value.startswith(SECRET_PREFIX):
            return "***"
        return value

    return walk(config)


class DatasourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Datasource
        fields = (
            "id",
            "app",
            "name",
            "type",
            "config",
            "transform",
            "status",
            "last_test_at",
            "last_error",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "app", "status", "last_test_at", "last_error", "created_by", "created_at", "updated_at")

    def to_representation(self, obj):
        data = super().to_representation(obj)
        data["config"] = _mask_config(data.get("config") or {})
        return data


class DatasourceQuerySerializer(serializers.Serializer):
    params = serializers.DictField(child=serializers.JSONField(), required=False, default=dict)
