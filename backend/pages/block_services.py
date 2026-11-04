"""可复用页面区块（PageBlock）的 schema 辅助与创建逻辑。

区块 schema 统一表示为节点子树 ``{"rootId": str, "nodes": {id: node}}``：

- 有承载页面（``Page.type == "fragment"``，路径 ``__blocks__/<code>``）时，区块以页面
  ``schema`` 为准，因此可直接在现有设计器中打开编辑；
- 无承载页面时使用 ``PageBlock.schema`` 中的子树兜底。

从页面选区创建区块时会深拷贝被选节点，并用 ``blk-<code>-`` 前缀重写节点 id，
避免与目标页面已有节点冲突（渲染时前端还会按实例再加一层前缀）。
"""
from __future__ import annotations

import copy
import re
import uuid

from rest_framework.exceptions import ValidationError

from pages.models import Page, PageBlock
from pages.services import default_page_schema

BLOCK_PAGE_PREFIX = "__blocks__"
BLOCK_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")


# ---------------------------------------------------------------------------
# 通用节点树工具
# ---------------------------------------------------------------------------
def _node_map(nodes) -> dict:
    if not isinstance(nodes, dict):
        return {}
    return {str(k): v for k, v in nodes.items() if isinstance(v, dict)}


def _child_ids(node: dict) -> list[str]:
    out: list[str] = []
    for cid in node.get("children") or []:
        if isinstance(cid, str):
            out.append(cid)
    for ids in (node.get("slots") or {}).values():
        if isinstance(ids, list):
            out.extend([cid for cid in ids if isinstance(cid, str)])
    return out


def normalize_subtree(raw) -> dict:
    """校验并归一化子树，返回 ``{"rootId": str, "nodes": dict}``。

    只保留从 rootId 可达的节点；悬空的 children/slots 引用会被裁掉。
    """
    if not isinstance(raw, dict):
        raise ValidationError({"detail": "schema 必须是 {rootId, nodes} 对象"})
    nodes = _node_map(raw.get("nodes"))
    root_id = str(raw.get("rootId") or "").strip()
    if not root_id or root_id not in nodes:
        raise ValidationError({"detail": "schema.rootId 必须存在于 nodes 中"})
    kept: dict[str, dict] = {}

    def walk(nid: str) -> None:
        node = nodes.get(nid)
        if not isinstance(node, dict) or nid in kept:
            return
        clone = copy.deepcopy(node)
        clone["id"] = nid
        children = [cid for cid in (clone.get("children") or []) if cid in nodes]
        clone["children"] = children
        slots = {}
        for name, ids in (clone.get("slots") or {}).items():
            if isinstance(ids, list):
                kept_ids = [cid for cid in ids if cid in nodes]
                if kept_ids:
                    slots[str(name)] = kept_ids
        clone["slots"] = slots
        kept[nid] = clone
        for cid in children:
            walk(cid)
        for ids in slots.values():
            for cid in ids:
                walk(cid)

    walk(root_id)
    return {"rootId": root_id, "nodes": kept}


def prefix_subtree_ids(subtree: dict, prefix: str) -> dict:
    """给子树内所有节点 id 加前缀并重写 children/slots 引用。"""
    normalized = normalize_subtree(subtree)
    if not prefix:
        return normalized
    mapping = {old: f"{prefix}{old}" for old in normalized["nodes"]}
    out: dict[str, dict] = {}
    for old_id, node in normalized["nodes"].items():
        clone = copy.deepcopy(node)
        clone["id"] = mapping[old_id]
        clone["children"] = [mapping[cid] for cid in node.get("children") or [] if cid in mapping]
        slots = {}
        for name, ids in (node.get("slots") or {}).items():
            kept = [mapping[cid] for cid in ids if cid in mapping]
            if kept:
                slots[str(name)] = kept
        clone["slots"] = slots
        out[mapping[old_id]] = clone
    return {"rootId": mapping[normalized["rootId"]], "nodes": out}


def _parent_map(nodes: dict) -> dict[str, str]:
    parents: dict[str, str] = {}
    for pid, node in nodes.items():
        for cid in _child_ids(node):
            parents.setdefault(cid, pid)
    return parents


def _top_level(ids: list[str], nodes: dict) -> list[str]:
    """过滤掉“祖先也被选中”的节点，避免重复拷贝子树。"""
    parents = _parent_map(nodes)
    selected = set(ids)
    out: list[str] = []
    for nid in ids:
        if nid not in nodes or nid in out:
            continue
        parent = parents.get(nid)
        drop = False
        while parent:
            if parent in selected:
                drop = True
                break
            parent = parents.get(parent)
        if not drop:
            out.append(nid)
    return out


