"""AI 全自动建站：一条指令完成应用、模型、内容、页面、发布与索引。

设计目标：
- **可执行**：不是只给「方案」，而是真正创建应用/模型/内容/页面并发布；
- **可回退**：每一步落进度与日志，失败保留已完成产物并给出错误步骤；
- **可控**：默认自动发布，也可关闭；工作流/实时通道/SSR 快照按需生成；
- **离线可用**：未配置 LLM 或调用失败时，使用本地蓝图生成器，保证任务能完成。

执行模型：``AiBuildJob`` + 后台线程（单进程）。生产可把 ``run_job`` 直接挂到 Celery。
"""
from __future__ import annotations

import copy
import base64
import json
import logging
import re
import threading
import time
import traceback
import urllib.request
import uuid
from datetime import timedelta
from pathlib import Path

from django.db import close_old_connections
from django.utils import timezone

from ai.crypto import decrypt_secret
from ai.models import AiBuildJob
from ai.providers import chat_config, is_configured

logger = logging.getLogger("ai.autobuild")

THEMES = {
    "light": {
        "bg": "#f7f8fa", "surface": "#ffffff", "hero": "#eef4ff",
        "title": "#111827", "text": "#4b5563", "accent": "#2563eb", "soft": "#dbeafe",
    },
    "dark": {
        "bg": "#0f172a", "surface": "#111c33", "hero": "#172554",
        "title": "#f8fafc", "text": "#cbd5e1", "accent": "#3b82f6", "soft": "#1e3a8a",
    },
    "blue": {
        "bg": "#f0f7ff", "surface": "#ffffff", "hero": "#dbeafe",
        "title": "#1e3a8a", "text": "#475569", "accent": "#2563eb", "soft": "#bfdbfe",
    },
    "warm": {
        "bg": "#fff7ed", "surface": "#ffffff", "hero": "#ffedd5",
        "title": "#7c2d12", "text": "#57534e", "accent": "#ea580c", "soft": "#fed7aa",
    },
    "green": {
        "bg": "#f0fdf4", "surface": "#ffffff", "hero": "#dcfce7",
        "title": "#14532d", "text": "#4b5563", "accent": "#16a34a", "soft": "#bbf7d0",
    },
}

STEPS = [
    ("plan", "生成建站蓝图"),
    ("app", "创建应用"),
    ("model", "创建内容模型"),
    ("content", "生成示例内容"),
    ("pages", "生成并发布页面"),
    ("review", "自动评审与修复"),
    ("workflow", "创建工作流"),
    ("realtime", "创建实时通道"),
    ("release", "发布应用"),
    ("index", "重建搜索索引"),
    ("ssr", "生成 SSR 快照"),
]

DEFAULT_OPTIONS = {
    "use_dsh": True,
    "sample_content": True,
    "create_workflow": True,
    "create_realtime": True,
    "generate_ssr": True,
    "publish": True,
    "enable_review": False,
    "use_llm": True,
    # PostgreSQL 数据源建站：单个 source 或多表 sources（一表一模型）
    "source": None,
    "sources": None,
    "pages_override": None,
    "master_detail": True,
}

CONTENT_FIELDS = [
    {"name": "title", "type": "string", "required": True, "label": "标题"},
    {"name": "summary", "type": "string", "ui": "textarea", "label": "摘要"},
    {"name": "content", "type": "string", "ui": "richtext", "label": "正文"},
    {"name": "cover", "type": "string", "label": "封面"},
    {"name": "author", "type": "string", "label": "作者"},
    {"name": "category", "type": "string", "label": "分类"},
    {"name": "tags", "type": "string", "label": "标签"},
    {"name": "status", "type": "string", "default": "published", "label": "状态"},
    {"name": "published_at", "type": "date", "label": "发布时间"},
]


# ---------------------------------------------------------------- 小工具

def _node(node_id: str, node_type: str, props: dict | None = None, children: list[str] | None = None, style: dict | None = None):
    return {
        "id": node_id,
        "type": node_type,
        "componentVersion": "2.0.0",
        "props": props or {},
        "children": children or [],
        **({"style": style} if style else {}),
    }


_VERSION_CACHE: dict[str, str] | None = None


def _component_versions() -> dict[str, str]:
    """组件注册表版本，避免生成页面出现「版本不一致」告警。"""
    global _VERSION_CACHE
    if _VERSION_CACHE is None:
        try:
            from components.models import ComponentMeta

            _VERSION_CACHE = dict(ComponentMeta.objects.values_list("name", "version"))
        except Exception:
            _VERSION_CACHE = {}
    return _VERSION_CACHE


def _schema(nodes: dict, title: str, description: str, theme: str) -> dict:
    versions = _component_versions()
    for node in nodes.values():
        if isinstance(node, dict):
            node["componentVersion"] = versions.get(node.get("type"), "2.0.0")
    return {
        "schemaVersion": 2,
        "rootId": "root",
        "nodes": nodes,
        "layout": {"mode": "flow", "width": 1200, "height": 900},
        "variables": {},
        "meta": {
            "title": title,
            "description": description,
            "lang": "zh-CN",
            "seo": {"description": description, "keywords": title},
            "background": {"backgroundColor": THEMES[theme]["bg"]},
        },
        "customCss": "",
    }


def _slug(text: str, fallback: str = "site") -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", str(text or "")).strip("-").lower()
    return value[:24] or fallback


def _trim(value, limit: int, default: str = "") -> str:
    return (str(value).strip() if value is not None else default)[:limit]


def _theme_of(name: str) -> str:
    return name if name in THEMES else "light"


def _detect_theme(prompt: str) -> str:
    text = str(prompt or "").lower()
    if any(word in text for word in ("深色", "暗色", "dark", "黑色", "科技")):
        return "dark"
    if any(word in text for word in ("蓝色", "blue", "清爽")):
        return "blue"
    if any(word in text for word in ("暖色", "橙色", "warm", "杂志")):
        return "warm"
    if any(word in text for word in ("绿色", "green", "自然", "环保")):
        return "green"
    return "light"


# ---------------------------------------------------------------- 蓝图

def _local_items(name: str, keyword: str, category: str) -> list[dict]:
    now = timezone.now()
    templates = [
        (f"{name}正式上线：从 0 到 1 的建站实践", "一次完整的产品上线复盘，包含目标、路径与关键取舍。"),
        (f"{keyword}趋势观察：今年值得关注的五个变化", "从用户需求、产品形态与内容供给三个角度拆解行业变化。"),
        (f"深度解析：{keyword}背后的产品思路", "拆解一个成功案例的设计逻辑、信息架构与增长路径。"),
        (f"新手入门指南：快速掌握{keyword}", "从零开始的上手清单，附常见问题与实用建议。"),
    ]
    rows = []
    for index, (title, summary) in enumerate(templates):
        rows.append({
            "title": title,
            "summary": summary,
            "content": (
                f"{summary}\n\n"
                f"本文围绕「{keyword}」展开，先给出结论，再拆解背后的方法：明确目标用户、梳理信息层级、"
                f"用可复用的组件搭出首屏与内容区，最后通过数据验证效果。\n\n"
                f"如果你正在规划自己的站点，可以从一个最小可用的首页开始，逐步补充列表、详情与关于页面，"
                f"让内容、导航与搜索形成闭环。"
            ),
            "category": category,
            "tags": f"{keyword},{category}",
            "author": "AI 编辑部",
            "published_at": (now - timedelta(days=index)).isoformat(),
        })
    return rows


def _local_topic(prompt: str) -> str:
    """从自然语言需求里提取一个简短主题词（本地模式用）。"""
    text = str(prompt or "").strip()
    text = re.sub(r"^(请|帮我|我想|想要|需要|做一个|做个|建一个|搭建|生成一个|创建|设计一个)\s*", "", text)
    text = re.split(r"[，,。；;：:\n]", text)[0].strip()
    text = re.sub(r"(包含|包括|要有|需要有|需要|带).*$", "", text).strip()
    text = re.sub(r"(网站|站点|官网|系统|门户|网页)$", "", text).strip()
    return text[:16] or "内容"


def _local_pages(prompt: str) -> list[dict]:
    """本地模式的动态页面计划：按行业生成不同频道。"""
    text = str(prompt or "")
    pages = [
        {"kind": "home", "name": "首页", "path": "home"},
        {"kind": "list", "name": "资讯", "path": "news", "category": "资讯", "title": "最新资讯"},
        {"kind": "detail", "name": "文章详情", "path": "article/:id", "list_path": "news"},
        {"kind": "about", "name": "关于我们", "path": "about"},
        {"kind": "contact", "name": "联系我们", "path": "contact"},
        {"kind": "search", "name": "站内搜索", "path": "search"},
    ]
    if any(word in text for word in ("游戏", "评测", "攻略", "媒体", "资讯")):
        pages.extend([
            {"kind": "list", "name": "评测", "path": "reviews", "category": "评测", "title": "游戏评测"},
            {"kind": "detail", "name": "评测详情", "path": "reviews/:id", "list_path": "reviews"},
            {"kind": "list", "name": "攻略", "path": "guides", "category": "攻略", "title": "攻略中心"},
            {"kind": "topic", "name": "专题", "path": "topics", "category": "专题", "title": "专题策划"},
        ])
    if any(word in text for word in ("企业", "官网", "产品", "SaaS", "服务")):
        pages.extend([
            {"kind": "list", "name": "产品", "path": "products", "category": "产品", "title": "产品与服务"},
            {"kind": "detail", "name": "产品详情", "path": "products/:id", "list_path": "products"},
            {"kind": "pricing", "name": "价格", "path": "pricing"},
            {"kind": "docs", "name": "文档", "path": "docs"},
        ])
    if any(word in text for word in ("教育", "课程", "培训")):
        pages.extend([
            {"kind": "list", "name": "课程", "path": "courses", "category": "课程", "title": "课程体系"},
            {"kind": "detail", "name": "课程详情", "path": "courses/:id", "list_path": "courses"},
            {"kind": "pricing", "name": "价格", "path": "pricing"},
        ])
    if any(word in text for word in ("大屏", "仪表盘", "看板", "图表", "报表", "数据总览")):
        pages.append({
            "kind": "dashboard", "name": "数据大屏", "path": "dashboard", "title": "数据大屏",
            "brief": "KPI 卡片 + 趋势图 + 分类占比 + 明细表格",
        })
    if any(word in text for word in ("表单", "录入", "提交", "预约", "登记")):
        pages.append({
            "kind": "form", "name": "在线表单", "path": "form", "title": "在线表单",
            "brief": "复杂表单，双列表单字段，带填写说明和提交按钮",
        })
    if any(word in text for word in ("落地页", "活动页", "专题页", "视觉页")):
        pages.append({
            "kind": "custom", "name": "专题落地页", "path": "campaign", "title": "专题落地页",
            "brief": "非对称图文布局，首屏 + 核心内容 + 数据区",
        })
    return pages


def local_blueprint(prompt: str) -> dict:
    topic = _local_topic(prompt)
    keyword = topic
    name = topic
    suffix = "站"
    for word in ("官网", "系统", "门户"):
        if word in prompt:
            suffix = word
            break
    if not name.endswith(("站", "官网", "系统", "门户")):
        name = f"{name}{suffix}"
    name = name[:20]
    theme = _detect_theme(prompt)
    category = "资讯"
    if any(word in prompt for word in ("产品", "商品", "电商", "商城")):
        category = "产品"
    elif any(word in prompt for word in ("案例", "客户", "方案")):
        category = "案例"
    highlights = [
        {"title": "精选内容", "text": "围绕核心主题持续更新，帮助你快速了解全貌。"},
        {"title": "清晰导航", "text": "首页、列表、详情与关于页形成完整浏览路径。"},
        {"title": "持续迭代", "text": "所有页面都是可视化草稿，可随时在设计器中调整。"},
    ]
    if suffix == "官网":
        tagline = f"{topic}官网，一站式了解产品与服务"
        description = f"{name}展示{topic}的产品、案例与服务信息，帮助客户快速了解并建立联系。"
    elif suffix == "系统":
        tagline = f"{topic}系统，让业务运转更清晰"
        description = f"{name}覆盖{topic}的核心流程与数据视图，帮助团队高效协作。"
    else:
        tagline = f"关于{topic}，这里有你需要的一切"
        description = f"{name}聚焦{topic}，提供精选内容、深度解读与实用指南。"
    return {
        "site": {
            "name": name,
            "tagline": tagline,
            "description": description,
            "theme": theme,
            "highlights": highlights,
        },
        "content": {
            "model": "article",
            "label": "内容",
            "items": _local_items(name, keyword, category),
        },
        "about": {
            "title": f"关于{name}",
            "sections": [
                {"heading": "我们是谁", "body": f"{name}是一个专注于{keyword}的内容站点，持续输出有价值的观察、教程与案例。"},
                {"heading": "我们在做什么", "body": "我们把分散的信息整理成清晰的结构：用列表快速浏览，用详情深入阅读，用搜索直达目标内容。"},
                {"heading": "联系我们", "body": "如果你有选题建议或合作意向，欢迎通过站点导航中的入口与我们取得联系。"},
            ],
        },
        "workflow": {"name": "内容发布审批", "description": "编辑提交内容后由应用所有者审核发布。"},
        "contact": {
            "email": "hello@example.com", "phone": "+86 400-000-0000",
            "address": "中国 · 上海", "hours": "工作日 09:00 - 18:00",
            "intro": "欢迎通过以下方式联系我们，我们会在 1 个工作日内回复。",
        },
        "pricing": {
            "title": "价格方案",
            "plans": [
                {"name": "基础版", "price": "¥0", "period": "/月", "features": ["基础页面", "社区支持", "1 个数据源"]},
                {"name": "专业版", "price": "¥199", "period": "/月", "features": ["全部组件", "优先支持", "10 个数据源"]},
                {"name": "企业版", "price": "定制", "period": "", "features": ["私有部署", "专属顾问", "不限数据源"]},
            ],
        },
        "docs": {
            "title": "文档中心",
            "sections": [
                {"heading": "快速开始", "body": "从创建应用开始，选择模板或让 AI 生成页面，然后在设计器中调整并发布。"},
                {"heading": "数据模型", "body": "数据模型定义字段与权限；内容通过公开 API 提供给页面和搜索。"},
                {"heading": "发布与回滚", "body": "每次发布都会生成不可变快照，可以灰度切换或回滚到上一版本。"},
            ],
        },
        "pages": _local_pages(prompt),
        "warnings": [],
    }


