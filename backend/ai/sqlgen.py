"""AI SQL 生成：只生成 SELECT，必须在外部数据源上执行。"""
from __future__ import annotations

import json
import re
import urllib.request

from rest_framework.exceptions import ValidationError

from datasources.executor import assert_select_only


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValidationError({"detail": "AI 返回的不是 JSON"})
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValidationError({"detail": "AI 返回的 SQL 不是合法 JSON"}) from exc
    return value if isinstance(value, dict) else {}


def local_sql(tables: list[dict]) -> str:
    if not tables:
        raise ValidationError({"detail": "数据库没有可查询的表"})
    table = tables[0]
    return f'SELECT * FROM "{table["schema"]}"."{table["name"]}" LIMIT 50'


def generate_sql(question: str, tables: list[dict], table_description: str) -> tuple[str, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        return local_sql(tables), "local-sql-template"
    cfg = chat_config()
    user = f"""数据库结构：
{table_description}

用户问题：{question}

只输出 JSON：{{"sql":"一条 SELECT 查询"}}
规则：
1. 只生成 SELECT，不生成 INSERT/UPDATE/DELETE/DDL。
2. 使用带双引号的 schema.table 和字段名。
3. 不确定字段时不要编造。
4. 默认加 LIMIT 100。
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
    with urllib.request.urlopen(req, timeout=cfg.get("timeout", 90)) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    sql = str(_extract_json(content).get("sql") or "").strip().rstrip(";")
    assert_select_only(sql)
    return sql, cfg["model"]
