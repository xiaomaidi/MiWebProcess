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

from django.db import IntegrityError, OperationalError, ProgrammingError, transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from pages.models import Page, PageBlock, PageBlockVersion
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
    # 区块创建即产生第一个版本快照，保证版本历史从 v1 开始连续。
    create_block_version(block, user, changelog="创建区块", force=True)
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


# ---------------------------------------------------------------------------
# 区块版本历史（PageBlockVersion）
# ---------------------------------------------------------------------------
def normalize_block_snapshot(raw) -> dict:
    """归一化版本快照，始终返回 ``{"rootId": str, "nodes": dict}`` 的深拷贝。"""
    if not isinstance(raw, dict):
        return {"rootId": "", "nodes": {}}
    nodes = _node_map(raw.get("nodes"))
    root_id = str(raw.get("rootId") or "")
    return {"rootId": root_id, "nodes": copy.deepcopy(nodes)}


def block_snapshot(block: PageBlock) -> dict:
    """区块当前 schema 的版本快照（承载页面优先，回退 block.schema）。"""
    return normalize_block_snapshot(block_schema(block))


def latest_block_version(block: PageBlock) -> PageBlockVersion | None:
    """最新版本快照；没有历史时返回 None。"""
    return block.versions.order_by("-version").first()


def _next_block_version_number(block: PageBlock) -> int:
    current = block.versions.aggregate(peak=Max("version")).get("peak") or 0
    return int(current) + 1


def _snapshot_equal(left, right) -> bool:
    return isinstance(left, dict) and isinstance(right, dict) and left == right


def create_block_version(
    block: PageBlock,
    user=None,
    changelog: str = "",
    *,
    snapshot: dict | None = None,
    force: bool = True,
) -> dict:
    """为区块创建一个版本快照。

    - ``snapshot`` 为空时取当前区块 schema（承载页面草稿优先）；
    - ``force=False`` 且快照与最新版本完全相同时跳过（返回 reason="unchanged"）；
    - 版本号在区块行锁内取 ``max(version)+1``，配合 unique(block, version) 防并发重复。

    返回 ``{version: PageBlockVersion|None, created: bool, reason: str, snapshot: dict}``。
    """
    if block is None or not getattr(block, "pk", None):
        raise ValidationError({"detail": "区块尚未保存，无法创建版本"})
    snap = block_snapshot(block) if snapshot is None else normalize_block_snapshot(snapshot)
    changelog = str(changelog or "")

    with transaction.atomic():
        # 锁定区块行，串行化同一区块的版本号分配。
        locked = PageBlock.objects.select_for_update().filter(pk=block.pk).first()
        if locked is None:
            raise ValidationError({"detail": "区块已不存在，无法创建版本"})
        latest = latest_block_version(block)
        if not force and latest is not None and _snapshot_equal(latest.snapshot, snap):
            return {"version": latest, "created": False, "reason": "unchanged", "snapshot": snap}
        version = PageBlockVersion.objects.create(
            block=block,
            version=_next_block_version_number(block),
            snapshot=snap,
            changelog=changelog,
            created_by=user if getattr(user, "is_authenticated", False) else None,
        )
    return {"version": version, "created": True, "reason": "", "snapshot": snap}


def _empty_page_schema_like(page: Page) -> dict:
    """恢复空画布时保留页面级 meta / variables / layout。"""
    base = default_page_schema()
    old = page.schema if isinstance(page.schema, dict) else {}
    for key in ("variables", "meta", "layout"):
        if isinstance(old.get(key), dict):
            base[key] = copy.deepcopy(old[key])
    return base


def _merge_snapshot_into_page_schema(page: Page, snapshot: dict) -> dict:
    """把 {rootId, nodes} 快照合并进承载页面 schema，保留页面级元数据。"""
    base = copy.deepcopy(page.schema) if isinstance(page.schema, dict) and page.schema else default_page_schema()
    base["rootId"] = snapshot["rootId"]
    base["nodes"] = copy.deepcopy(snapshot["nodes"])
    return base


