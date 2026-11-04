"""企业运维控制台 API：平台总览 + 系统备份。

新增模块，不修改任何既有视图/模型/迁移。挂载方式（由集成者修改 config/urls.py）：

    path("api/enterprise/", include("core.enterprise_urls")),

设计约束：
- 仅平台管理员（is_staff / is_superuser / is_platform_admin）可访问；
- 总览中的统计全部使用数据库聚合（COUNT），最近列表一律 LIMIT；
- 媒体目录扫描有文件数与耗时上限，并缓存 60 秒；
- 可选服务（缓存 / Celery broker）不可用时只返回状态字段，不影响接口本身；
- 备份目录可配置，接口只暴露文件名，不接受客户端传入路径。
"""
from __future__ import annotations

import logging
import os
import socket
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlparse

import django
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.db import connection
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from core.audit import write_audit_log

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量
RECENT_LIMIT = 10
FAILURE_LIMIT = 5
RECENT_RELEASES_LIMIT = 5
MAX_BACKUP_LIST = 200
BACKUP_LIST_TIMEOUT_SECONDS = 1.5
MEDIA_SCAN_MAX_FILES = 50_000
MEDIA_SCAN_MAX_SECONDS = 2.0
HEALTH_SOCKET_TIMEOUT = 0.8

DEFAULT_MAX_DB_BYTES = 4 * 1024 ** 3  # 4 GiB
DEFAULT_MAX_MEDIA_BYTES = 2 * 1024 ** 3  # 2 GiB

ALLOWED_BACKUP_SUFFIXES = {".zip", ".sqlite3", ".db", ".dump", ".json", ".gz"}
SYSTEM_BACKUP_SUFFIXES = {".zip", ".sqlite3", ".db", ".dump", ".gz"}

_BACKUP_LOCK = threading.Lock()
_STORAGE_CACHE_SECONDS = 60


# ---------------------------------------------------------------- 权限
class IsEnterpriseAdmin(BasePermission):
    """平台管理员：DRF IsAdminUser（is_staff）的超集，兼容项目内的平台管理员标记。"""

    message = "仅平台管理员（staff / superuser / platform_admin）可访问企业运维控制台"

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return bool(
            getattr(user, "is_superuser", False)
            or getattr(user, "is_platform_admin", False)
            or getattr(user, "is_staff", False)
        )