def _chat_json(system: str, user: str, *, max_tokens: int = 3500) -> dict:
    cfg = chat_config()
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.5,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg.get("timeout") or 90) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValueError("LLM 未返回 JSON")
    value, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("LLM 返回的蓝图不是对象")
    return value


def llm_blueprint(prompt: str) -> dict:
    system = "你是全自动建站规划器，只输出严格 JSON。"
    user = f"""根据用户需求生成一个可直接执行的站点蓝图。
用户需求：{prompt}

只输出 JSON：
{{
  "site": {{"name":"站点名(2-16字)","tagline":"首页主标题(6-24字)","description":"站点描述(20-60字)","theme":"light|dark|blue|warm|green","highlights":[{{"title":"4-8字","text":"20-40字"}}]}},
  "content": {{"model":"article","label":"内容","items":[{{"title":"标题","summary":"40-80字摘要","content":"120-220字正文","category":"分类","tags":"逗号分隔标签","author":"作者"}}]}},
  "pages": [{{"kind":"home|list|detail|about|contact|pricing|docs|topic|search|dashboard|form|custom","name":"页面名","path":"路径","category":"列表筛选分类(可选)","list_path":"详情对应的列表路径(可选)","title":"页面标题(可选)","brief":"布局说明(可选)"}}],
  "about": {{"title":"关于我们","sections":[{{"heading":"小节标题","body":"60-120字"}}]}},
  "contact": {{"email":"","phone":"","address":"","hours":"","intro":""}},
  "pricing": {{"title":"价格方案","plans":[{{"name":"基础版","price":"¥0","period":"/月","features":["特性1","特性2"]}}]}},
  "docs": {{"title":"文档中心","sections":[{{"heading":"","body":""}}]}},
  "workflow": {{"name":"内容发布审批","description":"一句话说明"}}
}}
要求：
1. highlights 恰好 3 条；content.items 恰好 4 条；about.sections 2-3 条。
2. pages 6-9 个：必须包含 home、至少一个 list、一个 detail（path 含 :id）、about、search；
   行业需要时增加 contact/pricing/docs/topic 或更多 list/detail；path 唯一，详情 path 如 article/:id。
   用户明确要「大屏/仪表盘/图表/报表」时加 kind=dashboard；要「复杂表单/录入/提交」时加 kind=form；
   要「特殊布局/落地页/活动页」时加 kind=custom；这些页面用 brief 描述布局目标。
3. 内容必须贴合用户需求所属行业，中文，不要 Markdown、不要代码块。
4. theme 根据需求选择：深色/科技=dark，蓝色/清爽=blue，暖色/杂志=warm，绿色/自然=green，其余=light。
5. model 使用英文标识符，默认 article。"""
    return _chat_json(system, user)


PAGE_KINDS = {
    "home", "list", "detail", "about", "contact", "pricing", "docs", "topic", "search",
    "dashboard", "form", "custom", "landing",
}


def _clean_page_path(raw: str, kind: str) -> str:
    text = str(raw or "").strip().strip("/")
    text = re.sub(r"[^A-Za-z0-9_\-/:]", "-", text)
    text = re.sub(r"/{2,}", "/", text)
    if kind == "detail" and ":id" not in text:
        text = f"{text or 'detail'}/:id"
    if kind != "detail":
        text = text.replace("/:id", "")
    return text[:200] or kind


def _display_page_title(value, site_name: str, fallback: str = "") -> str:
    text = str(value or "").strip()
    site = str(site_name or "").strip()
    if site:
        for sep in (" - ", " | ", " — ", "_", "-"):
            suffix = f"{sep}{site}"
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                break
    return text or fallback or site


def _normalize_pages(raw_pages, fallback: list[dict], site: dict) -> list[dict]:
    source = raw_pages if isinstance(raw_pages, list) and raw_pages else fallback
    pages: list[dict] = []
    seen: set[str] = set()
    for entry in source[:16]:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "").strip().lower()
        if kind not in PAGE_KINDS:
            continue
        path = _clean_page_path(entry.get("path") or kind, kind)
        if path in seen:
            continue
        seen.add(path)
        page = {
            "kind": kind,
            "name": _trim(entry.get("name") or kind, 40, kind),
            "path": path,
            "title": _trim(entry.get("title") or entry.get("name") or site.get("tagline"), 80),
            "description": _trim(entry.get("description") or site.get("description"), 160),
            "category": _trim(entry.get("category"), 30),
            "list_path": _trim(entry.get("list_path"), 200),
            "model": _trim(entry.get("model") or "article", 40, "article"),
            "brief": _trim(entry.get("brief") or entry.get("layout_brief"), 300),
        }
        pages.append(page)

    def ensure(kind: str, path: str, name: str):
        if not any(p["kind"] == kind for p in pages):
            fallback_page = next((p for p in fallback if p["kind"] == kind), None)
            item = dict(fallback_page or {"kind": kind, "name": name, "path": path})
            item.setdefault("title", name)
            item.setdefault("description", site.get("description"))
            item.setdefault("category", "")
            item.setdefault("list_path", "")
            item.setdefault("model", "article")
            pages.append(item)

    ensure("home", "home", "首页")
    ensure("list", "news", "资讯")
    ensure("detail", "article/:id", "文章详情")
    ensure("about", "about", "关于我们")
    ensure("contact", "contact", "联系我们")
    ensure("search", "search", "站内搜索")

    lists = [p for p in pages if p["kind"] in ("list", "topic")]
    details = [p for p in pages if p["kind"] == "detail"]
    if not lists:
        lists = [p for p in pages if p["kind"] == "list"]
    if not details:
        details = [p for p in pages if p["kind"] == "detail"]
    if lists and details:
        for detail in details:
            if not detail.get("list_path"):
                detail["list_path"] = lists[0]["path"]
        for item in lists:
            if not item.get("href"):
                detail = next((d for d in details if d.get("list_path") == item["path"]), details[0])
                item["href"] = detail["path"].replace(":id", "{id}")

    order = {"home": 0, "list": 1, "topic": 1, "detail": 2, "about": 3, "contact": 4,
             "pricing": 5, "docs": 6, "dashboard": 7, "form": 8, "custom": 8, "landing": 8, "search": 9}
    indexed = list(enumerate(pages))
    indexed.sort(key=lambda pair: (order.get(pair[1]["kind"], 7), pair[0]))
    return [page for _, page in indexed][:12]


