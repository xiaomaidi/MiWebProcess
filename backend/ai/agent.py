"""AI 多轮 Agent：工具调用、页面补丁提案与安全应用。

Agent 的能力边界：
- 只读工具（页面、组件、数据模型、记录检索、结构评审）直接执行；
- 写操作一律以「提案」返回，必须由用户在前端点击应用后才落库；
- 补丁在服务端再次校验组件类型与节点引用，防止模型生成非法结构。
"""
from __future__ import annotations

import copy
import json
import re
import urllib.request

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ai.models import AiConversation, AiMessage
from ai.providers import chat_config, is_configured
from ai.review import review_schema
from ai.services import validate_schema
from components.models import ComponentMeta

MAX_STEPS = 5
MAX_HISTORY = 20

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_page",
            "description": "读取当前页面 schema 摘要（节点 id、类型、props 键、meta）",
            "parameters": {
                "type": "object",
                "properties": {"page_id": {"type": "integer", "description": "页面 id，缺省为当前页面"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_pages",
            "description": "列出应用内页面（id、名称、路径、状态），用于查找跳转目标",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_components",
            "description": "列出可用组件类型（只能使用这些 type）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_models",
            "description": "列出应用内数据模型及其字段",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_records",
            "description": "按关键词检索某个数据模型的记录（只读，最多 5 条）",
            "parameters": {
                "type": "object",
                "properties": {
                    "model_id": {"type": "integer"},
                    "q": {"type": "string"},
                },
                "required": ["model_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_page",
            "description": "对当前页面做结构与可维护性评审",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_page_patch",
            "description": "提出页面局部修改提案（不会立即生效，等待用户确认）",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "一句话说明改了什么"},
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "op": {"type": "string", "enum": ["update_node", "add_node", "remove_node", "set_meta", "set_theme"]},
                                "node_id": {"type": "string"},
                                "parent_id": {"type": "string"},
                                "props": {"type": "object"},
                                "style": {"type": "object"},
                                "node": {"type": "object"},
                                "meta": {"type": "object"},
                                "dark": {"type": "boolean"},
                            },
                            "required": ["op"],
                        },
                    },
                },
                "required": ["summary", "ops"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_datasources",
            "description": "列出当前应用的数据源（名称/类型/状态，不返回密码）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_datasource",
            "description": "查看某个 PostgreSQL/MySQL/SQL Server 数据源的表与字段结构",
            "parameters": {
                "type": "object",
                "properties": {"datasource_id": {"type": "integer"}},
                "required": ["datasource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "preview_datasource",
            "description": "只读预览数据源某张表的前几行数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer"},
                    "table": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["datasource_id", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_datasource_import",
            "description": "提出把数据源表导入为平台数据模型的提案（等待用户确认后执行）",
            "parameters": {
                "type": "object",
                "properties": {
                    "datasource_id": {"type": "integer"},
                    "table": {"type": "string"},
                    "model_name": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["datasource_id", "table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_page",
            "description": "在应用中新建页面；提供 prompt 时由 AI 生成任意布局（仪表盘/表单/自定义）",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "path": {"type": "string"},
                    "type": {"type": "string", "enum": ["page", "layout", "popup"]},
                    "kind": {"type": "string", "enum": ["page", "dashboard", "form", "custom", "landing"]},
                    "prompt": {"type": "string"},
                },
                "required": ["name", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_model",
            "description": "新建一个数据模型（公开读取），字段使用 name/type/label 等结构",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "fields": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["name", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_page",
            "description": "发布指定页面并触发应用发布（需要所有者权限）",
            "parameters": {
                "type": "object",
                "properties": {"page_id": {"type": "integer"}, "path": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "publish_app",
            "description": "发布当前应用（需要所有者权限）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bind_datasource",
            "description": "把数据源绑定到页面节点；可设置 dataBinding，或给按钮添加点击调用动作",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "integer"},
                    "path": {"type": "string"},
                    "node_id": {"type": "string"},
                    "datasource_id": {"type": "integer"},
                    "field": {"type": "string"},
                    "loop_var": {"type": "string"},
                    "trigger": {"type": "string", "enum": ["binding", "click"]},
                },
                "required": ["node_id", "datasource_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rollback_page",
            "description": "把页面回滚到上一个 AI 快照或指定版本（草稿状态）",
            "parameters": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "integer"},
                    "path": {"type": "string"},
                    "version": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workflow",
            "description": "创建并发布一个审批工作流（默认开始→审批→结束）",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "nodes": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_page_schema",
            "description": "提出整页 schema 替换提案（仅在用户要求重做整页时使用）",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}, "schema": {"type": "object"}},
                "required": ["summary", "schema"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是 MiWebProcess 低代码平台的页面设计 Agent，用中文与用户多轮对话。
你可以读取页面、组件、数据模型和记录；任何修改都必须通过 propose_page_patch 或 propose_page_schema 提出提案，
由用户确认后才会应用。规则：
1. 修改前先调用 get_page 了解现有节点 id，不要臆造节点 id。
2. 只能使用 list_components 返回的组件 type；children 必须引用存在的节点。
3. 禁止 script/iframe/onclick/javascript: 等不安全内容。
4. 提案尽量小而具体：改文案/颜色/间距用 update_node；加区块用 add_node；整页重做才用 propose_page_schema。
5. 数据源：可用 list_datasources / inspect_datasource / preview_datasource 只读查看 PostgreSQL 等数据源；
   用户要求把表变成可复用数据时，用 propose_datasource_import 提出导入提案，由用户确认后执行。
6. 写工具：create_page / create_model / publish_page / publish_app / bind_datasource / rollback_page / create_workflow
   只返回待确认提案，不会直接修改应用；必须提示用户点击「应用修改」后才会执行。
   create_page 传 prompt（可加 kind=dashboard/form/custom）时，会由 AI 生成任意布局，不再只建空页。
   AI 修改页面/绑定数据源前会自动保存快照；用户说“撤销/回滚”时调用 rollback_page。
7. 回答简洁，说明改了什么、为什么；写工具会返回待确认提案，不要声称已经执行，必须提示用户点击「应用修改」后才会落库。
8. 按钮跳转：先调用 list_pages 找目标页面 path，再用 add_node 添加 ElButton，
   node.events.click = [{"id":"go_target","kind":"navigate","params":{"path":"目标页面path"}}]。
   navigate 的 path 是应用内页面路径，不要写 /run/... 或完整 URL。
9. 图表统一使用 wp-echarts：props.option 传完整 ECharts option（series/xAxis/yAxis/tooltip/legend/visualMap 等），
   props.chartType 只是无 option 时的示例类型；height 必须是数字（例如 300，不要写 "300px"），theme/renderer 可选。
   切换图表类型时必须同时替换 props.option：饼图改柱状图要给 series[].type="bar"、xAxis（category + 原饼图 name 作为 data）、yAxis（value + 原 value 作为 series.data）；只改 chartType 不会覆盖已有 option。
10. WebSocket 实时数据使用 wp-ws-live，props.datasourceId 填 websocket 数据源 ID。"""


# ---------------------------------------------------------------- 序列化

def message_payload(message: AiMessage) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "tool_name": message.tool_name,
        "tool_args": message.tool_args,
        "tool_result": message.tool_result,
        "proposal": message.proposal,
        "provider": message.provider,
        "model": message.model,
        "created_at": message.created_at,
    }


def conversation_payload(conversation: AiConversation, *, with_messages: bool = False) -> dict:
    payload = {
        "id": conversation.id,
        "app_id": conversation.app_id,
        "page_id": conversation.page_id,
        "title": conversation.title,
        "context": conversation.context,
        "created_at": conversation.created_at,
        "updated_at": conversation.updated_at,
        "message_count": conversation.messages.count(),
    }
    if with_messages:
        payload["messages"] = [message_payload(m) for m in conversation.messages.all()]
    return payload


# ---------------------------------------------------------------- 工具

class AgentContext:
    def __init__(self, conversation: AiConversation, user):
        self.conversation = conversation
        self.app = conversation.app
        self.user = user
        self.page = None
        self.executing = False
        if conversation.page_id:
            from pages.models import Page

            self.page = Page.objects.filter(app=self.app, id=conversation.page_id).first()

    def current_schema(self) -> dict:
        return (self.page.schema if self.page is not None else {}) or {}

    def page_summary(self, schema: dict | None = None) -> dict:
        schema = schema if schema is not None else self.current_schema()
        nodes = schema.get("nodes") or {}
        return {
            "page_id": self.page.id if self.page else None,
            "path": self.page.path if self.page else "",
            "name": self.page.name if self.page else "",
            "root_id": schema.get("rootId"),
            "node_count": len(nodes),
            "nodes": [
                {
                    "id": n.get("id"),
                    "type": n.get("type"),
                    "children": n.get("children") or [],
                    "props": sorted(list((n.get("props") or {}).keys()))[:12],
                }
                for n in nodes.values() if isinstance(n, dict)
            ][:80],
            "meta": schema.get("meta") or {},
        }


def _tool_get_page(ctx: AgentContext, args: dict) -> dict:
    return ctx.page_summary()


def _tool_list_pages(ctx: AgentContext, args: dict) -> dict:
    from pages.models import Page

    rows = [
        {"id": page.id, "name": page.name, "path": page.path, "status": page.status}
        for page in Page.objects.filter(app=ctx.app).order_by("id")[:80]
    ]
    return {"pages": rows}


def _tool_list_components(ctx: AgentContext, args: dict) -> dict:
    rows = list(
        ComponentMeta.objects.filter(is_enabled=True)
        .values("name", "label", "category", "is_container", "is_form_field")[:120]
    )
    return {"components": rows}


def _tool_list_models(ctx: AgentContext, args: dict) -> dict:
    from datamodels.models import DataModel

    rows = []
    for model in DataModel.objects.filter(app=ctx.app)[:30]:
        rows.append({
            "id": model.id,
            "name": model.name,
            "fields": [f.get("name") for f in (model.fields or []) if isinstance(f, dict)],
        })
    return {"models": rows}


def _tool_search_records(ctx: AgentContext, args: dict) -> dict:
    from datamodels.models import DataModel
    from datamodels.services import dynamic_query

    model_id = args.get("model_id")
    model = DataModel.objects.filter(app=ctx.app, id=model_id).first()
    if model is None:
        return {"error": "数据模型不存在"}
    rows = dynamic_query(model, {"search": args.get("q") or "", "size": 5})[:5]
    return {"model": model.name, "records": [{"id": r["id"], "data": r.get("data")} for r in rows]}


def _tool_review_page(ctx: AgentContext, args: dict) -> dict:
    return review_schema(ctx.current_schema())


def _tool_propose_patch(ctx: AgentContext, args: dict) -> dict:
    summary = str(args.get("summary") or "页面修改").strip()
    ops = args.get("ops")
    if not isinstance(ops, list) or not ops:
        return {"error": "ops 必须是非空数组"}
    if len(ops) > 20:
        return {"error": "单次提案最多 20 个操作"}
    return {
        "proposal": {
            "kind": "page_patch",
            "page_id": ctx.page.id if ctx.page else None,
            "summary": summary[:200],
            "ops": ops,
            "status": "pending",
        }
    }


def _tool_propose_schema(ctx: AgentContext, args: dict) -> dict:
    schema = args.get("schema")
    if not isinstance(schema, dict):
        return {"error": "schema 必须是对象"}
    try:
        schema = copy.deepcopy(schema)
        for node in (schema.get("nodes") or {}).values():
            _normalize_patch_node(node)
        schema = validate_schema(schema, ctx.app.name)
    except ValidationError as exc:
        return {"error": str(exc.detail)}
    return {
        "proposal": {
            "kind": "page_schema",
            "page_id": ctx.page.id if ctx.page else None,
            "summary": str(args.get("summary") or "整页替换")[:200],
            "schema": schema,
            "status": "pending",
        }
    }


def _tool_list_datasources(ctx: AgentContext, args: dict) -> dict:
    from datasources.models import Datasource

    rows = []
    for ds in Datasource.objects.filter(app=ctx.app).order_by("id")[:30]:
        rows.append({
            "id": ds.id, "name": ds.name, "type": ds.type, "status": ds.status,
            "last_test_at": ds.last_test_at, "last_error": (ds.last_error or "")[:200],
        })
    return {"datasources": rows}


def _get_datasource(ctx: AgentContext, datasource_id) -> tuple:
    from datasources.executor import decode_secrets
    from datasources.models import Datasource

    ds = Datasource.objects.filter(app=ctx.app, id=datasource_id).first()
    if ds is None:
        raise ValueError("数据源不存在")
    if ds.type not in ("postgres", "mysql", "sqlserver"):
        raise ValueError("仅支持 PostgreSQL/MySQL/SQL Server 数据源")
    cfg = decode_secrets(ds.config or {})
    return ds, cfg


def _tool_inspect_datasource(ctx: AgentContext, args: dict) -> dict:
    from datasources.executor import list_external_schema

    ds, cfg = _get_datasource(ctx, args.get("datasource_id"))
    tables = list_external_schema(ds.type, cfg)
    return {
        "datasource": {"id": ds.id, "name": ds.name, "type": ds.type},
        "tables": [
            {"schema": t.get("schema"), "name": t.get("name"), "columns": (t.get("columns") or [])[:30]}
            for t in tables[:20]
        ],
        "table_count": len(tables),
    }


def _tool_preview_datasource(ctx: AgentContext, args: dict) -> dict:
    from datasources.executor import execute_external_db

    ds, cfg = _get_datasource(ctx, args.get("datasource_id"))
    table = str(args.get("table") or "").strip()
    if not table:
        raise ValueError("table 必填")
    schema = str(cfg.get("schema") or "public")
    try:
        limit = min(20, max(1, int(args.get("limit") or 5)))
    except (TypeError, ValueError):
        limit = 5
    cfg = dict(cfg)
    cfg["query"] = f'SELECT * FROM "{schema}"."{table}" LIMIT {limit}'
    cfg["max_rows"] = limit
    rows = execute_external_db(ds.type, cfg, {})
    return {"table": table, "rows": rows[:limit], "count": len(rows)}


def _tool_propose_datasource_import(ctx: AgentContext, args: dict) -> dict:
    from datasources.executor import list_external_schema

    ds, cfg = _get_datasource(ctx, args.get("datasource_id"))
    table = str(args.get("table") or "").strip()
    if not table:
        raise ValueError("table 必填")
    tables = list_external_schema(ds.type, cfg)
    target = next((t for t in tables if str(t.get("name")) == table), None)
    if target is None:
        target = next((t for t in tables if str(t.get("name")).lower() == table.lower()), None)
    if target is None:
        raise ValueError(f"表 {table} 不存在")
    model_name = str(args.get("model_name") or table).strip()
    try:
        limit = min(500, max(1, int(args.get("limit") or 200)))
    except (TypeError, ValueError):
        limit = 200
    return {
        "proposal": {
            "kind": "datasource_import",
            "datasource_id": ds.id,
            "datasource_name": ds.name,
            "table": target.get("name"),
            "schema": target.get("schema"),
            "model_name": model_name,
            "limit": limit,
            "columns": [c.get("name") for c in (target.get("columns") or [])][:40],
            "status": "pending",
            "summary": f"把 {ds.name} 的 {target.get('name')} 导入为模型 {model_name}（最多 {limit} 行）",
        }
    }


def _require_agent_role(ctx: AgentContext, min_role: str = "editor") -> str:
    from core.permissions import ROLE_ORDER, get_app_role
    from wp_utils import is_platform_admin_full

    if is_platform_admin_full(ctx.user):
        return "owner"
    role = get_app_role(ctx.user, ctx.app)
    if role is None or ROLE_ORDER.get(role, 0) < ROLE_ORDER.get(min_role, 0):
        raise PermissionError(f"需要 {min_role} 及以上权限")
    return role


def _propose_write(tool: str, args: dict, summary: str) -> dict:
    """写工具默认只返回提案，由用户确认后在同一事务内执行。"""
    return {
        "ok": True,
        "pending": True,
        "message": "已生成待确认提案，请在前端点击「应用修改」后执行。",
        "proposal": {
            "kind": "agent_action",
            "tool": tool,
            "args": args,
            "summary": summary[:200],
            "status": "pending",
        },
    }


def _tool_create_page(ctx: AgentContext, args: dict) -> dict:
    from pages.models import Page
    from pages.services import default_page_schema, save_draft

    _require_agent_role(ctx, "editor")
    if not ctx.executing:
        return _propose_write("create_page", args, f"新建页面 {args.get('name') or ''} /{args.get('path') or ''}")
    name = str(args.get("name") or "").strip()[:200]
    path = str(args.get("path") or "").strip().strip("/")
    if not name or not path:
        raise ValueError("name 与 path 必填")
    if not re.match(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_:-]+)*$", path):
        raise ValueError("path 只能包含字母/数字/_/-/: 与 /")
    if Page.objects.filter(app=ctx.app, path=path).exists():
        raise ValueError(f"path {path} 已存在")
    page_type = str(args.get("type") or "page")
    if page_type not in dict(Page.TYPE_CHOICES):
        page_type = "page"
    page = Page.objects.create(app=ctx.app, name=name, path=path, type=page_type, schema=default_page_schema())
    if str(args.get("prompt") or "").strip():
        from ai.autobuild import THEMES
        from ai.pagelayout import generate_layout
        from datamodels.models import DataModel

        kind = str(args.get("kind") or "custom")
        if kind not in ("dashboard", "form", "custom", "landing"):
            kind = "custom"
        models = list(DataModel.objects.filter(app=ctx.app).order_by("id"))
        nav_links = [
            {"label": item.name, "path": item.path}
            for item in Page.objects.filter(app=ctx.app).exclude(path=path).order_by("id")[:9]
            if ":" not in item.path
        ]
        text = str(args.get("prompt"))
        theme_key = "dark" if any(word in text for word in ("深色", "暗色", "黑色", "dark")) else "light"
        palette = {**THEMES[theme_key], "dark": theme_key == "dark"}
        spec = {
            "name": name, "path": path, "kind": kind, "title": name,
            "description": text[:200], "brief": text[:300],
        }
        schema, provider = generate_layout(
            {"site_name": ctx.app.name, "description": ctx.app.description or text,
             "site_prompt": text, "use_llm": True},
            spec, kind, models, palette, nav_links,
        )
        page, errors, warnings = save_draft(page, schema, ctx.user)
        page.schema.setdefault("meta", {})["aiKind"] = kind
        page.schema["aiProvider"] = provider
        page.save(update_fields=["schema", "updated_at"])
    elif isinstance(args.get("schema"), dict):
        page, errors, warnings = save_draft(page, args["schema"], ctx.user)
    try:
        from core.audit import write_audit_log

        write_audit_log(user=ctx.user, action="ai.create_page", object_type="page",
                        object_id=page.id, app_id=ctx.app.id, after={"name": name, "path": path})
    except Exception:
        pass
    return {"ok": True, "page_id": page.id, "name": page.name, "path": page.path, "type": page.type}


def _tool_create_model(ctx: AgentContext, args: dict) -> dict:
    from datamodels.models import DataModel
    from datamodels.services import validate_fields_spec

    _require_agent_role(ctx, "editor")
    if not ctx.executing:
        return _propose_write("create_model", args, f"新建数据模型 {args.get('name') or ''}")
    name = re.sub(r"[^a-zA-Z0-9_]", "_", str(args.get("name") or "").strip())[:80]
    fields_raw = args.get("fields")
    if not name or not isinstance(fields_raw, list) or not fields_raw:
        raise ValueError("name 与 fields 必填")
    if DataModel.objects.filter(app=ctx.app, name=name).exists():
        raise ValueError(f"模型 {name} 已存在")
    fields = validate_fields_spec(fields_raw, app=ctx.app)
    model = DataModel.objects.create(app=ctx.app, name=name, fields=fields, is_public=True, created_by=ctx.user)
    try:
        from core.audit import write_audit_log

        write_audit_log(user=ctx.user, action="ai.create_model", object_type="datamodel",
                        object_id=model.id, app_id=ctx.app.id, after={"name": name, "fields": fields})
    except Exception:
        pass
    return {"ok": True, "model_id": model.id, "name": model.name, "fields": [f["name"] for f in fields]}


def _tool_publish_page(ctx: AgentContext, args: dict) -> dict:
    from pages.models import Page
    from pages.services import publish_page
    from releases.services import schedule_release_for_app

    _require_agent_role(ctx, "owner")
    if not ctx.executing:
        return _propose_write("publish_page", args, f"发布页面 {args.get('path') or args.get('page_id') or '当前页'}")
    page = None
    if args.get("page_id"):
        page = Page.objects.filter(app=ctx.app, id=args.get("page_id")).first()
    elif args.get("path"):
        page = Page.objects.filter(app=ctx.app, path=str(args.get("path")).strip("/")).first()
    if page is None:
        raise ValueError("页面不存在")
    version, errors, warnings = publish_page(page, ctx.user, "AI 助手发布")
    if version is None:
        raise ValueError(f"发布失败：{errors or warnings}")
    release, mode = schedule_release_for_app(ctx.app, changelog=f"AI 发布 {page.path}", trigger="ai_agent", user=ctx.user)
    return {
        "ok": True, "page_id": page.id, "path": page.path,
        "version": version.version, "release_id": release.id, "release_status": release.status, "mode": mode,
    }


def _tool_publish_app(ctx: AgentContext, args: dict) -> dict:
    from releases.services import schedule_release_for_app

    _require_agent_role(ctx, "owner")
    if not ctx.executing:
        return _propose_write("publish_app", args, "发布当前应用")
    ctx.app.status = "published"
    ctx.app.save(update_fields=["status", "updated_at"])
    release, mode = schedule_release_for_app(ctx.app, changelog="AI 助手发布应用", trigger="ai_agent", user=ctx.user)
    return {"ok": True, "release_id": release.id, "version": release.version, "status": release.status, "mode": mode}


def _tool_bind_datasource(ctx: AgentContext, args: dict) -> dict:
    from datasources.models import Datasource
    from pages.models import Page
    from pages.services import save_draft, snapshot_page

    _require_agent_role(ctx, "editor")
    if not ctx.executing:
        return _propose_write("bind_datasource", args, f"绑定数据源 {args.get('datasource_id') or ''} 到页面节点")
    ds = Datasource.objects.filter(app=ctx.app, id=args.get("datasource_id")).first()
    if ds is None:
        raise ValueError("数据源不存在")
    page = None
    if args.get("page_id"):
        page = Page.objects.filter(app=ctx.app, id=args.get("page_id")).first()
    elif args.get("path"):
        page = Page.objects.filter(app=ctx.app, path=str(args.get("path")).strip("/")).first()
    if page is None and ctx.page is not None:
        page = ctx.page
    if page is None:
        raise ValueError("页面不存在")
    schema = copy.deepcopy(page.schema or {})
    node = (schema.get("nodes") or {}).get(str(args.get("node_id")))
    if not isinstance(node, dict):
        raise ValueError("节点不存在")
    ref = f"ds_{ds.id}"
    trigger = str(args.get("trigger") or "binding")
    if trigger == "click":
        events = node.setdefault("events", {})
        events["click"] = [{"id": f"load_ds_{ds.id}", "kind": "callDatasource", "params": {"ref": ref}}]
        # 按钮点击后，数据落到 ds_{id}，再让目标列表读取；若节点自身也要绑定则保留。
    if trigger != "click" or args.get("field"):
        node["dataBinding"] = {
            "source": "datasource", "ref": ref,
            "field": str(args.get("field") or "data"),
            "loopVar": str(args.get("loop_var") or "row"),
        }
    snapshot_page(page, ctx.user, "AI 绑定数据源前快照")
    page, errors, warnings = save_draft(page, schema, ctx.user)
    return {"ok": True, "page_id": page.id, "path": page.path, "node_id": node.get("id"),
            "datasource_id": ds.id, "warnings": list(errors) + list(warnings)}


def _tool_rollback_page(ctx: AgentContext, args: dict) -> dict:
    from pages.models import Page, PageVersion

    _require_agent_role(ctx, "editor")
    if not ctx.executing:
        return _propose_write("rollback_page", args, f"回滚页面 {args.get('path') or args.get('page_id') or '当前页'}")
    page = None
    if args.get("page_id"):
        page = Page.objects.filter(app=ctx.app, id=args.get("page_id")).first()
    elif args.get("path"):
        page = Page.objects.filter(app=ctx.app, path=str(args.get("path")).strip("/")).first()
    if page is None and ctx.page is not None:
        page = ctx.page
    if page is None:
        raise ValueError("页面不存在")
    versions = PageVersion.objects.filter(page=page).order_by("-version")
    if args.get("version"):
        version = versions.filter(version=int(args["version"])).first()
    else:
        version = versions.first()
    if version is None:
        raise ValueError("没有可回滚的页面快照")
    page.schema = version.schema
    page.schema_version = version.schema_version
    page.version += 1
    page.status = "draft"
    page.save(update_fields=["schema", "schema_version", "version", "status", "updated_at"])
    try:
        from wp_utils import broadcast_draft_saved

        broadcast_draft_saved(page.app_id, page.id, page.version, ctx.user.username)
    except Exception:
        pass
    return {"ok": True, "page_id": page.id, "path": page.path, "version": version.version,
            "changelog": version.changelog, "model_version": page.version}


def _tool_create_workflow(ctx: AgentContext, args: dict) -> dict:
    from workflow.models import WorkflowDefinition

    _require_agent_role(ctx, "editor")
    if not ctx.executing:
        return _propose_write("create_workflow", args, f"创建工作流 {args.get('name') or ''}")
    name = str(args.get("name") or "").strip()[:100]
    if not name:
        raise ValueError("name 必填")
    nodes = args.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        nodes = [
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "approval", "type": "approval", "name": "审批", "assignee_role": "owner", "mode": "any", "timeout_hours": 24},
            {"id": "end", "type": "end", "name": "结束"},
        ]
    code = f"ai_flow_{int(timezone.now().timestamp())}"
    definition = WorkflowDefinition.objects.create(
        app=ctx.app, name=name, code=code,
        description=str(args.get("description") or "AI 助手创建")[:500],
        nodes=nodes, status="published", version=1, created_by=ctx.user,
    )
    return {"ok": True, "workflow_id": definition.id, "name": definition.name, "code": code}


TOOL_HANDLERS = {
    "get_page": _tool_get_page,
    "list_pages": _tool_list_pages,
    "list_components": _tool_list_components,
    "list_models": _tool_list_models,
    "search_records": _tool_search_records,
    "review_page": _tool_review_page,
    "list_datasources": _tool_list_datasources,
    "inspect_datasource": _tool_inspect_datasource,
    "preview_datasource": _tool_preview_datasource,
    "propose_datasource_import": _tool_propose_datasource_import,
    "create_page": _tool_create_page,
    "create_model": _tool_create_model,
    "publish_page": _tool_publish_page,
    "publish_app": _tool_publish_app,
    "bind_datasource": _tool_bind_datasource,
    "rollback_page": _tool_rollback_page,
    "create_workflow": _tool_create_workflow,
    "propose_page_patch": _tool_propose_patch,
    "propose_page_schema": _tool_propose_schema,
}


def execute_tool(name: str, args: dict, ctx: AgentContext) -> dict:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"未知工具 {name}"}
    try:
        return _jsonable(handler(ctx, args if isinstance(args, dict) else {}))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _jsonable(value):
    """工具结果进入 LLM 前转为可 JSON 序列化的结构（Decimal/日期等）。"""
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return value


# ---------------------------------------------------------------- LLM

def _chat(messages: list[dict], tools: bool = True) -> dict:
    cfg = chat_config()
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.3,
    }
    if tools:
        body["tools"] = TOOL_SPECS
        body["tool_choice"] = "auto"
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
    return payload.get("choices", [{}])[0].get("message", {})


class AgentStopped(Exception):
    def __init__(self, partial: str = ""):
        super().__init__("agent stopped")
        self.partial = partial


def _chat_stream(
    messages: list[dict],
    tools: bool = True,
    on_delta=None,
    should_stop=None,
) -> dict:
    """OpenAI-compatible SSE 流式调用；工具调用参数做增量拼接。"""
    cfg = chat_config()
    body = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": 0.3,
        "stream": True,
    }
    if tools:
        body["tools"] = TOOL_SPECS
        body["tool_choice"] = "auto"
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    content_parts: list[str] = []
    tool_calls: dict[int, dict] = {}
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout") or 90) as resp:
            for raw in resp:
                if should_stop and should_stop():
                    raise AgentStopped("".join(content_parts))
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (payload.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    content_parts.append(str(text))
                    if on_delta:
                        on_delta(str(text))
                for item in delta.get("tool_calls") or []:
                    try:
                        index = int(item.get("index") or 0)
                    except (TypeError, ValueError):
                        index = 0
                    entry = tool_calls.setdefault(index, {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    if item.get("id"):
                        entry["id"] = item["id"]
                    fn = item.get("function") or {}
                    if fn.get("name"):
                        entry["function"]["name"] += str(fn["name"])
                    if fn.get("arguments"):
                        entry["function"]["arguments"] += str(fn["arguments"])
    except AgentStopped:
        raise
    except Exception:
        # Provider 不支持 stream 时回退非流式；已经在输出的情况不再重复请求。
        if content_parts:
            raise
        return {**_chat(messages, tools), "streamed": False}
    calls = [tool_calls[index] for index in sorted(tool_calls)]
    return {"content": "".join(content_parts), "tool_calls": calls, "streamed": bool(content_parts)}


def _history(conversation: AiConversation) -> list[dict]:
    rows = list(conversation.messages.order_by("-id")[:MAX_HISTORY])[::-1]
    out = [{"role": "system", "content": SYSTEM_PROMPT}]
    for message in rows:
        if message.role == "user":
            out.append({"role": "user", "content": message.content})
        elif message.role == "assistant":
            text = message.content
            if message.proposal:
                text += f"\n[此前提案：{message.proposal.get('summary') or message.proposal.get('kind')}]"
            out.append({"role": "assistant", "content": text or "（已提出提案）"})
    return out


def run_turn(conversation: AiConversation, text: str, user, on_event=None, on_token=None, should_stop=None) -> dict:
    """执行一轮对话，返回 {user_message, assistant_message}。

    on_event 汇报工具进度；on_token 用于最终回答 token 流。
    """
    def emit(event: dict) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:
            pass

    ctx = AgentContext(conversation, user)
    user_message = AiMessage.objects.create(conversation=conversation, role="user", content=text)
    page_context = ctx.page_summary() if ctx.page else {"page": None}
    history = _history(conversation)
    history[-1]["content"] = (
        f"{text}\n\n[当前应用：{ctx.app.name}；当前页面摘要：{json.dumps(page_context, ensure_ascii=False)[:3000]}]"
    )

    if not is_configured():
        content, proposal, trace = local_agent_reply(ctx, text)
        assistant = _save_assistant(conversation, content, proposal, trace, provider="local", model="local-agent")
        return {"user_message": message_payload(user_message), "assistant_message": message_payload(assistant)}

    messages = history
    proposals: list[dict] = []
    trace: list[dict] = []
    provider = chat_config().get("provider_name") or ""
    model_name = chat_config().get("model") or ""
    try:
        for _ in range(MAX_STEPS):
            emit({"type": "status", "text": "正在分析页面与下一步操作…"})
            if on_token:
                reply = _chat_stream(messages, tools=True, on_delta=on_token, should_stop=should_stop)
            else:
                reply = _chat(messages, tools=True)
            tool_calls = reply.get("tool_calls") or []
            if not tool_calls:
                content = str(reply.get("content") or "").strip() or "（Agent 没有返回内容）"
                assistant = _save_assistant(
                    conversation, content, proposals[0] if proposals else {}, trace,
                    provider=provider, model=model_name,
                )
                return {
                    "user_message": message_payload(user_message),
                    "assistant_message": message_payload(assistant),
                    "streamed": bool(reply.get("streamed")),
                }

            messages.append({"role": "assistant", "content": reply.get("content") or "", "tool_calls": tool_calls})
            for call in tool_calls:
                fn = call.get("function") or {}
                name = str(fn.get("name") or "")
                emit({"type": "status", "text": f"正在执行工具：{name}…"})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = execute_tool(name, args, ctx)
                trace.append({"tool": name, "args": args, "result": _compact(result)})
                if isinstance(result.get("proposal"), dict):
                    proposals.append(result["proposal"])
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.get("id") or name,
                    "content": json.dumps(result, ensure_ascii=False)[:4000],
                })
        content = "已达到本轮工具调用上限。可以让我继续，或直接说明要修改的组件与文案。"
        assistant = _save_assistant(
            conversation, content, proposals[0] if proposals else {}, trace,
            provider=provider, model=model_name,
        )
        return {"user_message": message_payload(user_message), "assistant_message": message_payload(assistant)}
    except AgentStopped as exc:
        content = str(exc.partial or "").strip() or "已停止生成。"
        assistant = _save_assistant(
            conversation, content, proposals[0] if proposals else {}, trace,
            provider=provider, model=model_name,
        )
        return {
            "user_message": message_payload(user_message),
            "assistant_message": message_payload(assistant),
            "stopped": True,
            "streamed": bool(exc.partial),
        }
    except Exception as exc:  # noqa: BLE001
        content, proposal, local_trace = local_agent_reply(ctx, text)
        content = f"AI 服务暂不可用（{type(exc).__name__}），已切换到本地规则：\n{content}"
        assistant = _save_assistant(
            conversation, content, proposal or (proposals[0] if proposals else {}),
            trace + local_trace, provider="local-fallback", model="local-agent",
        )
        return {"user_message": message_payload(user_message), "assistant_message": message_payload(assistant)}


def _compact(result: dict) -> dict:
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) <= 1500:
        return result
    return {"truncated": text[:1500]}


def _save_assistant(
    conversation: AiConversation, content: str, proposal: dict, trace: list[dict],
    *, provider: str, model: str,
) -> AiMessage:
    assistant = AiMessage.objects.create(
        conversation=conversation, role="assistant", content=content,
        proposal=proposal or {}, provider=provider, model=model,
    )
    for item in trace[:12]:
        AiMessage.objects.create(
            conversation=conversation, role="tool", content="",
            tool_name=str(item.get("tool") or ""), tool_args=item.get("args") or {},
            tool_result=item.get("result") or {}, provider=provider, model=model,
        )
    conversation.updated_at = assistant.created_at
    conversation.save(update_fields=["updated_at"])
    if not conversation.title:
        conversation.title = (content or "新会话").strip().replace("\n", " ")[:60]
        conversation.save(update_fields=["title"])
    return assistant


# ---------------------------------------------------------------- 本地 Agent

def _new_node_id(schema: dict, prefix: str = "ai") -> str:
    used = set((schema.get("nodes") or {}).keys())
    index = 1
    while f"{prefix}-{index}" in used:
        index += 1
    return f"{prefix}-{index}"


def _find_node_by_text(schema: dict, text: str) -> str | None:
    needle = text.strip()
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict):
            continue
        props = node.get("props") or {}
        for key in ("content", "text", "label", "title"):
            if needle and needle in str(props.get(key) or ""):
                return node.get("id")
    return None


def local_agent_reply(ctx: AgentContext, text: str) -> tuple[str, dict, list[dict]]:
    """无 Provider 时的确定性 Agent：识别常见中文指令并生成补丁提案。"""
    schema = copy.deepcopy(ctx.current_schema())
    trace: list[dict] = [{"tool": "get_page", "args": {}, "result": {"pages": bool(schema)}}]
    if not schema or not schema.get("nodes"):
        return ("当前会话没有绑定页面。请在设计器里打开一个页面再使用 AI Agent。", {}, trace)

    text = str(text or "").strip()
    ops: list[dict] = []
    notes: list[str] = []

    if any(word in text for word in ("评审", "检查", "分析", "看看")):
        result = review_schema(schema)
        trace.append({"tool": "review_page", "args": {}, "result": {"score": result["score"], "issues": len(result["issues"])}})
        lines = [f"页面评审得分 {result['score']}：{result['summary']}"]
        for issue in result["issues"][:6]:
            lines.append(f"- [{issue['level']}] {issue['message']} → {issue['suggestion']}")
        return ("\n".join(lines), {}, trace)

    if any(word in text for word in ("深色", "暗色", "黑色", "夜间")):
        ops.append({"op": "set_theme", "dark": True})
        notes.append("切换到深色主题")
    elif any(word in text for word in ("浅色", "亮色", "白色", "日间")):
        ops.append({"op": "set_theme", "dark": False})
        notes.append("切换到浅色主题")

    title_match = re.search(r"(?:标题|大标题|首屏标题).{0,8}?(?:改为|改成|换成|设为|变成)[“\"']?([^”\"'，。,]+)", text)
    if title_match:
        title = title_match.group(1).strip()
        target = None
        for node in schema["nodes"].values():
            if isinstance(node, dict) and node.get("type") in ("wp-heading", "ElText"):
                target = node.get("id")
                break
        if target:
            ops.append({"op": "update_node", "node_id": target, "props": {"content": title}})
            ops.append({"op": "set_meta", "meta": {"title": title}})
            notes.append(f"标题改为「{title}」")

    button_match = re.search(r"按钮.{0,8}?(?:文案|文字)?.{0,4}?(?:改为|改成|换成|设为)[“\"']?([^”\"'，。,]+)", text)
    if button_match:
        label = button_match.group(1).strip()
        target = None
        for node in schema["nodes"].values():
            if isinstance(node, dict) and node.get("type") in ("ElButton", "wp-button"):
                target = node.get("id")
                break
        if target:
            ops.append({"op": "update_node", "node_id": target, "props": {"text": label}})
            notes.append(f"按钮文案改为「{label}」")

    if any(word in text for word in ("加一个", "新增", "添加", "加个")) and "按钮" in text:
        root_id = schema.get("rootId")
        node_id = _new_node_id(schema)
        label_match = re.search(r"按钮[“\"']?([^”\"'，。,]{0,12})", text)
        label = (label_match.group(1).strip() if label_match else "") or "了解更多"
        ops.append({
            "op": "add_node", "parent_id": root_id,
            "node": {
                "id": node_id, "type": "ElButton", "componentVersion": "2.0.0",
                "props": {"type": "primary", "size": "large", "text": label},
                "children": [], "style": {"marginTop": "16px"},
            },
        })
        notes.append(f"在根容器新增按钮「{label}」")

    remove_match = re.search(r"(?:删除|移除|去掉).{0,6}[“\"']?([^”\"'，。,]{1,20})", text)
    if remove_match:
        needle = remove_match.group(1).strip()
        target = _find_node_by_text(schema, needle)
        if target and target != schema.get("rootId"):
            ops.append({"op": "remove_node", "node_id": target})
            notes.append(f"删除包含「{needle}」的节点")

    if not ops:
        return (
            "本地 Agent 可以处理：改标题/按钮文案、切换深浅色、新增按钮、删除节点、页面评审。"
            "例如：「把首屏标题改成秋季新品」「加一个按钮 立即购买」「评审这个页面」。"
            "配置 AI Provider 后可以理解更复杂的多轮指令。",
            {},
            trace,
        )

    proposal = {
        "kind": "page_patch",
        "page_id": ctx.page.id if ctx.page else None,
        "summary": "；".join(notes),
        "ops": ops,
        "status": "pending",
    }
    return (f"我准备这样修改：{'；'.join(notes)}。确认后点击「应用修改」。", proposal, trace)


# ---------------------------------------------------------------- 应用提案

def _validate_ops(schema: dict, ops: list[dict]) -> list[dict]:
    nodes = schema.get("nodes") or {}
    root_id = schema.get("rootId")
    cleaned = []
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        if kind == "update_node":
            if op.get("node_id") in nodes:
                cleaned.append(op)
        elif kind == "remove_node":
            if op.get("node_id") in nodes and op.get("node_id") != root_id:
                cleaned.append(op)
        elif kind == "add_node":
            node = op.get("node")
            parent = op.get("parent_id")
            if isinstance(node, dict) and node.get("id") and node.get("type") and parent in nodes:
                cleaned.append(op)
        elif kind in ("set_meta", "set_theme", "set_var"):
            cleaned.append(op)
    return cleaned


def _normalize_chart_props(node_type: str, props: dict) -> dict:
    """兼容 AI 常见的 "300px" 高度写法；schema 校验要求 number。"""
    out = dict(props or {})
    if node_type == "wp-echarts" and "height" in out:
        raw = out["height"]
        if isinstance(raw, str):
            text = raw.strip().lower().replace("px", "")
            try:
                out["height"] = int(float(text))
            except ValueError:
                out.pop("height", None)
    return out


def _normalize_patch_node(node: dict) -> dict:
    if isinstance(node, dict):
        node["props"] = _normalize_chart_props(str(node.get("type") or ""), node.get("props") or {})
    return node


def apply_patch(schema: dict, ops: list[dict]) -> dict:
    out = copy.deepcopy(schema)
    nodes = out.setdefault("nodes", {})
    root_id = out.get("rootId")
    for op in _validate_ops(out, ops):
        kind = op["op"]
        if kind == "update_node":
            node = nodes.get(op["node_id"])
            if not isinstance(node, dict):
                continue
            if isinstance(op.get("props"), dict):
                node.setdefault("props", {}).update(_normalize_chart_props(str(node.get("type") or ""), op["props"]))
            if isinstance(op.get("style"), dict):
                node.setdefault("style", {}).update(op["style"])
        elif kind == "remove_node":
            node_id = op["node_id"]
            nodes.pop(node_id, None)
            for other in nodes.values():
                if isinstance(other, dict) and isinstance(other.get("children"), list):
                    other["children"] = [c for c in other["children"] if c != node_id]
        elif kind == "add_node":
            node = _normalize_patch_node(copy.deepcopy(op["node"]))
            node.setdefault("children", [])
            node.setdefault("props", {})
            nodes[node["id"]] = node
            parent = nodes.get(op["parent_id"])
            if isinstance(parent, dict):
                parent.setdefault("children", []).append(node["id"])
        elif kind == "set_meta":
            if isinstance(op.get("meta"), dict):
                out.setdefault("meta", {}).update(op["meta"])
        elif kind == "set_theme":
            _apply_theme(out, bool(op.get("dark")))
        elif kind == "set_var":
            variables = out.setdefault("variables", {})
            name = str(op.get("name") or "").strip()
            if name:
                variables[name] = {"value": op.get("value"), "scope": "page"}
    return out


def _apply_theme(schema: dict, dark: bool) -> None:
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


def apply_proposal(conversation: AiConversation, message: AiMessage, user) -> dict:
    """应用某条消息上的提案（服务端二次校验后落库）。"""
    proposal = message.proposal or {}
    if not proposal or proposal.get("status") == "applied":
        raise ValidationError({"detail": "该消息没有可应用的提案"})
    from core.audit import snapshot_instance, write_audit_log
    from pages.models import Page
    from pages.services import save_draft, snapshot_page

    kind = proposal.get("kind")
    if kind == "datasource_import":
        return apply_datasource_import(conversation, message, proposal, user)
    if kind == "agent_action":
        tool = str(proposal.get("tool") or "")
        handlers = {
            "create_page": _tool_create_page,
            "create_model": _tool_create_model,
            "publish_page": _tool_publish_page,
            "publish_app": _tool_publish_app,
            "bind_datasource": _tool_bind_datasource,
            "rollback_page": _tool_rollback_page,
            "create_workflow": _tool_create_workflow,
        }
        handler = handlers.get(tool)
        if handler is None:
            raise ValidationError({"detail": f"不支持的写操作：{tool}"})
        ctx = AgentContext(conversation, user)
        ctx.executing = True
        before_page = None
        if ctx.page is not None and tool in ("bind_datasource", "rollback_page"):
            before_page = {
                "page_id": ctx.page.id,
                "schema": copy.deepcopy(ctx.page.schema or {}),
                "version": ctx.page.version,
                "schema_version": ctx.page.schema_version,
            }
        with transaction.atomic():
            result = handler(ctx, proposal.get("args") or {})
        undo = {}
        if tool == "create_page" and result.get("page_id"):
            undo = {"kind": "delete_page", "page_id": result["page_id"]}
        elif tool == "create_model" and result.get("model_id"):
            undo = {"kind": "delete_model", "model_id": result["model_id"]}
        elif tool == "create_workflow" and result.get("workflow_id"):
            undo = {"kind": "delete_workflow", "workflow_id": result["workflow_id"]}
        elif before_page is not None:
            undo = {"kind": "page_schema", **before_page}
        proposal = {**proposal, "status": "applied", "undo": undo}
        message.proposal = proposal
        message.save(update_fields=["proposal"])
        try:
            from core.audit import write_audit_log

            write_audit_log(
                user=user,
                action=f"ai.agent.apply_{tool}",
                object_type="ai_agent",
                object_id=message.id,
                app_id=conversation.app_id,
                after={"tool": tool, "args": proposal.get("args") or {}, "result": result},
            )
        except Exception:
            pass
        return {**result, "ok": True, "kind": kind, "tool": tool, "proposal": proposal}
    page = None
    if proposal.get("page_id"):
        page = Page.objects.filter(app=conversation.app, id=proposal["page_id"]).first()
    if page is None and conversation.page_id:
        page = Page.objects.filter(app=conversation.app, id=conversation.page_id).first()

    if kind == "page_patch":
        if page is None:
            raise ValidationError({"detail": "提案未绑定页面"})
        before = snapshot_instance(page)
        before_schema = {"page_id": page.id, "schema": copy.deepcopy(page.schema or {}), "version": page.version, "schema_version": page.schema_version}
        snapshot_page(page, user, "AI 提案修改前快照")
        schema = apply_patch(page.schema or {}, proposal.get("ops") or [])
        schema = validate_schema(schema, conversation.app.name)
        page, errors, warnings = save_draft(page, schema, user)
        proposal = {**proposal, "status": "applied", "undo": {"kind": "page_schema", **before_schema}}
        message.proposal = proposal
        message.save(update_fields=["proposal"])
        write_audit_log(
            user=user, action="ai.agent.apply_patch", object_type="page", object_id=page.id,
            app_id=conversation.app_id, before=before, after=snapshot_instance(page),
        )
        return {
            "ok": True, "kind": kind, "page_id": page.id, "schema": page.schema,
            "warnings": list(errors) + list(warnings), "summary": proposal.get("summary"),
        }

    if kind == "page_schema":
        if page is None:
            raise ValidationError({"detail": "提案未绑定页面"})
        before_schema = {"page_id": page.id, "schema": copy.deepcopy(page.schema or {}), "version": page.version, "schema_version": page.schema_version}
        snapshot_page(page, user, "AI 整页替换前快照")
        schema = validate_schema(proposal.get("schema") or {}, conversation.app.name)
        page, errors, warnings = save_draft(page, schema, user)
        proposal = {**proposal, "status": "applied", "undo": {"kind": "page_schema", **before_schema}}
        message.proposal = proposal
        message.save(update_fields=["proposal"])
        return {"ok": True, "kind": kind, "page_id": page.id, "schema": page.schema, "warnings": warnings}

    raise ValidationError({"detail": f"不支持的提案类型：{kind}"})


def undo_proposal(conversation: AiConversation, message: AiMessage, user) -> dict:
    """撤销一次已经应用的 Agent 提案。仅支持有 undo 元数据的提案。"""
    proposal = message.proposal or {}
    if proposal.get("status") != "applied":
        raise ValidationError({"detail": "该提案尚未应用，不能撤销"})
    if proposal.get("undo_status") == "undone":
        raise ValidationError({"detail": "该提案已经撤销"})
    undo = proposal.get("undo") or {}
    kind = str(undo.get("kind") or "")
    if not kind:
        raise ValidationError({"detail": "该操作不支持撤销"})
    from appcore.models import App
    from datamodels.models import DataModel
    from pages.models import Page
    from workflow.models import WorkflowDefinition
    from django.db import transaction
    from core.audit import write_audit_log

    result = {"ok": True, "kind": "undo", "undo_kind": kind}
    with transaction.atomic():
        if kind == "page_schema":
            page = Page.objects.filter(app=conversation.app, id=undo.get("page_id")).first()
            if page is None:
                raise ValidationError({"detail": "页面不存在，无法撤销"})
            page.schema = copy.deepcopy(undo.get("schema") or {})
            page.schema_version = int(undo.get("schema_version") or page.schema_version)
            page.version += 1
            page.status = "draft"
            page.save(update_fields=["schema", "schema_version", "version", "status", "updated_at"])
            result.update({"page_id": page.id, "schema": page.schema})
            try:
                from wp_utils import broadcast_draft_saved

                broadcast_draft_saved(page.app_id, page.id, page.version, user.username)
            except Exception:
                pass
        elif kind == "delete_page":
            page = Page.objects.filter(app=conversation.app, id=undo.get("page_id")).first()
            if page is None:
                raise ValidationError({"detail": "页面不存在，可能已删除"})
            result["page_id"] = page.id
            page.delete()
            result["deleted"] = True
        elif kind == "delete_model":
            model = DataModel.objects.filter(app=conversation.app, id=undo.get("model_id")).first()
            if model is None:
                raise ValidationError({"detail": "数据模型不存在，可能已删除"})
            result["model_id"] = model.id
            model.delete()
            result["deleted"] = True
        elif kind == "delete_workflow":
            workflow = WorkflowDefinition.objects.filter(app=conversation.app, id=undo.get("workflow_id")).first()
            if workflow is None:
                raise ValidationError({"detail": "工作流不存在，可能已删除"})
            workflow.delete()
            result["deleted"] = True
        else:
            raise ValidationError({"detail": f"不支持的撤销类型：{kind}"})
    proposal = {**proposal, "undo_status": "undone"}
    message.proposal = proposal
    message.save(update_fields=["proposal"])
    write_audit_log(
        user=user, action="ai.agent.undo", object_type="ai_agent", object_id=message.id,
        app_id=conversation.app_id, after={"undo_kind": kind, "result": result},
    )
    return {**result, "proposal": proposal}


def apply_datasource_import(conversation: AiConversation, message: AiMessage, proposal: dict, user) -> dict:
    """把数据源表导入为公开数据模型（应用提案时执行）。"""
    from ai.autobuild import _detect_mapping, _field_name, _pg_field_type, _sql_value
    from datamodels.models import DataModel, DataRecord
    from datasources.executor import decode_secrets, execute_external_db, list_external_schema
    from datasources.models import Datasource

    ds = Datasource.objects.filter(app=conversation.app, id=proposal.get("datasource_id")).first()
    if ds is None:
        raise ValidationError({"detail": "数据源不存在"})
    if ds.type not in ("postgres", "mysql", "sqlserver"):
        raise ValidationError({"detail": "该数据源不支持表导入"})
    table_name = str(proposal.get("table") or "")
    cfg = decode_secrets(ds.config or {})
    tables = list_external_schema(ds.type, cfg)
    target = next((t for t in tables if str(t.get("name")) == table_name), None)
    if target is None:
        target = next((t for t in tables if str(t.get("name")).lower() == table_name.lower()), None)
    if target is None:
        raise ValidationError({"detail": f"表 {table_name} 不存在"})
    columns = target.get("columns") or []
    if not columns:
        raise ValidationError({"detail": "表没有可用字段"})

    used: set[str] = set()
    fields = []
    column_map: dict[str, str] = {}
    for column in columns[:40]:
        original = str(column.get("name") or "")
        name = _field_name(original, used)
        column_map[original] = name
        fields.append({
            "name": name, "type": _pg_field_type(column.get("type")), "required": False,
            "label": original[:80], "description": f"{ds.type} {column.get('type')}",
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

    model_name = str(proposal.get("model_name") or target.get("name") or "source_data")
    model_name = re.sub(r"[^a-zA-Z0-9_]", "_", model_name.lower()).strip("_")[:80] or "source_data"
    if DataModel.objects.filter(app=conversation.app, name=model_name).exists():
        model_name = f"{model_name}_{message.id}"
    model = DataModel.objects.create(
        app=conversation.app, name=model_name, fields=fields, is_public=True,
        data_scope="all", created_by=user,
    )

    schema = str(cfg.get("schema") or "public")
    try:
        limit = min(500, max(1, int(proposal.get("limit") or 200)))
    except (TypeError, ValueError):
        limit = 200
    cfg = dict(cfg)
    cfg["query"] = f'SELECT * FROM "{schema}"."{target.get("name")}" LIMIT {limit}'
    cfg["max_rows"] = limit
    rows = execute_external_db(ds.type, cfg, {})
    created = 0
    for row in rows:
        data = {}
        for original, value in row.items():
            name = column_map.get(original)
            if name:
                data[name] = _sql_value(value)
        if derive_summary:
            preferred = [k for k in ("symbol", "name", "title", "price", "pct_change") if data.get(k) not in (None, "")]
            values = [str(data[k]) for k in preferred[:4]] or [str(v) for k, v in data.items() if v not in (None, "")][:3]
            data["summary"] = " · ".join(values)[:300]
        if derive_content:
            import html as _html

            data["content"] = "".join(
                f"<p><strong>{_html.escape(str(k))}</strong>：{_html.escape(str(v))}</p>"
                for k, v in data.items() if v not in (None, "") and k not in ("summary", "content")
            )[:2000]
        DataRecord.objects.create(model=model, data=data, created_by=user, updated_by=user)
        created += 1

    proposal = {**proposal, "status": "applied", "model_id": model.id, "records": created}
    message.proposal = proposal
    message.save(update_fields=["proposal"])
    return {
        "ok": True,
        "kind": "datasource_import",
        "model_id": model.id,
        "model_name": model.name,
        "records": created,
        "fields": [f["name"] for f in fields],
        "datasource_id": ds.id,
    }
