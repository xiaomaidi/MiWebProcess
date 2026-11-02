"""AI 报表问答：把当前模型数据摘要交给模型回答；无 Provider 时返回本地统计。"""
from __future__ import annotations

import json
import urllib.request

from rest_framework.exceptions import ValidationError


def local_answer(question: str, rows: list[dict], fields: list[dict]) -> str:
    names = {f.get("name") for f in fields if isinstance(f, dict)}
    data = [r.get("data") or {} for r in rows]
    parts = [f"共 {len(data)} 条记录。"]
    if "status" in names:
        counts: dict[str, int] = {}
        for row in data:
            key = str(row.get("status") or "未设置")
            counts[key] = counts.get(key, 0) + 1
        parts.append("状态分布：" + "，".join(f"{k} {v} 条" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    for field in fields:
        if not isinstance(field, dict) or field.get("type") != "number":
            continue
        if any(word in question for word in ("金额", "合计", "总和", "总额")) or field.get("name") in question:
            values = []
            for row in data:
                try:
                    values.append(float(row.get(field["name"])))
                except (TypeError, ValueError):
                    pass
            if values:
                parts.append(f"{field.get('label') or field['name']} 合计 {round(sum(values), 2)}，平均 {round(sum(values)/len(values), 2)}。")
    return " ".join(parts)


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    if start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(text[start:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    return {}


def llm_answer(app_name: str, question: str, rows: list[dict], fields: list[dict]) -> str:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置 AI Provider"})
    cfg = chat_config()
    sample = [r.get("data") or {} for r in rows[:80]]
    user = f"""应用：{app_name}
数据字段：{json.dumps([{'name': f.get('name'), 'label': f.get('label'), 'type': f.get('type')} for f in fields], ensure_ascii=False)}
数据样本（最多 80 条）：{json.dumps(sample, ensure_ascii=False, default=str)}
用户问题：{question}

请用中文直接回答，不要编造样本中不存在的事实。涉及汇总时说明是样本范围。只输出 {{"answer": "..."}} JSON。
"""
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": "你是数据分析助手，只返回严格 JSON。"},
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
    with urllib.request.urlopen(req, timeout=cfg.get("timeout", 90)) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    parsed = _extract_json(content)
    return str(parsed.get("answer") or content).strip()