def _normalize_contact(raw, fallback: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    return {
        "email": _trim(data.get("email") or fallback.get("email"), 120),
        "phone": _trim(data.get("phone") or fallback.get("phone"), 60),
        "address": _trim(data.get("address") or fallback.get("address"), 120),
        "hours": _trim(data.get("hours") or fallback.get("hours"), 80),
        "intro": _trim(data.get("intro") or fallback.get("intro"), 300),
    }


def _normalize_pricing(raw, fallback: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    plans = []
    for item in (data.get("plans") if isinstance(data.get("plans"), list) else fallback.get("plans") or [])[:4]:
        if not isinstance(item, dict):
            continue
        plans.append({
            "name": _trim(item.get("name"), 30, "方案"),
            "price": _trim(item.get("price"), 30, "—"),
            "period": _trim(item.get("period"), 20),
            "features": [_trim(x, 40) for x in (item.get("features") or []) if str(x).strip()][:6],
        })
    return {"title": _trim(data.get("title") or fallback.get("title"), 60, "价格方案"), "plans": plans or fallback.get("plans") or []}


def _normalize_docs(raw, fallback: dict) -> dict:
    data = raw if isinstance(raw, dict) else {}
    sections = []
    for item in (data.get("sections") if isinstance(data.get("sections"), list) else fallback.get("sections") or [])[:6]:
        if isinstance(item, dict) and str(item.get("heading") or "").strip():
            sections.append({"heading": _trim(item.get("heading"), 60), "body": _trim(item.get("body"), 600)})
    return {"title": _trim(data.get("title") or fallback.get("title"), 60, "文档中心"), "sections": sections or fallback.get("sections") or []}


def normalize_blueprint(raw: dict, prompt: str) -> dict:
    """把 LLM/本地蓝图裁剪成稳定结构，缺什么补什么。"""
    fallback = local_blueprint(prompt)
    raw = raw if isinstance(raw, dict) else {}
    site = raw.get("site") if isinstance(raw.get("site"), dict) else {}
    content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
    about = raw.get("about") if isinstance(raw.get("about"), dict) else {}

    name = _trim(site.get("name") or fallback["site"]["name"], 20, fallback["site"]["name"])
    tagline = _trim(site.get("tagline") or fallback["site"]["tagline"], 40, fallback["site"]["tagline"])
    description = _trim(site.get("description") or fallback["site"]["description"], 120, fallback["site"]["description"])
    theme = _theme_of(str(site.get("theme") or fallback["site"]["theme"]))

    highlights = []
    raw_highlights = site.get("highlights")
    if not isinstance(raw_highlights, list):
        raw_highlights = []
    for entry in (raw_highlights or fallback["site"]["highlights"])[:3]:
        if isinstance(entry, dict) and str(entry.get("title") or "").strip():
            highlights.append({
                "title": _trim(entry.get("title"), 14),
                "text": _trim(entry.get("text"), 80),
            })
    while len(highlights) < 3:
        highlights.append(fallback["site"]["highlights"][len(highlights)])

    model_name = _trim(content.get("model") or "article", 40)
    model_name = re.sub(r"[^a-zA-Z0-9_]", "_", model_name)
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", model_name):
        model_name = "article"
    label = _trim(content.get("label") or "内容", 20, "内容")

    items = []
    source_items = content.get("items") if isinstance(content.get("items"), list) else []
    for entry in source_items[:6]:
        if not isinstance(entry, dict):
            continue
        title = _trim(entry.get("title"), 120)
        if not title:
            continue
        items.append({
            "title": title,
            "summary": _trim(entry.get("summary"), 200),
            "content": _trim(entry.get("content"), 3000),
            "category": _trim(entry.get("category") or "资讯", 30, "资讯"),
            "tags": _trim(entry.get("tags"), 120),
            "author": _trim(entry.get("author") or "AI 编辑部", 40, "AI 编辑部"),
        })
    if len(items) < 3:
        items = fallback["content"]["items"]
    for index, item in enumerate(items):
        item.setdefault("published_at", (timezone.now() - timedelta(days=index)).isoformat())
        if not item.get("content"):
            item["content"] = f"{item.get('summary') or item['title']}。\n\n这是由 AI 全自动建站生成的示例内容，可随时编辑或删除。"

    sections = []
    raw_sections = about.get("sections")
    if not isinstance(raw_sections, list):
        raw_sections = []
    for entry in (raw_sections or fallback["about"]["sections"])[:4]:
        if isinstance(entry, dict) and str(entry.get("heading") or "").strip():
            sections.append({
                "heading": _trim(entry.get("heading"), 40),
                "body": _trim(entry.get("body"), 600),
            })
    if not sections:
        sections = fallback["about"]["sections"]

    workflow = raw.get("workflow") if isinstance(raw.get("workflow"), dict) else {}
    site_payload = {"name": name, "tagline": tagline, "description": description, "theme": theme, "highlights": highlights}
    pages = _normalize_pages(raw.get("pages"), fallback.get("pages") or [], site_payload)
    return {
        "site": site_payload,
        "content": {"model": model_name, "label": label, "items": items[:6]},
        "pages": pages,
        "about": {"title": _trim(about.get("title") or f"关于{name}", 40), "sections": sections},
        "contact": _normalize_contact(raw.get("contact"), fallback.get("contact") or {}),
        "pricing": _normalize_pricing(raw.get("pricing"), fallback.get("pricing") or {}),
        "docs": _normalize_docs(raw.get("docs"), fallback.get("docs") or {}),
        "workflow": {
            "name": _trim(workflow.get("name") or fallback["workflow"]["name"], 40),
            "description": _trim(workflow.get("description") or fallback["workflow"]["description"], 120),
        },
        "warnings": list(raw.get("warnings") or []),
    }


def generate_blueprint(prompt: str, *, use_llm: bool = True) -> tuple[dict, str, str, list[str]]:
    """返回 (blueprint, provider, model, warnings)。"""
    warnings: list[str] = []
    provider, model = "local", "local-blueprint"
    if use_llm and is_configured():
        cfg = chat_config()
        try:
            raw = llm_blueprint(prompt)
            blueprint = normalize_blueprint(raw, prompt)
            provider = cfg.get("provider_name") or "llm"
            model = cfg.get("model") or ""
            return blueprint, provider, model, warnings
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"LLM 蓝图生成失败，已回退本地生成器：{type(exc).__name__}: {exc}")
    elif use_llm:
        warnings.append("未配置 AI Provider，使用本地蓝图生成器")
    blueprint = normalize_blueprint(local_blueprint(prompt), prompt)
    return blueprint, provider, model, warnings


# ---------------------------------------------------------------- 页面 Schema

def _nav(ctx: dict, links: list[dict]) -> dict:
    theme = THEMES[ctx.get("theme") or "light"]
    return _node("nav", "site-nav", {
        "brand": ctx["site_name"],
        "homePath": "home",
        "sticky": True,
        "dark": ctx.get("theme") == "dark",
        "showSearch": True,
        "searchPath": "search",
        "links": links,
    })


def _footer(ctx: dict) -> dict:
    theme = THEMES[ctx.get("theme") or "light"]
    return _node("footer", "ElContainer", {
        "direction": "vertical", "padding": 22, "background": theme["surface"],
    }, ["footerText"], {"marginTop": "24px"})


def _footer_text(ctx: dict, text: str) -> dict:
    theme = THEMES[ctx.get("theme") or "light"]
    return _node("footerText", "wp-text", {
        "content": text, "align": "center", "color": theme["text"], "fontSize": 12,
    })


def _base_nodes(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    return {
        "root": _node("root", "wp-canvas", {}, ["main"], {"minHeight": "100vh", "background": theme["bg"]}),
        "main": _node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": theme["bg"]}, ["nav"]),
    }


def _page(ctx: dict, nodes: dict, title: str) -> dict:
    out = _schema(nodes, title, ctx["description"], ctx["theme"])
    out["customCss"] = SOURCE_CSS
    return out


SOURCE_CSS = """
body{background:#0b0f14!important;color:#cbd5e1!important}
.wp-runtime{background:#0b0f14!important}
.wp-content-item{background:#121820!important;border:1px solid #1f2a37!important;border-radius:10px!important;padding:12px!important}
.wp-content-item-title a{color:#f3f6fa!important}
.wp-content-summary{color:#93a0ae!important}
.wp-content-meta{color:#6f7c8b!important}
.wp-content-tag{background:#2a1119!important;color:#ff7189!important;border-color:#3f1220!important}
.wp-content-title{color:#f8fafc!important;border-left:4px solid #e11d48;padding-left:10px}
.wp-content-cover{background:#1a2230!important}
.wp-article{background:#0b0f14!important;color:#cbd5e1!important}
.wp-article h1,.wp-article h2,.wp-article h3{color:#f8fafc!important}
.wp-article-content,.wp-article-content p,.wp-article-content li{color:#cbd5e1!important}
.wp-related-item{background:#121820!important;border:1px solid #1f2a37!important}
.wp-related-item strong{color:#f3f6fa!important}
.wp-list{background:#121820!important;border:1px solid #1f2a37!important}
"""


def build_home_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "news"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ])

    nodes["hero"] = _node("hero", "ElContainer", {
        "direction": "vertical", "padding": 64, "background": theme["hero"],
    }, ["heroTag", "heroTitle", "heroText", "heroButton"], {"textAlign": "center"})
    nodes["heroTag"] = _node("heroTag", "ElTag", {
        "text": "AI 全自动建站", "type": "primary", "effect": "light", "size": "small",
    }, [], {"marginBottom": "14px", "alignSelf": "center"})
    nodes["heroTitle"] = _node("heroTitle", "wp-heading", {
        "content": ctx["tagline"], "level": 1, "align": "center",
        "color": theme["title"], "marginBottom": 14,
    })
    nodes["heroText"] = _node("heroText", "wp-text", {
        "content": ctx["description"], "align": "center", "color": theme["text"],
        "fontSize": 15, "lineHeight": 1.8,
    }, [], {"maxWidth": "720px", "margin": "0 auto"})
    nodes["heroButton"] = _node("heroButton", "ElButton", {
        "type": "primary", "size": "large", "text": f"浏览{ctx['label']}",
    }, [], {"marginTop": "20px", "alignSelf": "center"})

    nodes["features"] = _node("features", "ElContainer", {
        "direction": "vertical", "padding": 40, "background": theme["surface"],
    }, ["featuresTitle", "featuresRow"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"})
    nodes["featuresTitle"] = _node("featuresTitle", "wp-heading", {
        "content": "站点亮点", "level": 2, "color": theme["title"], "marginBottom": 16,
    })
    nodes["featuresRow"] = _node("featuresRow", "ElRow", {"gutter": 16}, ["featCol1", "featCol2", "featCol3"])
    for index, highlight in enumerate(ctx["highlights"], start=1):
        col_id = f"featCol{index}"
        card_id = f"featCard{index}"
        head_id = f"featHead{index}"
        text_id = f"featText{index}"
        nodes[col_id] = _node(col_id, "ElCol", {"span": 8}, [card_id])
        nodes[card_id] = _node(card_id, "ElCard", {"shadow": "never"}, [head_id, text_id], {"padding": "18px", "background": theme["bg"], "borderRadius": "10px"})
        nodes[head_id] = _node(head_id, "wp-heading", {"content": highlight["title"], "level": 3, "color": theme["title"], "marginBottom": 8})
        nodes[text_id] = _node(text_id, "wp-text", {"content": highlight["text"], "color": theme["text"], "lineHeight": 1.7, "fontSize": 13})

    nodes["latest"] = _node("latest", "ElContainer", {
        "direction": "vertical", "padding": 36, "background": theme["bg"],
    }, ["latestTitle", "latestList"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"})
    nodes["latestTitle"] = _node("latestTitle", "wp-heading", {
        "content": f"最新{ctx['label']}", "level": 2, "color": theme["title"], "marginBottom": 16,
    })
    nodes["latestList"] = _node("latestList", "content-list", {
        "dataModelId": ctx["model_id"],
        "mode": "grid",
        "heading": "",
        "pageSize": 6,
        "showPagination": False,
        "showSearch": False,
        "hrefPattern": ctx.get("list_href") or "article/{id}",
        "filters": {"status": "published"},
        "showCategoryTabs": True,
        "categoryField": "category",
        "emptyText": "还没有内容，去后台添加第一篇吧",
    })

    channel_ids = []
    for index, channel in enumerate((ctx.get("home_channels") or [])[:3], start=1):
        section_id = f"channel{index}"
        head_id = f"channelHead{index}"
        list_id = f"channelList{index}"
        nodes[section_id] = _node(section_id, "ElContainer", {
            "direction": "vertical", "padding": 0, "background": theme["bg"],
        }, [head_id, list_id], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto", "padding": "20px 16px 0"})
        nodes[head_id] = _node(head_id, "wp-heading", {
            "content": channel.get("title") or "精选", "level": 2, "color": theme["title"], "marginBottom": 14,
        })
        nodes[list_id] = _node(list_id, "content-list", {
            "dataModelId": ctx["model_id"], "mode": "grid", "pageSize": 3,
            "showPagination": False, "showSearch": False, "showCategoryTabs": False,
            "hrefPattern": channel.get("href") or ctx.get("list_href") or "article/{id}",
            "filters": {"status": "published", **({"category": channel["category"]} if channel.get("category") else {})},
            "emptyText": "暂无内容",
        })
        channel_ids.append(section_id)

    nodes["aboutTeaser"] = _node("aboutTeaser", "ElContainer", {
        "direction": "vertical", "padding": 40, "background": theme["surface"],
    }, ["aboutTeaserTitle", "aboutTeaserText"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"})
    nodes["aboutTeaserTitle"] = _node("aboutTeaserTitle", "wp-heading", {
        "content": ctx["about_title"], "level": 2, "color": theme["title"], "marginBottom": 10,
    })
    nodes["aboutTeaserText"] = _node("aboutTeaserText", "wp-text", {
        "content": ctx["about_intro"], "color": theme["text"], "lineHeight": 1.8,
    })
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']} · 由 AI 全自动建站生成")

    nodes["main"]["children"] = ["nav", "hero", "features", "latest", *channel_ids, "aboutTeaser", "footer"]
    return _page(ctx, nodes, ctx["tagline"])


def build_list_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "news"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ])
    nodes["header"] = _node("header", "ElContainer", {
        "direction": "vertical", "padding": 36, "background": theme["hero"],
    }, ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {
        "content": ctx["label"], "level": 1, "align": "center", "color": theme["title"], "marginBottom": 8,
    })
    nodes["headerText"] = _node("headerText", "wp-text", {
        "content": ctx["description"], "align": "center", "color": theme["text"], "fontSize": 14,
    })

    nodes["body"] = _node("body", "ElContainer", {
        "direction": "vertical", "padding": 32, "background": theme["bg"],
    }, ["list"], {"maxWidth": "1180px", "width": "100%", "margin": "0 auto"})
    nodes["list"] = _node("list", "content-list", {
        "dataModelId": ctx["model_id"],
        "mode": "list",
        "pageSize": 10,
        "showPagination": True,
        "showSearch": True,
        "searchPlaceholder": f"搜索{ctx['label']}…",
        "hrefPattern": "article/{id}",
        "filters": {"status": "published"},
        "showCategoryTabs": True,
        "categoryField": "category",
        "emptyText": "暂无内容",
    })
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, f"{ctx['label']} - {ctx['site_name']}")


def build_detail_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "news"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ])
    nodes["article"] = _node("article", "article-detail", {
        "dataModelId": ctx["model_id"],
        "lookup": "id",
        "titleField": "title",
        "summaryField": "summary",
        "contentField": "content",
        "coverField": "cover",
        "authorField": "author",
        "dateField": "published_at",
        "categoryField": "category",
        "tagsField": "tags",
        "backPath": "news",
        "articlePath": "article/{id}",
        "showRelated": True,
        "relatedLimit": 3,
    }, [], {"maxWidth": "880px", "margin": "0 auto", "padding": "24px 16px"})
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "article", "footer"]
    return _page(ctx, nodes, ctx["site_name"])


def build_about_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "news"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ])
    nodes["hero"] = _node("hero", "ElContainer", {
        "direction": "vertical", "padding": 56, "background": theme["hero"],
    }, ["heroTitle", "heroText"], {"textAlign": "center"})
    nodes["heroTitle"] = _node("heroTitle", "wp-heading", {
        "content": ctx["about_title"], "level": 1, "align": "center", "color": theme["title"], "marginBottom": 10,
    })
    nodes["heroText"] = _node("heroText", "wp-text", {
        "content": ctx["tagline"], "align": "center", "color": theme["text"], "fontSize": 15,
    })

    children = ["aboutBody"]
    nodes["aboutBody"] = _node("aboutBody", "ElContainer", {
        "direction": "vertical", "padding": 40, "background": theme["surface"],
    }, [], {"maxWidth": "860px", "width": "100%", "margin": "0 auto", "borderRadius": "12px"})
    for index, section in enumerate(ctx["about_sections"], start=1):
        head = f"aboutHead{index}"
        body = f"aboutText{index}"
        nodes[head] = _node(head, "wp-heading", {
            "content": section["heading"], "level": 2, "color": theme["title"], "marginBottom": 8,
        })
        nodes[body] = _node(body, "wp-text", {
            "content": section["body"], "color": theme["text"], "lineHeight": 1.9, "fontSize": 14,
        }, [], {"marginBottom": "20px"})
        nodes["aboutBody"]["children"].extend([head, body])

    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "hero", "aboutBody", "footer"]
    return _page(ctx, nodes, ctx["about_title"])


def build_search_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "news"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ])
    nodes["search"] = _node("search", "site-search", {
        "heading": "站内搜索",
        "description": f"搜索{ctx['site_name']}已发布的全部内容。",
        "placeholder": "输入关键词，回车搜索…",
        "limit": 20,
    }, [], {"maxWidth": "820px", "margin": "32px auto", "padding": "0 16px"})
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "search", "footer"]
    return _page(ctx, nodes, f"搜索 - {ctx['site_name']}")


def build_contact_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    contact = ctx.get("contact") or {}
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [])
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {"content": "联系我们", "level": 1, "align": "center",
                                                              "color": theme["title"], "marginBottom": 8})
    nodes["headerText"] = _node("headerText", "wp-text", {"content": contact.get("intro") or "欢迎与我们联系。",
                                                         "align": "center", "color": theme["text"], "fontSize": 14})
    nodes["body"] = _node("body", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["bg"]},
                          ["cards"], {"maxWidth": "1100px", "width": "100%", "margin": "0 auto"})
    nodes["cards"] = _node("cards", "ElRow", {"gutter": 16}, ["c1", "c2", "c3", "c4"])
    items = [
        ("邮箱", contact.get("email") or "hello@example.com"),
        ("电话", contact.get("phone") or "400-000-0000"),
        ("地址", contact.get("address") or "中国"),
        ("工作时间", contact.get("hours") or "工作日 09:00 - 18:00"),
    ]
    for index, (label, value) in enumerate(items, start=1):
        col, card, head, text = f"c{index}", f"card{index}", f"h{index}", f"t{index}"
        nodes[col] = _node(col, "ElCol", {"span": 6}, [card])
        nodes[card] = _node(card, "ElCard", {"shadow": "never"}, [head, text],
                            {"background": theme["surface"], "borderRadius": "10px", "padding": "18px"})
        nodes[head] = _node(head, "wp-heading", {"content": label, "level": 3, "color": theme["title"], "marginBottom": 6})
        nodes[text] = _node(text, "wp-text", {"content": value, "color": theme["text"], "fontSize": 14})
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, "联系我们")


def build_pricing_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    pricing = ctx.get("pricing") or {}
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [])
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {"content": pricing.get("title") or "价格方案",
                                                              "level": 1, "align": "center",
                                                              "color": theme["title"], "marginBottom": 8})
    nodes["headerText"] = _node("headerText", "wp-text", {"content": "选择适合你的方案，随时升级或调整。",
                                                         "align": "center", "color": theme["text"], "fontSize": 14})
    nodes["body"] = _node("body", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["bg"]},
                          ["row"], {"maxWidth": "1100px", "width": "100%", "margin": "0 auto"})
    plans = (pricing.get("plans") or [])[:3]
    nodes["row"] = _node("row", "ElRow", {"gutter": 16}, [f"p{i}" for i in range(len(plans))])
    for index, plan in enumerate(plans, start=1):
        col, card, name, price, period = f"p{index}", f"pc{index}", f"pn{index}", f"pp{index}", f"pe{index}"
        nodes[col] = _node(col, "ElCol", {"span": 8}, [card])
        nodes[card] = _node(card, "ElCard", {"shadow": "never"}, [name, price, period],
                            {"background": theme["surface"], "borderRadius": "12px", "padding": "22px"})
        nodes[name] = _node(name, "wp-heading", {"content": plan.get("name") or "方案", "level": 3,
                                                "color": theme["title"], "marginBottom": 8})
        nodes[price] = _node(price, "wp-heading", {"content": f"{plan.get('price') or ''}{plan.get('period') or ''}",
                                                  "level": 2, "color": THEME_ACCENT(theme), "marginBottom": 10})
        nodes[period] = _node(period, "wp-text", {
            "content": " · ".join(plan.get("features") or []), "color": theme["text"], "fontSize": 13, "lineHeight": 1.8,
        })
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, pricing.get("title") or "价格方案")


def build_docs_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    docs = ctx.get("docs") or {}
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [])
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {"content": docs.get("title") or "文档中心",
                                                              "level": 1, "align": "center",
                                                              "color": theme["title"], "marginBottom": 8})
    nodes["headerText"] = _node("headerText", "wp-text", {"content": "从入门到进阶，快速了解平台能力。",
                                                         "align": "center", "color": theme["text"], "fontSize": 14})
    nodes["body"] = _node("body", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["surface"]},
                          [], {"maxWidth": "860px", "width": "100%", "margin": "0 auto", "borderRadius": "12px"})
    for index, section in enumerate((docs.get("sections") or [])[:6], start=1):
        head, text = f"dh{index}", f"dt{index}"
        nodes[head] = _node(head, "wp-heading", {"content": section.get("heading") or f"第 {index} 节",
                                                "level": 2, "color": theme["title"], "marginBottom": 8})
        nodes[text] = _node(text, "wp-text", {"content": section.get("body") or "", "color": theme["text"],
                                             "fontSize": 14, "lineHeight": 1.9}, [], {"marginBottom": "20px"})
        nodes["body"]["children"].extend([head, text])
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, docs.get("title") or "文档中心")


