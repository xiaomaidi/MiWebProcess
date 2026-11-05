"""市场组件代码签名与沙箱策略工具。

签名范围（canonical JSON，字段名排序、无多余空白、UTF-8）::

    {
      "schema": "wp-market-signing/v1",
      "kind": "component",
      "name": "...",
      "slug": "...",
      "sandboxed": true,
      "policy": {...规范化后的策略...},
      "source_url": "...",
      "element": "wp-widget-...",
      "payload": {...完整组件 payload...}
    }

- ``code_hash``：上述 canonical JSON 的 SHA-256 十六进制摘要。
- ``signature``：用 ``settings.MARKET_SIGNING_KEY`` 对该 canonical JSON 做
  HMAC-SHA256 的十六进制摘要。

密钥配置
--------
生产环境必须显式配置 ``MARKET_SIGNING_KEY``（建议 >= 32 字节随机值）：:

    MARKET_SIGNING_KEY=<random-secret>

若未配置，则回退到 ``settings.SECRET_KEY``。该回退仅用于开发/兼容旧部署；
轮换 ``SECRET_KEY`` 会让历史市场签名全部失效，且 SECRET_KEY 还承担
Django 会话等职责，不应作为长期签名密钥。签名密钥永远不会通过 API 返回。

签名不能替代源码审计：这里签名的是 ``source_url`` 与组件 schema，而不是
远端 ESM 文件的字节内容。远端 CDN 若原地替换文件，URL 不变则签名仍有效。
建议把构建产物放在不可变、内容寻址的 URL 下。
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import re
from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.exceptions import ValidationError

SIGNING_SCHEMA = "wp-market-signing/v1"
CODE_HASH_LENGTH = 64
SIGNATURE_LENGTH = 64
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_SOURCE_URL_LENGTH = 512  # 与 ComponentMeta.source_url(max_length=512) 对齐
MAX_POLICY_ORIGINS = 20
ELEMENT_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
HOST_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$", re.IGNORECASE)

DEFAULT_COMPONENT_POLICY = {
    "version": 1,
    "sandbox": True,
    "allow_scripts": True,
    "allow_same_origin": False,
    "allow_forms": False,
    "allow_popups": False,
    "network": "none",
    "allowed_origins": [],
    "timeout_ms": 10000,
}

_POLICY_NETWORKS = ("none", "allowlist")


def signing_key() -> bytes:
    """返回签名密钥字节；缺失时按文档回退 SECRET_KEY。"""
    key = str(getattr(settings, "MARKET_SIGNING_KEY", "") or "")
    if not key:
        key = str(getattr(settings, "SECRET_KEY", "") or "")
    if not key:
        raise ImproperlyConfigured(
            "MARKET_SIGNING_KEY 未配置且 SECRET_KEY 为空，无法签名市场组件"
        )
    return key.encode("utf-8")


def _json_safe(value):
    """把 JSONField 中的值递归转成可稳定序列化的 JSON 值。"""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValidationError({"payload": "payload 含非法浮点数"})
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return str(value)


def canonical_json(value) -> str:
    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _valid_host(host: str) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return bool(HOST_RE.match(host))


def _normalized_origin(parsed) -> str:
    """把 URL 归一化为 scheme://host[:port]；非法 host/port 抛 ValueError。"""
    if parsed.scheme not in ("http", "https"):
        raise ValueError("scheme")
    if parsed.username or parsed.password:
        raise ValueError("credentials")
    host = parsed.hostname or ""
    if not _valid_host(host):
        raise ValueError("host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("port") from exc
    host_text = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{host_text}" + (f":{port}" if port else "")


def normalize_policy(raw, *, kind: str = "component") -> dict:
    """校验并收紧沙箱策略。

    组件策略只允许调整 ``network`` / ``allowed_origins`` / ``timeout_ms``。
    任何试图开启 same-origin、表单、弹窗的字段都会被强制置为 False；
    iframe 端也固定使用 ``sandbox="allow-scripts"``。
    """
    if raw in (None, ""):
        raw = {}
    if not isinstance(raw, dict):
        raise ValidationError({"policy": "policy 必须是对象"})
    if kind != "component":
        # 区块不执行远端代码；保留任意 JSON 对象但不做安全承诺。
        if len(canonical_json(raw).encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValidationError({"policy": "policy 过大"})
        return _json_safe(raw)

    policy = dict(DEFAULT_COMPONENT_POLICY)
    network = str(raw.get("network") or "none").strip().lower()
    if network not in _POLICY_NETWORKS:
        raise ValidationError({"policy": "network 只能是 none 或 allowlist"})
    policy["network"] = network

    origins_raw = raw.get("allowed_origins") or []
    if not isinstance(origins_raw, list):
        raise ValidationError({"policy": "allowed_origins 必须是数组"})
    origins: list[str] = []
    for entry in origins_raw[:MAX_POLICY_ORIGINS]:
        origin = str(entry or "").strip()
        if not origin:
            continue
        parsed = urlparse(origin)
        try:
            normalized = _normalized_origin(parsed)
        except ValueError:
            raise ValidationError({"policy": f"allowed_origins 含非法来源：{origin[:80]}"})
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.params:
            raise ValidationError({"policy": f"allowed_origins 必须是纯 origin：{origin[:80]}"})
        if normalized not in origins:
            origins.append(normalized)
    policy["allowed_origins"] = origins

    timeout_raw = raw.get("timeout_ms", 10000)
    try:
        timeout_ms = int(timeout_raw)
    except (TypeError, ValueError):
        raise ValidationError({"policy": "timeout_ms 必须是整数"})
    policy["timeout_ms"] = max(1000, min(timeout_ms, 30000))

    # 这些是硬性安全边界，忽略/覆盖调用方输入。
    policy["version"] = 1
    policy["sandbox"] = True
    policy["allow_scripts"] = True
    policy["allow_same_origin"] = False
    policy["allow_forms"] = False
    policy["allow_popups"] = False
    return policy


def validate_source_url(value) -> str:
    source_url = str(value or "").strip()
    if not source_url:
        raise ValidationError({"payload": "组件 payload.source_url 必填（已构建的 ESM JS 地址）"})
    if len(source_url) > MAX_SOURCE_URL_LENGTH:
        raise ValidationError({"payload": "source_url 过长"})
    if "\\" in source_url or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in source_url):
        raise ValidationError({"payload": "source_url 含非法字符"})
    parsed = urlparse(source_url)
    if parsed.scheme:
        try:
            _normalized_origin(parsed)
        except ValueError:
            raise ValidationError({"payload": "source_url 只支持合法的 http(s) 地址或同源绝对路径"})
    else:
        if not source_url.startswith("/") or source_url.startswith("//"):
            raise ValidationError({"payload": "source_url 只支持 http(s) 绝对地址或同源绝对路径"})
    return source_url


def validate_element(value) -> str:
    element = str(value or "").strip()
    if not element:
        return ""
    if len(element) > 128 or not ELEMENT_RE.match(element):
        raise ValidationError({"payload": "element 必须是合法自定义元素名（小写字母/数字/连字符）"})
    if not element.startswith(("wp-market-", "wp-widget-")):
        raise ValidationError({"payload": "element 必须以 wp-market- 或 wp-widget- 开头"})
    return element


def element_for(payload: dict, slug: str) -> str:
    """组件安装时的自定义元素标签；显式 element 优先，否则按 slug 派生。"""
    explicit = validate_element(payload.get("element"))
    if explicit:
        return explicit
    derived = f"wp-market-{slug}".lower()
    derived = re.sub(r"[^a-z0-9-]", "-", derived)
    if not ELEMENT_RE.match(derived):
        derived = f"wp-market-{re.sub(r'[^a-z0-9]+', '-', derived).strip('-') or 'component'}"
    return derived


def validate_component_payload(payload: dict, *, require_source: bool = False) -> dict:
    """校验组件 payload 的结构/大小，返回原 payload。"""
    if not isinstance(payload, dict):
        raise ValidationError({"payload": "payload 必须是对象"})
    try:
        size = len(canonical_json(payload).encode("utf-8"))
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"payload": f"payload 无法序列化：{exc}"}) from exc
    if size > MAX_PAYLOAD_BYTES:
        raise ValidationError({"payload": "组件 payload 不能超过 256KB"})

    source_url = payload.get("source_url")
    if require_source or str(source_url or "").strip():
        validate_source_url(source_url)
    validate_element(payload.get("element"))

    for key in ("props_schema", "style_schema", "default_props", "payload_schema"):
        if key in payload and payload.get(key) is not None and not isinstance(payload.get(key), dict):
            raise ValidationError({"payload": f"{key} 必须是对象"})
    if "events" in payload and payload.get("events") is not None and not isinstance(payload.get("events"), list):
        raise ValidationError({"payload": "events 必须是数组"})
    if "accept_children" in payload and payload.get("accept_children") is not None and not isinstance(payload.get("accept_children"), list):
        raise ValidationError({"payload": "accept_children 必须是数组"})
    return payload


