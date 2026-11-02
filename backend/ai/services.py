"""AI 页面生成：OpenAI-compatible LLM + 无 Key 时的本地模板生成器。"""
from __future__ import annotations

import copy
import json
import re
import urllib.request
from typing import Any

from rest_framework.exceptions import ValidationError

from components.models import ComponentMeta


SAFE_COMPONENTS = [
    "wp-canvas", "ElContainer", "ElRow", "ElCol", "ElCard", "ElText", "ElButton", "ElDivider",
    "wp-heading", "wp-text", "wp-button", "wp-image", "site-nav", "content-list", "article-detail",
    "DataTable", "AutoForm", "RelationTable", "ApprovalPanel", "ReportTable", "ChartRenderer",
    "HtmlBlock", "MarkdownRenderer", "site-search", "ElTag",
]


def _node(node_id: str, node_type: str, props: dict | None = None, children: list[str] | None = None, style: dict | None = None):
    return {
        "id": node_id,
        "type": node_type,
        "componentVersion": "2.0.0",
        "props": props or {},
        "children": children or [],
        **({"style": style} if style else {}),
    }


def display_title(prompt: str, app_name: str) -> str:
    raw = str(prompt or "").strip().replace("\n", " ")
    if "游戏" in raw:
        return "游戏资讯"
    if "企业" in raw or "官网" in raw:
        return "企业官网"
    if "订单" in raw or "采购" in raw:
        return "采购订单"
    if "报表" in raw or "统计" in raw:
        return "数据报表"
    return re.sub(r"^(做一个|生成一个|设计一个|创建一个)\s*", "", raw)[:24] or f"{app_name} 新页面"


def polish_schema(schema: dict, prompt: str, app_name: str) -> dict:
    """填充模型偶尔保留的编辑器占位文案，避免首屏出现“标题/双击文本”。"""
    title = display_title(prompt, app_name)
    subtitle = "由 AI 生成页面草稿，可在设计器中继续调整布局、文案和数据绑定。"
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        props = node.setdefault("props", {})
        if not isinstance(props, dict):
            node["props"] = {}
            props = node["props"]
        node_type = node.get("type")
        if node_type in ("wp-heading", "ElText"):
            if str(props.get("content") or "").strip() in ("", "标题", "双击文本进行编辑"):
                props["content"] = title
        elif node_type == "wp-text":
            if str(props.get("content") or "").strip() in ("", "双击文本进行编辑"):
                props["content"] = subtitle
        elif node_type in ("wp-image", "ElImage"):
            if not str(props.get("src") or "").strip():
                props["src"] = "https://picsum.photos/seed/webprocess-ai/1200/640"
        elif node_type == "ElTag":
            if not str(props.get("text") or "").strip():
                props["text"] = "精选"
    return schema


def _pick_content_model(models: list[dict]) -> dict | None:
    for model in models:
        names = {f.get("name") for f in model.get("fields") or [] if isinstance(f, dict)}
        if "title" in names and ("content" in names or "summary" in names):
            return model
    return models[0] if models else None


def _pick_business_model(models: list[dict], prompt: str) -> dict | None:
    for model in models:
        if any(word in prompt for word in ("ERP", "订单", "采购", "库存")) and "order" in model.get("name", "").lower():
            return model
    return None


