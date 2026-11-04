"""应用级企业 SSO Provider 配置。

当前仅支持 OpenID Connect（authorization code + PKCE）。
- ``client_secret`` 落库加密（见 ``enterprise_sso.crypto``），且永不通过 API 返回。
- 校验规则集中在 ``enterprise_sso.validators``，模型 ``clean()`` 与序列化器共用。
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from enterprise_sso.crypto import EncryptedTextField
from enterprise_sso.validators import (
    DEFAULT_SCOPES,
    normalize_domains,
    normalize_scopes,
    validate_endpoint_url,
    validate_slug,
)

PROTOCOL_CHOICES = (("oidc", "OpenID Connect"),)
ROLE_CHOICES = (("viewer", "只读"), ("editor", "编辑"))
URL_FIELDS = ("issuer", "authorization_endpoint", "token_endpoint", "userinfo_endpoint")
REQUIRED_WHEN_ENABLED = (
    "issuer",
    "client_id",
    "client_secret",
    "authorization_endpoint",
    "token_endpoint",
    "userinfo_endpoint",
)


class SsoProvider(models.Model):
    """一个应用可配置多个 OIDC 身份提供方（如企业 IdP、Keycloak、Azure AD）。"""

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="sso_providers")
    name = models.CharField(max_length=160)
    slug = models.SlugField(max_length=64)
    protocol = models.CharField(max_length=20, choices=PROTOCOL_CHOICES, default="oidc")
    enabled = models.BooleanField(default=False)
    issuer = models.CharField(max_length=500, blank=True, default="")
    client_id = models.CharField(max_length=255, blank=True, default="")
    # 写接口可更新；读接口永不返回（序列化器 write_only + has_client_secret 摘要）。
    client_secret = EncryptedTextField(blank=True, default="")
    authorization_endpoint = models.CharField(max_length=500, blank=True, default="")
    token_endpoint = models.CharField(max_length=500, blank=True, default="")
    userinfo_endpoint = models.CharField(max_length=500, blank=True, default="")
    scopes = models.CharField(max_length=500, blank=True, default=DEFAULT_SCOPES)
    auto_create_user = models.BooleanField(default=True)
    default_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="viewer")
    allowed_email_domains = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_sso_providers"
        ordering = ("id",)
        unique_together = (("app", "slug"),)
        indexes = [models.Index(fields=["app", "enabled"], name="wp_sso_app_enabled_idx")]

    def __str__(self):
        return f"{self.app_id}/{self.slug}"

    @property
    def has_client_secret(self) -> bool:
        return bool(self.client_secret)

    @property
    def is_usable(self) -> bool:
        """启用且必填项齐备，才允许用于登录。"""
        if not self.enabled or self.protocol != "oidc":
            return False
        return all(str(getattr(self, field) or "").strip() for field in REQUIRED_WHEN_ENABLED)

    def clean(self):
        """模型级校验（DRF 序列化器复用同一套规则）。"""
        errors: dict[str, list[str]] = {}

        for field in URL_FIELDS:
            raw = getattr(self, field) or ""
            if not raw:
                continue
            try:
                setattr(self, field, validate_endpoint_url(raw))
            except ValidationError as exc:
                errors[field] = list(exc.messages)

        try:
            self.slug = validate_slug(self.slug)
        except ValidationError as exc:
            errors["slug"] = list(exc.messages)

        try:
            self.scopes = normalize_scopes(self.scopes)
        except ValidationError as exc:
            errors["scopes"] = list(exc.messages)

        try:
            self.allowed_email_domains = normalize_domains(self.allowed_email_domains)
        except ValidationError as exc:
            errors["allowed_email_domains"] = list(exc.messages)

        if self.default_role not in dict(ROLE_CHOICES):
            errors["default_role"] = ["default_role 只能是 viewer 或 editor"]

        if self.protocol not in dict(PROTOCOL_CHOICES):
            errors["protocol"] = ["目前仅支持 oidc 协议"]

        if self.enabled:
            for field in REQUIRED_WHEN_ENABLED:
                if not str(getattr(self, field) or "").strip():
                    errors.setdefault(field, []).append("启用 SSO 时该字段必填")

        if self.app_id and self.slug:
            duplicate = (
                SsoProvider.objects.filter(app_id=self.app_id, slug=self.slug)
                .exclude(pk=self.pk)
                .exists()
            )
            if duplicate:
                errors["slug"] = ["该应用下已存在同名 slug"]

        if errors:
            raise ValidationError(errors)
