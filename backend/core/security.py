"""平台级安全配置读取：环境变量默认，数据库界面覆盖。"""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache

CACHE_KEY = "security_settings_v1"


def get_security_config() -> dict:
    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    env_hosts = list(getattr(settings, "SSRF_ALLOWED_HOSTS", []) or [])
    env_private = bool(getattr(settings, "SSRF_ALLOW_PRIVATE", False))
    config = {"ssrf_allowed_hosts": env_hosts, "ssrf_allow_private": env_private, "source": "env"}
    try:
        from core.models import SecuritySetting

        row = SecuritySetting.objects.order_by("id").first()
        if row is not None:
            config = {
                "ssrf_allowed_hosts": list(row.ssrf_allowed_hosts or []),
                "ssrf_allow_private": bool(row.ssrf_allow_private),
                "source": "database",
            }
    except Exception:
        # 迁移完成前或数据库不可用时使用环境变量。
        pass
    cache.set(CACHE_KEY, config, 30)
    return config


def clear_security_cache() -> None:
    cache.delete(CACHE_KEY)
