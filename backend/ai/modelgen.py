"""AI 数据模型草稿：自然语言 → 字段定义；只返回草稿，不直接建表。"""
from __future__ import annotations

import json
import re
import urllib.request

from rest_framework.exceptions import ValidationError

from datamodels.services import validate_fields_spec


def _field(name: str, label: str, ftype: str = "string", required: bool = False, **extra):
    return {"name": name, "label": label, "type": ftype, "required": required, **extra}


def local_model_draft(prompt: str) -> dict:
    text = str(prompt or "")
    if any(word in text for word in ("文章", "资讯", "内容", "博客", "CMS")):
        return {
            "name": "ai_article",
            "fields": [
                _field("title", "标题", required=True),
                _field("slug", "Slug", required=True, unique=True),
                _field("summary", "摘要", ui="textarea"),
                _field("content", "正文", ui="richtext"),
                _field("cover", "封面"),
                _field("category", "分类"),
                _field("author", "作者"),
                _field("status", "状态", default="draft"),
                _field("published_at", "发布时间", "date"),
            ],
        }
    if any(word in text for word in ("订单", "采购", "销售", "ERP")):
        return {
            "name": "ai_order",
            "fields": [
                _field("order_no", "订单号", required=True, unique=True),
                _field("customer", "客户", required=True),
                _field("amount", "金额", "number", required=True),
                _field("status", "状态", default="draft"),
                _field("order_date", "下单日期", "date"),
                _field("remark", "备注", ui="textarea"),
            ],
        }
    if any(word in text for word in ("客户", "联系人", "CRM", "会员")):
        return {
            "name": "ai_customer",
            "fields": [
                _field("name", "姓名", required=True),
                _field("phone", "电话"),
                _field("email", "邮箱"),
                _field("company", "公司"),
                _field("level", "等级"),
                _field("status", "状态", default="active"),
                _field("remark", "备注", ui="textarea"),
            ],
        }
    if any(word in text for word in ("员工", "人员", "组织", "部门")):
        return {
            "name": "ai_employee",
            "fields": [
                _field("name", "姓名", required=True),
                _field("employee_no", "工号", required=True, unique=True),
                _field("department", "部门"),
                _field("position", "职位"),
                _field("phone", "电话"),
                _field("status", "状态", default="active"),
            ],
        }
    return {
        "name": "ai_data",
        "fields": [
            _field("title", "名称", required=True),
            _field("description", "描述", ui="textarea"),
            _field("status", "状态", default="draft"),
        ],
    }


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValidationError({"detail": "AI 返回的不是 JSON 对象"})
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValidationError({"detail": "AI 返回的模型不是合法 JSON"}) from exc
    if not isinstance(value, dict):
        raise ValidationError({"detail": "AI 返回的模型不是对象"})
    return value


def call_llm_model(app_name: str, prompt: str) -> tuple[dict, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置可用的 AI Provider"})
    cfg = chat_config()
    api_key = cfg["api_key"]
    base = cfg["base_url"]
    model = cfg["model"]
    user = f"""为 MiWebProcess 设计一个数据模型，应用：{app_name}
用户需求：{prompt}

只输出 JSON：
{{
  "name": "英文小写下划线模型名",
  "fields": [
    {{"name":"英文小写字段名","label":"中文显示名","type":"string|number|boolean|date|json|reference","required":true}}
  ]
}}
规则：
1. 4-10 个字段，必须包含一个主标题/名称字段。
2. type 只能使用 string/number/boolean/date/json。
3. 不要输出 reference 字段。
4. 字段名小写，使用下划线；不要 SQL 关键字。
5. 输出严格 JSON，不要 Markdown。
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
    content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    return _extract_json(content), model


def normalize_model_draft(draft: dict, app) -> dict:
    name = re.sub(r"[^a-z0-9_]", "_", str(draft.get("name") or "ai_model").lower())
    name = re.sub(r"_+", "_", name).strip("_") or "ai_model"
    fields = draft.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValidationError({"detail": "模型没有字段"})
    cleaned = []
    for item in fields[:30]:
        if not isinstance(item, dict):
            continue
        ftype = str(item.get("type") or "string")
        if ftype not in ("string", "number", "boolean", "date", "json", "reference"):
            ftype = "string"
        field = {
            "name": re.sub(r"[^a-z0-9_]", "_", str(item.get("name") or "").lower()).strip("_"),
            "label": str(item.get("label") or item.get("name") or "").strip(),
            "type": ftype,
            "required": bool(item.get("required")),
        }
        if field["name"]:
            cleaned.append(field)
    if not cleaned:
        raise ValidationError({"detail": "模型字段不合法"})
    return {"name": name, "fields": validate_fields_spec(cleaned, app)}
