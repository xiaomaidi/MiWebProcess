"""AI 任意页面布局生成：仪表盘、复杂表单、自定义落地页。

与固定模板不同，这里把真实组件目录、数据模型字段和样例数据交给 LLM，
让它直接产出可渲染的页面 Schema；没有 Provider 时用真实组件做确定性回退。
"""
from __future__ import annotations

import copy
import json
import re
import urllib.request
from typing import Any

from rest_framework.exceptions import ValidationError

from components.models import ComponentMeta

# 优先暴露给 LLM 的组件：覆盖布局、内容、图表、表格、表单。
PREFERRED = [
    "wp-canvas", "site-nav", "ElContainer", "ElRow", "ElCol", "ElCard", "ElDivider",
    "wp-heading", "wp-text", "wp-image", "ElTag", "ElButton",
    "content-list", "article-detail", "site-search",
    "report-table", "wp-table", "ElTable", "ElStatistic", "ElProgress", "wp-statcard",
    "wp-barchart", "wp-piechart", "chart-bar", "chart-line", "chart-pie",
    "auto-form", "ElDescriptions", "ElTimeline", "ElTimelineItem", "ElTabs", "ElTabPane",
]


def _node(node_id: str, node_type: str, props: dict | None = None, children: list[str] | None = None,
          style: dict | None = None, version: str = "2.0.0") -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "componentVersion": version,
        "props": props or {},
        "children": children or [],
        **({"style": style} if style else {}),
    }


def _catalog() -> list[dict]:
    rows = list(ComponentMeta.objects.filter(is_enabled=True, name__in=PREFERRED).values(
        "name", "label", "category", "is_container", "props_schema", "default_props", "version",
    ))
    order = {name: index for index, name in enumerate(PREFERRED)}
    rows.sort(key=lambda row: order.get(row["name"], 999))
    catalog = []
    for row in rows:
        schema = row.get("props_schema") if isinstance(row.get("props_schema"), dict) else {}
        props = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        keys = []
        for key, spec in list(props.items())[:18]:
            if not isinstance(spec, dict):
                continue
            item = {"key": key, "type": spec.get("type") or "string"}
            if spec.get("enum"):
                item["enum"] = spec["enum"][:8]
            if spec.get("default") is not None:
                item["default"] = spec["default"]
            keys.append(item)
        catalog.append({
            "name": row["name"], "label": row["label"], "category": row.get("category"),
            "container": bool(row.get("is_container")), "props": keys,
        })
    return catalog


def _versions() -> dict[str, str]:
    return dict(ComponentMeta.objects.filter(is_enabled=True).values_list("name", "version"))


def _model_payload(models: list) -> list[dict]:
    from datamodels.models import DataRecord

    payload = []
    for model in models[:8]:
        fields = []
        for field in model.fields or []:
            if isinstance(field, dict):
                fields.append({
                    "name": field.get("name"), "type": field.get("type"),
                    "label": field.get("label") or field.get("name"),
                })
        samples = []
        for record in DataRecord.objects.filter(model=model).order_by("-id")[:3]:
            data = record.data or {}
            samples.append({key: data.get(key) for key in list(data)[:12]})
        payload.append({
            "id": model.id, "name": model.name,
            "count": DataRecord.objects.filter(model=model).count(),
            "fields": fields, "samples": samples,
        })
    return payload


