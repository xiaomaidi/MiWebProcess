"""发布普通页面时自动发布其引用的可复用区块。

区块引用以 ``wp-block`` 节点的 props 表示（兼容 ``blockCode`` / ``block_code`` /
``blockId`` / ``block_id``）。本模块负责：

- 递归收集页面 schema 中的区块引用（含区块内嵌区块）；
- 在同一个应用内解析 ``PageBlock`` 与承载 fragment ``Page``；
- 对草稿有内容、且尚未发布相同 schema 的区块，复用
  :func:`pages.services.publish_page` 创建 ``PageVersion``；
- 深度限制（默认 8 层）与环检测，任何区块失败都不阻塞宿主页面发布。

返回值使用普通 dict/list（可直接 JSON 序列化），供发布 API 与管理命令复用。
"""
from __future__ import annotations

import json
from typing import Any, Iterator

from django.db import transaction

from pages.models import Page, PageBlock

MAX_BLOCK_DEPTH = 8
BLOCK_PAGE_PREFIX = "__blocks__/"


def empty_block_report() -> dict:
    """空报告，保证 API 响应字段稳定。"""
    return {
        "published": [],
        "skipped": [],
        "missing": [],
        "cycles": [],
        "depth_limited": [],
        "warnings": [],
        "info": [],
    }


# ---------------------------------------------------------------------------
# schema 工具
# ---------------------------------------------------------------------------
def _schema_equal(left: Any, right: Any) -> bool:
    """稳定比较两个 JSON schema（键顺序无关）。"""
    try:
        return json.dumps(left, sort_keys=True, ensure_ascii=False, default=str) == json.dumps(
            right, sort_keys=True, ensure_ascii=False, default=str
        )
    except (TypeError, ValueError):
        return left == right


def has_meaningful_schema(schema: Any) -> bool:
    """判断草稿 schema 是否有实际内容（不是只有空画布根节点）。

    - 至少有 rootId 且 rootId 在 nodes 中；
    - 默认空画布只有根节点且 props 为空，视为无内容；
    - 根节点为选区节点（非 wp-canvas）或根节点有 props 时，也算有内容。
    """
    if not isinstance(schema, dict):
        return False
    nodes = schema.get("nodes")
    root_id = schema.get("rootId")
    if not isinstance(nodes, dict) or not isinstance(root_id, str) or root_id not in nodes:
        return False
    root = nodes.get(root_id)
    if not isinstance(root, dict):
        return False
    if any(nid != root_id for nid in nodes):
        return True
    if root.get("type") not in (None, "", "wp-canvas"):
        return True
    props = root.get("props")
    return isinstance(props, dict) and bool(props)


def _block_ref_from_node(node: dict, node_id: str) -> dict | None:
    """从单个节点提取 wp-block 引用；兼容 camelCase / snake_case。"""
    if node.get("type") != "wp-block":
        return None
    props = node.get("props")
    if not isinstance(props, dict):
        props = {}

    raw_code = props.get("blockCode")
    if raw_code in (None, ""):
        raw_code = props.get("block_code")
    code = str(raw_code).strip() if raw_code not in (None, "") else ""

    raw_id = props.get("blockId")
    if raw_id in (None, ""):
        raw_id = props.get("block_id")
    block_id = None
    if raw_id not in (None, "", 0, "0"):
        try:
            parsed = int(raw_id)
        except (TypeError, ValueError):
            parsed = 0
        block_id = parsed if parsed > 0 else None

    if not code and block_id is None:
        return {
            "code": "",
            "block_id": None,
            "node_id": str(node_id or node.get("id") or ""),
            "invalid": True,
        }
    return {
        "code": code,
        "block_id": block_id,
        "node_id": str(node_id or node.get("id") or ""),
        "invalid": False,
    }


def iter_block_references(schema: Any) -> Iterator[dict]:
    """递归遍历 schema，产出所有 wp-block 引用（按节点去重）。"""
    if not isinstance(schema, dict):
        return
    seen_refs: set[tuple] = set()
    seen_containers: set[int] = set()

    def walk(value: Any, node_id: str = "") -> Iterator[dict]:
        if isinstance(value, dict):
            if id(value) in seen_containers:
                return
            seen_containers.add(id(value))
            ref = _block_ref_from_node(value, node_id)
            if ref is not None:
                key = (ref["node_id"], ref["code"], ref["block_id"])
                if key not in seen_refs:
                    seen_refs.add(key)
                    yield ref
            for key, child in value.items():
                if key == "nodes" and isinstance(child, dict):
                    for child_id, child_node in child.items():
                        yield from walk(child_node, str(child_id))
                else:
                    yield from walk(child, node_id)
        elif isinstance(value, list):
            if id(value) in seen_containers:
                return
            seen_containers.add(id(value))
            for item in value:
                yield from walk(item, node_id)

    yield from walk(schema)