# ---------------------------------------------------------------- 通用工具
def _truncate(value, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _iso(value) -> str | None:
    if value is None:
        return None
    try:
        return timezone.localtime(value).isoformat() if timezone.is_aware(value) else value.isoformat()
    except (ValueError, AttributeError, OverflowError):
        return None


def _human_bytes(value) -> str | None:
    if value is None:
        return None
    try:
        size = float(value)
    except (TypeError, ValueError):
        return None
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return None


def _settings_int(name: str, default: int) -> int:
    raw = getattr(settings, name, None)
    if raw is None:
        raw = os.environ.get(name)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _section(builder, fallback: dict) -> dict:
    """可选统计分区：单块失败不影响整个总览。"""
    try:
        return builder()
    except Exception as exc:  # noqa: BLE001 - 失败降级为错误字段
        logger.exception("enterprise overview section failed")
        return {**fallback, "error": _truncate(exc)}


def _short_backend(backend: str) -> str:
    name = str(backend or "").rsplit(".", 1)[-1]
    return name.replace("Cache", "").replace("Backend", "") or "unknown"


# ---------------------------------------------------------------- 健康检查
def _health_database() -> dict:
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        latency = int((time.perf_counter() - started) * 1000)
        return {
            "status": "ok",
            "configured": True,
            "configured_engine": getattr(connection, "vendor", "unknown"),
            "latency_ms": latency,
            "detail": "数据库连接正常",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "configured": True,
            "configured_engine": getattr(connection, "vendor", "unknown"),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": _truncate(exc),
        }


def _health_cache() -> dict:
    backend = str((settings.CACHES or {}).get("default", {}).get("BACKEND", ""))
    redis_configured = bool(getattr(settings, "REDIS_URL", None))
    configured = redis_configured or ("locmem" not in backend and "dummy" not in backend)
    key = f"wp-enterprise-health-{uuid.uuid4().hex}"
    started = time.perf_counter()
    try:
        cache.set(key, "ok", 10)
        value = cache.get(key)
        cache.delete(key)
        latency = int((time.perf_counter() - started) * 1000)
        ok = value == "ok"
        return {
            "status": "ok" if ok else "degraded",
            "configured": configured,
            "backend": _short_backend(backend),
            "latency_ms": latency,
            "detail": "缓存读写正常" if ok else "缓存读写返回值不一致",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "configured": configured,
            "backend": _short_backend(backend),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": _truncate(exc),
        }


def _health_celery_broker() -> dict:
    broker = str(getattr(settings, "CELERY_BROKER_URL", "") or "")
    eager = bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False))
    if not broker or broker.startswith("memory://"):
        return {
            "status": "not_configured",
            "configured": False,
            "broker": "memory://",
            "eager": eager,
            "latency_ms": None,
            "detail": "未配置 Redis/Celery broker，任务以 eager 同步模式执行",
        }
    parsed = urlparse(broker)
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname
    port = parsed.port or {"redis": 6379, "rediss": 6379, "amqp": 5672, "amqps": 5671}.get(scheme)
    safe_broker = f"{scheme}://{host}:{port}" if host and port else scheme or "unknown"
    if not host or not port:
        return {
            "status": "unknown",
            "configured": True,
            "broker": safe_broker,
            "eager": eager,
            "latency_ms": None,
            "detail": "无法解析 broker 地址，无法执行连通性检查",
        }
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=HEALTH_SOCKET_TIMEOUT):
            pass
        return {
            "status": "ok",
            "configured": True,
            "broker": safe_broker,
            "eager": eager,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": "broker 端口可连接",
        }
    except OSError as exc:
        return {
            "status": "error",
            "configured": True,
            "broker": safe_broker,
            "eager": eager,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "detail": _truncate(exc),
        }


def _overall_health(health: dict) -> str:
    if (health.get("database") or {}).get("status") != "ok":
        return "down"
    optional = ("cache", "celery_broker")
    if any((health.get(name) or {}).get("status") in ("error", "degraded") for name in optional):
        return "degraded"
    return "ok"


# ---------------------------------------------------------------- 存储统计
def _media_stats(force: bool = False) -> dict:
    root = Path(settings.MEDIA_ROOT)
    cache_key = f"wp-enterprise-media-{uuid.uuid5(uuid.NAMESPACE_URL, str(root)).hex[:12]}"
    if not force:
        try:
            cached = cache.get(cache_key)
        except Exception:  # noqa: BLE001
            cached = None
        if isinstance(cached, dict):
            return cached
    stats = {"files": 0, "bytes": 0, "truncated": False, "exists": root.exists()}
    if not root.exists():
        return stats
    started = time.monotonic()
    stack = [root]
    try:
        while stack:
            current = stack.pop()
            try:
                entries = os.scandir(current)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    try:
                        stats["bytes"] += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
                    stats["files"] += 1
                    if (
                        stats["files"] >= MEDIA_SCAN_MAX_FILES
                        or time.monotonic() - started > MEDIA_SCAN_MAX_SECONDS
                    ):
                        stats["truncated"] = True
                        stack.clear()
                        break
    except OSError:
        stats["truncated"] = True
    try:
        cache.set(cache_key, stats, _STORAGE_CACHE_SECONDS)
    except Exception:  # noqa: BLE001
        pass
    return stats


