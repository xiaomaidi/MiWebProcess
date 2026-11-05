"""设计器 schema 操作日志（append-only）服务层。

职责：

- 校验客户端提交的节点级 CRDT 操作（``node.upsert`` / ``node.delete`` /
  ``schema.meta``），统一 Lamport clock 结构。
- 在页面行锁内原子分配 ``seq``（每页从 1 单调递增），批量落库。
- 按 ``after`` 游标分页读取，供 REST / WebSocket 重放。
- 追加成功后向 ``designer_ops_{page_id}`` 频道广播（不发送整页 schema）。

设计边界：

- 操作日志是**审计 + 重放**来源，``Page.schema`` 仍是整页草稿快照；追加操作
  不会隐式修改 ``Page.schema`` / ``schema_revision``，整页保存仍由
  ``PUT /api/pages/{id}/schema/`` 负责。
- 日志只追加：模型层禁止 update/delete，本模块只使用 ``bulk_create`` 插入。
- 未实现自动清理；请用 ``after`` / ``limit`` 分页，长期运行可按审计策略归档。
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from asgiref.sync import async_to_sync
from django.db import IntegrityError, transaction
from django.db.models import Max

from pages.models import Page, PageSchemaOperation

OP_KINDS = ("node.upsert", "node.delete", "schema.meta")

MAX_BATCH_OPS = 200
MAX_OP_BYTES = 512 * 1024
MAX_BATCH_BYTES = 2 * 1024 * 1024
MAX_CLIENT_ID_LENGTH = 128
DEFAULT_OPS_LIMIT = 200
MAX_OPS_LIMIT = 500

GROUP_PREFIX = "designer_ops"
APPEND_RETRIES = 3


class SchemaOpValidationError(ValueError):
    """操作格式非法；``field`` 指向客户端可定位的字段。"""

    def __init__(self, message: str, field: str = ""):
        super().__init__(message)
        self.field = field


# ------------------------------------------------------------------ 基础校验


def normalize_client_id(value: Any) -> str:
    if not isinstance(value, str):
        raise SchemaOpValidationError("client_id 必须是非空字符串", "client_id")
    client_id = value.strip()
    if not client_id:
        raise SchemaOpValidationError("client_id 必须是非空字符串", "client_id")
    if len(client_id) > MAX_CLIENT_ID_LENGTH:
        raise SchemaOpValidationError(
            f"client_id 不能超过 {MAX_CLIENT_ID_LENGTH} 字符", "client_id"
        )
    return client_id


def normalize_base_revision(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        try:
            return max(0, int(default or 0))
        except (TypeError, ValueError):
            return 0
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaOpValidationError("base_revision 必须是非负整数", "base_revision")
    if value < 0:
        raise SchemaOpValidationError("base_revision 必须是非负整数", "base_revision")
    return value


def _normalize_clock(value: Any) -> dict:
    if not isinstance(value, dict):
        raise SchemaOpValidationError("clock 必须是对象", "clock")
    counter = value.get("counter")
    if isinstance(counter, bool) or not isinstance(counter, int) or counter < 0:
        raise SchemaOpValidationError(
            "clock.counter 必须是非负整数", "clock.counter"
        )
    client_id = value.get("clientId")
    if not isinstance(client_id, str) or not client_id.strip():
        raise SchemaOpValidationError(
            "clock.clientId 必须是非空字符串", "clock.clientId"
        )
    client_id = client_id.strip()
    if len(client_id) > MAX_CLIENT_ID_LENGTH:
        raise SchemaOpValidationError(
            f"clock.clientId 不能超过 {MAX_CLIENT_ID_LENGTH} 字符",
            "clock.clientId",
        )
    return {"counter": counter, "clientId": client_id}


def _json_size(value: Any) -> int:
    try:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise SchemaOpValidationError(f"操作无法序列化为 JSON: {exc}", "op") from exc
    return len(text.encode("utf-8"))


def _normalize_node(node_id: str, node: Any) -> dict:
    if not isinstance(node, dict):
        raise SchemaOpValidationError("node.upsert.node 必须是对象", "node")
    if node.get("id") != node_id:
        raise SchemaOpValidationError(
            "node.id 必须与 nodeId 一致", "node.id"
        )
    if not isinstance(node.get("type"), str) or not node.get("type"):
        raise SchemaOpValidationError("node.type 必须是非空字符串", "node.type")
    if not isinstance(node.get("props"), dict):
        raise SchemaOpValidationError("node.props 必须是对象", "node.props")
    children = node.get("children")
    if children is not None and not isinstance(children, list):
        raise SchemaOpValidationError("node.children 必须是数组", "node.children")
    slots = node.get("slots")
    if slots is not None:
        if not isinstance(slots, dict):
            raise SchemaOpValidationError("node.slots 必须是对象", "node.slots")
        for slot_name, ids in slots.items():
            if not isinstance(slot_name, str) or not isinstance(ids, list):
                raise SchemaOpValidationError(
                    "node.slots 必须是 插槽名 → 数组", "node.slots"
                )
    return node


def validate_op(op: Any, expected_client_id: str | None = None) -> dict:
    """校验并归一化单条操作；只保留协议字段，避免任意 JSON 膨胀。"""
    if not isinstance(op, dict):
        raise SchemaOpValidationError("op 必须是对象", "op")
    kind = op.get("kind")
    if kind not in OP_KINDS:
        raise SchemaOpValidationError(
            f"op.kind 必须是 {', '.join(OP_KINDS)} 之一", "op.kind"
        )
    clock = _normalize_clock(op.get("clock"))
    if expected_client_id is not None and clock["clientId"] != expected_client_id:
        raise SchemaOpValidationError(
            "clock.clientId 必须与 client_id 一致", "clock.clientId"
        )

    if kind == "node.upsert":
        node_id = op.get("nodeId")
        if not isinstance(node_id, str) or not node_id.strip():
            raise SchemaOpValidationError("nodeId 必须是非空字符串", "nodeId")
        node_id = node_id.strip()
        if len(node_id) > 200:
            raise SchemaOpValidationError("nodeId 不能超过 200 字符", "nodeId")
        node = _normalize_node(node_id, op.get("node"))
        normalized = {
            "kind": kind,
            "nodeId": node_id,
            "node": node,
            "clock": clock,
        }
    elif kind == "node.delete":
        node_id = op.get("nodeId")
        if not isinstance(node_id, str) or not node_id.strip():
            raise SchemaOpValidationError("nodeId 必须是非空字符串", "nodeId")
        node_id = node_id.strip()
        if len(node_id) > 200:
            raise SchemaOpValidationError("nodeId 不能超过 200 字符", "nodeId")
        normalized = {"kind": kind, "nodeId": node_id, "clock": clock}
    else:  # schema.meta
        meta = op.get("meta")
        if not isinstance(meta, dict):
            raise SchemaOpValidationError("meta 必须是对象", "meta")
        normalized = {"kind": kind, "meta": meta, "clock": clock}

    size = _json_size(normalized)
    if size > MAX_OP_BYTES:
        raise SchemaOpValidationError(
            f"单条操作不能超过 {MAX_OP_BYTES // 1024} KB", "op"
        )
    return normalized


def validate_batch(
    client_id: Any, ops: Any, base_revision: Any = None
) -> tuple[str, list[dict], int | None]:
    """校验一批操作；任一失败则整批拒绝（调用方在事务外调用）。"""
    clean_client = normalize_client_id(client_id)
    if not isinstance(ops, list):
        raise SchemaOpValidationError("ops 必须是数组", "ops")
    if not ops:
        raise SchemaOpValidationError("ops 不能为空", "ops")
    if len(ops) > MAX_BATCH_OPS:
        raise SchemaOpValidationError(
            f"单批最多 {MAX_BATCH_OPS} 条操作", "ops"
        )
    normalized: list[dict] = []
    total_bytes = 0
    for index, raw in enumerate(ops):
        try:
            op = validate_op(raw, expected_client_id=clean_client)
        except SchemaOpValidationError as exc:
            raise SchemaOpValidationError(
                f"ops[{index}]: {exc}", exc.field or f"ops[{index}]"
            ) from exc
        total_bytes += _json_size(op)
        if total_bytes > MAX_BATCH_BYTES:
            raise SchemaOpValidationError(
                f"单批操作不能超过 {MAX_BATCH_BYTES // 1024} KB", "ops"
            )
        normalized.append(op)
    base = normalize_base_revision(base_revision, 0) if base_revision not in (None, "") else None
    return clean_client, normalized, base


def parse_cursor(after_raw: Any, limit_raw: Any = None) -> tuple[int, int]:
    """解析 ``?after=&limit=``；after 默认 0，limit 夹在 1..MAX_OPS_LIMIT。"""
    try:
        after = int(after_raw) if after_raw not in (None, "") else 0
    except (TypeError, ValueError):
        raise SchemaOpValidationError("after 必须是非负整数", "after")
    if after < 0:
        raise SchemaOpValidationError("after 必须是非负整数", "after")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else DEFAULT_OPS_LIMIT
    except (TypeError, ValueError):
        raise SchemaOpValidationError("limit 必须是整数", "limit")
    limit = max(1, min(limit, MAX_OPS_LIMIT))
    return after, limit


# ------------------------------------------------------------------ 读写


def latest_seq(page_id: int) -> int:
    value = (
        PageSchemaOperation.objects.filter(page_id=page_id)
        .aggregate(last=Max("seq"))
        .get("last")
    )
    return int(value or 0)


def fetch_operations(
    page_id: int, after: int = 0, limit: int = DEFAULT_OPS_LIMIT
) -> tuple[list[PageSchemaOperation], bool]:
    """返回 ``seq > after`` 的操作（升序）以及是否还有更多。"""
    after, limit = parse_cursor(after, limit)
    qs = (
        PageSchemaOperation.objects.filter(page_id=page_id, seq__gt=after)
        .select_related("user")
        .order_by("seq")
    )
    rows = list(qs[: limit + 1])
    has_more = len(rows) > limit
    return rows[:limit], has_more


def append_operations(
    page_id: int,
    *,
    client_id: Any,
    ops: Any,
    base_revision: Any = None,
    user=None,
) -> list[PageSchemaOperation]:
    """校验并原子追加一批操作；返回带 ``seq`` 的已落库行。

    页面行锁 + ``MAX(seq)`` 计算保证并发追加时 seq 严格递增；唯一约束
    ``(page, seq)`` 是最后一道防线，冲突时重试。
    """
    clean_client, normalized_ops, requested_base = validate_batch(
        client_id, ops, base_revision
    )
    if not normalized_ops:
        raise SchemaOpValidationError("ops 不能为空", "ops")

    last_error: Exception | None = None
    for _attempt in range(APPEND_RETRIES):
        try:
            with transaction.atomic():
                page = (
                    Page.objects.select_for_update()
                    .only("id", "schema_revision")
                    .get(pk=page_id)
                )
                base = normalize_base_revision(
                    requested_base, int(page.schema_revision or 0)
                )
                last = (
                    PageSchemaOperation.objects.filter(page_id=page_id)
                    .aggregate(last=Max("seq"))
                    .get("last")
                )
                start = int(last or 0)
                rows = [
                    PageSchemaOperation(
                        page_id=page_id,
                        seq=start + offset + 1,
                        client_id=clean_client,
                        user=user,
                        base_revision=base,
                        op=op,
                    )
                    for offset, op in enumerate(normalized_ops)
                ]
                PageSchemaOperation.objects.bulk_create(rows)
            return rows
        except IntegrityError as exc:  # seq 竞争：重新计算后重试
            last_error = exc
            continue
    raise SchemaOpValidationError("操作日志写入冲突，请重试", "seq") from last_error


def operation_to_dict(row: PageSchemaOperation) -> dict:
    username = ""
    if row.user_id:
        try:
            username = row.user.username if row.user is not None else ""
        except Exception:  # noqa: BLE001 - 用户已删除 / 懒加载失败不影响日志读取
            username = ""
    return {
        "seq": int(row.seq),
        "client_id": row.client_id,
        "base_revision": int(row.base_revision or 0),
        "user_id": row.user_id,
        "username": username,
        "op": row.op,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def operations_to_dict(rows: Iterable[PageSchemaOperation]) -> list[dict]:
    return [operation_to_dict(row) for row in rows]


# ------------------------------------------------------------------ 广播


def group_for(page_id: int) -> str:
    return f"{GROUP_PREFIX}_{int(page_id)}"


def broadcast_operations(
    page_id: int,
    rows: list[PageSchemaOperation],
    *,
    sender: str = "",
    sender_channel: str = "",
) -> None:
    """向已连接的 ops 消费者广播追加结果（尽力而为，失败不影响写入）。

    事件处理器是 ``designer_ops``；``sender_channel`` 非空时发送方连接不会
    收到该事件（由消费者单独回 ack）。
    """
    if not rows:
        return
    payload = {
        "type": "ops",
        "page_id": int(page_id),
        "ops": operations_to_dict(rows),
        "last_seq": int(rows[-1].seq),
        "from": sender or "",
    }
    event = {
        "type": "designer_ops",
        "message": payload,
    }
    if sender_channel:
        event["sender_channel"] = sender_channel
    try:
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(group_for(page_id), event)
    except Exception:  # noqa: BLE001 - 广播失败不阻塞业务写入
        return


__all__ = [
    "OP_KINDS",
    "MAX_BATCH_OPS",
    "MAX_OP_BYTES",
    "MAX_BATCH_BYTES",
    "MAX_CLIENT_ID_LENGTH",
    "DEFAULT_OPS_LIMIT",
    "MAX_OPS_LIMIT",
    "GROUP_PREFIX",
    "SchemaOpValidationError",
    "normalize_client_id",
    "normalize_base_revision",
    "validate_op",
    "validate_batch",
    "parse_cursor",
    "latest_seq",
    "fetch_operations",
    "append_operations",
    "operation_to_dict",
    "operations_to_dict",
    "group_for",
    "broadcast_operations",
]