def _ref_key(ref: dict) -> tuple:
    if ref.get("code"):
        return ("code", str(ref["code"]))
    if ref.get("block_id"):
        return ("id", int(ref["block_id"]))
    return ("invalid", str(ref.get("node_id") or ""))


def _ref_label(ref: dict) -> str:
    if ref.get("code"):
        return str(ref["code"])
    if ref.get("block_id"):
        return f"#{ref['block_id']}"
    return f"node:{ref.get('node_id') or '?'}"


def _block_source_schema(block: PageBlock) -> dict:
    """区块用于继续向下查找嵌套引用的 schema（承载页面优先）。"""
    page = block.page if block.page_id else None
    if page is not None and isinstance(page.schema, dict) and page.schema.get("nodes"):
        return page.schema
    raw = block.schema if isinstance(block.schema, dict) else {}
    if raw.get("nodes") and raw.get("rootId"):
        return raw
    return {}


# ---------------------------------------------------------------------------
# 引用解析 / 图收集
# ---------------------------------------------------------------------------
def resolve_block(app, ref: dict) -> PageBlock | None:
    """在指定应用内按 code 优先、id 兜底解析 PageBlock。"""
    qs = PageBlock.objects.select_related("page").filter(app=app)
    code = str(ref.get("code") or "").strip()
    if code:
        block = qs.filter(code=code).first()
        if block is not None:
            return block
    block_id = ref.get("block_id")
    if block_id:
        block = qs.filter(pk=block_id).first()
        if block is not None:
            return block
    return None


def _is_block_carrier(page: Page) -> bool:
    """区块承载页面：类型 fragment，或位于 __blocks__/ 路径下的旧数据。"""
    return page.type == "fragment" or str(page.path or "").startswith(BLOCK_PAGE_PREFIX)


def collect_block_graph(app, schema: Any, *, max_depth: int = MAX_BLOCK_DEPTH) -> dict:
    """收集页面 schema 的区块引用图（不写库）。

    返回 ``{order, missing, cycles, depth_limited}``：

    - ``order``：可解析的区块，按“嵌套区块在前、引用页最后”的后序排列；
    - ``missing``：code/id 在应用内不存在，或引用缺少 code/id；
    - ``cycles``：引用环（例如 ``a -> b -> a``）；
    - ``depth_limited``：超过 ``max_depth`` 的引用。
    """
    try:
        limit = int(max_depth)
    except (TypeError, ValueError):
        limit = MAX_BLOCK_DEPTH
    limit = max(1, limit)

    result: dict = {"order": [], "missing": [], "cycles": [], "depth_limited": []}
    visited: set[tuple] = set()
    seen_missing: set[tuple] = set()
    seen_cycles: set[tuple] = set()
    seen_depth: set[tuple] = set()

    def walk(current_schema: Any, depth: int, path_keys: set[tuple], path_labels: list[str]) -> None:
        for ref in iter_block_references(current_schema):
            key = _ref_key(ref)
            label = _ref_label(ref)
            if key in path_keys:
                cycle_path = path_labels + [label]
                signature = tuple(cycle_path)
                if signature not in seen_cycles:
                    seen_cycles.add(signature)
                    result["cycles"].append(
                        {
                            "code": ref.get("code") or "",
                            "block_id": ref.get("block_id"),
                            "node_id": ref.get("node_id") or "",
                            "path": cycle_path,
                            "reason": "cycle",
                            "message": f"区块引用存在循环 (cycle): {' -> '.join(cycle_path)}",
                        }
                    )
                continue
            if key in visited:
                continue
            if depth + 1 > limit:
                signature = (key, depth + 1)
                if signature not in seen_depth:
                    seen_depth.add(signature)
                    result["depth_limited"].append(
                        {
                            "code": ref.get("code") or "",
                            "block_id": ref.get("block_id"),
                            "node_id": ref.get("node_id") or "",
                            "depth": depth + 1,
                            "max_depth": limit,
                            "reason": "depth_limit",
                            "message": (
                                f"区块嵌套超过 {limit} 层，已跳过 {label} "
                                f"(depth limit: {depth + 1} > {limit})"
                            ),
                        }
                    )
                continue

            visited.add(key)
            if ref.get("invalid"):
                entry = {
                    "code": "",
                    "block_id": None,
                    "node_id": ref.get("node_id") or "",
                    "reason": "invalid_ref",
                    "message": (
                        f"wp-block 引用缺少 blockCode/blockId（页面节点 "
                        f"{ref.get('node_id') or '?'}）"
                    ),
                }
                if key not in seen_missing:
                    seen_missing.add(key)
                    result["missing"].append(entry)
                continue

            block = resolve_block(app, ref)
            if block is None:
                target = ref.get("code") or (f"#{ref['block_id']}" if ref.get("block_id") else "?")
                entry = {
                    "code": ref.get("code") or "",
                    "block_id": ref.get("block_id"),
                    "node_id": ref.get("node_id") or "",
                    "reason": "missing",
                    "message": (
                        f"区块引用缺失 (missing block): {target}（页面节点 "
                        f"{ref.get('node_id') or '?'}）"
                    ),
                }
                if key not in seen_missing:
                    seen_missing.add(key)
                    result["missing"].append(entry)
                continue

            nested_schema = _block_source_schema(block)
            app_id = getattr(app, "id", app)
            if block.page_id and block.page.app_id != app_id:
                # PageBlock 属当前应用，但承载页面被错误指向别的应用：不递归/不发布。
                nested_schema = {}
            if nested_schema:
                walk(nested_schema, depth + 1, path_keys | {key}, path_labels + [label])
            result["order"].append({"block": block, "ref": ref, "depth": depth + 1})

    walk(schema or {}, 0, set(), [])
    return result