def build_custom_schema(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [])
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {"content": ctx.get("page_title") or ctx["site_name"],
                                                              "level": 1, "align": "center",
                                                              "color": theme["title"], "marginBottom": 8})
    nodes["headerText"] = _node("headerText", "wp-text", {"content": ctx.get("page_description") or ctx["description"],
                                                         "align": "center", "color": theme["text"], "fontSize": 14})
    nodes["body"] = _node("body", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["surface"]},
                          ["bodyText"], {"maxWidth": "860px", "width": "100%", "margin": "0 auto", "borderRadius": "12px"})
    nodes["bodyText"] = _node("bodyText", "wp-text", {
        "content": (ctx.get("about_intro") or ctx["description"]), "color": theme["text"], "fontSize": 14, "lineHeight": 1.9,
    })
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, ctx.get("page_title") or ctx["site_name"])


def THEME_ACCENT(theme: dict) -> str:
    return theme.get("soft") or theme.get("title")


# ---------------------------------------------------------------- 封面

def _make_covers(app, count: int = 6) -> list[str]:
    """生成站点封面图，返回可访问 URL 列表；失败时返回空列表。"""
    try:
        from PIL import Image, ImageDraw
    except Exception:
        return []
    try:
        from django.conf import settings

        target = Path(settings.MEDIA_ROOT) / "autobuild" / app.code
        target.mkdir(parents=True, exist_ok=True)
    except Exception:
        return []
    palettes = [
        ((15, 23, 42), (239, 68, 68)), ((30, 58, 138), (96, 165, 250)),
        ((17, 24, 39), (168, 85, 247)), ((6, 78, 59), (52, 211, 153)),
        ((120, 53, 15), (251, 191, 36)), ((76, 29, 149), (244, 114, 182)),
    ]
    urls = []
    for index in range(count):
        c1, c2 = palettes[index % len(palettes)]
        width, height = 900, 520
        image = Image.new("RGB", (width, height), c1)
        draw = ImageDraw.Draw(image, "RGBA")
        for y in range(height):
            ratio = y / max(1, height - 1) * 0.8
            draw.line(
                [(0, y), (width, y)],
                fill=(
                    int(c1[0] + (c2[0] - c1[0]) * ratio),
                    int(c1[1] + (c2[1] - c1[1]) * ratio),
                    int(c1[2] + (c2[2] - c1[2]) * ratio),
                ),
            )
        draw.ellipse([width * 0.55, -height * 0.2, width * 1.15, height * 0.75], fill=(255, 255, 255, 28))
        draw.ellipse([-width * 0.15, height * 0.55, width * 0.45, height * 1.25], fill=(0, 0, 0, 45))
        draw.rectangle([40, height - 86, 250, height - 40], fill=(255, 255, 255, 235))
        draw.text((56, height - 76), f"{app.code[:10].upper()}  {index + 1:02d}", fill=(20, 20, 20))
        filename = f"cover-{index + 1}.jpg"
        image.save(target / filename, quality=86)
        urls.append(f"/media/autobuild/{app.code}/{filename}")
    return urls


# ---------------------------------------------------------------- 任务执行

class _Cancelled(Exception):
    pass


def _log(job: AiBuildJob, message: str) -> None:
    line = f"[{timezone.now().strftime('%H:%M:%S')}] {message}"
    job.logs = (job.logs + "\n" + line).strip()[-20000:]
    AiBuildJob.objects.filter(id=job.id).update(logs=job.logs)


def _save_steps(job: AiBuildJob, steps: list[dict], *, status: str | None = None, progress: int | None = None, current: str | None = None) -> None:
    fields: dict = {"steps": steps}
    if status:
        fields["status"] = status
    if progress is not None:
        fields["progress"] = progress
    if current is not None:
        fields["current_step"] = current
    AiBuildJob.objects.filter(id=job.id).update(**fields)


def _unique_code(base: str) -> str:
    from appcore.models import App

    candidate = base
    suffix = 1
    while App.objects.filter(code=candidate).exists():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


# ---------------------------------------------------------------- PostgreSQL 数据源建站

def _quote_ident(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _source_cfg_from_dict(src: dict, user=None) -> dict | None:
    if not isinstance(src, dict):
        return None
    table = str(src.get("table") or "").strip()
    if not table:
        return None
    base: dict = {}
    datasource_id = src.get("datasource_id")
    if datasource_id:
        from core.permissions import get_app_role
        from datasources.executor import decode_secrets
        from datasources.models import Datasource
        from wp_utils import is_platform_admin_full

        ds = Datasource.objects.filter(id=datasource_id).first()
        if ds is None:
            raise ValidationError({"detail": "已有数据源不存在"})
        if not is_platform_admin_full(user) and (user is None or get_app_role(user, ds.app) is None):
            raise ValidationError({"detail": "没有该数据源的访问权限"})
        if ds.type != "postgres":
            raise ValidationError({"detail": "建站目前仅支持 PostgreSQL 数据源"})
        base = decode_secrets(ds.config or {})
    schema = str(src.get("schema") or base.get("schema") or "public").strip() or "public"
    try:
        limit = min(500, max(1, int(src.get("limit") or 200)))
    except (TypeError, ValueError):
        limit = 200
    database = str(src.get("database") or base.get("database") or "").strip()
    if not database:
        raise ValidationError({"detail": "PostgreSQL 数据源需要 database"})
    cfg = {
        "host": str(src.get("host") or base.get("host") or "127.0.0.1").strip(),
        "port": int(src.get("port") or base.get("port") or 5432),
        "database": database,
        "username": str(src.get("username") or base.get("username") or "").strip(),
        "password": decrypt_secret(str(src.get("password") or "")) or base.get("password") or "",
        "schema": schema,
        "table": table,
        "limit": limit,
        "ssl": str(src.get("ssl") or base.get("ssl") or "prefer"),
        "timeout": 15,
        "max_rows": limit,
        "query": f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)} LIMIT {limit}",
        "label": str(src.get("label") or "数据").strip() or "数据",
    }
    return cfg


def source_config(job: AiBuildJob) -> dict | None:
    """读取任务里的单个 PostgreSQL 数据源配置；密码在任务表里是密文。"""
    return _source_cfg_from_dict((job.options or {}).get("source"), job.user)


def source_configs(job: AiBuildJob) -> list[dict]:
    """支持 options.sources（多表/多模型），兼容单个 options.source。"""
    raw = (job.options or {}).get("sources")
    configs = []
    if isinstance(raw, list) and raw:
        for item in raw[:6]:
            cfg = _source_cfg_from_dict(item, job.user)
            if cfg is not None:
                configs.append(cfg)
        if configs:
            return configs
    one = source_config(job)
    return [one] if one is not None else []


def _pg_field_type(pg_type: str) -> str:
    text = str(pg_type or "").lower()
    if any(token in text for token in ("int", "numeric", "decimal", "real", "double", "money")):
        return "number"
    if text == "boolean":
        return "boolean"
    if "timestamp" in text or text == "date":
        return "date"
    if "json" in text:
        return "json"
    return "string"


def _field_name(name: str, used: set[str]) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]", "_", str(name or "")).strip("_") or "field"
    if base[0].isdigit():
        base = f"f_{base}"
    base = base[:60]
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}_{index}"
        index += 1
    used.add(candidate)
    return candidate


def _detect_mapping(columns: list[dict]) -> dict:
    names = [str(c.get("name") or "") for c in columns]
    lower = {name.lower(): name for name in names}

    def pick(candidates: list[str]) -> str:
        for candidate in candidates:
            if candidate in lower:
                return lower[candidate]
        return ""

    text_columns = [str(c.get("name")) for c in columns if _pg_field_type(c.get("type")) == "string"]
    title = pick(["title", "name", "symbol", "game", "product", "stock_name", "company"]) or (text_columns[0] if text_columns else (names[0] if names else ""))
    summary = pick(["summary", "description", "desc", "intro", "remark", "industry"]) or title
    content = pick(["content", "detail", "body", "description", "summary"]) or summary
    cover = pick(["cover", "image", "img", "logo", "icon", "picture"])
    author = pick(["author", "developer", "publisher", "maker", "company"])
    category = pick(["category", "genre", "type", "industry", "market", "sector"])
    tags = pick(["tags", "platform", "exchange", "label"])
    date = pick(["published_at", "release_date", "date", "updated_at", "created_at", "time"])
    status = pick(["status", "state"])
    return {
        "title": title, "summary": summary, "content": content, "cover": cover,
        "author": author, "category": category, "tags": tags, "date": date, "status": status,
    }


def _sql_value(value):
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")[:2000]
    return value


def _build_source_model(job: AiBuildJob, ctx: dict, cfg: dict) -> None:
    from datamodels.models import DataModel
    from datasources.executor import encode_secrets, list_external_schema
    from datasources.models import Datasource

    app = ctx["app"]
    tables = list_external_schema("postgres", cfg)
    target = None
    for table in tables:
        if str(table.get("schema")) == cfg["schema"] and str(table.get("name")) == cfg["table"]:
            target = table
            break
    if target is None:
        for table in tables:
            if str(table.get("name")).lower() == cfg["table"].lower():
                target = table
                break
    if target is None:
        raise RuntimeError(f"PostgreSQL 中找不到表 {cfg['schema']}.{cfg['table']}")
    columns = target.get("columns") or []
    if not columns:
        raise RuntimeError("表没有可用字段")

    used: set[str] = set()
    fields = []
    column_map: dict[str, str] = {}
    for column in columns[:40]:
        original = str(column.get("name") or "")
        name = _field_name(original, used)
        column_map[original] = name
        fields.append({
            "name": name,
            "type": _pg_field_type(column.get("type")),
            "required": False,
            "label": original[:80],
            "description": f"PostgreSQL {column.get('type')}",
        })
    mapping = {key: column_map.get(value, "") for key, value in _detect_mapping(columns).items()}
    mapping["columns"] = column_map
    derive_summary = not mapping.get("summary") or mapping.get("summary") == mapping.get("title")
    derive_content = not mapping.get("content") or mapping.get("content") == mapping.get("title")
    if derive_summary:
        fields.append({"name": "summary", "type": "string", "required": False, "label": "摘要"})
        mapping["summary"] = "summary"
    if derive_content:
        fields.append({"name": "content", "type": "string", "required": False, "label": "详情"})
        mapping["content"] = "content"

    model_name = re.sub(r"[^a-zA-Z0-9_]", "_", str(cfg["table"]).lower()).strip("_")[:80] or "source_data"
    if model_name[0].isdigit():
        model_name = f"t_{model_name}"
    if DataModel.objects.filter(app=app, name=model_name).exists():
        model_name = f"{model_name}_{len(ctx.get('sources') or []) + 1}"
    model = DataModel.objects.create(
        app=app, name=model_name, fields=fields, is_public=True,
        data_scope="all", created_by=job.user,
    )
    datasource = Datasource.objects.create(
        app=app, name=f"{cfg['table']} (PostgreSQL)", type="postgres",
        config=encode_secrets(cfg), status="active", created_by=job.user,
    )
    source = {
        "cfg": cfg, "model": model, "mapping": mapping, "columns": columns,
        "datasource": datasource, "label": cfg.get("label") or "数据",
        "derive_summary": derive_summary, "derive_content": derive_content,
        "field_labels": {name: original for original, name in column_map.items()},
    }
    ctx.setdefault("sources", []).append(source)
    if "model" not in ctx:
        ctx["model"] = model
        ctx["source_cfg"] = cfg
        ctx["source_mapping"] = mapping
        ctx["source_columns"] = columns
        ctx["source_label"] = source["label"]
        ctx["derive_summary"] = derive_summary
        ctx["derive_content"] = derive_content
        ctx["field_labels"] = source["field_labels"]
        ctx["datasource"] = datasource
        ctx["datasource_id"] = datasource.id
    _log(job, f"数据源已连接：{cfg['database']}.{cfg['schema']}.{cfg['table']}（{len(columns)} 列，模型 {model.name}）")


def _import_source_rows(job: AiBuildJob, ctx: dict, source: dict | None = None) -> None:
    from datamodels.models import DataRecord
    from datasources.executor import execute_external_db

    source = source or {
        "cfg": ctx["source_cfg"], "model": ctx["model"], "mapping": ctx["source_mapping"],
        "derive_summary": ctx.get("derive_summary"), "derive_content": ctx.get("derive_content"),
        "field_labels": ctx.get("field_labels") or {},
    }
    cfg = source["cfg"]
    model = source["model"]
    mapping = source["mapping"]
    rows = execute_external_db("postgres", cfg, {})
    created = 0
    for row in rows:
        data = {}
        for original, value in row.items():
            name = mapping["columns"].get(original)
            if name:
                data[name] = _sql_value(value)
        if mapping.get("status") and mapping["status"] in data:
            status_value = str(data.get(mapping["status"]) or "").lower()
            if status_value not in ("published", "draft", "scheduled", "rejected"):
                data[mapping["status"]] = "published"
        if mapping.get("date") and mapping["date"] in data:
            data["published_at"] = data.get(mapping["date"])
        if source.get("derive_summary"):
            preferred = [k for k in ("symbol", "name", "title", "price", "pct_change", "change", "industry", "market", "platform") if data.get(k) not in (None, "")]
            parts = [str(data[k]) for k in preferred[:4]] or [
                str(v) for k, v in data.items() if v not in (None, "") and k not in ("summary", "content", "ranking", "id")
            ][:3]
            data["summary"] = " · ".join(parts)[:300]
        if source.get("derive_content"):
            import html as _html

            labels = source.get("field_labels") or {}
            lines = [
                f"<p><strong>{_html.escape(str(labels.get(k, k)))}</strong>：{_html.escape(str(v))}</p>"
                for k, v in data.items()
                if v not in (None, "") and k not in ("summary", "content", "ranking", "created_at")
            ]
            data["content"] = "".join(lines[:10])[:2000]
        DataRecord.objects.create(model=model, data=data, created_by=job.user, updated_by=job.user)
        created += 1
    source["records"] = created
    ctx["records"] = ctx.get("records", 0) + created
    _log(job, f"从 PostgreSQL 导入 {created} 条记录（{source['model'].name}）")


