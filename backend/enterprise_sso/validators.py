"""SSO 配置校验工具：URL（https / localhost）、scope、域名白名单、slug。

模型 ``SsoProvider.clean()`` 与 API 序列化器共用同一套规则，保证「后台能存的
配置 = 登录流程能安全使用的配置」。
"""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

from django.core.exceptions import ValidationError

DEFAULT_SCOPES = "openid profile email"

# 仅这些主机名允许使用 http://（本地开发的自建 IdP）。
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain", "::1", "[::1]"}
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")
_DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")
_SCOPE_RE = re.compile(r"^[A-Za-z0-9._:\-/]{1,100}$")
_MAX_URL_LEN = 500


def is_loopback_host(host: str) -> bool:
    """判断主机名是否为回环地址（localhost / 127.0.0.0/8 / ::1）。"""
    name = str(host or "").strip().lower().rstrip(".")
    if not name:
        return False
    if name in _LOCAL_HOSTNAMES:
        return True
    try:
        ip = ipaddress.ip_address(name.strip("[]"))
    except ValueError:
        return False
    return ip.is_loopback


def _reject_unsafe_ip(host: str) -> None:
    """拒绝内网 / 链路本地 / 保留 IP 字面量，降低 SSRF 风险。

    只对「IP 字面量」生效；域名解析层面的内网指向由部署侧出口策略兜底。
    """
    raw = str(host or "").strip().strip("[]")
    try:
        ip = ipaddress.ip_address(raw)
    except ValueError:
        return
    if ip.is_loopback:
        return
    if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        raise ValidationError("禁止使用内网 / 链路本地 / 保留地址")


def validate_endpoint_url(value, *, allow_blank: bool = True) -> str:
    """校验 OIDC 端点：必须 https，或本地开发用的 http://localhost / 127.0.0.1。"""
    raw = str(value or "").strip()
    if not raw:
        if allow_blank:
            return ""
        raise ValidationError("该地址必填")
    if len(raw) > _MAX_URL_LEN:
        raise ValidationError(f"地址过长（最多 {_MAX_URL_LEN} 字符）")
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise ValidationError("仅支持 https:// 地址（本地 localhost 可用 http://）")
    if not parsed.hostname:
        raise ValidationError("地址缺少主机名")
    if parsed.username or parsed.password:
        raise ValidationError("地址不能包含用户名或密码")
    if parsed.fragment:
        raise ValidationError("地址不能包含 # 片段")
    host = parsed.hostname
    if parsed.scheme == "http" and not is_loopback_host(host):
        raise ValidationError("非 localhost 地址必须使用 https://")
    _reject_unsafe_ip(host)
    return raw


def validate_slug(value) -> str:
    slug = str(value or "").strip().lower()
    if not slug:
        raise ValidationError("slug 必填")
    if not _SLUG_RE.match(slug):
        raise ValidationError("slug 只能包含小写字母、数字、- 和 _，且以字母或数字开头/结尾")
    return slug


def normalize_scopes(value) -> str:
    """规范 scope 字符串：空格分隔、去重、必须包含 openid。"""
    if isinstance(value, (list, tuple)):
        parts = [str(item or "").strip() for item in value]
    else:
        parts = str(value or "").replace(",", " ").split()
    out: list[str] = []
    for item in parts:
        if not item:
            continue
        if not _SCOPE_RE.match(item):
            raise ValidationError(f"scope 含非法字符：{item}")
        if item not in out:
            out.append(item)
    if "openid" not in out:
        out.insert(0, "openid")
    return " ".join(out) or DEFAULT_SCOPES


def normalize_domains(value) -> list[str]:
    """邮箱域名白名单：数组或逗号分隔字符串 → 去重的小写域名数组（不支持通配符）。"""
    if value in (None, ""):
        return []
    if isinstance(value, str):
        items = [part for part in re.split(r"[,\s]+", value) if part]
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise ValidationError("allowed_email_domains 必须是域名数组")
    out: list[str] = []
    for item in items:
        domain = str(item or "").strip().lower().lstrip("@").rstrip(".")
        if not domain:
            continue
        if "*" in domain:
            raise ValidationError("allowed_email_domains 不支持通配符")
        if not _DOMAIN_RE.match(domain):
            raise ValidationError(f"非法邮箱域名：{item}")
        if domain not in out:
            out.append(domain)
    return out


def email_domain_allowed(email: str, domains: list[str]) -> bool:
    """邮箱是否落在白名单域名内（包含子域名）。"""
    if not domains:
        return True
    address = str(email or "").strip().lower()
    if "@" not in address:
        return False
    domain = address.rsplit("@", 1)[1].strip().rstrip(".")
    if not domain:
        return False
    for item in domains:
        allowed = str(item or "").lower().strip()
        if not allowed:
            continue
        if domain == allowed or domain.endswith("." + allowed):
            return True
    return False
