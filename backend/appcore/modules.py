"""平台应用模块目录与默认启用策略。"""
from __future__ import annotations

MODULE_DEFS = [
    {"key": "auth", "label": "登录与认证", "description": "应用登录、注册、成员准入", "icon": "Lock", "default": True},
    {"key": "workflow", "label": "工作流审批", "description": "流程定义、审批面板、真实待办", "icon": "Finished", "default": True},
    {"key": "cms", "label": "内容管理", "description": "文章、分类、标签、评论、素材", "icon": "Document", "default": False},
    {"key": "crm", "label": "客户管理", "description": "客户、商机、合同、工单", "icon": "UserFilled", "default": False},
    {"key": "members", "label": "会员中心", "description": "会员等级、积分、权益", "icon": "Medal", "default": False},
    {"key": "files", "label": "文件与素材", "description": "应用独立文件命名空间", "icon": "Folder", "default": True},
    {"key": "notifications", "label": "消息通知", "description": "站内信、邮件、审批提醒", "icon": "Bell", "default": True},
    {"key": "audit", "label": "操作审计", "description": "登录与业务操作审计", "icon": "DocumentChecked", "default": True},
    {"key": "search", "label": "全局搜索", "description": "跨模型内容搜索", "icon": "Search", "default": True},
    {"key": "reports", "label": "数据报表", "description": "聚合报表与导出", "icon": "DataLine", "default": True},
    {"key": "api", "label": "开放 API", "description": "应用级 Token 与外部集成", "icon": "Connection", "default": False},
    {"key": "ai", "label": "AI 助手", "description": "页面生成、数据模型与流程建议", "icon": "MagicStick", "default": True},
]
MODULE_MAP = {item["key"]: item for item in MODULE_DEFS}


def default_modules() -> list[dict]:
    return [{**item, "enabled": bool(item["default"])} for item in MODULE_DEFS]


def normalize_modules(raw) -> list[dict]:
    if isinstance(raw, dict):
        enabled = {str(k): bool(v) for k, v in raw.items()}
    elif isinstance(raw, list):
        enabled = {str(item.get("key")): bool(item.get("enabled")) for item in raw if isinstance(item, dict)}
    else:
        enabled = {}
    out = []
    for item in MODULE_DEFS:
        out.append({**item, "enabled": enabled.get(item["key"], bool(item["default"]))})
    return out


def module_for_path(path: str) -> str:
    """按页面路径推断能力模块；meta.module 优先。"""
    value = str(path or "").strip().strip("/")
    if value.startswith(("account/", "auth/")):
        return "auth"
    if value == "account" or value == "auth":
        return "auth"
    if value.startswith("cms/"):
        return "cms"
    if value.startswith("crm/"):
        return "crm"
    if value.startswith("members/"):
        return "members"
    if value.startswith("workflow/"):
        return "workflow"
    if value.startswith("reports/"):
        return "reports"
    if value.startswith("system/monitoring"):
        return "reports"
    if value.startswith("system/"):
        return "auth"
    return "core"


def enabled_module_map(app) -> dict:
    """未配置模块行的应用视为全部放行，避免历史应用被误伤。"""
    from appcore.models import AppModule

    rows = {item.key: item.enabled for item in AppModule.objects.filter(app=app)}
    if not rows:
        return {item["key"]: True for item in MODULE_DEFS}
    out = {}
    for item in MODULE_DEFS:
        out[item["key"]] = bool(rows.get(item["key"], item["default"]))
    return out


def module_enabled(app, key: str) -> bool:
    if not key or key == "core":
        return True
    return bool(enabled_module_map(app).get(key, True))


def require_module(app_or_id, key: str) -> None:
    from rest_framework.exceptions import PermissionDenied

    app = app_or_id
    if isinstance(app_or_id, int):
        from appcore.models import App
        app = App.objects.filter(pk=app_or_id).first()
    if app is not None and not module_enabled(app, key):
        raise PermissionDenied(f"模块未启用：{key}")


def module_for_model(name: str) -> str:
    value = str(name or "").lower()
    if any(key in value for key in ("article", "content", "category", "comment", "media", "banner")):
        return "cms"
    if any(key in value for key in ("customer", "contract", "ticket", "opportunity", "followup")):
        return "crm"
    if "member" in value or "point" in value:
        return "members"
    if any(key in value for key in ("expense", "purchase", "approval", "workflow")):
        return "workflow"
    return "core"