def rollback_block_version(
    block: PageBlock,
    target: PageBlockVersion,
    user=None,
    changelog: str = "",
) -> dict:
    """把指定版本快照恢复到区块的草稿（承载页面草稿或 block.schema）。

    安全约定：
    - 只写草稿，**不修改已发布的 PageVersion**；承载页面已发布时保持其
      ``status``（公开访问仍使用已发布快照），并在 ``warnings`` 中明确提示；
    - 回滚后自动生成一个新的版本快照，便于审计“回滚”动作。
    """
    if target is None or target.block_id != block.id:
        raise ValidationError({"detail": "版本快照不属于该区块"})
    snapshot = normalize_block_snapshot(target.snapshot)
    page = block.page if block.page_id else None
    warnings: list[str] = []
    info: list[str] = []

    previous_status = page.status if page is not None else None
    was_published = previous_status == "published"
    published_version = None
    if page is not None:
        current = page.current_version if page.current_version_id else None
        if current is None and was_published:
            current = page.versions.order_by("-version").first()
        published_version = current.version if current is not None else None

    has_snapshot = bool(snapshot["rootId"] and snapshot["rootId"] in snapshot["nodes"])
    with transaction.atomic():
        previous_block_version = block.version
        block.version = int(previous_block_version or 0) + 1
        if page is not None:
            if has_snapshot:
                merged = _merge_snapshot_into_page_schema(page, snapshot)
                if not isinstance(merged.get("schemaVersion"), int):
                    merged["schemaVersion"] = int(page.schema_version or 1)
            else:
                merged = _empty_page_schema_like(page)
                warnings.append("该版本快照为空，已恢复为空画布")
            page.schema = merged
            page.schema_version = int(merged.get("schemaVersion") or page.schema_version or 1)
            page.version += 1
            # 保持原状态：已发布页面只回滚草稿，公开内容继续使用已发布快照。
            page.save(update_fields=["schema", "schema_version", "version", "updated_at"])
            block.save(update_fields=["version", "updated_at"])
        else:
            block.schema = copy.deepcopy(snapshot) if has_snapshot else {"rootId": "", "nodes": {}}
            block.save(update_fields=["schema", "version", "updated_at"])

        if was_published:
            warnings.append(
                f"承载页面已发布（已发布快照 v{published_version}），回滚只恢复草稿 schema；"
                "已发布内容与公开访问保持不变，需重新发布后才会生效"
            )
        elif previous_status == "archived":
            warnings.append("承载页面已归档，回滚只恢复其草稿 schema，页面仍保持归档状态")
        if page is not None:
            info.append(f"已恢复承载页面草稿 schema（page v{page.version}）")
        else:
            info.append("已恢复区块兜底 schema（无承载页面）")

        created = create_block_version(
            block,
            user,
            changelog=changelog or f"回滚到 v{target.version}",
            force=False,
        )

    if created["created"]:
        info.append(f"已生成回滚后的版本快照 v{created['version'].version}")
    return {
        "block": block,
        "page": page,
        "target": target,
        "restored_snapshot": snapshot,
        "previous_block_version": previous_block_version,
        "previous_status": previous_status,
        "page_status": page.status if page is not None else None,
        "was_published": was_published,
        "published_version": published_version,
        "published_intact": was_published,
        "new_version": created["version"],
        "new_version_created": created["created"],
        "warnings": warnings,
        "info": info,
    }


# ---------------------------------------------------------------------------
# 市场发布（只依赖 market.models，不改 market 应用）
# ---------------------------------------------------------------------------
MARKET_BLOCK_KIND = "block"
MARKET_STATUS_CHOICES = ("draft", "published")
MARKET_VISIBILITY_CHOICES = ("public", "private")
MARKET_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


class MarketUnavailable(RuntimeError):
    """market 应用不可用（未安装、导入失败或数据表不可用）。"""


def _load_market_item_model():
    """惰性加载 market.models.MarketItem；不可用时抛 MarketUnavailable。"""
    try:
        from market.models import MarketItem
    except Exception as exc:  # noqa: BLE001 - 未安装/配置错误都视为不可用
        raise MarketUnavailable(f"market 应用不可用，无法发布区块: {type(exc).__name__}: {exc}") from exc
    return MarketItem


