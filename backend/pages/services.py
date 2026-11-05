"""页面草稿/发布业务逻辑。"""
from __future__ import annotations

import uuid

from core.schemas import validate_page_schema
from pages.models import Page, PageVersion
from pages.schema_sync import raise_revision_floor


def default_page_schema() -> dict:
    """新建页面的默认空 schema（根 wp-canvas 节点），保证设计器始终可拖放。"""
    root_id = "root-" + uuid.uuid4().hex[:12]
    return {
        "schemaVersion": 2,
        "rootId": root_id,
        "nodes": {
            root_id: {
                "id": root_id,
                "type": "wp-canvas",
                "componentVersion": "2.0.0",
                "props": {},
                "children": [],
            }
        },
        "variables": {},
        "meta": {"title": "", "lang": "zh-CN", "globalStyle": {"cssVars": {}}},
        "layout": {"mode": "flow", "width": 1200, "height": 800},
    }


def _schema_version_of(schema: dict) -> int:
    v = (schema or {}).get("schemaVersion")
    return int(v) if isinstance(v, int) else 1


def save_draft(page: Page, schema: dict, user=None) -> tuple[Page, list, list]:
    """保存草稿：宽松校验（错误不阻塞，仅记录），version+1。"""
    registry = None
    try:
        from components.services import get_component_registry

        registry = get_component_registry()
    except Exception:
        registry = None
    errors, warnings = validate_page_schema(schema, registry, strict=False)
    page.schema = schema or {}
    page.version += 1
    page.schema_version = _schema_version_of(page.schema)
    # 持久化修订号：AI / 区块 / 人工保存共用，便于实时同步与保存冲突检测。
    page.schema_revision = int(page.schema_revision or 0) + 1
    if user is not None and getattr(user, "is_authenticated", False):
        page.schema_updated_by = user
    page.save(
        update_fields=[
            "schema",
            "version",
            "schema_version",
            "schema_revision",
            "schema_updated_by",
            "updated_at",
        ]
    )
    # 让实时通道的临时 revision 不低于刚保存的持久化 revision。
    raise_revision_floor(page.id, page.schema_revision)
    # 区块承载页面被设计器保存时自动补一个版本快照（无变化时跳过）。
    if page.type == "fragment":
        try:
            from .block_services import create_block_version
            from .models import PageBlock

            block = PageBlock.objects.filter(page=page).first()
            if block is not None:
                create_block_version(block, user=user, changelog="设计器保存", force=False)
        except Exception:
            pass
    return page, errors, warnings


def snapshot_page(page: Page, user=None, changelog: str = "AI 修改前快照") -> PageVersion:
    """保存当前 schema 为版本快照（不改 page.status/version），供 AI 写操作回滚。"""
    last = PageVersion.objects.filter(page=page).order_by("-version").first()
    version = (last.version + 1) if last else 1
    return PageVersion.objects.create(
        page=page,
        version=version,
        schema=page.schema,
        schema_version=page.schema_version,
        publisher=user,
        changelog=changelog or "",
    )


def publish_page(
    page: Page,
    user,
    changelog: str = "",
    *,
    auto_blocks: bool = True,
    block_report: dict | None = None,
) -> tuple[PageVersion, list, list]:
    """严格校验并发布：创建 PageVersion 快照；失败时 errors 非空且不落库。

    ``auto_blocks=True`` 时，发布成功后自动发布页面 schema 引用的可复用区块
    （见 :mod:`pages.block_publish`）。区块发布失败只追加 warnings，不影响本页发布；
    ``block_report`` 传入 dict 时会填充结构化的区块发布报告，供 API 返回。
    区块自身的发布调用使用 ``auto_blocks=False``，避免递归重复触发。
    """
    from components.services import get_component_registry

    registry = get_component_registry()
    errors, warnings = validate_page_schema(page.schema, registry, strict=True)
    if errors:
        return None, errors, warnings
    last = PageVersion.objects.filter(page=page).order_by("-version").first()
    new_version = (last.version + 1) if last else 1
    pv = PageVersion.objects.create(
        page=page,
        version=new_version,
        schema=page.schema,
        schema_version=page.schema_version,
        publisher=user,
        changelog=changelog or "",
    )
    page.current_version = pv
    page.status = "published"
    page.version += 1
    page.save(update_fields=["current_version", "status", "version", "updated_at"])
    if auto_blocks:
        from pages.block_publish import auto_publish_referenced_blocks

        try:
            report = auto_publish_referenced_blocks(page, user, changelog)
        except Exception as exc:  # noqa: BLE001 - 区块失败不能影响宿主页面发布
            report = {
                "published": [],
                "skipped": [],
                "missing": [],
                "cycles": [],
                "depth_limited": [],
                "warnings": [f"自动发布引用区块失败: {type(exc).__name__}: {exc}"],
                "info": [],
            }
        warnings = list(warnings or []) + list(report.get("warnings") or [])
        if block_report is not None:
            block_report.clear()
            block_report.update(report)
    return pv, errors, warnings
