"""组件注册表访问（供页面 schema 校验 / 运行时使用）。"""
from django.core.cache import cache

from .models import ComponentMeta

REGISTRY_CACHE_KEY = "component_registry_v2"
REGISTRY_CACHE_SECONDS = 60

COMPONENT_CATEGORIES = [
    {"key": "basic", "label": "基础", "icon": "Grid"},
    {"key": "layout", "label": "布局", "icon": "Layout"},
    {"key": "form", "label": "表单", "icon": "EditPen"},
    {"key": "data", "label": "数据展示", "icon": "DataBoard"},
    {"key": "feedback", "label": "反馈", "icon": "ChatDotRound"},
    {"key": "nav", "label": "导航", "icon": "Compass"},
    {"key": "media", "label": "媒体/富文本", "icon": "Picture"},
    {"key": "chart", "label": "图表", "icon": "TrendCharts"},
    {"key": "advanced", "label": "高级/原生", "icon": "MagicStick"},
    {"key": "custom", "label": "自定义", "icon": "SetUp"},
]


def get_component_registry() -> dict:
    """{component_name: meta_dict}，仅含启用组件；Django cache 缓存 60s。"""
    cached = cache.get(REGISTRY_CACHE_KEY)
    if cached is not None:
        return cached
    registry = {}
    for meta in ComponentMeta.objects.filter(is_enabled=True):
        registry[meta.name] = {
            "name": meta.name,
            "label": meta.label,
            "type": meta.type,
            "category": meta.category,
            "version": meta.version,
            "icon": meta.icon,
            "source": meta.source,
            "element": meta.element,
            "source_url": meta.source_url,
            "is_container": meta.is_container,
            "is_form_field": meta.is_form_field,
            "default_children": meta.default_children or [],
            "actions_supported": meta.actions_supported or [],
            "props_schema": meta.props_schema or {},
            "style_schema": meta.style_schema or {},
            "default_props": meta.default_props or {},
            "events": meta.events or [],
            "provides": meta.provides or [],
            "consumes": meta.consumes or [],
            "payload_schema": meta.payload_schema or {},
            "slots": meta.slots or [],
            "accept_children": meta.accept_children or [],
            "accepts": meta.accept_children or [],
        }
    cache.set(REGISTRY_CACHE_KEY, registry, REGISTRY_CACHE_SECONDS)
    return registry


def invalidate_registry_cache() -> None:
    cache.delete(REGISTRY_CACHE_KEY)


def get_categories() -> list[dict]:
    return list(COMPONENT_CATEGORIES)