def normalize_market_slug(raw: str) -> str:
    """把区块 code 归一化为 market 要求的 slug（小写字母/数字/连字符）。"""
    slug = re.sub(r"[^a-z0-9-]+", "-", str(raw or "").strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:100]
    if not slug or not MARKET_SLUG_RE.match(slug):
        raise ValidationError({"slug": "无法从 code 生成合法市场 slug，请显式传入 slug"})
    return slug


def _clean_market_tags(tags) -> list[str]:
    if tags is None:
        return []
    if not isinstance(tags, (list, tuple)):
        raise ValidationError({"tags": "tags 必须是数组"})
    return [str(tag)[:40] for tag in tags if str(tag).strip()][:20]


def _market_item_matches_block(item, block: PageBlock) -> bool:
    """市场条目是否属于该区块（用于 create/update 幂等判定）。"""
    payload = item.payload if isinstance(item.payload, dict) else {}
    info = payload.get("block") if isinstance(payload.get("block"), dict) else {}
    try:
        block_id = int(info.get("id") or payload.get("block_id") or 0)
    except (TypeError, ValueError):
        block_id = 0
    try:
        app_id = int(info.get("app_id") or payload.get("app_id") or 0)
    except (TypeError, ValueError):
        app_id = 0
    if block_id and app_id:
        return block_id == block.id and app_id == block.app_id
    # 兼容历史条目：source_app + code 相同也视作同一区块。
    return bool(
        item.source_app_id
        and item.source_app_id == block.app_id
        and str(payload.get("code") or "") == block.code
    )


def _unique_market_slug(MarketItem, base: str, block: PageBlock) -> tuple[str, object | None]:
    """返回 (slug, 已有且属于本区块的条目)；slug 冲突时自动加序号。"""
    slug = base
    index = 2
    while True:
        item = MarketItem.objects.filter(kind=MARKET_BLOCK_KIND, slug=slug).first()
        if item is None or _market_item_matches_block(item, block):
            return slug, item
        slug = f"{base[:94]}-{index}"
        index += 1


def _market_install_schema(snapshot: dict) -> dict:
    """市场安装用 schema：承载页面快照取其内容子树；否则直接用快照。"""
    nodes = snapshot.get("nodes") if isinstance(snapshot.get("nodes"), dict) else {}
    root_id = str(snapshot.get("rootId") or "")
    root = nodes.get(root_id) if root_id else None
    if isinstance(root, dict) and root.get("type") == "wp-canvas":
        subtree = extract_subtree({"rootId": root_id, "nodes": nodes})
        if subtree.get("rootId") and subtree.get("nodes"):
            return subtree
    return copy.deepcopy(snapshot)


