"""服务端权威的设计器节点锁服务。

设计要点：
- **身份由服务端决定**：调用方只能传 ``user`` / ``user_id``（来自 JWT），
  客户端消息里的任何用户名/用户 ID 都不被信任。
- **TTL 90 秒**：``expires_at`` 之后锁视为空闲；心跳为当前会话在该页面的
  全部锁续期。
- **原子获取**：``select_for_update`` + 唯一约束 ``(page, node_id)`` 双重保证；
  并发插入触发 ``IntegrityError`` 时重试读取赢家。
- **会话恢复**：同一 ``session_id`` 重连后仍持有未过期的锁；锁在断线时释放，
  客户端依据 ``sessionStorage`` 中的 session/节点集合重新申请。
"""
from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from .lock_models import DesignerLock

# 锁租约：90 秒；前端建议每 30 秒心跳一次。
LOCK_TTL = timedelta(seconds=90)
LOCK_TTL_SECONDS = int(LOCK_TTL.total_seconds())

MAX_NODE_ID_LEN = 120
MAX_SELECTION_IDS = 200
CURSOR_MIN_INTERVAL_MS = 50

# --------------------------------------------------------------------------- 等待队列
# 队列刻意放在缓存（Redis / LocMem）而不是数据库：不新增迁移，释放锁时
# 在同一把缓存互斥锁内完成「摘下一位等待者 + 转移 DB 锁行」，保证公平。
# 可通过 settings 覆盖（测试/部署调参）：
#   DESIGNER_LOCK_QUEUE_TIMEOUT_SECONDS  默认 30
#   DESIGNER_LOCK_QUEUE_MAX              默认 50（每个节点）
#   DESIGNER_LOCK_QUEUE_POLL_SECONDS     默认 0.5（消费端检查过期/队首的间隔）
QUEUE_TIMEOUT_SECONDS = 30.0
MAX_LOCK_QUEUE = 50
QUEUE_POLL_SECONDS = 0.5
QUEUE_CACHE_PAD_SECONDS = 600
QUEUE_GUARD_SECONDS = 2.0
QUEUE_KEY_PREFIX = "designer_lock:queue"
QUEUE_GUARD_PREFIX = "designer_lock:queue-guard"
QUEUE_INDEX_PREFIX = "designer_lock:queue-index"
CONNECTION_KEY_PREFIX = "designer_lock:conn"


def queue_timeout_seconds() -> float:
    """单次排队最长等待秒数；允许 settings 覆盖，最小 0.05s。"""
    try:
        raw = getattr(settings, "DESIGNER_LOCK_QUEUE_TIMEOUT_SECONDS", QUEUE_TIMEOUT_SECONDS)
        value = float(raw)
    except (TypeError, ValueError):
        value = QUEUE_TIMEOUT_SECONDS
    return max(0.05, value)


def max_lock_queue() -> int:
    """每个节点的最大等待人数（含队首）。"""
    try:
        raw = int(getattr(settings, "DESIGNER_LOCK_QUEUE_MAX", MAX_LOCK_QUEUE))
    except (TypeError, ValueError):
        raw = MAX_LOCK_QUEUE
    return max(1, min(raw, 1000))


def queue_poll_seconds() -> float:
    """消费端队列巡检间隔（过期 / 队首可抢占）。"""
    try:
        raw = getattr(settings, "DESIGNER_LOCK_QUEUE_POLL_SECONDS", QUEUE_POLL_SECONDS)
        value = float(raw)
    except (TypeError, ValueError):
        value = QUEUE_POLL_SECONDS
    return max(0.02, min(value, 5.0))


def connection_key(page_id: int, session_id) -> str:
    """同一 ``page + session`` 的「最新连接」认领键（断线竞态保护）。"""
    return f"{CONNECTION_KEY_PREFIX}:{page_id}:{session_id}"


# --------------------------------------------------------------------------- 校验
def normalize_session_id(raw) -> uuid.UUID | None:
    """把任意输入规整为 UUID；非法返回 None。"""
    if isinstance(raw, uuid.UUID):
        return raw
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or len(text) > 64:
        return None
    try:
        return uuid.UUID(text)
    except (ValueError, TypeError, AttributeError):
        return None