def _prompt(app_name: str, page: dict, kind: str, models: list[dict], palette: dict,
            nav_links: list[dict], site_prompt: str) -> str:
    return f"""你是 MiWebProcess 的资深页面设计师。请生成一个可直接发布的页面 Schema。

站点：{app_name}
页面：{page.get('name')}（路径 /{page.get('path')}）
页面类型：{kind}
页面目标：{page.get('layout_brief') or page.get('title') or page.get('description') or kind}
站点需求：{site_prompt}

主题色：
- 背景 {palette.get('bg')}
- 卡片 {palette.get('surface')}
- 主色 {palette.get('hero')}
- 标题 {palette.get('title')}
- 正文 {palette.get('text')}

导航链接：{json.dumps(nav_links, ensure_ascii=False)}

数据模型（dataModelId/modelId 只能使用这些 id）：
{json.dumps(models, ensure_ascii=False)}

可用组件（只能使用这些 type，props 只能用列出的 key）：
{json.dumps(_catalog(), ensure_ascii=False)}

硬性要求：
1. 只输出 JSON，不要 Markdown；结构：
   {{"schemaVersion":2,"rootId":"root","nodes":{{...}},"layout":{{"mode":"flow","width":1200,"height":900}},"variables":{{}},"meta":{{"title":"","description":""}}}}
2. root 必须是 wp-canvas；所有 children 必须引用存在的节点；节点总数 12-60。
3. 必须有 site-nav（brand={app_name}，links 用上面的导航）和页脚 wp-text。
4. 仪表盘/dashboard：必须有 1 个隐藏的 content-list 数据加载器（dataModelId 真实，pageSize 6，
   showPagination=false，style.display=none）；至少 2 个 KPI 卡片（wp-statcard 或 ElStatistic）；
   图表用 report-table（dataModelId 真实，groupBy 用分类/状态字段，metrics 用 "count" 或 "sum:数值字段"，
   showChart=true，chartType=bar/pie，limit=6）；底部 1 个 wp-table 明细。
5. 复杂表单/form：用 auto-form，modelId 必须真实；mode=create；columns=2；submitText 明确；
   旁边可加说明卡片。表单页需要登录后提交。
6. 自定义页面/custom/landing：用 ElRow/ElCol + ElCard 做非对称布局，至少包含首屏、2 个内容区、1 个数据区（content-list/report-table）。
7. 不要 script/iframe/onclick/javascript:；不要使用未列出的组件；不要编造 dataModelId。
8. 中文文案，层级清晰，留白充分；颜色用主题色，不要纯白刺眼。
"""


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text or "").strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValidationError({"detail": "AI 未返回 JSON"})
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValidationError({"detail": "AI 返回的页面不是对象"})
    return value


def _call_llm(prompt: str) -> dict:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置 AI Provider"})
    cfg = chat_config()
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": "你只返回严格 JSON，不返回 Markdown。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.35,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
    content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    return _parse_json(content)


def _first_model(models: list) -> Any:
    return models[0] if models else None


def _first_text_field(model) -> str:
    for field in model.fields or []:
        if isinstance(field, dict) and field.get("type") in ("string", "reference"):
            return str(field.get("name") or "")
    return ""


def _first_number_field(model) -> str:
    if model is None:
        return ""
    names = [str(field.get("name") or "") for field in (model.fields or []) if isinstance(field, dict)]
    for name in ("price", "amount", "value", "total", "change", "pct_change", "score", "count"):
        if name in names:
            return name
    for field in model.fields or []:
        if isinstance(field, dict) and field.get("type") == "number" and field.get("name") not in ("ranking", "id"):
            return str(field.get("name") or "")
    return ""


def _group_field(model) -> str:
    if model is None:
        return ""
    names = [str(field.get("name") or "") for field in (model.fields or []) if isinstance(field, dict)]
    for name in ("category", "type", "status", "kind", "industry", "market", "name", "title", "symbol"):
        if name in names:
            return name
    return _first_text_field(model)


def _sample_stats(model) -> dict:
    from datamodels.models import DataRecord

    records = list(DataRecord.objects.filter(model=model).order_by("-id")[:200])
    count = DataRecord.objects.filter(model=model).count()
    numbers = []
    number_field = _first_number_field(model)
    for record in records:
        value = (record.data or {}).get(number_field)
        try:
            numbers.append(float(value))
        except (TypeError, ValueError):
            continue
    total = sum(numbers) if numbers else 0
    return {
        "count": count,
        "number_field": number_field,
        "sum": round(total, 2),
        "avg": round(total / len(numbers), 2) if numbers else 0,
        "max": round(max(numbers), 2) if numbers else 0,
    }