def _market_item_payload(item) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "name": item.name,
        "slug": item.slug,
        "description": item.description,
        "category": item.category,
        "tags": item.tags or [],
        "payload": item.payload or {},
        "status": item.status,
        "visibility": item.visibility,
        "source_app_id": item.source_app_id,
        "created_by_id": item.created_by_id,
        "installs": item.installs,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def publish_block_to_market(
    block: PageBlock,
    user=None,
    *,
    name: str = "",
    slug: str = "",
    status: str | None = None,
    visibility: str | None = None,
    description: str | None = None,
    category: str | None = None,
    tags=None,
    changelog: str = "",
) -> dict:
    """创建或更新 kind=block 的 MarketItem（按 slug 幂等）。

    - payload 含安装所需 ``schema``（{rootId, nodes}）与 name/code/版本元信息；
    - 同一区块重复发布会更新原条目（payload.block.id/app_id 匹配）；
    - ``status`` / ``visibility`` 省略时保留条目原值（新条目默认 draft/public），
      避免重复发布时意外下架或公开；
    - market 不可用时抛 :class:`MarketUnavailable`。
    """
    MarketItem = _load_market_item_model()

    status_value = str(status).strip().lower() if status not in (None, "") else None
    if status_value is not None and status_value not in MARKET_STATUS_CHOICES:
        raise ValidationError({"status": "status 只能是 draft 或 published"})
    visibility_value = str(visibility).strip().lower() if visibility not in (None, "") else None
    if visibility_value is not None and visibility_value not in MARKET_VISIBILITY_CHOICES:
        raise ValidationError({"visibility": "visibility 只能是 public 或 private"})
    clean_tags = _clean_market_tags(tags)

    explicit_slug = bool(str(slug or "").strip())
    base_slug = normalize_market_slug(slug or block.code)
    snapshot = block_snapshot(block)
    if not snapshot["rootId"] or snapshot["rootId"] not in snapshot["nodes"]:
        raise ValidationError({"detail": "区块还没有内容（schema 为空），无法发布到市场"})

    # 发布前确保当前 schema 有对应版本快照（schema 未变化时复用最新版本）。
    version_result = create_block_version(
        block,
        user,
        changelog=changelog or f"发布到市场 {base_slug}",
        force=False,
    )
    version_obj = version_result["version"]
    version_number = int(version_obj.version) if version_obj is not None else 0

    final_name = str(name or block.name)[:160]
    final_description = str(description if description is not None else block.description or "")
    final_category = str(category or "")[:60]

    try:
        if explicit_slug:
            # 显式 slug：被其它区块占用时明确报错，而不是静默改名。
            item = MarketItem.objects.filter(kind=MARKET_BLOCK_KIND, slug=base_slug).first()
            if item is not None and not _market_item_matches_block(item, block):
                raise ValidationError(
                    {"slug": f"市场 slug {base_slug} 已被其它条目占用，请换一个 slug"}
                )
            final_slug = base_slug
        else:
            final_slug, item = _unique_market_slug(MarketItem, base_slug, block)
    except (ProgrammingError, OperationalError) as exc:
        raise MarketUnavailable(f"market 数据表不可用: {type(exc).__name__}: {exc}") from exc

    install_schema = _market_install_schema(version_result["snapshot"])
    payload = {
        "schema": install_schema,
        "name": block.name,
        "code": block.code,
        "kind": MARKET_BLOCK_KIND,
        "version": version_number,
        "block": {
            "id": block.id,
            "code": block.code,
            "app_id": block.app_id,
            "version": version_number,
            "block_version": int(block.version or 0),
        },
        "meta": {
            "app_code": getattr(block.app, "code", "") if block.app_id else "",
            "block_code": block.code,
            "block_id": block.id,
            "node_count": len(version_result["snapshot"].get("nodes") or {}),
            "published_at": timezone.now().isoformat(),
        },
    }

    created = item is None
    # 省略 status/visibility 时保留条目原值；新条目默认 draft/public。
    final_status = status_value or (
        item.status if item is not None and item.status in MARKET_STATUS_CHOICES else "draft"
    )
    final_visibility = visibility_value or (
        item.visibility if item is not None and item.visibility in MARKET_VISIBILITY_CHOICES else "public"
    )
    try:
        with transaction.atomic():
            if item is None:
                item = MarketItem(kind=MARKET_BLOCK_KIND, slug=final_slug, created_by=user)
            item.name = final_name
            item.description = final_description
            if category is not None or created:
                item.category = final_category if category is not None else ""
            if tags is not None or created:
                item.tags = clean_tags
            item.payload = payload
            item.status = final_status
            item.visibility = final_visibility
            item.source_app = block.app if block.app_id else None
            item.save()
    except IntegrityError as exc:
        raise ValidationError({"slug": f"市场 slug {final_slug} 已存在"}) from exc
    except (ProgrammingError, OperationalError) as exc:
        raise MarketUnavailable(f"market 数据表不可用: {type(exc).__name__}: {exc}") from exc

    warnings: list[str] = []
    if not version_result["created"] and version_result["reason"] == "unchanged":
        warnings.append("当前 schema 与最新版本一致，复用最新版本快照")
    return {
        "item": _market_item_payload(item),
        "item_id": item.id,
        "created": created,
        "updated": not created,
        "slug": item.slug,
        "status": item.status,
        "visibility": item.visibility,
        "version": version_number,
        "block_version": int(block.version or 0),
        "warnings": warnings,
    }

