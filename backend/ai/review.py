"""页面结构与设计规则评审（不依赖截图）。"""
from __future__ import annotations


def review_schema(schema: dict) -> dict:
    issues: list[dict] = []
    nodes = (schema or {}).get("nodes") or {}
    root_id = (schema or {}).get("rootId")
    meta = (schema or {}).get("meta") or {}

    def add(level: str, message: str, node_id: str = "", suggestion: str = ""):
        issues.append({"level": level, "message": message, "node_id": node_id, "suggestion": suggestion})

    if not isinstance(nodes, dict) or not nodes or root_id not in nodes:
        return {"score": 0, "issues": [{"level": "error", "message": "页面缺少 root/nodes，无法评审", "node_id": "", "suggestion": "重新生成或检查页面 schema"}], "summary": "页面结构不完整"}
    if len(nodes) > 80:
        add("warning", f"页面节点过多（{len(nodes)} 个），首屏和编辑性能可能受影响", "", "拆分区块或减少装饰节点")

    types = [n.get("type") for n in nodes.values() if isinstance(n, dict)]
    if "wp-heading" not in types and "ElText" not in types:
        add("warning", "页面没有标题组件", "", "增加 wp-heading 作为页面主标题")
    if not any(t in types for t in ("content-list", "DataTable", "AutoForm", "ReportTable", "article-detail")):
        add("warning", "页面没有内容/数据组件", "", "增加内容列表、表格或表单，避免只有静态装饰")
    if not meta.get("title"):
        add("warning", "缺少页面标题 meta.title", "", "补充 SEO 标题")
    if not meta.get("description"):
        add("info", "缺少页面描述 meta.description", "", "补充 80 字以内描述")
    if not any(t == "site-nav" for t in types):
        add("info", "页面没有站点导航", "", "如需独立站点，增加 site-nav")

    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        props = node.get("props") or {}
        children = node.get("children") or []
        if node_type == "content-list" and not props.get("dataModelId"):
            add("error", "内容列表没有绑定数据模型", node_id, "设置 content-list.props.dataModelId")
        if node_type in ("wp-image", "ElImage") and not str(props.get("src") or "").strip():
            add("warning", "图片没有 src", node_id, "补充图片 URL 或使用占位图")
        if node_type in ("ElButton", "wp-button") and not str(props.get("text") or props.get("content") or "").strip():
            add("info", "按钮没有文案", node_id, "补充按钮文案")
        if isinstance(props.get("actions"), list):
            for action in props["actions"]:
                if isinstance(action, dict) and action.get("type") == "js":
                    add("error", "页面包含 JS action", node_id, "移除 JS action，使用平台动作")
        for child in children:
            if child not in nodes:
                add("error", f"children 引用了不存在的节点：{child}", node_id, "修复节点引用")

    errors = sum(1 for i in issues if i["level"] == "error")
    warnings = sum(1 for i in issues if i["level"] == "warning")
    score = max(0, 100 - errors * 20 - warnings * 8 - (len(issues) - errors - warnings) * 2)
    summary = "页面结构良好" if score >= 85 else "可以发布，但建议先处理警告" if score >= 60 else "建议修复后再发布"
    return {"score": score, "issues": issues, "summary": summary}
