"""诊断 Channels Channel Layer 配置（输出不包含密码/密钥）。

用法：
    python manage.py check_realtime_channels
    python manage.py check_realtime_channels --ping
    python manage.py check_realtime_channels --ping --timeout 5
"""
from __future__ import annotations

import re
import time
from importlib.metadata import PackageNotFoundError, version
from importlib.util import find_spec
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

REDIS_BACKEND = "channels_redis.core.RedisChannelLayer"
LEGACY_REDIS_BACKEND = "channels.layers.RedisChannelLayer"

_SENSITIVE_QUERY_KEYS = {
    "password",
    "passwd",
    "pass",
    "token",
    "secret",
    "auth",
    "apikey",
    "api_key",
}
_USERINFO_WITH_PASSWORD_RE = re.compile(r"(?i)(rediss?://[^:/@\s]+:)[^@\s]+@")


def mask_host(host) -> str:
    """遮蔽 hosts 中的密码，保留主机/端口/db 便于排查。支持 URL 与 tuple。"""
    if isinstance(host, str):
        try:
            parts = urlsplit(host)
        except ValueError:
            return "***"
        netloc = parts.netloc
        if "@" in netloc:
            userinfo, _, hostport = netloc.rpartition("@")
            if ":" in userinfo:
                username = userinfo.split(":", 1)[0]
                netloc = f"{username}:***@{hostport}" if username else f"***@{hostport}"
            # 只有用户名、没有密码时保留原样（用户名本身不是密钥）。
        query_pairs = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in _SENSITIVE_QUERY_KEYS:
                value = "***"
            query_pairs.append((key, value))
        return urlunsplit(
            (
                parts.scheme,
                netloc,
                parts.path,
                urlencode(query_pairs, doseq=True, safe="*"),
                parts.fragment,
            )
        )
    if isinstance(host, (tuple, list)):
        # channels_redis 可能接受 (host, port[, db[, password]])；第 4 项起一律遮蔽。
        if len(host) >= 4:
            return ":".join([str(host[0]), str(host[1]), str(host[2]), "***"])
        return ":".join(str(item) for item in host)
    return "***"


def sanitize_error(exc: BaseException, raw_url: str) -> str:
    """移除异常文本中的 Redis 密码（含 URL 编码形式），避免日志泄露。"""
    text = str(exc).strip() or exc.__class__.__name__
    try:
        password = urlsplit(raw_url).password
    except ValueError:
        password = None
    if password:
        text = text.replace(password, "***")
        decoded = unquote(password)
        if decoded and decoded != password:
            text = text.replace(decoded, "***")
    return _USERINFO_WITH_PASSWORD_RE.sub(r"\1***@", text)


def package_version(distribution: str) -> str | None:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return None


