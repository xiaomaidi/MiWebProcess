"""SSO 配置 API 的序列化器：client_secret 只写不读，其余校验复用模型 clean()。"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from enterprise_sso.models import SsoProvider

_WRITE_ONLY = ("client_secret",)
_READ_ONLY = ("id", "app_id", "has_client_secret", "created_at", "updated_at")


class SsoProviderSerializer(serializers.ModelSerializer):
    """应用编排者的配置视图。

    - ``client_secret``：write_only，可更新但永不回显；
    - ``has_client_secret``：只读摘要，供前端显示「已配置」；
    - 其余字段统一走 ``SsoProvider.clean()``，保证 API 与模型校验一致。
    """

    client_secret = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        max_length=1000,
    )
    has_client_secret = serializers.BooleanField(read_only=True)

    class Meta:
        model = SsoProvider
        fields = (
            "id",
            "app_id",
            "name",
            "slug",
            "protocol",
            "enabled",
            "issuer",
            "client_id",
            "client_secret",
            "has_client_secret",
            "authorization_endpoint",
            "token_endpoint",
            "userinfo_endpoint",
            "scopes",
            "auto_create_user",
            "default_role",
            "allowed_email_domains",
            "created_at",
            "updated_at",
        )
        read_only_fields = _READ_ONLY

    def validate(self, attrs):
        instance = self.instance
        merged: dict = {}
        for field in self.Meta.fields:
            if field in _WRITE_ONLY or field in _READ_ONLY:
                continue
            if field in attrs:
                merged[field] = attrs[field]
            elif instance is not None:
                merged[field] = getattr(instance, field)
            else:
                merged[field] = SsoProvider._meta.get_field(field).get_default()

        secret = attrs.get("client_secret", None)
        candidate = SsoProvider(**merged)
        candidate.pk = instance.pk if instance is not None else None
        candidate.app = getattr(instance, "app", None) or self.context.get("app")
        if instance is not None and not secret:
            # PATCH 未传/传空 → 保留原 secret（不覆盖、不回显）
            candidate.client_secret = instance.client_secret
        else:
            candidate.client_secret = secret or ""

        try:
            candidate.clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc

        # clean() 会规范化 slug / scopes / 域名 / URL，写回 validated_data
        for field in (
            "slug",
            "issuer",
            "authorization_endpoint",
            "token_endpoint",
            "userinfo_endpoint",
            "scopes",
            "allowed_email_domains",
        ):
            if field in merged:
                attrs[field] = getattr(candidate, field)

        if not secret:
            attrs.pop("client_secret", None)
        return attrs


class PublicSsoProviderSerializer(serializers.ModelSerializer):
    """登录页可见的最小信息：只有 id / name / slug。"""

    class Meta:
        model = SsoProvider
        fields = ("id", "name", "slug")