def _source_home(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    mapping = ctx["source_mapping"]
    filters = {"status": "published"} if mapping.get("status") else {}
    links = ctx.get("nav_links") or [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "data"},
        {"label": "实时", "path": "live"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ]
    list_href = ctx.get("list_href") or "data/{id}"
    nodes = _base_nodes(ctx)
    nodes["nav"] = _node("nav", "site-nav", {
        "brand": ctx["site_name"], "homePath": "home", "sticky": True,
        "dark": ctx["theme"] == "dark", "showSearch": True, "searchPath": "search", "links": links,
    })
    nodes["hero"] = _node("hero", "ElContainer", {"direction": "vertical", "padding": 54, "background": theme["hero"]},
                          ["heroTag", "heroTitle", "heroText", "heroBtn"],
                          {"background": f"linear-gradient(120deg,{theme['hero']} 0%,{theme['soft']} 60%,{theme['bg']} 100%)"})
    nodes["heroTag"] = _node("heroTag", "ElTag", {"text": "实时行情", "type": "danger", "effect": "dark", "size": "small"},
                             [], {"alignSelf": "center", "marginBottom": "14px"})
    nodes["heroTitle"] = _node("heroTitle", "wp-heading", {"content": ctx["tagline"], "level": 1, "align": "center",
                                                          "color": theme["title"], "marginBottom": 12})
    nodes["heroText"] = _node("heroText", "wp-text", {"content": ctx["description"], "align": "center",
                                                     "color": theme["text"], "fontSize": 15, "lineHeight": 1.8},
                              [], {"maxWidth": "760px", "margin": "0 auto"})
    nodes["heroBtn"] = _node("heroBtn", "ElButton", {"type": "danger", "size": "large", "text": f"浏览{ctx['label']}"},
                             [], {"alignSelf": "center", "marginTop": "18px"})
    nodes["mainRow"] = _node("mainRow", "ElRow", {"gutter": 18}, ["latestCol", "rankCol"],
                             {"maxWidth": "1240px", "width": "100%", "margin": "0 auto", "padding": "24px 16px 0"})
    nodes["latestCol"] = _node("latestCol", "ElCol", {"span": 16}, ["latestHead", "latestList"])
    nodes["rankCol"] = _node("rankCol", "ElCol", {"span": 8}, ["rankHead", "rankList"])
    nodes["latestHead"] = _node("latestHead", "wp-heading", {"content": f"最新{ctx['label']}", "level": 2,
                                                            "color": theme["title"], "marginBottom": 14})
    nodes["latestList"] = _node("latestList", "content-list", {
        "dataModelId": ctx["model_id"], "mode": "list", "pageSize": 8,
        "showPagination": False, "showSearch": False, "showCategoryTabs": False,
        "hrefPattern": list_href, "filters": filters,
        "titleField": mapping["title"], "summaryField": mapping["summary"],
        "coverField": mapping["cover"], "dateField": mapping["date"],
        "authorField": mapping["author"], "tagsField": mapping["tags"],
        "categoryField": mapping["category"],
    })
    nodes["rankHead"] = _node("rankHead", "wp-heading", {"content": "热门排行", "level": 2,
                                                        "color": theme["title"], "marginBottom": 14})
    nodes["rankList"] = _node("rankList", "content-list", {
        "dataModelId": ctx["model_id"], "mode": "ranking", "pageSize": 6,
        "showPagination": False, "showSearch": False, "showCategoryTabs": False,
        "hrefPattern": list_href, "filters": filters,
        "titleField": mapping["title"], "summaryField": mapping["summary"],
        "coverField": mapping["cover"], "dateField": mapping["date"],
    })
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']} · 数据来自 PostgreSQL")
    nodes["main"]["children"] = ["nav", "hero", "mainRow", "footer"]
    return _page(ctx, nodes, ctx["tagline"])


def _source_live_page(ctx: dict) -> dict:
    theme = THEMES[ctx["theme"]]
    columns = [c.get("name") for c in (ctx.get("source_columns") or [])][:4]
    fields = [ctx["source_mapping"]["columns"].get(c, "") for c in columns]
    fields = [f for f in fields if f][:3]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _node("nav", "site-nav", {
        "brand": ctx["site_name"], "homePath": "home", "sticky": True,
        "dark": ctx["theme"] == "dark", "showSearch": True, "searchPath": "search",
        "links": [
            {"label": "首页", "path": "home"}, {"label": ctx["label"], "path": "data"},
            {"label": "实时", "path": "live"}, {"label": "关于", "path": "about"},
            {"label": "搜索", "path": "search"},
        ],
    })
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {"content": "实时数据", "level": 1, "align": "center",
                                                              "color": theme["title"], "marginBottom": 8})
    nodes["headerText"] = _node("headerText", "wp-text", {
        "content": "直接查询 PostgreSQL 数据源；需要登录且是应用成员。",
        "align": "center", "color": theme["text"], "fontSize": 13,
    })
    nodes["body"] = _node("body", "ElContainer", {"direction": "vertical", "padding": 28, "background": theme["bg"]},
                          ["loadBtn", "liveList"], {"maxWidth": "1000px", "width": "100%", "margin": "0 auto"})
    nodes["loadBtn"] = _node("loadBtn", "ElButton", {"type": "danger", "size": "large", "text": "加载 PostgreSQL 数据"},
                             [], {"alignSelf": "center", "marginBottom": "16px"})
    nodes["loadBtn"]["events"] = {"click": [{
        "id": "load-ds", "kind": "callDatasource", "params": {"ref": f"ds_{ctx['datasource_id']}"},
    }]}
    nodes["liveList"] = _node("liveList", "wp-list", {"direction": "vertical", "gap": 8, "padding": 12,
                                                      "background": theme["surface"], "borderRadius": 8},
                              ["liveRow"])
    nodes["liveList"]["dataBinding"] = {
        "source": "datasource", "ref": f"ds_{ctx['datasource_id']}", "field": "data", "loopVar": "row",
    }
    content = " · ".join("{{row.%s}}" % field for field in fields) if fields else "{{row}}"
    nodes["liveRow"] = _node("liveRow", "wp-text", {
        "content": content, "color": theme["text"], "fontSize": 14, "lineHeight": 1.6,
    }, [], {"display": "block", "padding": "4px 0"})
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, "实时数据")


def _publish_source_pages_legacy(job: AiBuildJob, ctx: dict) -> None:
    from pages.models import Page
    from pages.services import publish_page, save_draft

    app = ctx["app"]
    blueprint = ctx["blueprint"]
    site = blueprint["site"]
    about = blueprint["about"]
    mapping = ctx["source_mapping"]
    ctx.update({
        "theme": site["theme"], "site_name": site["name"], "tagline": site["tagline"],
        "description": site["description"], "label": ctx.get("source_label") or "数据",
        "model_id": ctx["model"].id, "highlights": site["highlights"],
        "about_title": about["title"], "about_sections": about["sections"],
        "about_intro": (about["sections"][0]["body"] if about["sections"] else site["description"])[:180],
    })
    latest = _source_home(ctx)
    list_schema = build_list_schema(ctx)
    list_nodes = list_schema["nodes"]
    if "headerTitle" in list_nodes:
        list_nodes["headerTitle"]["props"]["content"] = f"{ctx['label']}列表"
    if "headerText" in list_nodes:
        list_nodes["headerText"]["props"]["content"] = f"共 {ctx.get('records', 0)} 条 PostgreSQL 数据"
    list_nodes["list"]["props"].update({
        "hrefPattern": "data/{id}", "filters": {"status": "published"} if mapping.get("status") else {},
        "titleField": mapping["title"], "summaryField": mapping["summary"], "coverField": mapping["cover"],
        "dateField": mapping["date"], "authorField": mapping["author"], "tagsField": mapping["tags"],
        "categoryField": mapping["category"],
    })
    detail = build_detail_schema(ctx)
    detail["nodes"]["article"]["props"].update({
        "titleField": mapping["title"], "summaryField": mapping["summary"], "contentField": mapping["content"],
        "coverField": mapping["cover"], "authorField": mapping["author"], "dateField": mapping["date"],
        "categoryField": mapping["category"], "tagsField": mapping["tags"],
        "articlePath": "data/{id}", "backPath": "data",
    })
    definitions = [
        ("home", f"{ctx['site_name']}首页", latest),
        ("data", f"{ctx['label']}列表", list_schema),
        ("data/:id", f"{ctx['label']}详情", detail),
        ("search", "站内搜索", build_search_schema(ctx)),
        ("about", "关于我们", build_about_schema(ctx)),
    ]
    if ctx.get("datasource_id"):
        definitions.append(("live", "实时数据", _source_live_page(ctx)))
    links = [
        {"label": "首页", "path": "home"},
        {"label": ctx["label"], "path": "data"},
        {"label": "实时", "path": "live"},
        {"label": "关于", "path": "about"},
        {"label": "搜索", "path": "search"},
    ]
    for _path, _name, schema_obj in definitions:
        nav = (schema_obj.get("nodes") or {}).get("nav")
        if nav:
            nav.setdefault("props", {})["links"] = links
    created = []
    for path, name, schema_obj in definitions:
        page = Page.objects.create(app=app, name=name, path=path, type="page", schema={})
        page, errors, warnings = save_draft(page, schema_obj, job.user)
        version, pub_errors, pub_warnings = publish_page(page, job.user, "PostgreSQL 数据源建站")
        if version is None:
            raise RuntimeError(f"页面 {path} 发布失败：{pub_errors or pub_warnings}")
        created.append({"id": page.id, "name": name, "path": path, "version": version.version})
        _log(job, f"页面已发布：{name} /{path}")
    ctx["pages"] = created


def _source_slug(source: dict) -> str:
    base = _slug(str(source["model"].name or "data"), "data")
    return base.replace("_", "-")[:40] or "data"


def _with_source(ctx: dict, source: dict):
    keys = (
        "model", "model_id", "label", "source_cfg", "source_mapping", "source_columns",
        "source_label", "derive_summary", "derive_content", "field_labels", "datasource", "datasource_id",
    )
    saved = {key: ctx.get(key) for key in keys}
    ctx.update({
        "model": source["model"], "model_id": source["model"].id, "label": source["label"],
        "source_cfg": source["cfg"], "source_mapping": source["mapping"], "source_columns": source["columns"],
        "source_label": source["label"], "derive_summary": source.get("derive_summary"),
        "derive_content": source.get("derive_content"), "field_labels": source.get("field_labels") or {},
        "datasource": source.get("datasource"), "datasource_id": (source.get("datasource").id if source.get("datasource") else None),
    })
    return saved


def _restore_source(ctx: dict, saved: dict) -> None:
    for key, value in saved.items():
        if value is None:
            ctx.pop(key, None)
        else:
            ctx[key] = value


def _source_list_schema(ctx: dict, source: dict, list_path: str, detail_path: str) -> dict:
    saved = _with_source(ctx, source)
    try:
        schema_obj = build_list_schema(ctx)
    finally:
        _restore_source(ctx, saved)
    nodes = schema_obj["nodes"]
    nodes["headerTitle"]["props"]["content"] = source["label"]
    nodes["headerText"]["props"]["content"] = f"共 {source.get('records', 0)} 条 PostgreSQL 数据"
    mapping = source["mapping"]
    nodes["list"]["props"].update({
        "hrefPattern": detail_path.replace(":id", "{id}"),
        "filters": {"status": "published"} if mapping.get("status") else {},
        "showCategoryTabs": False,
        "titleField": mapping["title"], "summaryField": mapping["summary"], "coverField": mapping["cover"],
        "dateField": mapping["date"], "authorField": mapping["author"], "tagsField": mapping["tags"],
        "categoryField": mapping["category"],
    })
    schema_obj["meta"]["title"] = f"{source['label']} - {ctx['site_name']}"
    return schema_obj


def _source_detail_schema(ctx: dict, source: dict, list_path: str, detail_path: str) -> dict:
    relations = [
        item for item in (ctx.get("relations") or [])
        if item.get("master") == source["model"].name
    ] if ctx.get("enable_master_detail") else []
    if relations:
        return _source_master_detail_schema(ctx, source, list_path, relations)
    saved = _with_source(ctx, source)
    try:
        schema_obj = build_detail_schema(ctx)
    finally:
        _restore_source(ctx, saved)
    mapping = source["mapping"]
    schema_obj["nodes"]["article"]["props"].update({
        "titleField": mapping["title"], "summaryField": mapping["summary"], "contentField": mapping["content"],
        "coverField": mapping["cover"], "authorField": mapping["author"], "dateField": mapping["date"],
        "categoryField": "", "tagsField": mapping["tags"],
        "articlePath": detail_path.replace(":id", "{id}"), "backPath": list_path,
    })
    schema_obj["meta"]["title"] = f"{source['label']}详情 - {ctx['site_name']}"
    relations = [item for item in (ctx.get("relations") or []) if item.get("master") == source["model"].name] if ctx.get("enable_master_detail") else []
    if relations:
        versions = _component_versions()
        main = schema_obj["nodes"]["main"]
        children = main.get("children") or []
        for index, relation in enumerate(relations, start=1):
            child = next((item for item in (ctx.get("sources") or []) if item["model"].id == relation["child_id"]), None)
            if child is None:
                continue
            section_id, head_id, table_id = f"relSection{index}", f"relTitle{index}", f"relTable{index}"
            columns = []
            for field in (child["model"].fields or [])[:8]:
                if isinstance(field, dict):
                    columns.append({"prop": field.get("name"), "label": field.get("label") or field.get("name")})
            schema_obj["nodes"][section_id] = _node(section_id, "ElContainer", {
                "direction": "vertical", "padding": 18, "background": THEMES[ctx["theme"]]["surface"],
            }, [head_id, table_id], {"maxWidth": "880px", "width": "100%", "margin": "18px auto", "borderRadius": "10px"})
            schema_obj["nodes"][head_id] = _node(head_id, "wp-heading", {
                "content": f"{child['label']}明细", "level": 3,
                "color": THEMES[ctx["theme"]]["title"], "marginBottom": 10,
            })
            schema_obj["nodes"][table_id] = _node(table_id, "relation-table", {
                "modelId": child["model"].id,
                "masterModelId": source["model"].id,
                "foreignKey": relation["foreign_key"],
                "parentId": "",
                "parentField": "id",
                "title": "",
                "columns": columns,
                "pageSize": 5,
                "stripe": True,
                "border": True,
                "allowAdd": False,
                "editable": False,
                "allowDelete": False,
            })
            schema_obj["nodes"][table_id]["componentVersion"] = versions.get("relation-table", "2.0.0")
            if "footer" in children:
                children.insert(children.index("footer"), section_id)
            else:
                children.append(section_id)
        main["children"] = children
    return schema_obj