def _database_bytes() -> tuple[int | None, str]:
    db = settings.DATABASES.get("default", {})
    vendor = getattr(connection, "vendor", "")
    size: int | None = None
    try:
        if vendor == "sqlite":
            name = db.get("NAME")
            if name and str(name) != ":memory:":
                path = Path(str(name))
                if path.exists():
                    size = path.stat().st_size
        elif vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_database_size(current_database())")
                row = cursor.fetchone()
                if row:
                    size = int(row[0])
    except Exception:  # noqa: BLE001 - DB 大小是可选信息
        size = None
    return size, vendor


# ---------------------------------------------------------------- 备份目录
def _backup_dir() -> Path:
    raw = getattr(settings, "ENTERPRISE_BACKUP_DIR", "") or os.environ.get("WP_ENTERPRISE_BACKUP_DIR", "")
    if raw:
        return Path(str(raw)).expanduser().resolve()
    return (Path(settings.BASE_DIR) / "backups").resolve()


def _backup_kind(name: str) -> str:
    suffix = Path(name).suffix.lower()
    if suffix == ".json":
        return "app_export"
    if suffix in SYSTEM_BACKUP_SUFFIXES:
        return "system_backup"
    return "other"


def _describe_backup_file(path: Path) -> dict:
    stat = path.stat()
    created = datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc)
    return {
        "name": path.name,
        "size": int(stat.st_size),
        "size_human": _human_bytes(stat.st_size),
        "created_at": _iso(created),
        "kind": _backup_kind(path.name),
        "age_seconds": max(int(time.time() - stat.st_mtime), 0),
    }


def _list_backup_files(limit: int = MAX_BACKUP_LIST) -> dict:
    directory = _backup_dir()
    entries: list[dict] = []
    truncated = False
    exists = directory.is_dir()
    if exists:
        started = time.monotonic()
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if len(entries) >= limit:
                        truncated = True
                        break
                    if time.monotonic() - started > BACKUP_LIST_TIMEOUT_SECONDS:
                        truncated = True
                        break
                    name = entry.name
                    if not name or name.startswith(".") or name.startswith("~") or name.endswith(".part"):
                        continue
                    if Path(name).suffix.lower() not in ALLOWED_BACKUP_SUFFIXES:
                        continue
                    try:
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        entries.append(_describe_backup_file(Path(entry.path)))
                    except OSError:
                        continue
        except FileNotFoundError:
            exists = False
        except OSError:
            logger.exception("enterprise backups: 无法读取备份目录")
    entries.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    total_bytes = sum(item["size"] for item in entries)
    return {
        "directory_name": directory.name,
        "exists": exists,
        "writable": bool(exists and os.access(directory, os.W_OK)),
        "count": len(entries),
        "total_bytes": total_bytes,
        "total_human": _human_bytes(total_bytes),
        "truncated": truncated,
        "latest": entries[0] if entries else None,
        "results": entries,
    }


def _sqlite_backup(target: Path) -> None:
    source_name = str(settings.DATABASES.get("default", {}).get("NAME") or "")
    if not source_name:
        raise RuntimeError("未配置 SQLite 数据库，无法备份")
    is_uri = source_name.startswith("file:")
    if not is_uri and not Path(source_name).exists():
        raise RuntimeError("SQLite 数据库文件不存在，无法备份")
    # 内存测试库是 file:...?mode=memory&cache=shared URI，需要 uri=True 才能连上。
    source = sqlite3.connect(source_name, uri=is_uri)
    try:
        dest = sqlite3.connect(str(target))
        try:
            source.backup(dest)
            dest.commit()
        finally:
            dest.close()
    finally:
        source.close()


def _backup_instructions() -> dict:
    return {
        "create": "POST /api/enterprise/backups/（JSON：{\"include_media\": false}）",
        "list": "GET /api/enterprise/backups/",
        "cli": "python manage.py backup_system --output backups/<name>.zip",
        "restore": "python manage.py restore_system backups/<name>.zip --yes（危险：会覆盖数据库与媒体）",
        "note": "备份文件只保存在服务端备份目录，接口不提供下载/删除，也不接受客户端传入路径。",
    }


