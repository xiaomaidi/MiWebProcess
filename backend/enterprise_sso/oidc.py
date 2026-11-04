"""OIDC 协议实现：state、PKCE、授权 URL、令牌交换、userinfo、id_token 校验。

安全约定：
- 所有出站地址必须是 https，或本地开发用的 http://localhost / 127.0.0.1。
- 绝不把 code / access_token / refresh_token / id_token / client_secret 写入日志。
- state 使用 ``django.core.signing`` 签名（含时间戳，默认 10 分钟有效），并额外写入缓存
  以支持「一次性使用」；缓存不可用时仅依赖签名（跨 worker / 重启仍可校验）。
- PKCE 的 code_verifier 由 (SECRET_KEY, state) HMAC 派生，不在任何 URL 中出现。
- id_token 仅用于配置一致性校验（iss/aud/exp/nonce），身份信息一律来自 token_endpoint
  换取到的 access_token 调用 userinfo（服务端到服务端、TLS 保护）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, SignatureExpired, dumps, loads

from enterprise_sso.validators import DEFAULT_SCOPES, validate_endpoint_url

try:  # 优先使用 requests（requirements 未固定，但环境通常已安装）
    import requests as _requests
except Exception:  # pragma: no cover
    _requests = None

logger = logging.getLogger("enterprise_sso")

STATE_SALT = "enterprise_sso.oidc.state"
STATE_MAX_AGE = 600  # 10 分钟
TOKEN_TIMEOUT = (5, 10)  # (connect, read)
USERINFO_TIMEOUT = (5, 10)
#: 令牌交换允许的时钟偏差（id_token.exp）
_CLOCK_SKEW = 60


class SsoFlowError(Exception):
    """登录流程的「可安全展示」错误：只暴露 code 给前端，不含内部细节。"""

    default_messages = {
        "state_invalid": "登录状态无效，请重新发起登录",
        "state_expired": "登录状态已过期，请重新发起登录",
        "state_mismatch": "登录状态与应用不匹配，请重新发起登录",
        "provider_disabled": "该企业登录方式已停用",
        "provider_error": "身份提供方返回错误，请重试",
        "missing_code": "缺少授权码，请重新发起登录",
        "token_exchange_failed": "授权码校验失败，请重新发起登录",
        "userinfo_failed": "无法获取企业用户信息，请稍后再试",
        "userinfo_invalid": "企业用户信息不完整，请联系管理员",
        "issuer_mismatch": "身份提供方 issuer 校验失败",
        "audience_mismatch": "id_token 受众校验失败",
        "id_token_invalid": "id_token 解析失败",
        "id_token_expired": "id_token 已过期，请重新登录",
        "nonce_mismatch": "id_token nonce 校验失败",
        "email_missing": "企业账号未返回邮箱，无法登录",
        "email_unverified": "企业账号邮箱未验证，无法登录",
        "email_domain_not_allowed": "该邮箱域名不在允许范围内",
        "account_not_found": "账号不存在，请联系管理员开通",
        "account_disabled": "账号已被禁用",
        "app_login_disabled": "该应用已关闭登录",
        "network_error": "无法连接身份提供方，请稍后再试",
        "config_invalid": "SSO 配置不完整，请联系管理员",
        "server_error": "登录处理失败，请稍后再试",
    }

    def __init__(self, code: str, *, http_status: int = 400, detail: str = ""):
        self.code = code
        self.http_status = http_status
        self.detail = detail
        super().__init__(code)

    @property
    def message(self) -> str:
        return self.default_messages.get(self.code, "登录失败，请稍后再试")


class StateError(SsoFlowError):
    pass


def _cache_key(state: str) -> str:
    return "sso:state:" + hashlib.sha256(state.encode("utf-8")).hexdigest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def issue_state(record: dict) -> str:
    """生成签名 state，并在共享缓存中登记一次性标记（缓存不可用则仅用签名）。"""
    payload = dict(record or {})
    payload.update({"v": 1, "n": secrets.token_urlsafe(24), "iat": int(time.time())})
    token = dumps(payload, salt=STATE_SALT, compress=True)
    try:
        cache.set(_cache_key(token), payload["iat"], STATE_MAX_AGE)
    except Exception:
        logger.warning("sso.state.cache_set_failed")
    return token


def consume_state(state: str) -> dict:
    """校验 state 的签名与时效，返回载荷；缓存命中时删除标记（一次性使用）。"""
    raw = str(state or "").strip()
    if not raw or len(raw) > 4096:
        raise StateError("state_invalid")
    try:
        payload = loads(raw, salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except SignatureExpired as exc:
        raise StateError("state_expired") from exc
    except BadSignature as exc:
        raise StateError("state_invalid") from exc
    except Exception as exc:  # 非法 JSON / 编码错误
        raise StateError("state_invalid") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1:
        raise StateError("state_invalid")
    try:
        marker = cache.get(_cache_key(raw))
        if marker is None:
            # 其他 worker 已消费 / 缓存重启：签名有效即放行（授权码本身一次性）。
            logger.debug("sso.state.cache_miss")
        else:
            cache.delete(_cache_key(raw))
    except Exception:
        logger.warning("sso.state.cache_delete_failed")
    return payload


def derive_code_verifier(state: str) -> str:
    """由 (SECRET_KEY, state) 派生 PKCE code_verifier（无状态、不出现在 URL 中）。"""
    key = str(getattr(settings, "SECRET_KEY", "") or "").encode("utf-8")
    digest = hmac.new(key, f"sso-pkce:{state}".encode("utf-8"), hashlib.sha256).digest()
    return _b64url(digest)


def code_challenge_for(verifier: str) -> str:
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def assert_secure_endpoint(url: str, field: str = "endpoint") -> str:
    """出站地址二次校验（即使数据库被绕过写入也要拦住 http 明文端点）。"""
    try:
        return validate_endpoint_url(url, allow_blank=False)
    except ValidationError as exc:
        raise SsoFlowError("config_invalid", detail=f"{field}: {exc.messages[0]}") from exc


def build_authorize_url(
    provider,
    *,
    redirect_uri: str,
    state: str,
    nonce: str,
    code_challenge: str = "",
) -> str:
    base = assert_secure_endpoint(provider.authorization_endpoint, "authorization_endpoint")
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": redirect_uri,
        "scope": provider.scopes or DEFAULT_SCOPES,
        "state": state,
        "nonce": nonce,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    separator = "&" if urlparse(base).query else "?"
    return f"{base}{separator}{urlencode(params)}"


# ---------------------------------------------------------------- HTTP


def _parse_json(text: str) -> dict:
    try:
        data = json.loads(text or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _http_post_form(url: str, data: dict, *, timeout=TOKEN_TIMEOUT) -> tuple[int, dict]:
    """POST application/x-www-form-urlencoded → (status, json)，不跟随重定向。"""
    body = urlencode(data).encode("utf-8")
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    if _requests is not None:
        try:
            resp = _requests.post(
                url,
                data=data,
                headers={"Accept": "application/json"},
                timeout=timeout,
                allow_redirects=False,
            )
        except Exception as exc:  # requests.RequestException 等
            logger.warning("sso.http.post_failed url=%s error=%s", _safe_url(url), type(exc).__name__)
            raise SsoFlowError("network_error", http_status=502) from exc
        return int(resp.status_code), _parse_json(resp.text)

    request = Request(url, data=body, method="POST", headers=headers)
    try:
        with urlopen(request, timeout=timeout[1] if isinstance(timeout, tuple) else timeout) as resp:
            return int(getattr(resp, "status", 200)), _parse_json(
                resp.read().decode("utf-8", errors="replace")
            )
    except HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return int(exc.code), _parse_json(text)
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("sso.http.post_failed url=%s error=%s", _safe_url(url), type(exc).__name__)
        raise SsoFlowError("network_error", http_status=502) from exc


def _http_get_json(url: str, access_token: str, *, timeout=USERINFO_TIMEOUT) -> tuple[int, dict]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if _requests is not None:
        try:
            resp = _requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        except Exception as exc:
            logger.warning("sso.http.get_failed url=%s error=%s", _safe_url(url), type(exc).__name__)
            raise SsoFlowError("network_error", http_status=502) from exc
        return int(resp.status_code), _parse_json(resp.text)

    request = Request(url, method="GET", headers=headers)
    try:
        with urlopen(request, timeout=timeout[1] if isinstance(timeout, tuple) else timeout) as resp:
            return int(getattr(resp, "status", 200)), _parse_json(
                resp.read().decode("utf-8", errors="replace")
            )
    except HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return int(exc.code), _parse_json(text)
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("sso.http.get_failed url=%s error=%s", _safe_url(url), type(exc).__name__)
        raise SsoFlowError("network_error", http_status=502) from exc


def _safe_url(url: str) -> str:
    """日志用地址：去掉 query / fragment（可能含 code 等敏感参数）。"""
    try:
        parsed = urlparse(str(url or ""))
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return "?"


# ---------------------------------------------------------------- 令牌 / 声明


def exchange_code(
    provider,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str = "",
) -> dict:
    """用授权码换取令牌（client_secret_post），返回原始 token 响应。"""
    url = assert_secure_endpoint(provider.token_endpoint, "token_endpoint")
    secret = provider.client_secret or ""
    if not secret:
        raise SsoFlowError("config_invalid", detail="client_secret missing")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": secret,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    status, payload = _http_post_form(url, data)
    if status < 200 or status >= 300:
        # 只记录状态码；响应体可能含令牌/内部信息，不落日志。
        logger.warning("sso.token_exchange_failed app=%s provider=%s status=%s", provider.app_id, provider.slug, status)
        raise SsoFlowError("token_exchange_failed", http_status=502)
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        raise SsoFlowError("token_exchange_failed", http_status=502)
    return payload


def fetch_userinfo(provider, access_token: str) -> dict:
    url = assert_secure_endpoint(provider.userinfo_endpoint, "userinfo_endpoint")
    status, payload = _http_get_json(url, access_token)
    if status < 200 or status >= 300:
        logger.warning("sso.userinfo_failed app=%s provider=%s status=%s", provider.app_id, provider.slug, status)
        raise SsoFlowError("userinfo_failed", http_status=502)
    if not isinstance(payload, dict) or not str(payload.get("sub") or "").strip():
        raise SsoFlowError("userinfo_invalid")
    return payload


def decode_id_token(id_token: str) -> dict:
    """解析 JWT payload（不校验签名，仅用于 iss/aud/exp/nonce 一致性检查）。"""
    parts = str(id_token or "").split(".")
    if len(parts) != 3:
        raise SsoFlowError("id_token_invalid")
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        claims = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise SsoFlowError("id_token_invalid") from exc
    if not isinstance(claims, dict):
        raise SsoFlowError("id_token_invalid")
    return claims


def validate_id_token(provider, id_token: str, *, nonce: str = "") -> dict:
    claims = decode_id_token(id_token)
    configured = str(provider.issuer or "").strip()
    if configured:
        if str(claims.get("iss") or "").rstrip("/") != configured.rstrip("/"):
            raise SsoFlowError("issuer_mismatch")
    audience = claims.get("aud")
    audiences = [audience] if isinstance(audience, str) else list(audience or [])
    if provider.client_id not in audiences:
        raise SsoFlowError("audience_mismatch")
    expires = claims.get("exp")
    if isinstance(expires, (int, float)) and expires < time.time() - _CLOCK_SKEW:
        raise SsoFlowError("id_token_expired")
    returned_nonce = claims.get("nonce")
    if nonce and returned_nonce and not hmac.compare_digest(str(returned_nonce), str(nonce)):
        raise SsoFlowError("nonce_mismatch")
    return claims


def assert_issuer(provider, claims: dict) -> None:
    """userinfo 里若带 iss，必须与配置一致（部分 IdP 不返回，不影响流程）。"""
    configured = str(provider.issuer or "").strip()
    returned = str((claims or {}).get("iss") or "").strip()
    if configured and returned and returned.rstrip("/") != configured.rstrip("/"):
        raise SsoFlowError("issuer_mismatch")


def map_claims(claims: dict) -> dict:
    """userinfo → 平台用户字段（sub/email/name）。"""
    data = claims or {}
    email = str(data.get("email") or "").strip()
    given = str(data.get("given_name") or "").strip()
    family = str(data.get("family_name") or "").strip()
    name = str(data.get("name") or "").strip() or " ".join(part for part in (given, family) if part)
    username_hint = str(data.get("preferred_username") or "").strip()
    if not username_hint and email:
        username_hint = email.split("@", 1)[0]
    if not username_hint and name:
        username_hint = name
    return {
        "sub": str(data.get("sub") or "").strip(),
        "email": email,
        "email_verified": data.get("email_verified"),
        "name": name,
        "given_name": given,
        "family_name": family,
        "username_hint": username_hint,
    }