def _source_master_detail_schema(ctx: dict, source: dict, list_path: str, relations: list[dict]) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [])
    mapping = source["mapping"]
    relation_payload = []
    for relation in relations:
        child = next((item for item in (ctx.get("sources") or []) if item["model"].id == relation["child_id"]), None)
        if child is None:
            continue
        columns = []
        for field in (child["model"].fields or [])[:8]:
            if isinstance(field, dict):
                columns.append({"prop": field.get("name"), "label": field.get("label") or field.get("name")})
        relation_payload.append({
            "modelId": child["model"].id,
            "foreignKey": relation["foreign_key"],
            "title": f"{child['label']}明细",
            "columns": columns,
            "allowAdd": True,
            "fields": [
                {
                    "name": field.get("name"), "type": field.get("type") or "string",
                    "label": field.get("label") or field.get("name"),
                    "required": bool(field.get("required")),
                }
                for field in (child["model"].fields or [])[:30] if isinstance(field, dict)
            ],
        })
    nodes["detail"] = _node("detail", "public-master-detail", {
        "masterModelId": source["model"].id,
        "masterKeyField": "id",
        "titleField": mapping["title"],
        "summaryField": mapping["summary"],
        "contentField": mapping["content"],
        "relations": relation_payload,
        "backPath": list_path,
        "listPath": list_path,
    }, [], {"maxWidth": "960px", "margin": "0 auto", "padding": "24px 16px"})
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "detail", "footer"]
    schema = _page(ctx, nodes, f"{source['label']}详情 - {ctx['site_name']}")
    schema.setdefault("meta", {})["allowPublicSubmit"] = True
    schema["meta"]["requireCaptcha"] = True
    return schema


def _source_overview(ctx: dict, sources: list[dict]) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _node("nav", "site-nav", {
        "brand": ctx["site_name"], "homePath": "home", "sticky": True,
        "dark": ctx["theme"] == "dark", "showSearch": True, "searchPath": "search",
        "links": ctx.get("nav_links") or [],
    })
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 40, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {"content": "数据总览", "level": 1, "align": "center",
                                                              "color": theme["title"], "marginBottom": 8})
    nodes["headerText"] = _node("headerText", "wp-text", {
        "content": f"共 {len(sources)} 个数据模型、{ctx.get('records', 0)} 条记录，来自 PostgreSQL。",
        "align": "center", "color": theme["text"], "fontSize": 14,
    })
    nodes["body"] = _node("body", "ElContainer", {"direction": "vertical", "padding": 32, "background": theme["bg"]},
                          [], {"maxWidth": "1240px", "width": "100%", "margin": "0 auto"})
    for index, source in enumerate(sources, start=1):
        section, head, text, list_id = f"ov{index}", f"ovh{index}", f"ovt{index}", f"ovl{index}"
        slug = _source_slug(source)
        nodes[section] = _node(section, "ElContainer", {"direction": "vertical", "padding": 0, "background": theme["bg"]},
                               [head, text, list_id], {"marginBottom": "24px"})
        nodes[head] = _node(head, "wp-heading", {"content": f"{source['label']}（{source['model'].name}）",
                                                "level": 2, "color": theme["title"], "marginBottom": 6})
        nodes[text] = _node(text, "wp-text", {"content": f"{source.get('records', 0)} 条记录 · 数据源 {source['cfg']['table']}",
                                             "color": theme["text"], "fontSize": 13}, [], {"marginBottom": "10px"})
        nodes[list_id] = _node(list_id, "content-list", {
            "dataModelId": source["model"].id, "mode": "grid", "pageSize": 3,
            "showPagination": False, "showSearch": False, "showCategoryTabs": False,
            "hrefPattern": f"data/{slug}/{{id}}",
            "filters": {"status": "published"} if source["mapping"].get("status") else {},
            "titleField": source["mapping"]["title"], "summaryField": source["mapping"]["summary"],
            "coverField": source["mapping"]["cover"], "dateField": source["mapping"]["date"],
        })
        nodes["body"]["children"].append(section)
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']} · PostgreSQL 多模型")
    nodes["main"]["children"] = ["nav", "header", "body", "footer"]
    return _page(ctx, nodes, f"数据总览 - {ctx['site_name']}")


def _source_join_schema(ctx: dict, master: dict, child: dict, relation: dict, chain: list[dict] | None = None) -> dict:
    theme = THEMES[ctx["theme"]]
    nodes = _base_nodes(ctx)
    nodes["nav"] = _nav(ctx, ctx.get("nav_links") or [])
    nodes["header"] = _node("header", "ElContainer", {"direction": "vertical", "padding": 32, "background": theme["hero"]},
                            ["headerTitle", "headerText"], {"textAlign": "center"})
    nodes["headerTitle"] = _node("headerTitle", "wp-heading", {
        "content": f"{master['label']} × {child['label']}", "level": 1, "align": "center",
        "color": theme["title"], "marginBottom": 8,
    })
    nodes["headerText"] = _node("headerText", "wp-text", {
        "content": f"按 {relation['foreign_key']} 关联的宽表视图",
        "align": "center", "color": theme["text"], "fontSize": 13,
    })
    chain = chain or [relation]
    relations_payload = []
    mask_fields = []
    sensitive = re.compile(r"(phone|mobile|email|id_card|identity|address|contact|手机|邮箱|身份证|地址)", re.I)
    for field in (master["model"].fields or []):
        if isinstance(field, dict) and sensitive.search(str(field.get("name") or "")):
            mask_fields.append(str(field.get("name")))
    for index, item in enumerate(chain):
        child_source = next((source for source in (ctx.get("sources") or []) if source["model"].id == item["child_id"]), None)
        if child_source is not None:
            relations_payload.append({
                "modelId": child_source["model"].id,
                "foreignKey": item["foreign_key"],
                "parentKey": "id" if index else "id",
            })
            prefix = ["child_", "grandchild_", "level3_"][index] if index < 3 else f"level{index + 2}_"
            for field in (child_source["model"].fields or []):
                if isinstance(field, dict) and sensitive.search(str(field.get("name") or "")):
                    mask_fields.append(f"{prefix}{field.get('name')}")
    nodes["join"] = _node("join", "public-join-table", {
        "masterModelId": master["model"].id,
        "childModelId": child["model"].id,
        "foreignKey": relation["foreign_key"],
        "masterKeyField": "id",
        "relations": relations_payload,
        "maskFields": mask_fields,
        "title": f"{master['label']}汇总",
        "pageSize": 20,
    }, [], {"margin": "20px 0"})
    nodes["footer"] = _footer(ctx)
    nodes["footerText"] = _footer_text(ctx, f"© {timezone.now().year} {ctx['site_name']}")
    nodes["main"]["children"] = ["nav", "header", "join", "footer"]
    return _page(ctx, nodes, f"{master['label']}汇总 - {ctx['site_name']}")


def _publish_source_pages(job: AiBuildJob, ctx: dict) -> None:
    from pages.models import Page
    from pages.services import publish_page, save_draft

    app = ctx["app"]
    blueprint = ctx["blueprint"]
    site = blueprint["site"]
    about = blueprint["about"]
    sources = ctx.get("sources") or []
    if not sources:
        raise RuntimeError("没有可用的 PostgreSQL 数据源")
    first = sources[0]
    first_slug = _source_slug(first)
    ctx.update({
        "theme": site["theme"], "site_name": site["name"], "tagline": site["tagline"],
        "description": site["description"], "label": first["label"],
        "model": first["model"], "model_id": first["model"].id,
        "source_mapping": first["mapping"], "source_cfg": first["cfg"],
        "source_columns": first["columns"], "source_label": first["label"],
        "derive_summary": first.get("derive_summary"), "derive_content": first.get("derive_content"),
        "field_labels": first.get("field_labels") or {},
        "datasource": first.get("datasource"), "datasource_id": (first.get("datasource").id if first.get("datasource") else None),
        "highlights": site["highlights"], "about_title": about["title"],
        "about_sections": about["sections"],
        "about_intro": (about["sections"][0]["body"] if about["sections"] else site["description"])[:180],
        "list_href": f"data/{first_slug}/{{id}}",
        "site_prompt": job.prompt,
        "use_llm": bool(job.options.get("use_llm", True)),
        "enable_master_detail": bool(job.options.get("master_detail", False)),
    })
    custom_specs = [
        spec for spec in (blueprint.get("pages") or [])
        if spec.get("kind") in ("dashboard", "form", "custom", "landing")
    ]
    join_specs = []
    for relation in (ctx.get("relations") or [])[:2]:
        master = next((item for item in sources if item["model"].id == relation.get("master_id")), None)
        child = next((item for item in sources if item["model"].id == relation.get("child_id")), None)
        if master is None or child is None:
            continue
        join_specs.append({
            "path": f"join/{_source_slug(master)}-{_source_slug(child)}",
            "name": f"{master['label']}汇总",
            "master": master,
            "child": child,
            "relation": relation,
            "chain": [relation],
        })
    links = [{"label": "首页", "path": "home"}]
    if len(sources) > 1:
        links.append({"label": "总览", "path": "overview"})
    for source in sources[:4]:
        links.append({"label": source["label"], "path": f"data/{_source_slug(source)}"})
    if ctx.get("datasource_id"):
        links.append({"label": "实时", "path": "live"})
    for spec in custom_specs[:3]:
        links.append({"label": spec["name"], "path": spec["path"]})
    for spec in join_specs:
        links.append({"label": spec["name"], "path": spec["path"]})
    links.extend([{"label": "关于", "path": "about"}, {"label": "搜索", "path": "search"}])
    ctx["nav_links"] = links[:13]
    for spec in join_specs:
        current = spec["child"]["model"].name
        for relation in ctx.get("relations") or []:
            if len(spec["chain"]) >= 3:
                break
            if relation.get("master") != current or relation.get("child") == spec["master"]["model"].name:
                continue
            if any(item.get("child") == relation.get("child") for item in spec["chain"]):
                continue
            spec["chain"].append(relation)
            current = relation.get("child")

    definitions: list[tuple[str, str, dict, str]] = []
    definitions.append(("home", f"{ctx['site_name']}首页", _source_home(ctx), "home"))
    for source in sources:
        slug = _source_slug(source)
        list_path = f"data/{slug}"
        detail_path = f"data/{slug}/:id"
        definitions.append((list_path, source["label"], _source_list_schema(ctx, source, list_path, detail_path), "list"))
        definitions.append((detail_path, f"{source['label']}详情", _source_detail_schema(ctx, source, list_path, detail_path), "detail"))
    if len(sources) > 1:
        definitions.append(("overview", "数据总览", _source_overview(ctx, sources), "overview"))
    for spec in join_specs:
        definitions.append((spec["path"], spec["name"], _source_join_schema(ctx, spec["master"], spec["child"], spec["relation"], spec["chain"]), "join"))
    if ctx.get("datasource_id"):
        definitions.append(("live", "实时数据", _source_live_page(ctx), "live"))
    definitions.append(("search", "站内搜索", build_search_schema(ctx), "search"))
    definitions.append(("about", "关于我们", build_about_schema(ctx), "about"))
    page_kinds = {spec.get("kind") for spec in blueprint.get("pages") or []}
    if "contact" in page_kinds:
        definitions.append(("contact", "联系我们", build_contact_schema(ctx), "contact"))
    if "pricing" in page_kinds:
        definitions.append(("pricing", "价格", build_pricing_schema(ctx), "pricing"))
    if "docs" in page_kinds:
        definitions.append(("docs", "文档", build_docs_schema(ctx), "docs"))
    for spec in custom_specs:
        from ai.pagelayout import generate_layout

        if any(item[0] == spec["path"] for item in definitions):
            continue
        palette = {**THEMES[ctx["theme"]], "dark": ctx["theme"] == "dark"}
        schema_obj, layout_provider = generate_layout(
            ctx, spec, spec["kind"], [source["model"] for source in sources], palette, ctx["nav_links"],
        )
        definitions.append((spec["path"], spec.get("title") or spec["name"], schema_obj, spec["kind"]))
        _log(job, f"AI 布局生成 {spec['path']}（{spec['kind']}，{layout_provider}）")

    override = job.options.get("pages_override")
    if isinstance(override, list) and override:
        selected = [item for item in override if isinstance(item, dict) and item.get("enabled", True) is not False]
        allowed = {str(item.get("path") or "") for item in selected}
        names = {str(item.get("path") or ""): str(item.get("name") or "") for item in selected}
        if allowed:
            kept = [item for item in definitions if item[0] in allowed]
            if not any(item[0] == "home" for item in kept):
                kept.insert(0, next(item for item in definitions if item[0] == "home"))
            definitions = [(path, names.get(path) or name, schema, kind) for path, name, schema, kind in kept]
            keep_paths = {item[0] for item in definitions}
            ctx["nav_links"] = [link for link in ctx["nav_links"] if link["path"] in keep_paths or link["path"] == "search"]

    for _path, _name, schema_obj, _kind in definitions:
        nav = (schema_obj.get("nodes") or {}).get("nav")
        if nav:
            nav.setdefault("props", {})["links"] = ctx["nav_links"]
    created = []
    for path, name, schema_obj, kind in definitions:
        schema_obj.setdefault("meta", {})["aiKind"] = kind
        page = Page.objects.create(app=app, name=name[:200], path=path, type="page", schema={})
        page, errors, warnings = save_draft(page, schema_obj, job.user)
        version, pub_errors, pub_warnings = publish_page(page, job.user, "PostgreSQL 数据源建站")
        if version is None:
            raise RuntimeError(f"页面 {path} 发布失败：{pub_errors or pub_warnings}")
        created.append({"id": page.id, "name": name, "path": path, "kind": kind, "version": version.version})
        _log(job, f"页面已发布：{name} /{path}")
    ctx["pages"] = created


def _link_source_relations(job: AiBuildJob, ctx: dict) -> None:
    """把 *_id 字段自动关联到同名模型（多表编排），并记录主从关系。"""
    sources = ctx.get("sources") or []
    by_name = {source["model"].name: source for source in sources}

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

    by_norm = {normalize(source["model"].name): source for source in sources}
    linked = 0
    relations = []
    for source in sources:
        fields = source["model"].fields or []
        changed = False
        for field in fields:
            if not isinstance(field, dict):
                continue
            name = str(field.get("name") or "")
            if not name.endswith("_id") or name in ("id", "user_id"):
                continue
            prefix = name[:-3]
            target = by_name.get(prefix) or by_name.get(f"{prefix}s")
            if target is None:
                target = by_norm.get(normalize(prefix))
            if target is None:
                normalized_prefix = normalize(prefix)
                target = next(
                    (item for model_name, item in by_norm.items()
                     if normalize(model_name).endswith(normalized_prefix)),
                    None,
                )
            if target is None:
                continue
            field["type"] = "reference"
            field["ref_model"] = target["model"].name
            changed = True
            linked += 1
            relations.append({
                "master": target["model"].name,
                "master_id": target["model"].id,
                "child": source["model"].name,
                "child_id": source["model"].id,
                "foreign_key": name,
            })
        if changed:
            source["model"].fields = fields
            source["model"].save(update_fields=["fields", "updated_at"])
    if relations:
        ctx["relations"] = relations
        _log(job, f"自动关联 {linked} 个 *_id 字段，生成 {len(relations)} 条主从关系")