def _backup_capabilities() -> dict:
    return {
        "create": True,
        "include_media": True,
        "download": False,
        "delete": False,
        "max_db_bytes": _settings_int("ENTERPRISE_BACKUP_MAX_DB_BYTES", DEFAULT_MAX_DB_BYTES),
        "max_media_bytes": _settings_int("ENTERPRISE_BACKUP_MAX_MEDIA_BYTES", DEFAULT_MAX_MEDIA_BYTES),
    }


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------- 总览
def _section_apps(now) -> dict:
    from appcore.models import App

    week_ago = now - timedelta(days=7)
    stats = App.objects.aggregate(
        total=Count("id"),
        draft=Count("id", filter=Q(status="draft")),
        published=Count("id", filter=Q(status="published")),
        archived=Count("id", filter=Q(status="archived")),
        new_last_7d=Count("id", filter=Q(created_at__gte=week_ago)),
    )
    return {
        "total": stats["total"] or 0,
        "by_status": {
            "draft": stats["draft"] or 0,
            "published": stats["published"] or 0,
            "archived": stats["archived"] or 0,
        },
        "new_last_7d": stats["new_last_7d"] or 0,
    }


def _section_users(now) -> dict:
    from accounts.models import User

    week_ago = now - timedelta(days=7)
    stats = User.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(is_active=True)),
        staff=Count("id", filter=Q(is_staff=True)),
        superuser=Count("id", filter=Q(is_superuser=True)),
        platform_admin=Count("id", filter=Q(is_platform_admin=True)),
        new_last_7d=Count("id", filter=Q(date_joined__gte=week_ago)),
    )
    total = stats["total"] or 0
    active = stats["active"] or 0
    return {
        "total": total,
        "active": active,
        "inactive": max(total - active, 0),
        "staff": stats["staff"] or 0,
        "superuser": stats["superuser"] or 0,
        "platform_admin": stats["platform_admin"] or 0,
        "new_last_7d": stats["new_last_7d"] or 0,
    }


def _section_data() -> dict:
    from datamodels.models import DataModel, DataRecord

    return {
        "models": DataModel.objects.count(),
        "records": DataRecord.objects.count(),
    }


def _serialize_audit(log) -> dict:
    app = getattr(log, "app", None)
    return {
        "id": log.id,
        "username": log.username or "",
        "user_id": log.user_id,
        "action": log.action,
        "object_type": log.object_type,
        "object_id": log.object_id,
        "app_id": log.app_id,
        "app_name": getattr(app, "name", "") if app is not None else "",
        "ip": log.ip,
        "created_at": _iso(log.created_at),
    }


def _section_audit(now) -> dict:
    from audit.models import AuditLog

    stats = AuditLog.objects.aggregate(
        total=Count("id"),
        last_24h=Count("id", filter=Q(created_at__gte=now - timedelta(hours=24))),
        last_7d=Count("id", filter=Q(created_at__gte=now - timedelta(days=7))),
    )
    # 以主键倒序取最近记录：走主键索引，避免在无 created_at 索引的大表上排序。
    recent = list(AuditLog.objects.select_related("app").order_by("-id")[:RECENT_LIMIT])
    return {
        "total": stats["total"] or 0,
        "last_24h": stats["last_24h"] or 0,
        "last_7d": stats["last_7d"] or 0,
        "recent": [_serialize_audit(item) for item in recent],
    }