def normalize_node_id(raw) -> str | None:
    """节点 ID 只做长度/控制字符校验，保持与前端 schema 节点 ID 兼容。"""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or len(text) > MAX_NODE_ID_LEN:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return None
    return text


def normalize_selection_ids(raw) -> list[str] | None:
    """选择集：最多 200 个节点，逐个做长度校验；非法项丢弃。"""
    if not isinstance(raw, (list, tuple)):
        return None
    cleaned: list[str] = []
    for item in list(raw)[:MAX_SELECTION_IDS]:
        node = normalize_node_id(item)
        if node is not None:
            cleaned.append(node)
    return cleaned


# --------------------------------------------------------------------------- 序列化
def _lock_payload(lock: DesignerLock, username: str | None = None) -> dict:
    if username is None:
        try:
            username = lock.user.username
        except Exception:  # pragma: no cover - 用户已删除等极端情况
            username = ""
    return {
        "nodeId": lock.node_id,
        "userId": lock.user_id,
        "username": username or "",
        "sessionId": str(lock.session_id),
        "expiresAt": lock.expires_at.isoformat() if lock.expires_at else None,
    }


def _username_for(user_id: int | None) -> str:
    if not user_id:
        return ""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk=user_id).values_list("username", flat=True).first() or ""


# --------------------------------------------------------------------------- 清理 / 快照
def cleanup_expired(page_id: int | None = None) -> int:
    """删除已过期的锁记录；返回删除条数。"""
    now = timezone.now()
    qs = DesignerLock.objects.filter(expires_at__lte=now)
    if page_id is not None:
        qs = qs.filter(page_id=page_id)
    deleted, _ = qs.delete()
    return int(deleted or 0)


def live_locks(page_id: int) -> list[dict]:
    payloads = [
        _lock_payload(lock)
        for lock in DesignerLock.objects.filter(page_id=page_id, expires_at__gt=timezone.now())
        .select_related("user")
        .order_by("node_id")
    ]
    return payloads


def snapshot_for_session(page_id: int, user_id: int, session_id) -> dict:
    """连接时的完整快照：先清理过期，再区分「本会话的锁」与「他人的锁」。"""
    sid = normalize_session_id(session_id)
    cleanup_expired(page_id)
    rows = (
        DesignerLock.objects.filter(page_id=page_id, expires_at__gt=timezone.now())
        .select_related("user")
        .order_by("node_id")
    )
    locks: list[dict] = []
    owned: list[str] = []
    for lock in rows:
        payload = _lock_payload(lock)
        locks.append(payload)
        if sid is not None and str(lock.session_id) == str(sid) and lock.user_id == user_id:
            owned.append(lock.node_id)
    return {
        "locks": locks,
        "ownedNodeIds": owned,
        "sessionId": str(sid) if sid is not None else "",
    }


def recovery_plan(page_id: int, user_id: int, session_id, candidate_node_ids) -> dict:
    """重连恢复计划：候选节点中哪些仍归本会话、哪些空闲可重取、哪些被他人占用。"""
    sid = normalize_session_id(session_id)
    candidates = normalize_selection_ids(candidate_node_ids) or []
    cleanup_expired(page_id)
    rows = DesignerLock.objects.filter(
        page_id=page_id, node_id__in=candidates, expires_at__gt=timezone.now()
    ).select_related("user")
    by_node = {lock.node_id: lock for lock in rows}
    owned: list[str] = []
    recoverable: list[str] = []
    lost: list[dict] = []
    now = timezone.now()
    for node_id in candidates:
        lock = by_node.get(node_id)
        if lock is None:
            recoverable.append(node_id)
        elif sid is not None and str(lock.session_id) == str(sid) and lock.user_id == user_id:
            owned.append(node_id)
        elif lock.expires_at <= now:
            recoverable.append(node_id)
        else:
            lost.append({"nodeId": node_id, "owner": _lock_payload(lock)})
    return {"owned": owned, "recoverable": recoverable, "lost": lost}