def local_generate(app_name: str, prompt: str, models: list[dict]) -> dict:
    """无 API Key 时的确定性生成器：使用编辑精选组件，保证一定能渲染。"""
    dark = any(word in prompt for word in ("深色", "暗色", "黑色", "dark"))
    bg = "#0f172a" if dark else "#f7f8fa"
    surface = "#111c33" if dark else "#ffffff"
    title_color = "#f8fafc" if dark else "#111827"
    text_color = "#cbd5e1" if dark else "#4b5563"
    accent = "#3b82f6"
    content_model = _pick_content_model(models)
    business_model = _pick_business_model(models, prompt)

    heading = display_title(prompt, app_name)
    subtitle = "由 AI 生成页面草稿，可在设计器中继续调整布局、文案和数据绑定。"
    nodes: dict[str, Any] = {}

    def add(node_id: str, node_type: str, props: dict, children: list[str] | None = None, style: dict | None = None):
        nodes[node_id] = _node(node_id, node_type, props, children, style)
        return node_id

    add("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": bg})
    add("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": bg}, ["nav", "hero", "section", "footer"])
    add(
        "nav", "site-nav",
        {
            "brand": app_name,
            "homePath": "home",
            "sticky": True,
            "dark": dark,
            "showSearch": True,
            "searchPath": "search",
            "links": [
                {"label": "首页", "path": "home"},
                {"label": "资讯", "path": "news/games"},
                {"label": "专题", "path": "news/reviews"},
            ],
        },
    )
    add(
        "hero", "ElContainer",
        {
            "direction": "vertical",
            "padding": 48,
            "background": "#172554" if dark else "#eef4ff",
        },
        ["heroTag", "heroTitle", "heroText", "heroButton"],
        {"textAlign": "center"},
    )
    add("heroTag", "ElTag", {"type": "primary", "effect": "light", "size": "small"}, [], {"marginBottom": "12px"})
    nodes["heroTag"]["props"]["text"] = "AI 生成草稿"
    add("heroTitle", "wp-heading", {"content": heading, "level": 1, "align": "center", "color": title_color, "marginBottom": 12})
    add("heroText", "wp-text", {"content": subtitle, "align": "center", "color": text_color, "fontSize": 15, "lineHeight": 1.8})
    add("heroButton", "ElButton", {"type": "primary", "size": "large", "text": "浏览内容"}, [], {"marginTop": "18px"})
    add("section", "ElContainer", {"direction": "vertical", "padding": 24, "background": bg}, ["sectionTitle", "content"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"})

    if business_model is not None and any(word in prompt for word in ("ERP", "订单", "采购", "库存")):
        add("sectionTitle", "wp-heading", {"content": "业务数据", "level": 2, "color": title_color, "marginBottom": 12})
        add(
            "content", "DataTable",
            {
                "dataModelId": business_model["id"],
                "remote": True,
                "autoColumns": True,
                "showPagination": True,
                "pageSize": 10,
                "showSearch": True,
                "exportable": True,
                "emptyText": "暂无数据",
            },
        )
    elif any(word in prompt for word in ("报表", "统计", "图表")) and content_model:
        add("sectionTitle", "wp-heading", {"content": "数据概览", "level": 2, "color": title_color, "marginBottom": 12})
        add(
            "content", "ReportTable",
            {
                "dataModelId": content_model["id"],
                "groupBy": "status",
                "metrics": "count,sum:amount",
                "title": "数据报表",
                "showChart": True,
                "chartType": "bar",
            },
        )
    elif content_model is not None:
        add("sectionTitle", "wp-heading", {"content": "最新内容", "level": 2, "color": title_color, "marginBottom": 12})
        fields = {f.get("name") for f in content_model.get("fields") or [] if isinstance(f, dict)}
        props = {
            "dataModelId": content_model["id"],
            "mode": "grid",
            "heading": "",
            "pageSize": 6,
            "showPagination": True,
            "showSearch": True,
            "searchPlaceholder": "搜索内容…",
            "hrefPattern": "article/{id}",
            "showCategoryTabs": "category" in fields,
            "emptyText": "暂无内容",
        }
        if "status" in fields:
            props["filters"] = {"status": "published"}
        add("content", "content-list", props)
    else:
        add("sectionTitle", "wp-heading", {"content": "开始搭建", "level": 2, "color": title_color, "marginBottom": 12})
        add("content", "wp-text", {"content": "当前应用还没有数据模型，可先在设计器中添加组件，或创建内容模型后重新生成。", "color": text_color, "lineHeight": 1.8})

    add("footer", "ElContainer", {"direction": "vertical", "padding": 20, "background": surface}, ["footerText"])
    add("footerText", "wp-text", {"content": f"© {app_name} · AI 生成草稿", "align": "center", "color": text_color, "fontSize": 12})

    return {
        "schemaVersion": 2,
        "rootId": "root",
        "nodes": nodes,
        "layout": {"mode": "flow", "width": 1200, "height": 900},
        "variables": {},
        "meta": {
            "title": heading,
            "description": subtitle,
            "lang": "zh-CN",
            "seo": {"description": subtitle},
        },
        "customCss": "",
    }


def _compact_components() -> list[dict]:
    rows = list(ComponentMeta.objects.filter(is_enabled=True, name__in=SAFE_COMPONENTS).values("name", "label", "type"))
    return rows


def _set_theme(schema: dict, dark: bool) -> bool:
    bg = "#0f172a" if dark else "#f7f8fa"
    surface = "#111c33" if dark else "#ffffff"
    hero_bg = "#172554" if dark else "#eef4ff"
    title_color = "#f8fafc" if dark else "#111827"
    text_color = "#cbd5e1" if dark else "#4b5563"
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        props = node.setdefault("props", {})
        style = node.setdefault("style", {})
        node_type = node.get("type")
        if node.get("id") in ("root", "main") or node_type == "ElContainer":
            props["background"] = hero_bg if node.get("id") == "hero" else bg
            style["background"] = props["background"]
        if node_type == "site-nav":
            props["dark"] = dark
        if node_type in ("wp-heading", "ElText"):
            props["color"] = title_color
        if node_type == "wp-text":
            props["color"] = text_color
        if node_type == "ElCard":
            props["background"] = surface
    return True


def local_edit(schema: dict, prompt: str) -> tuple[dict, bool, list[str]]:
    """无 Key 时的局部编辑：主题、标题、按钮文案。保留所有节点 id。"""
    out = copy.deepcopy(schema)
    text = str(prompt or "").strip()
    changed = False
    warnings: list[str] = []

    if any(word in text for word in ("深色", "暗色", "黑色", "dark")):
        changed = _set_theme(out, True) or changed
    elif any(word in text for word in ("浅色", "亮色", "白色", "light")):
        changed = _set_theme(out, False) or changed

    nodes = out.get("nodes") or {}
    title_match = re.search(r"(?:大标题|首屏标题|标题).{0,8}?(?:改为|改成|换成|设为|变成)[“\"]?([^”\"，。]+)", text)
    if title_match:
        title = title_match.group(1).strip()
        found = False
        for node in nodes.values():
            if isinstance(node, dict) and node.get("type") in ("wp-heading", "ElText"):
                node.setdefault("props", {})["content"] = title
                found = True
                break
        if found:
            out.setdefault("meta", {})["title"] = title
            changed = True
        else:
            warnings.append("没有找到可修改的标题节点")

    button_match = re.search(r"(?:按钮|按钮文字).{0,8}?(?:改为|改成|换成|设为)[“\"]?([^”\"，。]+)", text)
    if button_match:
        label = button_match.group(1).strip()
        for node in nodes.values():
            if isinstance(node, dict) and node.get("type") in ("ElButton", "wp-button"):
                node.setdefault("props", {})["text"] = label
                changed = True
                break

    if not changed:
        warnings.append("本地模式暂只支持修改深色/浅色主题、标题和按钮文案；更复杂的修改需要配置 AI_API_KEY。")
    return out, changed, warnings


def call_llm_edit(app_name: str, prompt: str, schema: dict) -> tuple[dict, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置可用的 AI Provider"})
    cfg = chat_config()
    api_key = cfg["api_key"]
    base = cfg["base_url"]
    model = cfg["model"]
    user = f"""你在修改 MiWebProcess 页面 Schema，应用：{app_name}
用户修改要求：{prompt}

当前 Schema：
{json.dumps(schema, ensure_ascii=False)}

规则：
1. 只输出完整的新 Schema，JSON 对象，不要 Markdown。
2. 保留 schemaVersion、rootId、节点 id 和未涉及节点的结构；只修改用户要求的节点/样式/文案。
3. 只能使用当前 schema 里已有的组件 type，不要新增未知组件。
4. 不要修改 dataModelId 为不存在的值，不要新增 script/iframe/onclick/JS action。
5. 必须保持 children 引用有效。
"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只返回严格 JSON。"},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": f"AI 请求失败: {exc}"}) from exc
    text = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(value, dict):
                return value, model
        except json.JSONDecodeError:
            pass
    raise ValidationError({"detail": "AI 返回的不是合法 JSON"})


def local_variants(app_name: str, prompt: str, models: list[dict]) -> list[dict]:
    """同一内容结构生成三种可比较的主题方案。"""
    base = local_generate(app_name, prompt, models)
    definitions = [
        ("A", "深色科技", "dark"),
        ("B", "清爽浅色", "blue"),
        ("C", "暖色杂志", "warm"),
    ]
    variants = []
    for code, label, theme in definitions:
        schema = copy.deepcopy(base)
        if theme == "dark":
            _set_theme(schema, True)
        else:
            _set_theme(schema, False)
            if theme == "blue":
                bg, hero_bg, title_color, text_color = "#f0f7ff", "#dbeafe", "#1e3a8a", "#475569"
            else:
                bg, hero_bg, title_color, text_color = "#fff7ed", "#ffedd5", "#7c2d12", "#57534e"
            for node in (schema.get("nodes") or {}).values():
                if not isinstance(node, dict):
                    continue
                node.setdefault("style", {})
                props = node.setdefault("props", {})
                if node.get("id") in ("root", "main"):
                    node["style"]["background"] = bg
                    props["background"] = bg
                if node.get("id") == "hero":
                    node["style"]["background"] = hero_bg
                    props["background"] = hero_bg
                if node.get("type") in ("wp-heading", "ElText"):
                    props["color"] = title_color
                if node.get("type") == "wp-text":
                    props["color"] = text_color
        schema.setdefault("meta", {})["title"] = f"{display_title(prompt, app_name)} · 方案{code}"
        variants.append({"code": code, "label": label, "schema": schema})
    return variants


def _prompt(app_name: str, prompt: str, models: list[dict], components: list[dict]) -> str:
    model_rows = [
        {
            "id": m["id"],
            "name": m["name"],
            "fields": [f.get("name") for f in m.get("fields") or [] if isinstance(f, dict)],
        }
        for m in models[:20]
    ]
    return f"""你是 MiWebProcess 的网页设计器助手。请根据用户需求生成一个可直接渲染的页面 Schema。

应用名称：{app_name}
用户需求：{prompt}

可用组件（只能使用这些 type）：
{json.dumps(components, ensure_ascii=False)}

可用数据模型（dataModelId 只能使用这些 id）：
{json.dumps(model_rows, ensure_ascii=False)}

要求：
1. 只输出 JSON，不要 markdown。
2. 结构必须是 {{"schemaVersion":2,"rootId":"root","nodes":{{...}},"layout":{{"mode":"flow","width":1200,"height":900}},"variables":{{}},"meta":{{...}}}}。
3. root 必须是 wp-canvas，所有 children 必须引用存在的节点。
4. 使用真实组件 type，不要编造组件；content-list/DataTable/ReportTable 的 dataModelId 必须来自上面的模型。
5. 页面要包含导航、首屏、内容区、页脚；优先响应式、留白和清晰层级。
6. 不要输出 script、iframe、内联 JS、onclick 或 actions。
7. 文案使用中文，符合用户行业和页面目的。
8. 节点总数不超过 80。
"""


def call_llm(app_name: str, prompt: str, models: list[dict]) -> tuple[dict, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置可用的 AI Provider"})
    cfg = chat_config()
    api_key = cfg["api_key"]
    base = cfg["base_url"]
    model = cfg["model"]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只返回严格 JSON，不返回 Markdown。"},
            {"role": "user", "content": _prompt(app_name, prompt, models, _compact_components())},
        ],
        "temperature": 0.4,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": f"AI 请求失败: {exc}"}) from exc
    text = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        return json.loads(text), model
    except json.JSONDecodeError:
        # 部分兼容接口会在 JSON 后面追加说明文字；取第一个完整 JSON 对象。
        start = text.find("{")
        if start >= 0:
            try:
                value, _end = json.JSONDecoder().raw_decode(text[start:])
                if isinstance(value, dict):
                    return value, model
            except json.JSONDecodeError:
                pass
        raise ValidationError({"detail": "AI 返回的不是合法 JSON"})


def validate_schema(schema: Any, app_name: str) -> dict:
    if not isinstance(schema, dict):
        raise ValidationError({"detail": "AI 返回的 schema 不是对象"})
    nodes = schema.get("nodes")
    root_id = schema.get("rootId")
    if not isinstance(nodes, dict) or not nodes or root_id not in nodes:
        raise ValidationError({"detail": "schema 缺少 root/nodes"})
    if len(nodes) > 200:
        raise ValidationError({"detail": "页面节点过多，最多 200 个"})
    allowed = set(ComponentMeta.objects.filter(is_enabled=True).values_list("name", flat=True))
    if not allowed:
        allowed = set(SAFE_COMPONENTS)
    allowed.add("wp-canvas")
    for node_id, node in nodes.items():
        if not isinstance(node, dict) or not isinstance(node.get("type"), str):
            raise ValidationError({"detail": f"节点 {node_id} 结构不合法"})
        if node["type"] not in allowed:
            raise ValidationError({"detail": f"未知组件类型：{node['type']}"})
        children = node.get("children") or []
        if not isinstance(children, list):
            node["children"] = []
        for child in list(node.get("children") or []):
            if child not in nodes:
                node["children"].remove(child)
        props = node.get("props") or {}
        if not isinstance(props, dict):
            node["props"] = {}
        for key, value in list(node["props"].items()):
            if isinstance(value, str) and ("javascript:" in value.lower() or "<script" in value.lower()):
                node["props"][key] = ""
        if isinstance(node["props"].get("actions"), list):
            node["props"]["actions"] = [
                a for a in node["props"]["actions"]
                if isinstance(a, dict) and a.get("type") != "js"
            ]
        node.setdefault("componentVersion", "2.0.0")
    schema.setdefault("schemaVersion", 2)
    schema.setdefault("layout", {"mode": "flow", "width": 1200, "height": 900})
    schema.setdefault("variables", {})
    meta = schema.setdefault("meta", {})
    if not isinstance(meta, dict):
        schema["meta"] = {}
        meta = schema["meta"]
    meta.setdefault("title", f"{app_name} · AI 页面")
    meta.setdefault("lang", "zh-CN")
    meta.setdefault("description", "由 AI 生成的页面草稿")
    return schema