def extract_subtree(schema: dict, node_ids=None) -> dict:
    """从页面 schema 中提取选区子树。

    ``node_ids`` 为空时取根画布的直接子节点；否则取指定节点（自动去掉已被祖先覆盖的节点）。
    返回 ``{"rootId": str, "nodes": dict}``，rootId 为选区根节点；多个根时使用一个
    合成的 ``wp-container`` 作为根（便于作为单棵子树渲染/存储）。
    """
    if not isinstance(schema, dict):
        schema = {}
    nodes = _node_map(schema.get("nodes"))
    root_id = str(schema.get("rootId") or "")
    if not nodes:
        return {"rootId": "", "nodes": {}}

    wanted = [str(n) for n in (node_ids or []) if isinstance(n, str) and n]
    if not wanted:
        root = nodes.get(root_id) or {}
        wanted = [cid for cid in (root.get("children") or []) if cid in nodes]
    tops = _top_level(wanted, nodes)
    if not tops:
        return {"rootId": "", "nodes": {}}

    copied: dict[str, dict] = {}

    def walk(nid: str) -> None:
        if nid in copied or nid not in nodes:
            return
        node = nodes[nid]
        clone = copy.deepcopy(node)
        clone["id"] = nid
        children = [cid for cid in (clone.get("children") or []) if cid in nodes]
        clone["children"] = children
        slots = {}
        for name, ids in (clone.get("slots") or {}).items():
            if not isinstance(ids, list):
                continue
            kept = [cid for cid in ids if cid in nodes]
            if kept:
                slots[str(name)] = kept
        clone["slots"] = slots
        copied[nid] = clone
        for cid in children:
            walk(cid)
        for ids in slots.values():
            for cid in ids:
                walk(cid)

    for nid in tops:
        walk(nid)

    if len(tops) == 1:
        return {"rootId": tops[0], "nodes": copied}

    wrapper_id = "block-group-" + uuid.uuid4().hex[:10]
    wrapper = {
        "id": wrapper_id,
        "type": "wp-container",
        "componentVersion": "2.0.0",
        "props": {},
        "children": list(tops),
    }
    copied[wrapper_id] = wrapper
    return {"rootId": wrapper_id, "nodes": copied}


def subtree_into_schema(subtree: dict, name: str = "") -> dict:
    """把子树挂到一张新的页面画布下（返回完整页面 schema）。"""
    schema = default_page_schema()
    if name:
        meta = schema.setdefault("meta", {})
        meta["title"] = name
    normalized = normalize_subtree(subtree) if subtree and subtree.get("nodes") else {"rootId": "", "nodes": {}}
    root = schema["nodes"][schema["rootId"]]
    if normalized["nodes"]:
        schema["nodes"].update(normalized["nodes"])
        root["children"] = [normalized["rootId"]]
    return schema


def node_count(schema: dict) -> int:
    nodes = _node_map((schema or {}).get("nodes"))
    return len(nodes)


# ---------------------------------------------------------------------------
# 区块 schema / 编码
# ---------------------------------------------------------------------------
def block_schema(block: PageBlock) -> dict:
    """区块 schema：承载页面的 schema 优先，其次 block.schema 兜底。"""
    page = block.page if block.page_id else None
    page_schema = (page.schema or {}) if page is not None else {}
    if isinstance(page_schema, dict) and page_schema.get("rootId") and page_schema.get("nodes"):
        return page_schema
    raw = block.schema or {}
    if isinstance(raw, dict) and raw.get("rootId") and raw.get("nodes"):
        try:
            return normalize_subtree(raw)
        except ValidationError:
            return {"rootId": "", "nodes": {}}
    return {"rootId": "", "nodes": {}}


def block_page_path(code: str) -> str:
    return f"{BLOCK_PAGE_PREFIX}/{code}"


def normalize_block_code(raw: str) -> str:
    code = str(raw or "").strip()
    if not code:
        return ""
    if not BLOCK_CODE_RE.match(code):
        raise ValidationError({"code": "code 只能包含字母、数字、下划线和连字符，长度 1-80"})
    return code


def slug_block_code(name: str) -> str:
    base = _SLUG_RE.sub("-", str(name or "").strip()).strip("-_").lower()
    if not base:
        base = "block"
    base = base[:60]
    return base or "block"


def unique_block_code(app, base: str) -> str:
    code = base
    index = 2
    while PageBlock.objects.filter(app=app, code=code).exists():
        code = f"{base}-{index}"[:80]
        index += 1
    return code