# --------------------------------------------------------------------------- 获取 / 释放
def acquire_lock(page_id: int, user, session_id, node_id) -> dict:
    """原子获取（或续租）一把锁。

    返回::

        {"granted": True,  "lock": {...}, "reason": "created|refreshed|expired"}
        {"granted": False, "owner": {...}|None, "reason": "locked|invalid|contended"}
    """
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    if sid is None or node is None:
        return {"granted": False, "owner": None, "reason": "invalid"}
    if user is None or not getattr(user, "id", None):
        return {"granted": False, "owner": None, "reason": "invalid"}

    now = timezone.now()
    expires = now + LOCK_TTL
    username = getattr(user, "username", "") or ""

    # 最多重试 3 次：并发插入时唯一约束会抛 IntegrityError，重试即可读到赢家。
    for _ in range(3):
        try:
            with transaction.atomic():
                lock = (
                    DesignerLock.objects.select_for_update()
                    .filter(page_id=page_id, node_id=node)
                    .first()
                )
                # 行锁拿到后重新取时间，避免等待期间租约状态变化导致误判。
                now = timezone.now()
                expires = now + LOCK_TTL
                if lock is not None:
                    # 会话 UUID 会在 snapshot 中广播给同页成员，因此必须同时校验
                    # user_id：不同用户即使知道 session UUID 也不能续租/抢占。
                    same_owner = lock.session_id == sid and lock.user_id == user.id
                    if lock.expires_at > now and not same_owner:
                        return {
                            "granted": False,
                            "owner": _lock_payload(lock, _username_for(lock.user_id)),
                            "reason": "locked",
                        }
                    if same_owner:
                        # 本会话续租：不改变 acquired_at。
                        lock.expires_at = expires
                        lock.save(update_fields=["expires_at"])
                        return {"granted": True, "lock": _lock_payload(lock, username), "reason": "refreshed"}
                    # 过期锁抢占：服务端重新分配归属。
                    lock.user_id = user.id
                    lock.session_id = sid
                    lock.acquired_at = now
                    lock.expires_at = expires
                    lock.save(update_fields=["user", "session_id", "acquired_at", "expires_at"])
                    return {"granted": True, "lock": _lock_payload(lock, username), "reason": "expired"}

                try:
                    # 嵌套保存点：并发唯一冲突只回滚这一次插入。
                    with transaction.atomic():
                        lock = DesignerLock.objects.create(
                            page_id=page_id,
                            node_id=node,
                            user_id=user.id,
                            session_id=sid,
                            expires_at=expires,
                        )
                except IntegrityError:
                    continue
                return {"granted": True, "lock": _lock_payload(lock, username), "reason": "created"}
        except IntegrityError:
            continue

    lock = DesignerLock.objects.filter(page_id=page_id, node_id=node).first()
    if lock is not None and lock.expires_at > timezone.now() and not (
        lock.session_id == sid and lock.user_id == user.id
    ):
        return {
            "granted": False,
            "owner": _lock_payload(lock, _username_for(lock.user_id)),
            "reason": "contended",
        }
    if (
        lock is not None
        and lock.session_id == sid
        and lock.user_id == user.id
        and lock.expires_at > timezone.now()
    ):
        return {"granted": True, "lock": _lock_payload(lock, username), "reason": "refreshed"}
    return {"granted": False, "owner": None, "reason": "contended"}


def release_lock(page_id: int, user_id: int, session_id, node_id, username: str = "") -> dict | None:
    """释放本会话持有的锁；不能释放他人的锁。成功返回被释放锁的载荷。"""
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    if sid is None or node is None or not user_id:
        return None
    lock = (
        DesignerLock.objects.filter(
            page_id=page_id, node_id=node, user_id=user_id, session_id=sid
        )
        .select_related("user")
        .first()
    )
    if lock is None:
        return None
    payload = _lock_payload(lock, username or None)
    lock.delete()
    return payload


