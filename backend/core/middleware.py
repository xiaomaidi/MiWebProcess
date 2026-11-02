"""全 API 敏感字段脱敏中间件。

字段级的数据模型脱敏仍由 datamodels.visible_data 负责；这里兜底
所有 JSON 响应中的密码、密钥、token 等敏感键，避免新增接口遗忘。
"""
from __future__ import annotations

import json

SENSITIVE_KEYS = {
    "password",
    "passwd",
    "password_hash",
    "secret",
    "client_secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "private_key",
    "authorization",
}
AUTH_PATHS = (
    "/api/auth/token/",
    "/api/auth/login/",
    "/api/auth/refresh/",
    "/api/auth/register/",
)


def _scrub(value):
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                out[key] = "***"
            else:
                out[key] = _scrub(item)
        return out
    return value


class SensitiveDataMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(AUTH_PATHS):
            return response
        if response.status_code >= 400:
            return response
        content_type = response.get("Content-Type", "")
        if "application/json" not in content_type:
            return response
        if getattr(response, "streaming", False):
            return response
        try:
            payload = json.loads(response.content.decode("utf-8"))
            cleaned = _scrub(payload)
            body = json.dumps(cleaned, ensure_ascii=False).encode("utf-8")
            response.content = body
            response["Content-Length"] = str(len(body))
        except Exception:
            # 不因为脱敏失败破坏正常响应；字段级脱敏仍在前置服务执行。
            return response
        return response