def _chrome(ctx: dict, app_name: str, palette: dict, nav_links: list[dict], versions: dict[str, str]):
    nav = _node("ai-nav", "site-nav", {
        "brand": app_name, "homePath": "home", "sticky": True,
        "dark": bool(palette.get("dark")), "showSearch": True, "searchPath": "search",
        "links": nav_links,
    }, version=versions.get("site-nav", "2.0.0"))
    footer = _node("ai-footer", "ElContainer", {
        "direction": "vertical", "padding": 20, "background": palette.get("surface"),
    }, ["ai-footer-text"], {"marginTop": "24px"}, version=versions.get("ElContainer", "2.0.0"))
    footer_text = _node("ai-footer-text", "wp-text", {
        "content": f"© {app_name} · AI 生成", "align": "center",
        "color": palette.get("text"), "fontSize": 12,
    }, version=versions.get("wp-text", "2.0.0"))
    return nav, footer, footer_text


def _local_dashboard(ctx: dict, page: dict, model, palette: dict, nav_links: list[dict],
                     versions: dict[str, str]) -> dict:
    app_name = ctx["site_name"]
    stats = _sample_stats(model) if model is not None else {"count": 0, "sum": 0, "avg": 0, "max": 0}
    text_field = _group_field(model) if model is not None else ""
    number_field = stats.get("number_field") or ""
    nodes: dict[str, Any] = {}
    nav, footer, footer_text = _chrome(ctx, app_name, palette, nav_links, versions)

    def add(node_id, node_type, props=None, children=None, style=None):
        nodes[node_id] = _node(node_id, node_type, props, children, style, versions.get(node_type, "2.0.0"))
        return node_id

    add("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": palette.get("bg")})
    add("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": palette.get("bg")},
        ["ai-nav", "header", "loader", "kpis", "charts", "table", "ai-footer"])
    add("loader", "content-list", {
        "dataModelId": model.id if model is not None else 0,
        "mode": "list", "pageSize": 6, "showPagination": False,
        "showSearch": False, "showCategoryTabs": False, "hrefPattern": "news/{id}",
    }, [], {"display": "none"})
    add("header", "ElContainer", {"direction": "vertical", "padding": 34, "background": palette.get("hero")},
        ["headTitle", "headText"], {"textAlign": "center"})
    add("headTitle", "wp-heading", {
        "content": page.get("title") or page.get("name") or "数据大屏", "level": 1, "align": "center",
        "color": palette.get("title"), "marginBottom": 8,
    })
    add("headText", "wp-text", {
        "content": page.get("description") or "关键指标、趋势与明细一屏掌握。",
        "align": "center", "color": palette.get("text"), "fontSize": 14,
    })
    add("kpis", "ElRow", {"gutter": 16}, ["k1", "k2", "k3", "k4"],
        {"maxWidth": "1240px", "width": "100%", "margin": "0 auto", "padding": "20px 16px 0"})
    kpis = [
        ("记录总数", stats["count"], "条"),
        (f"{number_field or '数值'}合计", stats["sum"], ""),
        (f"{number_field or '数值'}均值", stats["avg"], ""),
        (f"{number_field or '数值'}峰值", stats["max"], ""),
    ]
    for index, (label, value, suffix) in enumerate(kpis, start=1):
        col, card, title, number = f"k{index}", f"kc{index}", f"kt{index}", f"kv{index}"
        add(col, "ElCol", {"span": 6}, [card])
        add(card, "ElCard", {"shadow": "never"}, [title, number], {
            "background": palette.get("surface"), "borderRadius": "10px", "padding": "16px",
        })
        add(title, "wp-text", {"content": label, "color": palette.get("text"), "fontSize": 13})
        if index == 1:
            add(number, "wp-statcard", {
                "label": "记录总数", "color": palette.get("title"),
                "background": "transparent", "fontSize": 30,
            })
        else:
            add(number, "ElStatistic", {
                "title": "", "value": value, "suffix": suffix,
                "precision": 0 if isinstance(value, int) else 2,
            })
    add("charts", "ElRow", {"gutter": 16}, ["c1", "c2"],
        {"maxWidth": "1240px", "width": "100%", "margin": "0 auto", "padding": "16px"})
    name_field = text_field or "name"
    value_field = number_field or "id"
    status_field = ""
    ranking_field = ""
    if model is not None:
        names = [str(field.get("name") or "") for field in (model.fields or []) if isinstance(field, dict)]
        status_field = "status" if "status" in names else ""
        ranking_field = "ranking" if "ranking" in names else ""
    bar_field = ranking_field or status_field or name_field
    chart_metrics = f"sum:{number_field}" if number_field else "count"
    chart2_metrics = chart_metrics if status_field else (f"avg:{number_field}" if number_field else "count")
    chart2_title = "状态占比" if status_field else ("均价占比" if number_field else "占比分析")
    chart_defs = [
        ("c1", "cc1", "ch1", "分类统计", "report-table", {
            "dataModelId": model.id if model is not None else 0,
            "groupBy": name_field, "metrics": chart_metrics, "limit": 6,
            "showChart": True, "chartType": "bar", "title": "分类统计",
        }),
        ("c2", "cc2", "ch2", chart2_title, "report-table", {
            "dataModelId": model.id if model is not None else 0,
            "groupBy": status_field or name_field, "metrics": chart2_metrics, "limit": 6,
            "showChart": True, "chartType": "pie", "title": chart2_title,
        }),
    ]
    for col, card, chart, title, chart_type, chart_props in chart_defs:
        add(col, "ElCol", {"span": 12}, [card])
        add(card, "ElCard", {"shadow": "never"}, [title, chart], {
            "background": palette.get("surface"), "borderRadius": "10px", "padding": "14px",
        })
        add(title, "wp-heading", {"content": title, "level": 3,
                                  "color": palette.get("title"), "marginBottom": 8})
        add(chart, chart_type, chart_props)
    add("table", "ElContainer", {"direction": "vertical", "padding": 16, "background": palette.get("bg")},
        ["tableTitle", "tableBody"], {"maxWidth": "1240px", "width": "100%", "margin": "0 auto"})
    add("tableTitle", "wp-heading", {"content": "数据明细", "level": 2,
                                     "color": palette.get("title"), "marginBottom": 10})
    columns = []
    if model is not None:
        for field in (model.fields or [])[:8]:
            if isinstance(field, dict):
                columns.append({"key": field.get("name"), "label": field.get("label") or field.get("name")})
    add("tableBody", "wp-table", {
        "columns": columns or [{"key": "name", "label": "名称"}],
        "pageSize": 6, "stripe": True, "bordered": True, "showIndex": True,
    })
    nodes["ai-nav"] = nav
    nodes["ai-footer"] = footer
    nodes["ai-footer-text"] = footer_text
    return _wrap(nodes, page, app_name)