def _section_jobs() -> dict:
    from appcore.models import ScheduledJob

    stats = ScheduledJob.objects.aggregate(
        total=Count("id"),
        enabled=Count("id", filter=Q(enabled=True)),
        failed=Count("id", filter=Q(last_status="failed")),
        never_run=Count("id", filter=Q(last_run_at__isnull=True)),
    )
    failures = list(
        ScheduledJob.objects.select_related("app")
        .filter(last_status__in=("failed", "error"))
        .order_by(F("last_run_at").desc(nulls_last=True), "-id")[:FAILURE_LIMIT]
    )
    return {
        "total": stats["total"] or 0,
        "enabled": stats["enabled"] or 0,
        "failed": stats["failed"] or 0,
        "never_run": stats["never_run"] or 0,
        "recent_failures": [
            {
                "id": job.id,
                "app_id": job.app_id,
                "app_name": getattr(getattr(job, "app", None), "name", ""),
                "name": job.name,
                "code": job.code,
                "handler": job.handler,
                "cron": job.cron,
                "enabled": job.enabled,
                "last_status": job.last_status,
                "last_error": _truncate(job.last_error),
                "last_run_at": _iso(job.last_run_at),
            }
            for job in failures
        ],
    }


def _section_webhooks() -> dict:
    from appcore.models import WebhookDelivery, WebhookEndpoint

    endpoints = WebhookEndpoint.objects.aggregate(
        total=Count("id"),
        enabled=Count("id", filter=Q(enabled=True)),
        failing=Count("id", filter=Q(last_status="failed")),
    )
    deliveries = WebhookDelivery.objects.aggregate(
        total=Count("id"),
        failed=Count("id", filter=Q(ok=False)),
    )
    failures = list(
        WebhookDelivery.objects.select_related("endpoint")
        .filter(ok=False)
        .order_by("-id")[:FAILURE_LIMIT]
    )
    return {
        "endpoints": endpoints["total"] or 0,
        "enabled": endpoints["enabled"] or 0,
        "failing": endpoints["failing"] or 0,
        "deliveries": deliveries["total"] or 0,
        "failed_deliveries": deliveries["failed"] or 0,
        "recent_failures": [
            {
                "id": item.id,
                "endpoint_id": item.endpoint_id,
                "endpoint_name": getattr(getattr(item, "endpoint", None), "name", ""),
                "event": item.event,
                "status_code": item.status_code,
                "error": _truncate(item.error),
                "created_at": _iso(item.created_at),
            }
            for item in failures
        ],
    }


def _section_notifications() -> dict:
    from appcore.models import NotificationLog

    stats = NotificationLog.objects.aggregate(
        total=Count("id"),
        sent=Count("id", filter=Q(status="sent")),
        failed=Count("id", filter=Q(status="failed")),
        unread=Count("id", filter=Q(read_at__isnull=True)),
    )
    return {
        "total": stats["total"] or 0,
        "sent": stats["sent"] or 0,
        "failed": stats["failed"] or 0,
        "unread": stats["unread"] or 0,
    }


def _section_releases() -> dict:
    from releases.models import Release

    by_status = {
        str(row["status"]): row["c"]
        for row in Release.objects.values("status").annotate(c=Count("id"))
    }
    recent = list(Release.objects.select_related("app").order_by("-id")[:RECENT_RELEASES_LIMIT])
    return {
        "total": sum(by_status.values()),
        "by_status": by_status,
        "active": by_status.get("active", 0),
        "failed": by_status.get("failed", 0),
        "recent": [
            {
                "id": item.id,
                "app_id": item.app_id,
                "app_code": getattr(getattr(item, "app", None), "code", ""),
                "version": item.version,
                "status": item.status,
                "traffic_ratio": item.traffic_ratio,
                "created_at": _iso(item.created_at),
            }
            for item in recent
        ],
    }


def _section_storage() -> dict:
    media = _media_stats()
    db_bytes, vendor = _database_bytes()
    return {
        "media_files": media.get("files", 0),
        "media_bytes": media.get("bytes", 0),
        "media_human": _human_bytes(media.get("bytes", 0)),
        "media_truncated": bool(media.get("truncated")),
        "media_exists": bool(media.get("exists")),
        "database_bytes": db_bytes,
        "database_human": _human_bytes(db_bytes),
        "database_engine": vendor,
        "total_bytes": (media.get("bytes", 0) or 0) + (db_bytes or 0),
    }