def release_session_locks(page_id: int, user_id: int, session_id, username: str = "") -> list[dict]:
    """释放某用户 + 某会话在该页面的全部锁；返回用于广播的载荷列表。"""
    sid = normalize_session_id(session_id)
    if sid is None or not user_id:
        return []
    rows = list(
        DesignerLock.objects.filter(page_id=page_id, user_id=user_id, session_id=sid).select_related("user")
    )
    if not rows:
        return []
    payloads = [_lock_payload(lock, username or None) for lock in rows]
    DesignerLock.objects.filter(pk__in=[lock.pk for lock in rows]).delete()
    return payloads


def heartbeat(page_id: int, user_id: int, session_id) -> dict:
    """心跳：为当前会话在该页面的所有锁续期。"""
    sid = normalize_session_id(session_id)
    if sid is None or not user_id:
        return {"count": 0, "expiresAt": None}
    expires = timezone.now() + LOCK_TTL
    count = DesignerLock.objects.filter(page_id=page_id, user_id=user_id, session_id=sid).update(
        expires_at=expires
    )
    return {"count": int(count or 0), "expiresAt": expires.isoformat()}


def node_owner(page_id: int, node_id) -> dict | None:
    """返回节点当前的有效持锁者；锁不存在/已过期返回 None。"""
    node = normalize_node_id(node_id)
    if node is None:
        return None
    lock = (
        DesignerLock.objects.filter(
            page_id=page_id, node_id=node, expires_at__gt=timezone.now()
        )
        .select_related("user")
        .first()
    )
    return _lock_payload(lock) if lock is not None else None


# --------------------------------------------------------------------------- 队列存储
# 队列条目字段（同时保留 snake_case 与协议用 camelCase，便于排查和兼容）：
#   page / node / user / userId / session / sessionId / requestId /
#   enqueued_at / enqueuedAt / timeout_at / timeoutAt / timeoutSeconds
def _queue_key(page_id: int, node_id: str) -> str:
    return f"{QUEUE_KEY_PREFIX}:{page_id}:{node_id}"


def _queue_guard_key(page_id: int, node_id: str) -> str:
    return f"{QUEUE_GUARD_PREFIX}:{page_id}:{node_id}"


def _queue_index_key(page_id: int, user_id: int, session_id) -> str:
    return f"{QUEUE_INDEX_PREFIX}:{page_id}:{user_id}:{session_id}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _queue_ttl() -> int:
    return max(60, int(queue_timeout_seconds() + QUEUE_CACHE_PAD_SECONDS))


@contextmanager
def _queue_guard(page_id: int, node_id: str):
    """缓存级互斥：cache.add 在 Redis / LocMem 上都是原子的。

    ``yield`` 布尔值表示是否成功拿到互斥锁。拿不到时调用方应降级而不是死等，
    避免单个慢 Redis 卡死整个 WebSocket consumer。
    """
    key = _queue_guard_key(page_id, node_id)
    token = uuid.uuid4().hex
    acquired = False
    deadline = time.monotonic() + QUEUE_GUARD_SECONDS
    while time.monotonic() < deadline:
        try:
            acquired = bool(cache.add(key, token, timeout=10))
        except Exception:
            acquired = False
            break
        if acquired:
            break
        time.sleep(0.01)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                if cache.get(key) == token:
                    cache.delete(key)
            except Exception:  # pragma: no cover - 缓存故障时不影响主流程
                pass


def _load_waiters(page_id: int, node_id: str) -> list[dict]:
    try:
        raw = cache.get(_queue_key(page_id, node_id))
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    items = data.get("waiters") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if isinstance(item, dict) and item.get("node") == node_id:
            out.append(item)
    return out


def _save_waiters(page_id: int, node_id: str, waiters: list[dict]) -> None:
    try:
        if waiters:
            cache.set(
                _queue_key(page_id, node_id),
                json.dumps({"v": 1, "waiters": waiters}, ensure_ascii=False, default=str),
                timeout=_queue_ttl(),
            )
        else:
            cache.delete(_queue_key(page_id, node_id))
    except Exception:  # pragma: no cover
        pass