def _local_form(ctx: dict, page: dict, model, palette: dict, nav_links: list[dict],
                versions: dict[str, str]) -> dict:
    app_name = ctx["site_name"]
    nodes: dict[str, Any] = {}

    def add(node_id, node_type, props=None, children=None, style=None):
        nodes[node_id] = _node(node_id, node_type, props, children, style, versions.get(node_type, "2.0.0"))
        return node_id

    nav, footer, footer_text = _chrome(ctx, app_name, palette, nav_links, versions)
    add("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": palette.get("bg")})
    add("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": palette.get("bg")},
        ["ai-nav", "header", "body", "ai-footer"])
    add("header", "ElContainer", {"direction": "vertical", "padding": 36, "background": palette.get("hero")},
        ["headTitle", "headText"], {"textAlign": "center"})
    add("headTitle", "wp-heading", {"content": page.get("title") or page.get("name") or "在线表单",
                                    "level": 1, "align": "center", "color": palette.get("title")})
    add("headText", "wp-text", {"content": page.get("description") or "请填写以下信息并提交。",
                                "align": "center", "color": palette.get("text"), "fontSize": 14})
    add("body", "ElRow", {"gutter": 18}, ["formCol", "tipCol"],
        {"maxWidth": "1040px", "width": "100%", "margin": "0 auto", "padding": "24px 16px"})
    add("formCol", "ElCol", {"span": 16}, ["formCard"])
    add("formCard", "ElCard", {"shadow": "never"}, ["formTitle", "form"],
        {"background": palette.get("surface"), "borderRadius": "10px", "padding": "18px"})
    add("formTitle", "wp-heading", {"content": "填写信息", "level": 2,
                                    "color": palette.get("title"), "marginBottom": 12})
    add("form", "auto-form", {
        "modelId": model.id if model is not None else 0,
        "mode": "create", "columns": 2, "showReset": True,
        "submitText": "提交", "successMessage": "提交成功",
    })
    add("tipCol", "ElCol", {"span": 8}, ["tipCard"])
    add("tipCard", "ElCard", {"shadow": "never"}, ["tipTitle", "tipText"],
        {"background": palette.get("surface"), "borderRadius": "10px", "padding": "18px"})
    add("tipTitle", "wp-heading", {"content": "填写说明", "level": 3,
                                   "color": palette.get("title"), "marginBottom": 8})
    add("tipText", "wp-text", {
        "content": "带 * 的字段为必填项；提交后可在后台记录中查看。若需要审批，请在应用工作流中启用。",
        "color": palette.get("text"), "fontSize": 13, "lineHeight": 1.8,
    })
    nodes["ai-nav"] = nav
    nodes["ai-footer"] = footer
    nodes["ai-footer-text"] = footer_text
    return _wrap(nodes, page, app_name)