def module_available(module: str) -> bool:
    try:
        return find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def redis_version_tuple(value: str) -> tuple[int, ...]:
    """把 '7.2.4' 之类的版本号转为 tuple，用于版本比较。"""
    parts = []
    for piece in str(value or "").split("."):
        digits = "".join(char for char in piece if char.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


class Command(BaseCommand):
    help = "检查实时 Channel Layer 配置；--ping 可选探测 Redis 连通性（自动脱敏）"

    def add_arguments(self, parser):
        parser.add_argument("--ping", action="store_true", help="Ping 所有已配置的 Redis host")
        parser.add_argument(
            "--timeout",
            type=float,
            default=3.0,
            help="Ping 连接/读取超时秒数（默认 3）",
        )

    def handle(self, *args, **options):
        layers = getattr(settings, "CHANNEL_LAYERS", None) or {}
        layer_config = layers.get("default") if isinstance(layers, dict) else None
        if not isinstance(layer_config, dict):
            layer_config = {}
        backend = str(layer_config.get("BACKEND") or "")
        config = layer_config.get("CONFIG") or {}
        if not isinstance(config, dict):
            config = {}
        hosts = config.get("hosts") or []
        if isinstance(hosts, str):
            hosts = [hosts]
        is_redis = "RedisChannelLayer" in backend
        is_in_memory = "InMemoryChannelLayer" in backend

        if is_redis:
            mode = "redis (groups shared across ASGI workers)"
        elif is_in_memory:
            mode = "in-memory (single ASGI process only; not for multi-worker)"
        else:
            mode = "custom/unknown (verify cross-worker behavior)"

        self.stdout.write("Realtime channel layer")
        self.stdout.write(f"  backend : {backend or '(not configured)'}")
        self.stdout.write(f"  mode    : {mode}")

        if is_redis:
            if backend == LEGACY_REDIS_BACKEND:
                self.stdout.write(
                    self.style.WARNING(
                        "  warning : channels.layers.RedisChannelLayer was removed in Channels 4; "
                        f"use {REDIS_BACKEND}"
                    )
                )
            self.stdout.write("  hosts   :")
            if hosts:
                for host in hosts:
                    self.stdout.write(f"    - {mask_host(host)}")
            else:
                self.stdout.write("    (none configured)")
            self.stdout.write(f"  capacity: {config.get('capacity', '(channels_redis default)')}")
            self.stdout.write(f"  expiry  : {config.get('expiry', '(channels_redis default)')}s")
        else:
            self.stdout.write("  hosts   : (none; no external broker)")

        channels_redis_version = package_version("channels-redis")
        redis_version = package_version("redis")
        deps = {
            "channels_redis": module_available("channels_redis"),
            "redis": module_available("redis"),
        }
        self.stdout.write(
            "  deps    : "
            f"channels_redis={channels_redis_version or ('importable' if deps['channels_redis'] else 'NOT INSTALLED')}, "
            f"redis={redis_version or ('importable' if deps['redis'] else 'NOT INSTALLED')}"
        )

        if is_redis and not deps["channels_redis"]:
            self.stdout.write(
                self.style.WARNING(
                    "  warning : channels_redis is not installed; WebSocket connections will "
                    "fail until it is installed. Install: pip install 'channels_redis>=4.3,<5.0'"
                )
            )
        if is_redis and not deps["redis"]:
            self.stdout.write(
                self.style.WARNING(
                    "  warning : redis is not installed. Install: pip install 'redis>=5.0'"
                )
            )

        if options.get("ping"):
            self._ping(hosts, is_redis=is_redis, timeout=options.get("timeout", 3.0))

    def _ping(self, hosts, *, is_redis: bool, timeout) -> None:
        if not is_redis:
            self.stdout.write(
                self.style.WARNING("Ping skipped: channel layer is not Redis-backed.")
            )
            return
        if not hosts:
            raise CommandError(
                "Ping failed: no Redis hosts configured in CHANNEL_LAYERS['default']['CONFIG']['hosts']."
            )
        try:
            import redis
        except ImportError as exc:
            raise CommandError(
                "Ping failed: Python package 'redis' is not installed (pip install 'redis>=5.0')."
            ) from exc

        try:
            timeout = float(timeout)
        except (TypeError, ValueError):
            timeout = 3.0
        if timeout <= 0:
            timeout = 3.0

        failures = 0
        for host in hosts:
            if not isinstance(host, str) or "://" not in host:
                self.stdout.write(
                    self.style.WARNING(
                        f"  PING {mask_host(host)} skipped: only redis:// / rediss:// URLs are supported"
                    )
                )
                continue
            label = mask_host(host)
            client = None
            started = time.monotonic()
            try:
                # 健康检查用 RESP2：Redis 5 等旧版本不支持 RESP3 的 HELLO，仍可安全 PING。
                client = redis.from_url(
                    host,
                    socket_connect_timeout=timeout,
                    socket_timeout=timeout,
                    protocol=2,
                )
                client.ping()
                elapsed_ms = (time.monotonic() - started) * 1000
                self.stdout.write(self.style.SUCCESS(f"  PING {label} OK ({elapsed_ms:.1f} ms)"))
                server_version = ""
                try:
                    info = client.info("server")
                    if isinstance(info, dict):
                        server_version = str(info.get("redis_version") or "")
                except Exception:  # noqa: BLE001 - INFO 可能被 ACL 禁止，忽略
                    server_version = ""
                if server_version:
                    self.stdout.write(f"  server  : Redis {server_version}")
                    if redis_version_tuple(server_version) < (6, 0):
                        self.stdout.write(
                            self.style.WARNING(
                                "  warning : Redis < 6 does not support RESP3 (HELLO); "
                                "channels_redis 4.3 may fail until Redis is upgraded (recommend 7.x)."
                            )
                        )
            except Exception as exc:  # noqa: BLE001 - 健康检查需要报告任意连接错误
                failures += 1
                self.stderr.write(
                    self.style.ERROR(f"  PING {label} FAILED: {sanitize_error(exc, host)}")
                )
            finally:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:  # noqa: BLE001 - 关闭失败不影响诊断结果
                        pass

        if failures:
            raise CommandError(f"Ping failed for {failures} Redis host(s).")