def _prune_waiters(waiters: list[dict], now_ms: int | None = None) -> tuple[list[dict], list[dict]]:
    now = _now_ms() if now_ms is None else now_ms
    kept: list[dict] = []
    expired: list[dict] = []
    for entry in waiters:
        try:
            deadline = int(entry.get("timeoutAt") or 0)
        except (TypeError, ValueError):
            deadline = 0
        if deadline and deadline <= now:
            expired.append(entry)
        else:
            kept.append(entry)
    return kept, expired


def _same_waiter(entry: dict, user_id: int, session_id) -> bool:
    try:
        same_user = int(entry.get("userId") or 0) == int(user_id or 0)
    except (TypeError, ValueError):
        same_user = False
    return same_user and str(entry.get("sessionId") or "") == str(session_id)


def _build_waiter(
    page_id: int, user, session_id, node_id: str, request_id: str, timeout_seconds: float
) -> dict:
    now = timezone.now()
    deadline = now + timedelta(seconds=timeout_seconds)
    session_text = str(session_id)
    username = getattr(user, "username", "") or ""
    return {
        "page": page_id,
        "node": node_id,
        "user": username,
        "username": username,
        "userId": int(getattr(user, "id", 0) or 0),
        "session": session_text,
        "sessionId": session_text,
        "requestId": str(request_id or ""),
        "enqueued_at": now.isoformat(),
        "enqueuedAt": int(now.timestamp() * 1000),
        "timeout_at": deadline.isoformat(),
        "timeoutAt": int(deadline.timestamp() * 1000),
        "timeoutSeconds": float(timeout_seconds),
    }


def _public_waiter(entry: dict, position: int) -> dict:
    return {
        "nodeId": str(entry.get("node") or ""),
        "position": int(position),
        "userId": int(entry.get("userId") or 0),
        "username": str(entry.get("user") or entry.get("username") or ""),
        "sessionId": str(entry.get("sessionId") or entry.get("session") or ""),
        "requestId": str(entry.get("requestId") or ""),
        "enqueuedAt": str(entry.get("enqueued_at") or ""),
        "timeoutAt": str(entry.get("timeout_at") or ""),
        "timeoutMs": int(entry.get("timeoutAt") or 0),
    }


def _index_read(page_id: int, user_id: int, session_id) -> list[str]:
    try:
        raw = cache.get(_queue_index_key(page_id, user_id, session_id))
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if isinstance(item, str) and item]


def _index_write(page_id: int, user_id: int, session_id, nodes: list[str]) -> None:
    try:
        key = _queue_index_key(page_id, user_id, session_id)
        if nodes:
            cache.set(key, json.dumps(nodes), timeout=_queue_ttl())
        else:
            cache.delete(key)
    except Exception:  # pragma: no cover
        pass


def _index_add(page_id: int, user_id: int, session_id, node_id: str) -> None:
    nodes = _index_read(page_id, user_id, session_id)
    if node_id not in nodes:
        nodes.append(node_id)
    _index_write(page_id, user_id, session_id, nodes)


def _index_remove(page_id: int, user_id: int, session_id, node_id: str) -> None:
    nodes = [item for item in _index_read(page_id, user_id, session_id) if item != node_id]
    _index_write(page_id, user_id, session_id, nodes)