def _local_custom(ctx: dict, page: dict, model, palette: dict, nav_links: list[dict],
                  versions: dict[str, str]) -> dict:
    app_name = ctx["site_name"]
    nodes: dict[str, Any] = {}

    def add(node_id, node_type, props=None, children=None, style=None):
        nodes[node_id] = _node(node_id, node_type, props, children, style, versions.get(node_type, "2.0.0"))
        return node_id

    nav, footer, footer_text = _chrome(ctx, app_name, palette, nav_links, versions)
    add("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": palette.get("bg")})
    add("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": palette.get("bg")},
        ["ai-nav", "hero", "split", "data", "ai-footer"])
    add("hero", "ElContainer", {"direction": "vertical", "padding": 58, "background": palette.get("hero")},
        ["heroTag", "heroTitle", "heroText"], {"textAlign": "center"})
    add("heroTag", "ElTag", {"text": "AI 生成", "type": "primary", "effect": "light", "size": "small"})
    add("heroTitle", "wp-heading", {"content": page.get("title") or page.get("name") or app_name,
                                    "level": 1, "align": "center", "color": palette.get("title")})
    add("heroText", "wp-text", {"content": page.get("description") or ctx.get("description") or "",
                                "align": "center", "color": palette.get("text"), "fontSize": 15, "lineHeight": 1.8})
    add("split", "ElRow", {"gutter": 18}, ["left", "right"],
        {"maxWidth": "1180px", "width": "100%", "margin": "0 auto", "padding": "24px 16px"})
    add("left", "ElCol", {"span": 15}, ["leftCard"])
    add("leftCard", "ElCard", {"shadow": "never"}, ["leftTitle", "leftText"],
        {"background": palette.get("surface"), "borderRadius": "10px", "padding": "20px"})
    add("leftTitle", "wp-heading", {"content": "核心内容", "level": 2,
                                    "color": palette.get("title"), "marginBottom": 8})
    add("leftText", "wp-text", {"content": ctx.get("description") or "",
                                "color": palette.get("text"), "fontSize": 14, "lineHeight": 1.9})
    add("right", "ElCol", {"span": 9}, ["rightCard"])
    add("rightCard", "ElCard", {"shadow": "never"}, ["rightTitle", "rightList"],
        {"background": palette.get("surface"), "borderRadius": "10px", "padding": "20px"})
    add("rightTitle", "wp-heading", {"content": "最新内容", "level": 2,
                                     "color": palette.get("title"), "marginBottom": 8})
    add("rightList", "content-list", {
        "dataModelId": model.id if model is not None else 0, "mode": "list",
        "pageSize": 5, "showPagination": False, "showSearch": False,
        "showCategoryTabs": False, "hrefPattern": "news/{id}",
    })
    add("data", "ElContainer", {"direction": "vertical", "padding": 20, "background": palette.get("bg")},
        ["dataTitle", "dataTable"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"})
    add("dataTitle", "wp-heading", {"content": "数据一览", "level": 2,
                                    "color": palette.get("title"), "marginBottom": 10})
    add("dataTable", "content-list", {
        "dataModelId": model.id if model is not None else 0, "mode": "list",
        "pageSize": 8, "showPagination": True, "showSearch": True,
        "showCategoryTabs": False, "hrefPattern": "news/{id}",
    })
    nodes["ai-nav"] = nav
    nodes["ai-footer"] = footer
    nodes["ai-footer-text"] = footer_text
    return _wrap(nodes, page, app_name)


def _wrap(nodes: dict, page: dict, app_name: str) -> dict:
    return {
        "schemaVersion": 2,
        "rootId": "root",
        "nodes": nodes,
        "layout": {"mode": "flow", "width": 1200, "height": 900},
        "variables": {},
        "meta": {
            "title": page.get("title") or page.get("name") or app_name,
            "description": page.get("description") or f"{app_name} · AI 生成页面",
            "lang": "zh-CN",
        },
        "customCss": "",
    }


def _ensure_chrome(schema: dict, app_name: str, palette: dict, nav_links: list[dict],
                   versions: dict[str, str]) -> dict:
    nodes = schema.setdefault("nodes", {})
    if not isinstance(nodes, dict):
        schema["nodes"] = {}
        nodes = schema["nodes"]
    root_id = schema.get("rootId")
    root = nodes.get(root_id) if root_id else None
    if not isinstance(root, dict):
        root_id = "root"
        schema["rootId"] = "root"
        root = _node("root", "wp-canvas", {}, [], {"minHeight": "100vh", "background": palette.get("bg")},
                     versions.get("wp-canvas", "2.0.0"))
        nodes["root"] = root
    children = [child for child in root.get("children") or [] if child in nodes]
    if not any(isinstance(node, dict) and node.get("type") == "site-nav" for node in nodes.values()):
        nav, _footer, _footer_text = _chrome({}, app_name, palette, nav_links, versions)
        nav["id"] = "ai-nav"
        nodes["ai-nav"] = nav
        children.insert(0, "ai-nav")
    if not any(isinstance(node, dict) and "footer" in str(node.get("id")) for node in nodes.values()):
        _nav, footer, footer_text = _chrome({}, app_name, palette, nav_links, versions)
        footer["id"] = "ai-footer"
        footer["children"] = ["ai-footer-text"]
        footer_text["id"] = "ai-footer-text"
        nodes["ai-footer"] = footer
        nodes["ai-footer-text"] = footer_text
        children.append("ai-footer")
    root["children"] = children
    return schema


def _bind_models(schema: dict, models: list) -> None:
    if not models:
        return
    default_id = models[0].id
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        props = node.setdefault("props", {})
        if not isinstance(props, dict):
            node["props"] = {}
            props = node["props"]
        node_type = node.get("type")
        if node_type in ("content-list", "article-detail", "report-table", "ElTable") and not props.get("dataModelId"):
            props["dataModelId"] = default_id
        if node_type == "auto-form":
            if not props.get("modelId"):
                props["modelId"] = default_id
            model = models[0]
            current = props.get("fields")
            if isinstance(current, list) and current:
                bad = any(not isinstance(field, dict) or not field.get("type") for field in current)
                if bad:
                    current = None
            else:
                current = None
            if not current and model is not None:
                current = []
                for field in model.fields or []:
                    if not isinstance(field, dict):
                        continue
                    current.append({
                        "name": field.get("name"),
                        "type": field.get("type") or "string",
                        "label": field.get("label") or field.get("name"),
                        "required": bool(field.get("required")),
                        **({"ui": field["ui"]} if field.get("ui") else {}),
                    })
                props["fields"] = current
            props.setdefault("mode", "create")
            props.setdefault("columns", 2)
            props.setdefault("submitText", "提交")
            props.setdefault("successMessage", "提交成功")


def _prune_unreachable(schema: dict) -> None:
    nodes = schema.get("nodes") or {}
    root_id = schema.get("rootId")
    if not isinstance(nodes, dict) or root_id not in nodes:
        return
    reachable = set()
    stack = [root_id]
    while stack:
        node_id = stack.pop()
        if node_id in reachable or node_id not in nodes:
            continue
        reachable.add(node_id)
        node = nodes.get(node_id)
        if isinstance(node, dict):
            stack.extend([child for child in node.get("children") or [] if child in nodes])
    for node_id in list(nodes):
        if node_id not in reachable:
            nodes.pop(node_id, None)
    schema["nodes"] = nodes


def _normalize(schema: dict, page: dict, app_name: str, palette: dict, nav_links: list[dict],
               models: list, versions: dict[str, str], kind: str) -> dict:
    from ai.services import polish_schema, validate_schema

    schema = validate_schema(polish_schema(copy.deepcopy(schema), page.get("description") or page.get("name") or "", app_name), app_name)
    _bind_models(schema, models)
    _ensure_chrome(schema, app_name, palette, nav_links, versions)
    _prune_unreachable(schema)
    for node in (schema.get("nodes") or {}).values():
        if isinstance(node, dict):
            node["componentVersion"] = versions.get(node.get("type"), node.get("componentVersion") or "2.0.0")
    schema.setdefault("meta", {})
    schema["meta"]["title"] = page.get("title") or page.get("name") or app_name
    schema["meta"]["description"] = page.get("description") or schema["meta"].get("description") or ""
    return schema


def _safe_local(kind: str, ctx: dict, page: dict, model, palette: dict, nav_links: list[dict],
                versions: dict[str, str]) -> dict:
    if kind == "dashboard":
        return _local_dashboard(ctx, page, model, palette, nav_links, versions)
    if kind == "form":
        return _local_form(ctx, page, model, palette, nav_links, versions)
    return _local_custom(ctx, page, model, palette, nav_links, versions)


def generate_layout(ctx: dict, page: dict, kind: str, models: list, palette: dict,
                    nav_links: list[dict]) -> tuple[dict, str]:
    """返回 (schema, provider)。LLM 失败/无 Key 时使用本地真实组件回退。"""
    from ai.providers import is_configured
    from components.services import get_component_registry
    from core.schemas import validate_page_schema

    versions = _versions()
    model_payload = _model_payload(models)

    def strict(schema: dict) -> dict:
        errors, _warnings = validate_page_schema(schema, get_component_registry(), strict=True)
        if errors:
            raise ValidationError({"detail": "；".join(errors[:4])})
        if kind == "dashboard" and not any(
            isinstance(node, dict) and node.get("type") == "content-list"
            for node in (schema.get("nodes") or {}).values()
        ):
            raise ValidationError({"detail": "仪表盘缺少公开数据加载器"})
        return schema

    if is_configured() and ctx.get("use_llm", True):
        try:
            prompt = _prompt(ctx.get("site_name") or "站点", page, kind, model_payload, palette,
                             nav_links, ctx.get("site_prompt") or ctx.get("description") or "")
            raw = _call_llm(prompt)
            schema = _normalize(raw, page, ctx.get("site_name") or "站点", palette, nav_links, models, versions, kind)
            schema = strict(schema)
            if kind == "form":
                schema.setdefault("meta", {})["allowPublicSubmit"] = True
                schema["meta"]["requireCaptcha"] = True
            return schema, "llm"
        except Exception:
            pass
    schema = _safe_local(kind, ctx, page, _first_model(models), palette, nav_links, versions)
    schema = _normalize(schema, page, ctx.get("site_name") or "站点", palette, nav_links, models, versions, kind)
    if kind == "form":
        schema.setdefault("meta", {})["allowPublicSubmit"] = True
        schema["meta"]["requireCaptcha"] = True
    return strict(schema), "local"
