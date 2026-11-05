"""设计器 schema 同步辅助：规范化哈希 + 实时通道的临时 revision。

- :func:`compute_schema_hash`：对 schema 做稳定 JSON 序列化（key 排序）后 SHA-256。
  数据库 JSONB 会重排对象 key，只有规范化后的哈希才能跨保存/进程比较。
- 实时 WebSocket 广播的 revision 是临时的（不落库），存放在缓存里；真正的持久化
  修订号是 ``Page.schema_revision``，冲突检测使用后者。

多进程部署时缓存应使用 Redis（settings.REDIS_URL）；未配置 Redis 时 Django 使用
进程内 LocMemCache，此时各 worker 的临时 revision 独立，仅适合单进程/MVP。
"""
from __future__ import annotations

import hashlib
import json

from django.core.cache import cache

REVISION_CACHE_PREFIX = "pages:schema_sync:rev:"
REVISION_CACHE_TTL = 60 * 60 * 6  # 临时 revision 只需覆盖一次编辑会话


def revision_cache_key(page_id: int) -> str:
    return f"{REVISION_CACHE_PREFIX}{int(page_id)}"


def canonical_schema_json(schema) -> str:
    """稳定序列化：对象 key 排序、紧凑分隔符，保证同一 schema 哈希一致。"""
    return json.dumps(
        schema if schema is not None else {},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def compute_schema_hash(schema) -> str:
    """schema → 64 位十六进制 SHA-256（对 JSONB key 顺序不敏感）。"""
    return hashlib.sha256(canonical_schema_json(schema).encode("utf-8")).hexdigest()


def raise_revision_floor(page_id: int, revision: int) -> None:
    """保证临时 revision 不低于持久化 revision（保存成功后调用）。

    缓存异常不影响主流程；极端竞态下可能短暂回退，但下次消息会重新对齐。
    """
    try:
        key = revision_cache_key(page_id)
        target = max(1, int(revision or 1))
        current = cache.get(key)
        if current is None:
            cache.add(key, target, REVISION_CACHE_TTL)
        elif int(current) < target:
            cache.set(key, target, REVISION_CACHE_TTL)
    except Exception:  # noqa: BLE001 - 缓存不可用时不阻塞保存
        return


def next_ephemeral_revision(page_id: int, default_revision: int = 1) -> int:
    """原子递增临时 revision；首次使用时以持久化 revision 为起点。"""
    key = revision_cache_key(page_id)
    floor = max(1, int(default_revision or 1))
    try:
        cache.add(key, floor, REVISION_CACHE_TTL)
        return int(cache.incr(key))
    except Exception:  # noqa: BLE001 - 缓存降级时至少返回一个单调值
        return floor + 1


def reset_revision_cache(page_id: int) -> None:
    """测试/运维用：清除某页的临时 revision。"""
    try:
        cache.delete(revision_cache_key(page_id))
    except Exception:  # noqa: BLE001
        return