def _section_backups() -> dict:
    listed = _list_backup_files()
    latest = listed.get("latest")
    return {
        "count": listed.get("count", 0),
        "total_bytes": listed.get("total_bytes", 0),
        "total_human": listed.get("total_human"),
        "latest": latest,
        "directory_name": listed.get("directory_name"),
        "writable": listed.get("writable", False),
    }


def _environment() -> dict:
    return {
        "django_version": django.get_version(),
        "debug": bool(settings.DEBUG),
        "database_engine": getattr(connection, "vendor", "unknown"),
        "cache_backend": _short_backend(str((settings.CACHES or {}).get("default", {}).get("BACKEND", ""))),
        "celery_eager": bool(getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False)),
        "timezone": str(getattr(settings, "TIME_ZONE", "")),
    }


# ---------------------------------------------------------------- 视图
@api_view(["GET"])
@permission_classes([IsEnterpriseAdmin])
def overview(request):
    """GET /api/enterprise/overview/ — 平台运维总览（管理员）。"""
    now = timezone.now()

    health = {
        "database": _health_database(),
        "cache": _health_cache(),
        "celery_broker": _health_celery_broker(),
    }

    payload = {
        "generated_at": _iso(now),
        "environment": _environment(),
        "health": {**health, "overall": _overall_health(health)},
        "apps": _section(
            lambda: _section_apps(now),
            {"total": 0, "by_status": {"draft": 0, "published": 0, "archived": 0}, "new_last_7d": 0},
        ),
        "users": _section(
            lambda: _section_users(now),
            {
                "total": 0, "active": 0, "inactive": 0, "staff": 0,
                "superuser": 0, "platform_admin": 0, "new_last_7d": 0,
            },
        ),
        "data": _section(_section_data, {"models": 0, "records": 0}),
        "storage": _section(
            _section_storage,
            {
                "media_files": 0, "media_bytes": 0, "media_human": None,
                "media_truncated": False, "media_exists": False,
                "database_bytes": None, "database_human": None,
                "database_engine": getattr(connection, "vendor", "unknown"), "total_bytes": 0,
            },
        ),
        "audit": _section(
            lambda: _section_audit(now),
            {"total": 0, "last_24h": 0, "last_7d": 0, "recent": []},
        ),
        "jobs": _section(
            _section_jobs,
            {"total": 0, "enabled": 0, "failed": 0, "never_run": 0, "recent_failures": []},
        ),
        "webhooks": _section(
            _section_webhooks,
            {
                "endpoints": 0, "enabled": 0, "failing": 0,
                "deliveries": 0, "failed_deliveries": 0, "recent_failures": [],
            },
        ),
        "notifications": _section(
            _section_notifications,
            {"total": 0, "sent": 0, "failed": 0, "unread": 0},
        ),
        "releases": _section(
            _section_releases,
            {"total": 0, "by_status": {}, "active": 0, "failed": 0, "recent": []},
        ),
        "backups": _section(
            _section_backups,
            {"count": 0, "total_bytes": 0, "total_human": None, "latest": None,
             "directory_name": None, "writable": False},
        ),
    }
    return Response(payload)


@api_view(["GET", "POST"])
@permission_classes([IsEnterpriseAdmin])
def backups(request):
    """GET /api/enterprise/backups/ 列出备份；POST 创建备份（管理员）。"""
    if request.method == "GET":
        listed = _list_backup_files()
        return Response(
            {
                "engine": getattr(connection, "vendor", "unknown"),
                "directory": {
                    "name": listed.get("directory_name"),
                    "exists": listed.get("exists", False),
                    "writable": listed.get("writable", False),
                },
                "count": listed.get("count", 0),
                "total_bytes": listed.get("total_bytes", 0),
                "total_human": listed.get("total_human"),
                "truncated": listed.get("truncated", False),
                "latest": listed.get("latest"),
                "results": listed.get("results", []),
                "limits": {
                    "max_entries": MAX_BACKUP_LIST,
                    "allowed_suffixes": sorted(ALLOWED_BACKUP_SUFFIXES),
                    "list_timeout_seconds": BACKUP_LIST_TIMEOUT_SECONDS,
                },
                "capabilities": _backup_capabilities(),
                "instructions": _backup_instructions(),
            }
        )

    return _create_backup(request)