# ---------------------------------------------------------------------------
# 发布
# ---------------------------------------------------------------------------
def _already_published(page: Page, latest: Any = None) -> bool:
    """页面已发布且已有快照与草稿 schema/版本完全一致。"""
    if page.status != "published":
        return False
    candidates = []
    current = page.current_version if page.current_version_id else None
    if current is not None:
        candidates.append(current)
    if latest is not None and (current is None or latest.id != current.id):
        candidates.append(latest)
    for snapshot in candidates:
        if _schema_equal(snapshot.schema, page.schema) and int(
            snapshot.schema_version or 0
        ) == int(page.schema_version or 0):
            return True
    return False


def _publish_block_page(page_id: int, user, changelog: str) -> dict:
    """在独立事务内锁定并发布一个区块页面；不向调用方抛出发布错误。"""
    from pages.services import publish_page

    try:
        with transaction.atomic():
            try:
                page = Page.objects.select_for_update().get(pk=page_id)
            except Page.DoesNotExist:
                return {
                    "page_version": None,
                    "reason": "missing_page",
                    "detail": "承载页面已不存在",
                    "warnings": [],
                }
            if not _is_block_carrier(page):
                return {
                    "page_version": None,
                    "reason": "not_fragment",
                    "detail": "承载页面不是 fragment 类型",
                    "warnings": [],
                }
            if page.status == "archived":
                return {
                    "page_version": None,
                    "reason": "archived",
                    "detail": "承载页面已归档",
                    "warnings": [],
                }
            if not has_meaningful_schema(page.schema):
                return {
                    "page_version": None,
                    "reason": "empty",
                    "detail": "草稿为空",
                    "warnings": [],
                }
            latest = page.versions.order_by("-version").first()
            if _already_published(page, latest):
                return {
                    "page_version": None,
                    "reason": "unchanged",
                    "detail": "已发布相同 schema，未创建新版本",
                    "warnings": [],
                }
            page_version, errors, warnings = publish_page(
                page,
                user,
                changelog,
                auto_blocks=False,
            )
            if page_version is None:
                return {
                    "page_version": None,
                    "reason": "validation_failed",
                    "detail": "; ".join(errors) or "schema 校验失败",
                    "warnings": list(warnings or []),
                }
            return {
                "page_version": page_version,
                "page_path": page.path,
                "reason": "",
                "detail": "",
                "warnings": list(warnings or []),
            }
    except Exception as exc:  # noqa: BLE001 - 区块失败不能影响宿主页面发布
        return {
            "page_version": None,
            "reason": "publish_failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "warnings": [],
        }


def _skipped_entry(block: PageBlock, reason: str, message: str, page: Page | None = None) -> dict:
    return {
        "code": block.code,
        "block_id": block.id,
        "page_id": page.id if page is not None else (block.page_id or None),
        "page_path": page.path if page is not None else "",
        "reason": reason,
        "message": message,
    }


