"""AI 整站草稿：生成首页、列表页、详情页的页面计划，不自动发布。"""
from __future__ import annotations

import copy
import json
import re
import urllib.request
from typing import Any

from rest_framework.exceptions import ValidationError

from ai.services import _pick_content_model, display_title, local_generate


def _node(node_id: str, node_type: str, props: dict | None = None, children: list[str] | None = None, style: dict | None = None):
    return {
        "id": node_id,
        "type": node_type,
        "componentVersion": "2.0.0",
        "props": props or {},
        "children": children or [],
        **({"style": style} if style else {}),
    }


def _schema(nodes: dict[str, Any], title: str) -> dict:
    return {
        "schemaVersion": 2,
        "rootId": "root",
        "nodes": nodes,
        "layout": {"mode": "flow", "width": 1200, "height": 900},
        "variables": {},
        "meta": {"title": title, "description": f"{title} · AI 建站草稿", "lang": "zh-CN"},
        "customCss": "",
    }


def _nav(app_name: str, home: str, list_path: str) -> dict:
    return _node("nav", "site-nav", {
        "brand": app_name,
        "homePath": home,
        "sticky": True,
        "showSearch": True,
        "searchPath": "search",
        "links": [
            {"label": "首页", "path": home},
            {"label": "资讯", "path": list_path},
        ],
    })


def _list_schema(app_name: str, title: str, model: dict, home_path: str, list_path: str, detail_pattern: str) -> dict:
    fields = {f.get("name") for f in model.get("fields") or [] if isinstance(f, dict)}
    props: dict[str, Any] = {
        "dataModelId": model["id"],
        "mode": "list",
        "heading": "",
        "pageSize": 10,
        "showPagination": True,
        "showSearch": True,
        "searchPlaceholder": "搜索标题、摘要或标签…",
        "hrefPattern": detail_pattern,
        "showCategoryTabs": "category" in fields,
        "emptyText": "暂无内容",
    }
    if "status" in fields:
        props["filters"] = {"status": "published"}
    nodes = {
        "root": _node("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": "#f7f8fa"}),
        "main": _node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#f7f8fa"}, ["nav", "header", "content"]),
        "nav": _nav(app_name, home_path, list_path),
        "header": _node("header", "ElContainer", {"direction": "vertical", "padding": 32, "background": "#ffffff"}, ["title", "desc"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"}),
        "title": _node("title", "wp-heading", {"content": title, "level": 1, "color": "#111827", "marginBottom": 8}),
        "desc": _node("desc", "wp-text", {"content": "浏览全部已发布内容", "color": "#6b7280", "fontSize": 13}),
        "content": _node("content", "ElContainer", {"direction": "vertical", "padding": 24, "background": "#f7f8fa"}, ["list"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"}),
        "list": _node("list", "content-list", props),
    }
    return _schema(nodes, title)


def _detail_schema(app_name: str, title: str, model: dict, home_path: str, list_path: str, detail_pattern: str) -> dict:
    nodes = {
        "root": _node("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": "#f7f8fa"}),
        "main": _node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#f7f8fa"}, ["nav", "article"]),
        "nav": _nav(app_name, home_path, list_path),
        "article": _node("article", "article-detail", {
            "dataModelId": model["id"],
            "lookup": "id",
            "titleField": "title",
            "summaryField": "summary",
            "contentField": "content",
            "coverField": "cover",
            "authorField": "author",
            "dateField": "published_at",
            "categoryField": "category",
            "tagsField": "tags",
            "backPath": list_path,
            "articlePath": detail_pattern,
            "showRelated": True,
            "relatedLimit": 3,
        }),
    }
    return _schema(nodes, title)


def call_llm_site_meta(app_name: str, prompt: str) -> dict:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置可用的 AI Provider"})
    cfg = chat_config()
    api_key = cfg["api_key"]
    base = cfg["base_url"]
    model = cfg["model"]
    user = f"""为 MiWebProcess 规划一个内容站点，应用：{app_name}
用户需求：{prompt}

只输出 JSON：
{{"site_name":"站点名","home_title":"首页主标题","home_subtitle":"一句副标题","theme":"dark|light|blue","pages":[{{"name":"页面名","kind":"home|list|detail"}}]}}
要求：中文；站点名 2-12 字；首页标题 6-24 字；副标题 12-36 字；pages 固定包含 home/list/detail 三项；严格 JSON。
"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只返回严格 JSON。"},
            {"role": "user", "content": user},
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
        raise ValidationError({"detail": f"AI 建站规划失败: {exc}"}) from exc
    text = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValidationError({"detail": "AI 返回的建站规划不是 JSON"})
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValidationError({"detail": "AI 返回的建站规划不是合法 JSON"}) from exc
    if not isinstance(value, dict):
        raise ValidationError({"detail": "AI 返回的建站规划不是对象"})
    return value


def build_site_plan(app_name: str, prompt: str, models: list[dict], existing_paths: set[str] | None = None, site_meta: dict | None = None) -> dict:
    existing_paths = existing_paths or set()
    content_model = _pick_content_model(models)
    meta = copy.deepcopy(site_meta or {})
    title = str(meta.get("site_name") or display_title(prompt, app_name))
    home_title = str(meta.get("home_title") or title)
    home_subtitle = str(meta.get("home_subtitle") or "由 AI 建站生成的页面草稿，可在设计器中继续调整。")
    if content_model is None:
        home = local_generate(app_name, prompt, models)
        return {
            "site": {"name": title, "description": prompt, "kind": "home-only"},
            "pages": [{"name": f"{title}首页", "path": "ai-home", "kind": "home", "schema": home}],
            "warnings": ["当前应用没有可用内容模型，只生成了首页；创建内容模型后可生成列表/详情页。"],
        }

    home_path = "ai-home"
    list_path = "ai-news"
    detail_pattern = "ai-article/:id"
    home = local_generate(app_name, prompt, models)
    # 调整首页导航、标题文案和内容链接，使三页形成闭环。
    for node in (home.get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        if node.get("type") == "site-nav":
            node.setdefault("props", {})["links"] = [
                {"label": "首页", "path": home_path},
                {"label": "资讯", "path": list_path},
            ]
            node["props"]["brand"] = title
        if node.get("type") == "content-list":
            node.setdefault("props", {})["hrefPattern"] = detail_pattern
        if node.get("id") == "heroTitle":
            node.setdefault("props", {})["content"] = home_title
        if node.get("id") == "heroText":
            node.setdefault("props", {})["content"] = home_subtitle
    home.setdefault("meta", {})["title"] = home_title
    home["meta"]["description"] = home_subtitle

    pages = [
        {"name": f"{title}首页", "path": home_path, "kind": "home", "schema": home},
        {"name": f"{title}列表", "path": list_path, "kind": "list", "schema": _list_schema(app_name, f"{title}资讯", content_model, home_path, list_path, detail_pattern)},
        {"name": f"{title}详情", "path": detail_pattern, "kind": "detail", "schema": _detail_schema(app_name, title, content_model, home_path, list_path, detail_pattern)},
    ]
    warnings = []
    conflicts = [p["path"] for p in pages if p["path"] in existing_paths]
    if conflicts:
        warnings.append(f"以下路径已存在，请修改后再创建：{', '.join(conflicts)}")
    return {
        "site": {"name": title, "description": prompt, "kind": "content-portal"},
        "pages": pages,
        "warnings": warnings,
    }