def signing_payload(item) -> dict:
    """构造参与签名的 canonical JSON 对象（仅安全/安装相关字段）。"""
    payload = item.payload if isinstance(item.payload, dict) else {}
    source_url = str(payload.get("source_url") or "").strip()
    try:
        element = element_for(payload, item.slug)
    except ValidationError:
        element = str(payload.get("element") or "").strip()
    return {
        "schema": SIGNING_SCHEMA,
        "kind": item.kind,
        "name": item.name,
        "slug": item.slug,
        "sandboxed": bool(item.sandboxed),
        "policy": item.policy or {},
        "source_url": source_url,
        "element": element,
        "payload": payload,
    }


def compute_hash_and_signature(item) -> tuple[str, str]:
    body = canonical_json(signing_payload(item)).encode("utf-8")
    code_hash = hashlib.sha256(body).hexdigest()
    signature = hmac.new(signing_key(), body, hashlib.sha256).hexdigest()
    return code_hash, signature


def sign_item(item, user):
    """计算并写入签名元数据（不保存）。调用方负责 save。"""
    code_hash, signature = compute_hash_and_signature(item)
    from django.utils import timezone

    item.code_hash = code_hash
    item.signature = signature
    item.signed_at = timezone.now()
    item.signer = user
    return item


def verify_item(item) -> tuple[bool, str]:
    """重算存储 payload 的签名；返回 (是否有效, 原因)。"""
    if not item.code_hash or not item.signature:
        return False, "组件未签名，不能安装"
    if len(item.code_hash) != CODE_HASH_LENGTH or len(item.signature) != SIGNATURE_LENGTH:
        return False, "签名格式不正确"
    try:
        expected_hash, expected_signature = compute_hash_and_signature(item)
    except Exception as exc:  # noqa: BLE001
        return False, f"签名校验失败：{type(exc).__name__}"
    if not hmac.compare_digest(str(item.code_hash), expected_hash):
        return False, "组件内容已被修改（code_hash 不匹配），请重新签名"
    if not hmac.compare_digest(str(item.signature), expected_signature):
        return False, "组件签名无效，请重新签名"
    return True, ""


def signing_metadata(item) -> dict:
    """可安全返回给客户端的签名元数据（绝不含签名密钥）。"""
    valid, reason = verify_item(item)
    return {
        "signed": bool(item.signature and item.code_hash and item.signed_at),
        "signature_valid": valid,
        "signature_error": "" if valid else reason,
        "code_hash": item.code_hash or "",
        "signature": item.signature or "",
        "signed_at": item.signed_at.isoformat() if item.signed_at else None,
        "signer": item.signer.username if item.signer_id and item.signer else "",
    }
