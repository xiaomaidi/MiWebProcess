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

import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .lock_models import DesignerLock

# 锁租约：90 秒；前端建议每 30 秒心跳一次。
LOCK_TTL = timedelta(seconds=90)
LOCK_TTL_SECONDS = int(LOCK_TTL.total_seconds())

MAX_NODE_ID_LEN = 120
MAX_SELECTION_IDS = 200
CURSOR_MIN_INTERVAL_MS = 50


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
