"""AI 权限建议：根据字段名称和模型配置给出可审阅的权限草稿。"""
from __future__ import annotations

import re


SENSITIVE_RE = re.compile(r"(password|passwd|secret|token|api_?key|phone|mobile|email|id_card|identity|salary|amount|price)", re.I)


def suggest_permissions(fields: list[dict]) -> dict:
    names = [str(f.get("name") or "") for f in fields if isinstance(f, dict)]
    mask_fields = {}
    for name in names:
        if SENSITIVE_RE.search(name):
            mask_fields[name] = ["viewer"]
    owner_candidates = [n for n in names if n in ("owner_id", "user_id", "created_by", "owner", "creator")]
    row_owner = owner_candidates[0] if owner_candidates else ""
    action_roles = {
        "view": [],
        "create": ["editor", "owner"],
        "update": ["editor", "owner"],
        "delete": ["owner"],
        "export": ["owner"],
    }
    notes = []
    if mask_fields:
        notes.append("检测到敏感字段，建议至少对查看者脱敏：" + "、".join(mask_fields))
    if row_owner:
        notes.append(f"检测到归属字段 {row_owner}，建议启用“仅本人数据”。")
    else:
        notes.append("未检测到明确归属字段，默认保持全部数据范围。")
    notes.append("新增/编辑建议限制 editor 及以上，删除/导出限制 owner。")
    return {
        "data_scope": "owner" if row_owner else "all",
        "row_owner_field": row_owner,
        "action_roles": action_roles,
        "mask_fields": mask_fields,
        "notes": notes,
    }