def auto_publish_referenced_blocks(
    page: Page,
    user=None,
    changelog: str = "",
    *,
    max_depth: int = MAX_BLOCK_DEPTH,
) -> dict:
    """发布 ``page`` 引用的区块（递归、限深、环安全），返回结构化报告。

    对每个区块页面在独立事务中 ``select_for_update`` 后判断：
    - 承载页面存在且为 fragment（兼容 ``__blocks__/`` 旧路径）；
    - 草稿 schema 有实际内容；
    - 尚未发布相同 schema/版本（避免重复 PageVersion）。

    区块校验/发布失败只记入 ``warnings`` 与 ``skipped``，不会让宿主页面发布失败。
    """
    report = empty_block_report()
    if page is None or not isinstance(page.schema, dict):
        return report

    graph = collect_block_graph(page.app, page.schema, max_depth=max_depth)
    report["missing"] = graph["missing"]
    report["cycles"] = graph["cycles"]
    report["depth_limited"] = graph["depth_limited"]
    for bucket in ("missing", "cycles", "depth_limited"):
        for entry in graph[bucket]:
            message = str(entry.get("message") or "")
            if message:
                report["warnings"].append(message)

    host_path = str(page.path or f"#{page.id}")

    for item in graph["order"]:
        block: PageBlock = item["block"]
        block_page = block.page if block.page_id else None
        if block_page is None:
            message = f"区块 {block.code} 没有承载页面，跳过自动发布 (no backing page)"
            report["skipped"].append(_skipped_entry(block, "no_page", message, None))
            report["warnings"].append(message)
            continue

        # 先做一次快速判断，避免为显然不可发布的区块开启事务；真正发布时会再次校验。
        if block_page.app_id != page.app_id:
            message = f"区块 {block.code} 的承载页面属于其他应用，跳过自动发布 (cross-app)"
            report["skipped"].append(_skipped_entry(block, "cross_app", message, block_page))
            report["warnings"].append(message)
            continue
        if not _is_block_carrier(block_page):
            message = f"区块 {block.code} 的承载页面不是 fragment，跳过自动发布"
            report["skipped"].append(_skipped_entry(block, "not_fragment", message, block_page))
            report["warnings"].append(message)
            continue
        if block_page.status == "archived":
            message = f"区块 {block.code} 的承载页面已归档，跳过自动发布"
            report["skipped"].append(_skipped_entry(block, "archived", message, block_page))
            report["warnings"].append(message)
            continue
        if not has_meaningful_schema(block_page.schema):
            message = f"区块 {block.code} 草稿为空，跳过自动发布 (empty draft)"
            report["skipped"].append(_skipped_entry(block, "empty", message, block_page))
            report["warnings"].append(message)
            continue

        block_changelog = f"auto: block {block.code} for page {host_path}"
        outcome = _publish_block_page(block_page.id, user, block_changelog)
        page_version = outcome.get("page_version")
        if page_version is not None:
            report["published"].append(
                {
                    "code": block.code,
                    "block_id": block.id,
                    "page_id": page_version.page_id,
                    "page_path": outcome.get("page_path") or block_page.path,
                    "version": page_version.version,
                    "schema_version": page_version.schema_version,
                    "changelog": page_version.changelog,
                }
            )
            report["info"].append(
                f"已自动发布区块 {block.code} (v{page_version.version})"
            )
            continue

        reason = str(outcome.get("reason") or "publish_failed")
        detail = str(outcome.get("detail") or "")
        for warning in outcome.get("warnings") or []:
            if warning:
                report["warnings"].append(f"区块 {block.code}: {warning}")
        if reason == "unchanged":
            report["skipped"].append(
                _skipped_entry(
                    block,
                    "unchanged",
                    f"区块 {block.code} 已发布且 schema 未变化，跳过 (unchanged)",
                    block_page,
                )
            )
            continue
        message = f"区块 {block.code} 自动发布失败 ({reason}): {detail}"
        report["skipped"].append(_skipped_entry(block, reason, message, block_page))
        report["warnings"].append(message)

    return report


def check_block_references(app, schema: Any, *, max_depth: int = MAX_BLOCK_DEPTH) -> dict:
    """只检查引用（不发布），供管理命令 ``--dry-run`` 使用。"""
    return collect_block_graph(app, schema, max_depth=max_depth)


__all__ = [
    "MAX_BLOCK_DEPTH",
    "auto_publish_referenced_blocks",
    "check_block_references",
    "collect_block_graph",
    "empty_block_report",
    "has_meaningful_schema",
    "iter_block_references",
    "resolve_block",
]