def _step_plan(job: AiBuildJob, ctx: dict) -> None:
    blueprint = provider = model = None
    warnings = []
    if job.options.get("use_dsh", True):
        try:
            from ai.dsh import build_blueprint as dsh_build_blueprint, configured as dsh_configured

            if dsh_configured():
                _log(job, "使用 DSH 高级引擎生成建站蓝图")
                result = dsh_build_blueprint(job.prompt, job.options or {})
                blueprint = result["blueprint"]
                provider = result["provider"]
                model = result["model"]
                warnings = result["warnings"]
                _log(job, f"DSH 蓝图已返回：{blueprint['site'].get('name')}")
        except Exception as exc:  # noqa: BLE001
            warnings = [f"DSH 不可用，已回退内置蓝图：{type(exc).__name__}: {exc}"]
            _log(job, warnings[0])
    if blueprint is None:
        blueprint, provider, model, warnings = generate_blueprint(
            job.prompt, use_llm=bool(job.options.get("use_llm", True))
        )
    job.blueprint = blueprint
    job.provider = provider
    job.model = model
    AiBuildJob.objects.filter(id=job.id).update(blueprint=blueprint, provider=provider, model=model)
    ctx["blueprint"] = blueprint
    ctx["warnings"] = warnings
    for warning in warnings:
        _log(job, f"提示：{warning}")
    _log(job, f"蓝图：{blueprint['site']['name']} / 主题 {blueprint['site']['theme']} / {len(blueprint['content']['items'])} 条示例内容")


def _step_app(job: AiBuildJob, ctx: dict) -> None:
    from appcore.models import App, AppMember

    blueprint = ctx["blueprint"]
    site = blueprint["site"]
    code = _unique_code(f"auto-{_slug(site['name'], 'site')}-{uuid.uuid4().hex[:4]}")
    app = App.objects.create(
        name=site["name"][:200],
        code=code,
        description=site["description"],
        owner=job.user,
        status="draft",
    )
    AppMember.objects.create(app=app, user=job.user, role="owner")
    ctx["app"] = app
    job.app = app
    AiBuildJob.objects.filter(id=job.id).update(app=app)
    _log(job, f"应用已创建：{app.name} /{app.code}")


def _step_model(job: AiBuildJob, ctx: dict) -> None:
    configs = source_configs(job)
    if configs:
        for cfg in configs:
            _build_source_model(job, ctx, cfg)
        _link_source_relations(job, ctx)
        return
    from datamodels.models import DataModel
    from datamodels.services import validate_fields_spec

    app = ctx["app"]
    blueprint = ctx["blueprint"]
    fields = validate_fields_spec(copy.deepcopy(CONTENT_FIELDS), app=app)
    model = DataModel.objects.create(
        app=app,
        name=blueprint["content"]["model"],
        fields=fields,
        is_public=True,
        data_scope="all",
        review_required=bool(job.options.get("enable_review", False)),
        review_roles=["owner"] if job.options.get("enable_review") else [],
        created_by=job.user,
    )
    ctx["model"] = model
    _log(job, f"内容模型已创建：{model.name}（{len(fields)} 个字段，公开读取）")


def _step_content(job: AiBuildJob, ctx: dict) -> None:
    if ctx.get("source_cfg"):
        for source in ctx.get("sources") or []:
            _import_source_rows(job, ctx, source)
        return
    from datamodels.models import DataRecord

    app = ctx["app"]
    model = ctx["model"]
    blueprint = ctx["blueprint"]
    covers = _make_covers(app, count=max(3, min(6, len(blueprint["content"]["items"]))))
    created = 0
    if job.options.get("sample_content", True):
        for index, item in enumerate(blueprint["content"]["items"]):
            data = {
                "title": item["title"],
                "summary": item.get("summary") or "",
                "content": item.get("content") or "",
                "cover": covers[index % len(covers)] if covers else "",
                "author": item.get("author") or "AI 编辑部",
                "category": item.get("category") or "资讯",
                "tags": item.get("tags") or "",
                "status": "published",
                "published_at": item.get("published_at") or timezone.now().isoformat(),
            }
            DataRecord.objects.create(model=model, data=data, created_by=job.user, updated_by=job.user)
            created += 1

    # 动态频道：为每个分类频道补 2 条示例，避免“产品/课程/专题”页空白。
    categories = []
    for spec in blueprint.get("pages") or []:
        if spec.get("kind") in ("list", "topic") and spec.get("category"):
            categories.append(spec["category"])
    if job.options.get("sample_content", True) and blueprint["content"]["items"]:
        existing = {str((record.data or {}).get("category") or "") for record in DataRecord.objects.filter(model=model)}
        templates = blueprint["content"]["items"][:2]
        for category in dict.fromkeys(categories):
            if category in existing:
                continue
            for index, item in enumerate(templates):
                data = {
                    "title": f"{category}｜{item['title']}",
                    "summary": item.get("summary") or "",
                    "content": item.get("content") or "",
                    "cover": covers[index % len(covers)] if covers else "",
                    "author": item.get("author") or "AI 编辑部",
                    "category": category,
                    "tags": item.get("tags") or "",
                    "status": "published",
                    "published_at": (timezone.now() - timedelta(days=index)).isoformat(),
                }
                DataRecord.objects.create(model=model, data=data, created_by=job.user, updated_by=job.user)
                created += 1
    ctx["records"] = created
    _log(job, f"示例内容：{created} 条（已发布）")


def _step_pages(job: AiBuildJob, ctx: dict) -> None:
    if ctx.get("source_cfg"):
        _publish_source_pages(job, ctx)
        return
    from pages.models import Page
    from pages.services import publish_page, save_draft
    from datamodels.models import DataModel

    app = ctx["app"]
    model = ctx["model"]
    blueprint = ctx["blueprint"]
    site = blueprint["site"]
    theme = site["theme"]
    highlights = site["highlights"]
    about = blueprint["about"]
    ctx.update({
        "theme": theme,
        "site_name": site["name"],
        "tagline": site["tagline"],
        "description": site["description"],
        "label": blueprint["content"]["label"],
        "model_id": model.id,
        "highlights": highlights,
        "about_title": about["title"],
        "about_intro": (about["sections"][0]["body"] if about["sections"] else site["description"])[:180],
        "about_sections": about["sections"],
        "site_prompt": job.prompt,
        "use_llm": bool(job.options.get("use_llm", True)),
    })
    layout_models = list(DataModel.objects.filter(app=app).order_by("id"))

    override = job.options.get("pages_override")
    if isinstance(override, list) and override:
        cleaned = [page for page in override[:16] if isinstance(page, dict) and page.get("enabled", True) is not False]
        page_specs = _normalize_pages(cleaned, blueprint.get("pages") or [], site)
    else:
        page_specs = blueprint.get("pages") or _normalize_pages([], [], site)
    nav_links = [
        {"label": spec["name"], "path": spec["path"]}
        for spec in page_specs
        if spec["kind"] in ("home", "list", "topic", "about", "contact", "pricing", "docs",
                            "dashboard", "form", "custom", "landing", "search")
    ][:9]
    if not any(link["path"] == "search" for link in nav_links):
        nav_links.append({"label": "搜索", "path": "search"})
    lists = [spec for spec in page_specs if spec["kind"] in ("list", "topic")]
    details = [spec for spec in page_specs if spec["kind"] == "detail"]
    first_detail = details[0] if details else {"path": "article/:id", "list_path": "news"}
    first_list = lists[0] if lists else {"path": "news", "name": "资讯"}
    ctx.update({
        "nav_links": nav_links,
        "list_href": (first_detail.get("path") or "article/:id").replace(":id", "{id}"),
        "home_channels": [
            {
                "title": spec.get("title") or spec["name"],
                "category": spec.get("category") or "",
                "href": (spec.get("href") or ctx.get("list_href") or "article/{id}"),
            }
            for spec in lists
            if spec.get("category")
        ],
    })

    created_pages = []
    for spec in page_specs:
        kind = spec["kind"]
        path = spec["path"]
        name = spec["name"]
        ctx["page_title"] = spec.get("title") or name
        ctx["page_description"] = spec.get("description") or ctx["description"]
        if kind == "home":
            schema_obj = build_home_schema(ctx)
        elif kind in ("list", "topic"):
            schema_obj = build_list_schema(ctx)
            list_nodes = schema_obj["nodes"]
            heading = _display_page_title(spec.get("title") or name, ctx["site_name"], name)
            list_nodes["headerTitle"]["props"]["content"] = heading
            list_nodes["headerText"]["props"]["content"] = spec.get("description") or ctx["description"]
            filters = {"status": "published"}
            category = spec.get("category") or ("专题" if kind == "topic" else "")
            if category:
                filters["category"] = category
            list_nodes["list"]["props"].update({
                "hrefPattern": spec.get("href") or ctx["list_href"],
                "filters": filters,
                "showCategoryTabs": False,
            })
            schema_obj["meta"]["title"] = f"{spec.get('title') or name} - {ctx['site_name']}"
        elif kind == "detail":
            schema_obj = build_detail_schema(ctx)
            article = schema_obj["nodes"]["article"]["props"]
            article.update({
                "articlePath": path.replace(":id", "{id}"),
                "backPath": spec.get("list_path") or first_list["path"],
                "categoryField": "",
            })
            schema_obj["meta"]["title"] = f"{spec.get('title') or name} - {ctx['site_name']}"
        elif kind == "about":
            schema_obj = build_about_schema(ctx)
        elif kind == "contact":
            schema_obj = build_contact_schema(ctx)
        elif kind == "pricing":
            schema_obj = build_pricing_schema(ctx)
        elif kind == "docs":
            schema_obj = build_docs_schema(ctx)
        elif kind in ("dashboard", "form", "custom", "landing"):
            from ai.pagelayout import generate_layout

            palette = {**THEMES[ctx["theme"]], "dark": ctx["theme"] == "dark"}
            schema_obj, layout_provider = generate_layout(
                ctx, spec, kind, layout_models, palette, nav_links,
            )
            _log(job, f"AI 布局生成 {path}（{kind}，{layout_provider}）")
        elif kind == "search":
            schema_obj = build_search_schema(ctx)
        else:
            schema_obj = build_custom_schema(ctx)
        nav = (schema_obj.get("nodes") or {}).get("nav")
        if nav:
            nav.setdefault("props", {})["links"] = nav_links
        schema_obj.setdefault("meta", {})["aiKind"] = kind
        page = Page.objects.create(app=app, name=name[:200], path=path, type="page", schema={})
        page, errors, warnings = save_draft(page, schema_obj, job.user)
        for message in list(errors) + list(warnings):
            _log(job, f"页面 {path} 校验提示：{message}")
        version, publish_errors, publish_warnings = publish_page(page, job.user, "AI 全自动建站")
        if version is None:
            raise RuntimeError(f"页面 {path} 发布失败：{publish_errors or publish_warnings}")
        created_pages.append({"id": page.id, "name": name, "path": path, "kind": kind, "version": version.version})
        _log(job, f"页面已发布：{name} /{path}（{kind}）")
    ctx["pages"] = created_pages


def _step_review(job: AiBuildJob, ctx: dict) -> None:
    """结构评审 + 截图评审，并对可确定的问题自动修复一轮。"""
    from ai.review import review_schema
    from pages.models import Page

    app = ctx["app"]
    pages = list(Page.objects.filter(app=app).order_by("id"))
    if not pages:
        return

    def structure_round():
        rows = []
        for page in pages:
            result = review_schema(page.schema or {})
            rows.append({"page": page, "score": result.get("score", 0), "issues": result.get("issues") or []})
        errors = sum(1 for row in rows for issue in row["issues"] if issue.get("level") == "error")
        warnings = sum(1 for row in rows for issue in row["issues"] if issue.get("level") == "warning")
        avg = round(sum(row["score"] for row in rows) / max(1, len(rows)), 1)
        return {"score": avg, "errors": errors, "warnings": warnings, "pages": rows}

    before = structure_round()
    _log(job, f"结构评审：平均 {before['score']} 分，error {before['errors']}，warning {before['warnings']}")
    fixed_pages = []
    if before["errors"] or before["warnings"] or before["score"] < 80:
        fixed_pages = _apply_review_fixes(job, ctx, pages)
        if fixed_pages:
            _log(job, f"自动修复 {len(fixed_pages)} 个页面：{', '.join(fixed_pages)}")
    after = structure_round()

    visual = {"score": None, "pages": 0, "issues": 0, "mode": "skipped", "warnings": []}
    try:
        visual = _visual_round(job, ctx, pages)
    except Exception as exc:  # noqa: BLE001
        visual["warnings"].append(f"截图评审失败：{type(exc).__name__}: {exc}")
        _log(job, visual["warnings"][-1])

    ctx["review"] = {
        "structure": {"before": before["score"], "after": after["score"],
                      "errors": after["errors"], "warnings": after["warnings"]},
        "visual": visual,
        "fixed_pages": fixed_pages,
    }
    _log(job, f"评审完成：结构 {after['score']} 分，视觉 {visual.get('score') if visual.get('score') is not None else '跳过'}")


def _apply_review_fixes(job: AiBuildJob, ctx: dict, pages: list) -> list[str]:
    from pages.services import publish_page, save_draft

    fixed = []
    for page in pages:
        schema = copy.deepcopy(page.schema or {})
        nodes = schema.setdefault("nodes", {})
        meta = schema.setdefault("meta", {})
        changed = False
        if not str(meta.get("title") or "").strip():
            meta["title"] = page.name
            changed = True
        if not str(meta.get("description") or "").strip():
            meta["description"] = ctx.get("description") or ctx.get("site_name") or page.name
            changed = True
        if not any(isinstance(n, dict) and n.get("type") == "site-nav" for n in nodes.values()):
            nav = _nav(ctx, ctx.get("nav_links") or [])
            nav["id"] = "reviewNav"
            nodes["reviewNav"] = nav
            main = nodes.get("main") or nodes.get(schema.get("rootId") or "")
            if isinstance(main, dict):
                main["children"] = ["reviewNav", *(main.get("children") or [])]
            changed = True
        if not any(isinstance(n, dict) and n.get("type") == "wp-text" and "footer" in str(n.get("id")) for n in nodes.values()):
            footer = _footer(ctx)
            footer["id"] = "reviewFooter"
            footer["children"] = ["reviewFooterText"]
            footer_text = _footer_text(ctx, f"© {timezone.now().year} {ctx.get('site_name') or ''}")
            footer_text["id"] = "reviewFooterText"
            nodes["reviewFooter"] = footer
            nodes["reviewFooterText"] = footer_text
            main = nodes.get("main") or nodes.get(schema.get("rootId") or "")
            if isinstance(main, dict):
                main["children"] = [*(main.get("children") or []), "reviewFooter"]
            changed = True
        if not changed:
            continue
        page, errors, warnings = save_draft(page, schema, job.user)
        version, pub_errors, pub_warnings = publish_page(page, job.user, "AI 自动评审修复")
        if version is not None:
            fixed.append(page.path)
        else:
            _log(job, f"修复发布失败 {page.path}：{pub_errors or pub_warnings}")
    return fixed


