"""共享组件注册表读取与 v2 紧凑格式归一化。

shared/component-registry.json 是前后端唯一事实源：
- 旧版条目可直接带 props_schema；
- 新版条目用紧凑 props：{"text": ["string", "文字", "按钮"]}；
归一化后写入 ComponentMeta（props_schema 等），与前端 normalizeRegistry 保持一致。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STANDARD_ACTIONS = [
    "setVariable", "callDatasource", "navigate", "openModal", "openDrawer", "closeDrawer",
    "message", "notification", "confirm", "record", "condition", "loop", "parallel",
    "tryCatch", "delay", "setStyle", "emit", "submitForm", "resetForm", "download",
    "copy", "print", "http", "js",
]

NATIVE_TAGS = {
    "div", "section", "article", "header", "footer", "main", "nav", "aside", "span",
    "p", "a", "img", "video", "audio", "iframe", "canvas", "svg", "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "td", "th", "form", "label", "strong", "em", "br", "hr",
}


def _infer_source(raw: dict) -> str:
    if raw.get("source"):
        return raw["source"]
    name = raw.get("name", "")
    if name.startswith("wp-"):
        return "legacy"
    if name.startswith("chart-"):
        return "chart"
    if name in {"rich-text", "markdown", "code-block"}:
        return "rich"
    if name in {"html", "component-slot", "repeater", "conditional", "portal"}:
        return "advanced"
    if name in NATIVE_TAGS:
        return "native"
    return "element-plus"


def _default_ui(prop: dict) -> str:
    if prop.get("x-ui") or prop.get("ui"):
        return prop.get("x-ui") or prop.get("ui")
    t = prop.get("type") or prop.get("t") or "string"
    if prop.get("enum"):
        return "select"
    if t == "boolean":
        return "switch"
    if t in ("number", "integer"):
        return "number"
    if t in ("array", "object"):
        return "json"
    return ""


def _normalize_prop(key: str, spec: Any) -> dict:
    if isinstance(spec, str):
        return {"type": "string", "title": key, "default": spec}
    if isinstance(spec, list):
        typ = spec[0] if len(spec) > 0 and isinstance(spec[0], str) else "string"
        title = spec[1] if len(spec) > 1 and isinstance(spec[1], str) else key
        out: dict[str, Any] = {"type": typ, "title": title}
        if len(spec) > 2 and spec[2] is not None:
            out["default"] = spec[2]
        extra = spec[3] if len(spec) > 3 and isinstance(spec[3], dict) else {}
        if extra:
            if extra.get("description"):
                out["description"] = extra["description"]
            if "enum" in extra:
                out["enum"] = extra["enum"]
            for src, dst in (("minimum", "minimum"), ("maximum", "maximum"), ("multipleOf", "multipleOf")):
                if src in extra:
                    out[dst] = extra[src]
            if "items" in extra:
                out["items"] = extra["items"]
            if "properties" in extra:
                out["properties"] = extra["properties"]
            ui = extra.get("x-ui") or extra.get("ui")
            if ui:
                out["x-ui"] = ui
            group = extra.get("x-group") or extra.get("g")
            if group:
                out["x-group"] = group
            bindable = extra.get("x-bindable", extra.get("b"))
            if bindable is not None:
                out["x-bindable"] = bindable
            options = extra.get("x-options") or extra.get("options")
            if options:
                out["x-options"] = options
        ui = _default_ui(out)
        if ui and "x-ui" not in out:
            out["x-ui"] = ui
        return out
    if isinstance(spec, dict):
        out = {
            "type": spec.get("type") or spec.get("t") or "string",
            "title": spec.get("title") or key,
        }
        if spec.get("default", spec.get("d")) is not None:
            out["default"] = spec.get("default", spec.get("d"))
        if spec.get("description"):
            out["description"] = spec["description"]
        for key_name in ("enum", "minimum", "maximum", "multipleOf", "items", "properties"):
            if key_name in spec:
                out[key_name] = spec[key_name]
        ui = spec.get("x-ui") or spec.get("ui") or _default_ui(out)
        if ui:
            out["x-ui"] = ui
        group = spec.get("x-group") or spec.get("g")
        if group:
            out["x-group"] = group
        bindable = spec.get("x-bindable", spec.get("b"))
        if bindable is not None:
            out["x-bindable"] = bindable
        options = spec.get("x-options") or spec.get("options")
        if options:
            out["x-options"] = options
        return out
    return {"type": "string", "title": key}


def build_props_schema(raw: dict) -> dict:
    if isinstance(raw.get("props_schema"), dict) and raw["props_schema"].get("properties"):
        return raw["props_schema"]
    props = raw.get("props") or {}
    return {
        "type": "object",
        "properties": {key: _normalize_prop(key, spec) for key, spec in props.items()},
    }


def normalize_registry(raw: dict) -> dict:
    common_style = raw.get("style_schema") or {
        "preset": "common",
        "groups": ["layout", "size", "spacing", "typography", "background", "border", "effect"],
        "responsive": True,
    }
    components = []
    for c in raw.get("components") or []:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        category = c.get("category") or "custom"
        accepts = c.get("accepts", c.get("accept_children") or [])
        if not isinstance(accepts, list):
            accepts = []
        is_container = bool(c.get("container", len(accepts) > 0))
        slots = c.get("slots")
        if slots is None:
            slots = ["default"] if is_container else []
        components.append(
            {
                "name": c["name"],
                "label": c.get("label") or c["name"],
                "type": c.get("type") or category,
                "category": category,
                "version": c.get("version") or "2.0.0",
                "icon": c.get("icon") or "",
                "source": _infer_source(c),
                "element": c.get("element") or c["name"],
                "is_container": is_container,
                "is_form_field": bool(c.get("form", False)),
                "default_children": c.get("default_children") or [],
                "actions_supported": c.get("actions") or STANDARD_ACTIONS,
                "props_schema": build_props_schema(c),
                "style_schema": {**common_style, **(c.get("style") or {})},
                "default_props": c.get("default_props") or {},
                "events": c.get("events") or ["click"],
                "slots": slots,
                "accept_children": accepts,
                "accepts": accepts,
            }
        )
    return {
        "version": raw.get("version") or "2.0.0",
        "schemaVersion": raw.get("schemaVersion") or 2,
        "categories": raw.get("categories") or [],
        "style_schema": common_style,
        "components": components,
    }


def load_registry(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return normalize_registry(data)