def _unique_path(app, path: str) -> str:
    candidate = path
    index = 2
    while Page.objects.filter(app=app, path=candidate).exists():
        candidate = f"{path}-{index}"
        index += 1
    return candidate


# ---------------------------------------------------------------------------
# 创建 / 更新 / 删除
# ---------------------------------------------------------------------------
def create_block(
    app,
    user,
    *,
    name: str,
    code: str = "",
    description: str = "",
    source_page: Page | None = None,
    node_ids=None,
    source_schema: dict | None = None,
) -> tuple[PageBlock, Page, list[str]]:
    """创建区块 + 承载 fragment 页面（从可选来源节点拷贝）。

    ``source_page`` + ``node_ids``：从既有页面选区拷贝；
    ``source_schema``：直接给出 {rootId, nodes} 子树；
    都没有时创建空区块（空白画布，可在设计器中编辑）。
    """
    warnings: list[str] = []
    name = str(name or "").strip()
    if not name:
        raise ValidationError({"name": "name 必填"})
    requested = normalize_block_code(code)
    base = requested or slug_block_code(name)
    final_code = unique_block_code(app, base)
    if requested and final_code != requested:
        warnings.append(f"code {requested} 已存在，已自动改为 {final_code}")

    if source_page is not None:
        subtree = extract_subtree(source_page.schema or {}, node_ids)
    elif source_schema is not None:
        subtree = normalize_subtree(source_schema)
    else:
        subtree = {"rootId": "", "nodes": {}}

    if subtree.get("nodes"):
        subtree = prefix_subtree_ids(subtree, f"blk-{final_code}-")

    page_schema = subtree_into_schema(subtree, name=name)
    path = _unique_path(app, block_page_path(final_code))
    if path != block_page_path(final_code):
        warnings.append(f"区块路径 {block_page_path(final_code)} 已被占用，已改用 {path}")

    page = Page.objects.create(
        app=app,
        name=name,
        path=path,
        type="fragment",
        status="draft",
        schema=page_schema,
        schema_version=int(page_schema.get("schemaVersion") or 2),
    )
    block = PageBlock.objects.create(
        app=app,
        name=name,
        code=final_code,
        description=str(description or ""),
        page=page,
        schema=copy.deepcopy(page_schema),
        version=1,
        created_by=user,
    )
    return block, page, warnings


def sync_block_page_path(block: PageBlock, new_code: str) -> None:
    """code 变更后同步承载页面路径（仅限 ``__blocks__/`` 下的 fragment 页面）。"""
    page = block.page if block.page_id else None
    if page is None or page.type != "fragment":
        return
    if not page.path.startswith(f"{BLOCK_PAGE_PREFIX}/"):
        return
    target = block_page_path(new_code)
    if page.app_id != block.app_id or page.path == target:
        return
    if Page.objects.filter(app_id=block.app_id, path=target).exclude(id=page.id).exists():
        raise ValidationError({"detail": f"区块路径 {target} 已存在"})
    page.path = target
    page.save(update_fields=["path", "updated_at"])


def archive_block_page(block: PageBlock) -> Page | None:
    """默认删除语义：保留承载页面（归档），避免误删设计稿。"""
    page = block.page if block.page_id else None
    if page is None:
        return None
    if page.status != "archived":
        page.status = "archived"
        page.save(update_fields=["status", "updated_at"])
    return page


def delete_block_page_if_safe(block: PageBlock) -> bool:
    """显式确认删除时，才删除专用 fragment 页面（且无其它区块引用）。"""
    page = block.page if block.page_id else None
    if page is None or page.type != "fragment" or not page.path.startswith(f"{BLOCK_PAGE_PREFIX}/"):
        return False
    if PageBlock.objects.filter(page=page).exclude(id=block.id).exists():
        return False
    page.delete()
    return True


def rewrite_block_references(app, old_code: str, new_code: str) -> int:
    """Rewrite wp-block reference props in all draft page schemas after code rename."""
    if not old_code or not new_code or old_code == new_code:
        return 0
    changed = 0
    for page in Page.objects.filter(app=app).exclude(type="fragment"):
        schema = page.schema or {}
        nodes = schema.get("nodes") or {}
        page_changed = False
        for node in nodes.values():
            if not isinstance(node, dict) or node.get("type") != "wp-block":
                continue
            props = node.get("props") or {}
            if str(props.get("blockCode") or props.get("block_code") or "") == old_code:
                props["blockCode"] = new_code
                props.pop("block_code", None)
                node["props"] = props
                page_changed = True
        if page_changed:
            page.schema = schema
            page.save(update_fields=["schema", "updated_at"])
            changed += 1
    return changed