def _visual_round(job: AiBuildJob, ctx: dict, pages: list) -> dict:
    from django.conf import settings

    from ai.visual import review_screenshot

    if not getattr(settings, "AUTOBUILD_SCREENSHOT", True):
        return {"score": None, "pages": 0, "issues": 0, "mode": "disabled", "warnings": []}
    browser = _browser_path()
    if not browser:
        return {"score": None, "pages": 0, "issues": 0, "mode": "unavailable",
                "warnings": ["未找到 Chrome/Edge，跳过截图评审"]}
    frontend = str(getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if not frontend or not _url_ok(frontend):
        return {"score": None, "pages": 0, "issues": 0, "mode": "unavailable",
                "warnings": [f"前端地址不可访问（{frontend}），跳过截图评审"]}

    # 截图走运行时接口，必须先有一个 active release。
    try:
        from releases.services import get_active_release, run_compile_pipeline, schedule_release_for_app

        if get_active_release(ctx["app"]) is None:
            release, _mode = schedule_release_for_app(ctx["app"], changelog="评审临时发布", trigger="ai_review", user=job.user)
            for _ in range(10):
                release.refresh_from_db()
                if release.status == "active":
                    break
                time.sleep(0.5)
            if release.status != "active":
                run_compile_pipeline(release.id)
    except Exception as exc:  # noqa: BLE001
        return {"score": None, "pages": 0, "issues": 0, "mode": "unavailable",
                "warnings": [f"评审临时发布失败：{type(exc).__name__}: {exc}"]}

    candidates = []
    for page in pages:
        if ":" in page.path:
            continue
        candidates.append(page)
        if len(candidates) >= 3:
            break
    scores, issues_count, warnings = [], 0, []
    for page in candidates:
        url = f"{frontend}/run/{ctx['app'].code}/{page.path}?review=1"
        raw = _capture_page(browser, url)
        if raw is None:
            warnings.append(f"{page.path} 截图失败")
            continue
        data_uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
        result = review_screenshot(data_uri, schema=page.schema or {}, page_name=page.name)
        scores.append(result.get("score", 0))
        issues_count += len(result.get("issues") or [])
        warnings.extend(result.get("warnings") or [])
        _log(job, f"截图评审 {page.path}：{result.get('score')} 分，{len(result.get('issues') or [])} 个问题")
    return {
        "score": round(sum(scores) / max(1, len(scores)), 1) if scores else None,
        "pages": len(scores),
        "issues": issues_count,
        "mode": "heuristic" if scores else "unavailable",
        "warnings": warnings[:5],
    }


def _browser_path() -> str | None:
    import shutil

    from django.conf import settings

    configured = str(getattr(settings, "AUTOBUILD_BROWSER", "") or "")
    if configured and Path(configured).exists():
        return configured
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    for name in ("msedge", "chrome", "google-chrome", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _url_ok(url: str) -> bool:
    import urllib.request

    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=3) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def _capture_page(browser: str, url: str) -> bytes | None:
    import shutil
    import subprocess
    import tempfile

    workdir = tempfile.mkdtemp(prefix="wp-shot-")
    output = Path(workdir) / "shot.png"
    profile = Path(workdir) / "profile"
    profile.mkdir(exist_ok=True)
    try:
        proc = subprocess.run(
            [
                browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--no-sandbox", f"--user-data-dir={profile}", "--window-size=1440,1000",
                "--virtual-time-budget=12000", "--run-all-compositor-stages-before-draw",
                f"--screenshot={output}", url,
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45,
        )
        if proc.returncode != 0 or not output.exists():
            return None
        return output.read_bytes()
    except Exception:
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _step_workflow(job: AiBuildJob, ctx: dict) -> None:
    if not job.options.get("create_workflow", True):
        return
    from workflow.models import WorkflowDefinition

    app = ctx["app"]
    blueprint = ctx["blueprint"]
    name = blueprint["workflow"]["name"]
    definition = WorkflowDefinition.objects.create(
        app=app,
        name=name,
        code=f"auto_flow_{job.id}",
        description=blueprint["workflow"]["description"],
        status="published",
        version=1,
        created_by=job.user,
        nodes=[
            {"id": "start", "type": "start", "name": "开始"},
            {
                "id": "approval", "type": "approval", "name": "内容审核",
                "assignee_role": "owner", "mode": "any", "timeout_hours": 24,
            },
            {"id": "end", "type": "end", "name": "结束", "on_approve": {"status": "published"}, "on_reject": {"status": "draft"}},
        ],
    )
    ctx["workflow_id"] = definition.id
    _log(job, f"工作流已创建并发布：{definition.name}")


def _step_realtime(job: AiBuildJob, ctx: dict) -> None:
    if not job.options.get("create_realtime", True):
        return
    from realtime.models import RealtimeChannel

    app = ctx["app"]
    channel = RealtimeChannel.objects.create(
        app=app,
        name="站点通知",
        slug=f"site-notify-{job.id}",
        kind="ws",
        topic=f"site/{app.code}/notify",
        description="AI 全自动建站创建的实时通知通道",
        enabled=True,
        created_by=job.user,
    )
    ctx["channel_id"] = channel.id
    _log(job, f"实时通道已创建：{channel.name}（{channel.topic}）")


def _step_release(job: AiBuildJob, ctx: dict) -> None:
    if not job.options.get("publish", True):
        return
    from appcore.models import App
    from releases.services import get_active_release, run_compile_pipeline, schedule_release_for_app

    app = ctx["app"]
    app.status = "published"
    app.save(update_fields=["status", "updated_at"])
    release, mode = schedule_release_for_app(app, changelog="AI 全自动建站", trigger="ai_autobuild", user=job.user)
    # Celery 未启动时 .delay() 只排队不执行；这里兜底等待并同步编译，保证建站后立即可访问。
    for _ in range(6):
        release.refresh_from_db()
        if release.status == "active":
            break
        time.sleep(0.5)
    if release.status != "active":
        run_compile_pipeline(release.id)
        release.refresh_from_db()
    active = get_active_release(app)
    ctx["release_id"] = active.id if active else release.id
    _log(job, f"应用已发布：release #{ctx['release_id']}（{mode}/{release.status}）")


def _step_index(job: AiBuildJob, ctx: dict) -> None:
    from search.services import rebuild_app, stats

    app = ctx["app"]
    result = rebuild_app(app)
    ctx["index_docs"] = result.get("created", 0)
    _log(job, f"搜索索引已重建：{result.get('created', 0)} 条（当前 {stats(app).get('documents', 0)} 条文档）")


def _step_ssr(job: AiBuildJob, ctx: dict) -> None:
    if not job.options.get("generate_ssr", True):
        return
    from django.conf import settings
    from pages.models import Page
    from runtime.ssr import page_targets, ssr_available, write_snapshot

    if not ssr_available():
        _log(job, "跳过 SSR：未找到 frontend/dist-ssr 产物")
        return
    output = Path(settings.PRERENDER_DIR)
    generated = 0
    for page in Page.objects.filter(app=ctx["app"], status="published"):
        for target in page_targets(page)[:20]:
            try:
                if write_snapshot(ctx["app"], target, output):
                    generated += 1
            except Exception as exc:  # noqa: BLE001
                _log(job, f"SSR 失败 {target}：{type(exc).__name__}: {exc}")
    ctx["ssr_pages"] = generated
    _log(job, f"SSR 快照：{generated} 个页面")


STEP_HANDLERS = {
    "plan": _step_plan,
    "app": _step_app,
    "model": _step_model,
    "content": _step_content,
    "pages": _step_pages,
    "review": _step_review,
    "workflow": _step_workflow,
    "realtime": _step_realtime,
    "release": _step_release,
    "index": _step_index,
    "ssr": _step_ssr,
}


def _build_result(job: AiBuildJob, ctx: dict) -> dict:
    app = ctx["app"]
    pages = ctx.get("pages") or []
    home = next((page for page in pages if page["path"] == "home"), pages[0] if pages else {})
    paths = {page.get("path") for page in pages}
    links = {
        "runtime": f"/run/{app.code}/home",
        "search": f"/run/{app.code}/search",
        "admin": f"/admin/apps/{app.id}",
        "designer": f"/design/{app.id}/{home.get('id', '')}",
        "review": f"/admin/reviews?app={app.id}",
    }
    if "data" in paths:
        links["list"] = f"/run/{app.code}/data"
    elif any(str(path).startswith("data/") for path in paths):
        first_data = next(path for path in paths if str(path).startswith("data/"))
        links["list"] = f"/run/{app.code}/{first_data}"
    if "overview" in paths:
        links["overview"] = f"/run/{app.code}/overview"
    if "live" in paths:
        links["live"] = f"/run/{app.code}/live"
    return {
        "app_id": app.id,
        "app_code": app.code,
        "app_name": app.name,
        "model_id": ctx["model"].id,
        "model_name": ctx["model"].name,
        "records": ctx.get("records", 0),
        "pages": pages,
        "release_id": ctx.get("release_id"),
        "index_docs": ctx.get("index_docs", 0),
        "ssr_pages": ctx.get("ssr_pages", 0),
        "workflow_id": ctx.get("workflow_id"),
        "channel_id": ctx.get("channel_id"),
        "review": ctx.get("review") or {},
        "provider": job.provider,
        "model": job.model,
        "links": links,
        "warnings": ctx.get("warnings") or [],
    }


def run_job(job_id: int) -> None:
    """执行建站任务（同步函数；可直接放线程或 Celery）。"""
    close_old_connections()
    job = AiBuildJob.objects.filter(id=job_id).first()
    if job is None or job.status not in ("pending",):
        close_old_connections()
        return
    steps = [
        {"key": key, "label": label, "status": "pending", "message": ""}
        for key, label in STEPS
    ]
    AiBuildJob.objects.filter(id=job.id).update(
        status="running", started_at=timezone.now(), steps=steps, progress=0, current_step="plan",
    )
    job.refresh_from_db()
    _log(job, f"任务开始：{job.prompt[:80]}")
    ctx: dict = {}
    try:
        for index, (key, label) in enumerate(STEPS):
            job.refresh_from_db(fields=["cancel_requested", "logs"])
            if job.cancel_requested:
                raise _Cancelled()
            step = steps[index]
            step.update({"status": "running", "started_at": timezone.now().isoformat()})
            _save_steps(job, steps, current=key)
            _log(job, f"开始：{label}")
            try:
                STEP_HANDLERS[key](job, ctx)
            except Exception as exc:  # noqa: BLE001
                step.update({"status": "failed", "message": f"{type(exc).__name__}: {exc}", "finished_at": timezone.now().isoformat()})
                _save_steps(job, steps, status="failed", current=key)
                raise
            step.update({"status": "done", "finished_at": timezone.now().isoformat(), "message": "完成"})
            progress = int((index + 1) / len(STEPS) * 100)
            _save_steps(job, steps, progress=progress)
            _log(job, f"完成：{label}")

        job.refresh_from_db()
        result = _build_result(job, ctx)
        AiBuildJob.objects.filter(id=job.id).update(
            status="success", result=result, progress=100, current_step="", finished_at=timezone.now(),
        )
        _log(job, f"建站完成：{result['app_name']}，{len(result['pages'])} 个页面，{result['records']} 条内容")
        _record_usage(job, ctx, True)
        try:
            from core.audit import write_audit_log

            write_audit_log(
                user=job.user, action="ai.autobuild", object_type="app",
                object_id=ctx["app"].id, app_id=ctx["app"].id, after=result,
            )
        except Exception:
            pass
    except _Cancelled:
        AiBuildJob.objects.filter(id=job.id).update(
            status="cancelled", current_step="", finished_at=timezone.now(),
        )
        _log(job, "任务已取消")
    except Exception as exc:  # noqa: BLE001
        logger.exception("autobuild job %s failed", job_id)
        error = f"{type(exc).__name__}: {exc}"
        AiBuildJob.objects.filter(id=job.id).update(
            status="failed", error=error[:2000], current_step="", finished_at=timezone.now(),
        )
        _log(job, f"失败：{error}")
        _log(job, traceback.format_exc()[-1500:])
        _record_usage(job, ctx, False, error)
    finally:
        close_old_connections()


def _record_usage(job: AiBuildJob, ctx: dict, success: bool, error: str = "") -> None:
    try:
        from ai.usage import record_usage

        record_usage(
            user=job.user,
            app=ctx.get("app"),
            action="autobuild",
            provider=job.provider or "local",
            model=job.model or "local-blueprint",
            prompt=job.prompt,
            response=json.dumps(
                {"app": getattr(ctx.get("app"), "code", ""), "pages": len(ctx.get("pages") or [])},
                ensure_ascii=False,
            ) if success else "",
            success=success,
            error=error,
        )
    except Exception:
        pass


def start_job(job: AiBuildJob, *, sync: bool = False) -> None:
    if sync:
        run_job(job.id)
        return
    from django.conf import settings

    # 有 Redis/Celery worker 时优先投递持久化任务；否则退回本地线程。
    if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", True):
        try:
            from ai.tasks import run_autobuild_job

            result = run_autobuild_job.delay(job.id)
            if getattr(result, "id", None):
                return
        except Exception:  # noqa: BLE001
            logger.warning("autobuild celery submit failed; fallback to thread", exc_info=True)
    thread = threading.Thread(target=run_job, args=(job.id,), daemon=True, name=f"ai-build-{job.id}")
    thread.start()


def job_payload(job: AiBuildJob) -> dict:
    return {
        "id": job.id,
        "status": job.status,
        "app_id": job.app_id,
        "prompt": job.prompt,
        "options": job.options,
        "progress": job.progress,
        "current_step": job.current_step,
        "steps": job.steps,
        "logs": job.logs,
        "blueprint": job.blueprint,
        "result": job.result,
        "error": job.error,
        "provider": job.provider,
        "model": job.model,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