# --------------------------------------------------------------------------- 队列 API
def enqueue_waiter(
    page_id: int,
    user,
    session_id,
    node_id,
    request_id: str = "",
    timeout_seconds: float | None = None,
) -> dict:
    """把请求者追加到节点等待队列。

    返回::

        {"queued": True, "position": 1, "timeoutAt": "...", "waiter": {...},
         "queueLength": 1, "queueFull": False}
        {"queued": False, "reason": "full|busy|invalid", "position": 0, ...}

    同一 ``(userId, sessionId)`` 重复申请幂等：保留原排队位置与超时，
    不会因客户端重试而被插到队尾。
    """
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    user_id = int(getattr(user, "id", 0) or 0) if user is not None else 0
    if sid is None or node is None or not user_id:
        return {"queued": False, "reason": "invalid", "position": 0, "timeoutAt": "", "waiter": None, "queueLength": 0}

    requested = queue_timeout_seconds()
    if timeout_seconds is not None:
        try:
            requested = min(requested, max(0.1, float(timeout_seconds)))
        except (TypeError, ValueError):
            pass

    with _queue_guard(page_id, node) as ok:
        if not ok:
            return {"queued": False, "reason": "busy", "position": 0, "timeoutAt": "", "waiter": None, "queueLength": 0}
        waiters = _load_waiters(page_id, node)
        kept, expired = _prune_waiters(waiters)
        for index, entry in enumerate(kept):
            if _same_waiter(entry, user_id, sid):
                changed = bool(expired)
                new_request_id = str(request_id or "")
                if new_request_id and entry.get("requestId") != new_request_id:
                    # 重复 acquire 时把授权/超时回执指向最新一次请求。
                    entry["requestId"] = new_request_id
                    changed = True
                if changed:
                    _save_waiters(page_id, node, kept)
                _index_add(page_id, user_id, sid, node)
                return {
                    "queued": True,
                    "position": index + 1,
                    "timeoutAt": str(entry.get("timeout_at") or ""),
                    "waiter": entry,
                    "queueLength": len(kept),
                    "queueFull": False,
                    "expired": expired,
                }
        limit = max_lock_queue()
        if len(kept) >= limit:
            if expired:
                _save_waiters(page_id, node, kept)
            return {
                "queued": False,
                "reason": "full",
                "position": 0,
                "timeoutAt": "",
                "waiter": None,
                "queueLength": len(kept),
                "queueFull": True,
                "expired": expired,
            }
        entry = _build_waiter(page_id, user, sid, node, request_id, requested)
        kept.append(entry)
        _save_waiters(page_id, node, kept)
        _index_add(page_id, user_id, sid, node)
        return {
            "queued": True,
            "position": len(kept),
            "timeoutAt": entry["timeout_at"],
            "waiter": entry,
            "queueLength": len(kept),
            "queueFull": False,
            "expired": expired,
        }


def waiter_state(page_id: int, user_id: int, session_id, node_id) -> dict:
    """查询本会话在某个节点的排队状态（position 从 1 开始）。

    这里只做内存过滤、不写回缓存：过期项必须由各自的等待者通过
    ``take_expired_waiter`` 摘除，否则会吞掉应发给他的 ``lock-timeout``。
    """
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    if sid is None or node is None or not user_id:
        return {"queued": False, "position": 0, "timeoutAt": "", "timeoutMs": 0, "queueLength": 0, "waiter": None}
    waiters = _load_waiters(page_id, node)
    kept, _expired = _prune_waiters(waiters)
    for index, entry in enumerate(kept):
        if _same_waiter(entry, user_id, sid):
            return {
                "queued": True,
                "position": index + 1,
                "timeoutAt": str(entry.get("timeout_at") or ""),
                "timeoutMs": int(entry.get("timeoutAt") or 0),
                "queueLength": len(kept),
                "waiter": entry,
            }
    return {"queued": False, "position": 0, "timeoutAt": "", "timeoutMs": 0, "queueLength": len(kept), "waiter": None}


def queue_snapshot(page_id: int, node_id) -> list[dict]:
    """按位置返回某节点的等待者公开载荷（内存中剔除超时项，不写回）。"""
    node = normalize_node_id(node_id)
    if node is None:
        return []
    waiters = _load_waiters(page_id, node)
    kept, _expired = _prune_waiters(waiters)
    return [_public_waiter(entry, index + 1) for index, entry in enumerate(kept)]


def take_expired_waiter(page_id: int, user_id: int, session_id, node_id) -> dict | None:
    """若本会话的等待项已超时，原子摘除并返回该条目；否则 None。

    只摘除调用者自己的条目；其他等待者的过期项留给其各自的巡检任务，
    确保每个人都能收到一次 ``lock-timeout``。
    """
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    if sid is None or node is None or not user_id:
        return None
    with _queue_guard(page_id, node) as ok:
        if not ok:
            return None
        waiters = _load_waiters(page_id, node)
        now = _now_ms()
        found = None
        remaining: list[dict] = []
        for entry in waiters:
            try:
                deadline = int(entry.get("timeoutAt") or 0)
            except (TypeError, ValueError):
                deadline = 0
            if _same_waiter(entry, user_id, sid) and deadline and deadline <= now:
                found = entry
                continue
            remaining.append(entry)
        if found is not None:
            _save_waiters(page_id, node, remaining)
            _index_remove(page_id, user_id, sid, node)
        return found


