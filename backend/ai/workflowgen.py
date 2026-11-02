"""AI 工作流草稿：自然语言 → 审批节点；只填充设计器，不直接发布。"""
from __future__ import annotations

import json
import re
import urllib.request

from rest_framework.exceptions import ValidationError


def _code(prompt: str, prefix: str = "ai_flow") -> str:
    ascii_words = re.findall(r"[a-zA-Z0-9]+", prompt)
    if ascii_words:
        return re.sub(r"[^a-z0-9_]", "_", "_".join(ascii_words).lower())[:40]
    return f"{prefix}_{abs(hash(prompt)) % 10000}"


def local_workflow(prompt: str) -> dict:
    text = str(prompt or "")
    if any(word in text for word in ("采购", "订单", "金额", "报销")):
        nodes = [
            {"id": "dept", "name": "部门审批", "type": "approval", "assignee_role": "editor", "mode": "any", "timeout_hours": 24},
            {"id": "amount_gate", "name": "金额 > 20000", "type": "condition", "condition": {"field": "amount", "operator": "gt", "value": 20000}, "false_next": "end"},
            {"id": "finance", "name": "财务会签", "type": "approval", "assignee_role": "owner", "mode": "all", "timeout_hours": 48, "approvers": [{"assignee_role": "owner"}, {"assignee_role": "editor"}]},
        ]
        return {"name": "采购订单审批", "code": _code(prompt, "purchase_approval"), "description": "部门审批后按金额进入财务会签", "nodes": nodes}
    if any(word in text for word in ("请假", "休假", "考勤")):
        nodes = [
            {"id": "manager", "name": "直属主管审批", "type": "approval", "assignee_role": "owner", "mode": "any", "timeout_hours": 24},
            {"id": "hr", "name": "人事审批", "type": "approval", "assignee_role": "editor", "mode": "any", "timeout_hours": 24},
        ]
        return {"name": "请假审批", "code": _code(prompt, "leave_approval"), "description": "主管审批后由人事确认", "nodes": nodes}
    nodes = [
        {"id": "review", "name": "负责人审批", "type": "approval", "assignee_role": "owner", "mode": "any", "timeout_hours": 24},
        {"id": "confirm", "name": "确认", "type": "approval", "assignee_role": "editor", "mode": "any", "timeout_hours": 24},
    ]
    return {"name": "AI 审批流程", "code": _code(prompt), "description": "AI 生成的两级审批流程", "nodes": nodes}


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValidationError({"detail": "AI 返回的不是 JSON 对象"})
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValidationError({"detail": "AI 返回的流程不是合法 JSON"}) from exc
    if not isinstance(value, dict):
        raise ValidationError({"detail": "AI 返回的流程不是对象"})
    return value


def call_llm_workflow(app_name: str, prompt: str) -> tuple[dict, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置 AI Provider"})
    cfg = chat_config()
    user = f"""为 MiWebProcess 设计审批工作流，应用：{app_name}
需求：{prompt}

只输出 JSON：
{{"name":"流程名","code":"英文小写下划线","description":"说明","nodes":[
  {{"id":"dept","name":"部门审批","type":"approval","assignee_role":"editor","mode":"any","timeout_hours":24}},
  {{"id":"gate","name":"金额条件","type":"condition","condition":{{"field":"amount","operator":"gt","value":20000}},"false_next":"end"}}
]}}
规则：
1. 节点 2-6 个，只使用 approval / condition。
2. approval 的 assignee_role 只能是 viewer/editor/owner；mode 为 all/any。
3. condition 的 operator 只能是 eq/ne/contains/gt/lt；false_next 只能是 end 或某个节点 id。
4. id 唯一，英文小写；不要输出 start/end 节点。
5. 严格 JSON，不要 Markdown。
"""
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": "你只返回严格 JSON。"},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        f"{cfg['base_url'].rstrip('/')}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 90)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": f"AI 请求失败: {exc}"}) from exc
    content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    return _extract_json(content), cfg["model"]


def normalize_workflow(draft: dict) -> dict:
    name = str(draft.get("name") or "AI 审批流程").strip()
    code = re.sub(r"[^a-z0-9_]", "_", str(draft.get("code") or "").lower()).strip("_") or "ai_flow"
    description = str(draft.get("description") or "")
    raw_nodes = draft.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValidationError({"detail": "流程没有节点"})
    nodes = []
    seen = set()
    for index, item in enumerate(raw_nodes[:12]):
        if not isinstance(item, dict):
            continue
        node_type = item.get("type")
        if node_type not in ("approval", "condition"):
            continue
        node_id = re.sub(r"[^a-z0-9_]", "_", str(item.get("id") or f"node_{index + 1}").lower()).strip("_")
        if not node_id or node_id in seen:
            node_id = f"node_{index + 1}"
        seen.add(node_id)
        node = {"id": node_id, "name": str(item.get("name") or f"节点 {index + 1}"), "type": node_type}
        if node_type == "approval":
            role = str(item.get("assignee_role") or "editor")
            node["assignee_role"] = role if role in ("viewer", "editor", "owner") else "editor"
            node["mode"] = "all" if item.get("mode") == "all" else "any"
            node["timeout_hours"] = max(0, int(item.get("timeout_hours") or 0))
            approvers = item.get("approvers")
            if isinstance(approvers, list):
                node["approvers"] = [
                    {"assignee_role": a.get("assignee_role") if a.get("assignee_role") in ("viewer", "editor", "owner") else "owner"}
                    for a in approvers if isinstance(a, dict)
                ]
        else:
            cond = item.get("condition") if isinstance(item.get("condition"), dict) else {}
            node["condition"] = {
                "field": str(cond.get("field") or "status"),
                "operator": cond.get("operator") if cond.get("operator") in ("eq", "ne", "contains", "gt", "lt") else "eq",
                "value": cond.get("value", ""),
            }
            node["false_next"] = str(item.get("false_next") or "end")
        nodes.append(node)
    if not nodes:
        raise ValidationError({"detail": "没有有效的工作流节点"})
    # 修正条件节点指向后面节点的引用（若模型给了合法 id）。
    ids = {n["id"] for n in nodes}
    for node in nodes:
        if node["type"] == "condition" and node.get("false_next") not in ids and node.get("false_next") != "end":
            node["false_next"] = "end"
    return {"name": name[:80], "code": code[:60], "description": description[:300], "nodes": nodes}