def _create_backup(request):
    payload = request.data if isinstance(request.data, dict) else {}
    include_media = _parse_bool(payload.get("include_media", False))

    if not _BACKUP_LOCK.acquire(blocking=False):
        return Response({"detail": "已有备份任务正在执行，请稍后再试"}, status=http_status.HTTP_409_CONFLICT)

    directory = _backup_dir()
    final: Path | None = None
    part: Path | None = None
    try:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return Response(
                {"detail": f"备份目录不可用：{_truncate(exc)}"}, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        db_bytes, vendor = _database_bytes()
        max_db = _settings_int("ENTERPRISE_BACKUP_MAX_DB_BYTES", DEFAULT_MAX_DB_BYTES)
        if db_bytes is not None and db_bytes > max_db:
            return Response(
                {"detail": f"数据库大小 {_human_bytes(db_bytes)} 超过单次备份上限 {_human_bytes(max_db)}，"
                           "请使用命令行 backup_system 手工备份。"},
                status=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        if include_media:
            media = _media_stats()
            max_media = _settings_int("ENTERPRISE_BACKUP_MAX_MEDIA_BYTES", DEFAULT_MAX_MEDIA_BYTES)
            if (media.get("bytes") or 0) > max_media:
                return Response(
                    {"detail": f"媒体目录大小 {_human_bytes(media.get('bytes'))} 超过备份上限 "
                               f"{_human_bytes(max_media)}，请关闭「包含媒体文件」后重试。"},
                    status=http_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )

        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        token = uuid.uuid4().hex[:6]
        suffix = ".sqlite3" if vendor == "sqlite" else ".zip"
        filename = f"webprocess-enterprise-{stamp}-{token}{suffix}"
        final = directory / filename
        part = directory / f"{filename}.part"
        if part.exists():
            part.unlink()
        if final.exists():
            return Response({"detail": "备份文件已存在，请重试"}, status=http_status.HTTP_409_CONFLICT)

        if vendor == "sqlite":
            _sqlite_backup(part)
        else:
            import io

            buffer = io.StringIO()
            call_command(
                "backup_system",
                output=str(part),
                no_media=not include_media,
                verbosity=0,
                stdout=buffer,
            )
        if not part.exists() or part.stat().st_size <= 0:
            raise RuntimeError("备份命令未生成有效文件")
        os.replace(part, final)
        part = None
        entry = _describe_backup_file(final)
    except Exception as exc:  # noqa: BLE001
        logger.exception("enterprise backup failed")
        for candidate in (part, final):
            try:
                if candidate is not None and candidate.exists() and candidate.name.endswith(".part"):
                    candidate.unlink()
            except OSError:
                pass
        return Response(
            {"detail": f"备份失败：{_truncate(exc)}，可在服务器执行 python manage.py backup_system 手工备份。"},
            status=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        _BACKUP_LOCK.release()

    write_audit_log(
        user=getattr(request, "user", None),
        action="backup.create",
        object_type="backup",
        object_id=entry["name"],
        after={"size": entry["size"], "include_media": include_media, "engine": vendor},
        request=request,
    )
    return Response(
        {
            "ok": True,
            "message": "备份创建成功" if not include_media else "备份创建成功（含媒体文件）",
            "filename": entry["name"],
            "size": entry["size"],
            "size_human": entry["size_human"],
            "created_at": entry["created_at"],
            "engine": vendor,
            "include_media": include_media,
            "backup": entry,
        },
        status=http_status.HTTP_201_CREATED,
    )