def cancel_waiter(page_id: int, user_id: int, session_id, node_id) -> dict:
    """撤销单个节点的排队（客户端取消 / 断线清理）。"""
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    if sid is None or node is None or not user_id:
        return {"removed": False, "position": 0, "queueLength": 0}
    with _queue_guard(page_id, node) as ok:
        waiters = _load_waiters(page_id, node)
        kept, expired = _prune_waiters(waiters)
        removed = None
        position = 0
        remaining: list[dict] = []
        for index, entry in enumerate(kept):
            if removed is None and _same_waiter(entry, user_id, sid):
                removed = entry
                position = index + 1
                continue
            remaining.append(entry)
        if ok and (removed is not None or expired):
            _save_waiters(page_id, node, remaining)
        if removed is not None:
            _index_remove(page_id, user_id, sid, node)
        return {
            "removed": removed is not None,
            "position": position,
            "queueLength": len(remaining),
            "queueFull": False,
            "expired": expired,
        }


def cancel_session_waiters(page_id: int, user_id: int, session_id, nodes: list[str] | None = None) -> list[str]:
    """取消某会话在该页面的全部等待项；返回被取消的节点 ID。"""
    sid = normalize_session_id(session_id)
    if sid is None or not user_id:
        return []
    targets = nodes if nodes is not None else _index_read(page_id, user_id, sid)
    removed: list[str] = []
    for node in list(targets):
        result = cancel_waiter(page_id, user_id, sid, node)
        if result["removed"]:
            removed.append(node)
    _index_write(page_id, user_id, sid, [node for node in _index_read(page_id, user_id, sid) if node not in removed])
    return removed


def claim_head_lock(page_id: int, user, session_id, node_id) -> dict:
    """队首在锁过期/释放后尝试原子取得锁。

    只有队列头名可以调用成功；成功后在同一个缓存互斥区内把自身移出队列，
    因此不会出现「甲乙同时自认为队首并一起抢到」的重复授权。
    """
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    user_id = int(getattr(user, "id", 0) or 0) if user is not None else 0
    if sid is None or node is None or not user_id:
        return {"granted": False, "reason": "invalid", "position": 0, "queueLength": 0}
    with _queue_guard(page_id, node) as ok:
        if not ok:
            return {"granted": False, "reason": "busy", "position": 0, "queueLength": 0}
        waiters = _load_waiters(page_id, node)
        kept, expired = _prune_waiters(waiters)
        index = next((i for i, entry in enumerate(kept) if _same_waiter(entry, user_id, sid)), -1)
        if index < 0:
            if expired:
                _save_waiters(page_id, node, kept)
            _index_remove(page_id, user_id, sid, node)
            return {
                "granted": False,
                "reason": "not-queued",
                "position": 0,
                "queueLength": len(kept),
                "expired": expired,
            }
        if index != 0:
            if expired:
                _save_waiters(page_id, node, kept)
            return {
                "granted": False,
                "reason": "not-head",
                "position": index + 1,
                "queueLength": len(kept),
                "timeoutAt": str(kept[index].get("timeout_at") or ""),
                "expired": expired,
            }
        entry = kept[index]
        result = acquire_lock(page_id, user, sid, node)
        if not result.get("granted"):
            if expired:
                _save_waiters(page_id, node, kept)
            return {
                "granted": False,
                "reason": "locked",
                "position": 1,
                "queueLength": len(kept),
                "owner": result.get("owner"),
                "expired": expired,
            }
        kept.pop(0)
        _save_waiters(page_id, node, kept)
        _index_remove(page_id, user_id, sid, node)
        return {
            "granted": True,
            "lock": result["lock"],
            "requestId": str(entry.get("requestId") or ""),
            "queueLength": len(kept),
            "reason": "granted",
            "expired": expired,
        }


