"""AI Provider 解析与连接测试。"""
from __future__ import annotations

import json
import time
import urllib.request

from django.conf import settings

from ai.crypto import decrypt_secret, mask_key
from ai.models import AiProvider


def active_provider() -> AiProvider | None:
    return (
        AiProvider.objects.filter(enabled=True)
        .order_by("-is_default", "id")
        .first()
    )


def chat_config() -> dict:
    from wp_utils import validate_outbound_url

    provider = active_provider()
    if provider is not None:
        base_url = provider.base_url.rstrip("/")
        validate_outbound_url(base_url)
        return {
            "api_key": decrypt_secret(provider.api_key),
            "base_url": base_url,
            "model": provider.model,
            "timeout": provider.timeout or 90,
            "temperature": provider.temperature if provider.temperature is not None else 0.4,
            "provider_id": provider.id,
            "provider_name": provider.name,
            "provider_type": provider.provider_type,
            "source": "database",
        }
    base_url = str(getattr(settings, "AI_BASE_URL", "https://api.deepseek.com/v1")).rstrip("/")
    validate_outbound_url(base_url)
    return {
        "api_key": str(getattr(settings, "AI_API_KEY", "") or "").strip(),
        "base_url": base_url,
        "model": str(getattr(settings, "AI_MODEL", "deepseek-chat")),
        "timeout": 90,
        "temperature": 0.4,
        "provider_id": None,
        "provider_name": "环境变量",
        "provider_type": "env",
        "source": "environment",
    }


def is_configured() -> bool:
    cfg = chat_config()
    if cfg["source"] == "database":
        return bool(cfg["api_key"]) or cfg.get("provider_type") == "ollama"
    return bool(cfg["api_key"])


def status_payload() -> dict:
    cfg = chat_config()
    configured = is_configured()
    return {
        "configured": configured,
        "provider": cfg.get("provider_name") or "",
        "provider_type": cfg.get("provider_type") or "",
        "source": cfg.get("source") or "",
        "model": cfg.get("model") or "",
        "mode": "llm" if configured else "local",
        "provider_id": cfg.get("provider_id"),
    }


def provider_payload(provider: AiProvider) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "provider_type": provider.provider_type,
        "base_url": provider.base_url,
        "model": provider.model,
        "api_key": mask_key(provider.api_key),
        "has_api_key": bool(provider.api_key),
        "enabled": provider.enabled,
        "is_default": provider.is_default,
        "temperature": provider.temperature,
        "timeout": provider.timeout,
        "last_test_at": provider.last_test_at,
        "last_error": provider.last_error,
        "created_at": provider.created_at,
        "updated_at": provider.updated_at,
    }


def test_provider(provider: AiProvider) -> dict:
    cfg = {
        "api_key": decrypt_secret(provider.api_key),
        "base_url": provider.base_url.rstrip("/"),
        "model": provider.model,
        "timeout": min(30, provider.timeout or 30),
    }
    start = time.perf_counter()
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "max_tokens": 8,
        "temperature": 0,
    }
    headers = {"Content-Type": "application/json"}
    if cfg["api_key"]:
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
        latency = int((time.perf_counter() - start) * 1000)
        return {"ok": True, "message": content[:120] or "连接成功", "latency_ms": latency}
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - start) * 1000)
        return {"ok": False, "message": str(exc)[:500], "latency_ms": latency}
