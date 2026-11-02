"""页面草稿/发布业务逻辑。"""
from __future__ import annotations

import uuid

from core.schemas import validate_page_schema
from pages.models import Page, PageVersion


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
    page.save(update_fields=["schema", "version", "schema_version", "updated_at"])
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


def publish_page(page: Page, user, changelog: str = "") -> tuple[PageVersion, list, list]:
    """严格校验并发布：创建 PageVersion 快照；失败时 errors 非空且不落库。"""
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
    return pv, errors, warnings