def release_lock_and_grant_next(
    page_id: int, user_id: int, session_id, node_id, username: str = ""
) -> dict | None:
    """释放自己的锁，并把锁原子转交给队首（若有）。

    返回 ``{"released": {...}, "granted": {...}|None, "waiter": {...}|None,
    "expired": [...], "queueLength": n}``；无权释放时返回 None。
    """
    sid = normalize_session_id(session_id)
    node = normalize_node_id(node_id)
    if sid is None or node is None or not user_id:
        return None

    with _queue_guard(page_id, node) as ok:
        if not ok:
            # 缓存互斥不可用：降级为只释放；等待者依靠 poll/下次 acquire 夺回，
            # 不会把锁永久交给错误的人。
            payload = release_lock(page_id, user_id, sid, node, username)
            if payload is None:
                return None
            return {
                "released": payload,
                "granted": None,
                "waiter": None,
                "expired": [],
                "queueLength": 0,
            }

        waiters = _load_waiters(page_id, node)
        kept, expired = _prune_waiters(waiters)
        chosen: tuple[dict, object] | None = None
        dropped = 0
        while kept:
            candidate = kept[0]
            try:
                candidate_user_id = int(candidate.get("userId") or 0)
            except (TypeError, ValueError):
                candidate_user_id = 0
            candidate_session = normalize_session_id(candidate.get("sessionId") or candidate.get("session"))
            if not candidate_user_id or candidate_session is None:
                kept.pop(0)
                dropped += 1
                continue
            from django.contrib.auth import get_user_model

            candidate_user = get_user_model().objects.filter(pk=candidate_user_id, is_active=True).first()
            if candidate_user is None:
                kept.pop(0)
                dropped += 1
                continue
            chosen = (candidate, candidate_user)
            break

        released_payload: dict | None = None
        granted_payload: dict | None = None
        try:
            with transaction.atomic():
                lock = (
                    DesignerLock.objects.select_for_update()
                    .filter(page_id=page_id, node_id=node)
                    .first()
                )
                if lock is None or lock.user_id != user_id or lock.session_id != sid:
                    return None
                released_payload = _lock_payload(lock, username or None)
                now = timezone.now()
                expires = now + LOCK_TTL
                if chosen is None:
                    lock.delete()
                else:
                    candidate, candidate_user = chosen
                    candidate_session = normalize_session_id(
                        candidate.get("sessionId") or candidate.get("session")
                    )
                    lock.user_id = candidate_user.id
                    lock.session_id = candidate_session
                    lock.acquired_at = now
                    lock.expires_at = expires
                    lock.save(update_fields=["user", "session_id", "acquired_at", "expires_at"])
                    granted_payload = _lock_payload(
                        lock, str(candidate.get("user") or candidate.get("username") or candidate_user.username)
                    )
        except IntegrityError:  # pragma: no cover - 行已存在时理论不会触发
            return None

        if chosen is not None:
            kept.pop(0)
            _index_remove(page_id, int(chosen[0].get("userId") or 0), chosen[0].get("sessionId"), node)
        if chosen is not None or expired or dropped:
            _save_waiters(page_id, node, kept)
        return {
            "released": released_payload,
            "granted": granted_payload,
            "waiter": chosen[0] if chosen is not None else None,
            "expired": expired,
            "queueLength": len(kept),
        }


def release_session_locks_with_queue(
    page_id: int, user_id: int, session_id, username: str = ""
) -> list[dict]:
    """断线时释放本会话在该页面的全部锁，并逐个把锁转交给队首。"""
    sid = normalize_session_id(session_id)
    if sid is None or not user_id:
        return []
    node_ids = list(
        DesignerLock.objects.filter(page_id=page_id, user_id=user_id, session_id=sid).values_list(
            "node_id", flat=True
        )
    )
    results: list[dict] = []
    for node_id in node_ids:
        result = release_lock_and_grant_next(page_id, user_id, sid, node_id, username)
        if result is not None:
            result["nodeId"] = node_id
            results.append(result)
    return results
