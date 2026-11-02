"""AI 内容翻译：保留 HTML 标签，翻译标题/摘要/正文。"""
from __future__ import annotations

import json
import re
import urllib.request

from rest_framework.exceptions import ValidationError


def local_translate(data: dict, target_lang: str) -> dict:
    return dict(data)


def llm_translate(app_name: str, data: dict, target_lang: str) -> tuple[dict, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置 AI Provider"})
    cfg = chat_config()
    user = f"""把下面的内容翻译为 {target_lang}，应用：{app_name}
要求：
1. 只翻译文本，保留 HTML 标签结构。
2. 标题、摘要、正文、标签都要翻译。
3. 返回 JSON，键与输入一致。
4. 不要解释，不要 Markdown。

输入：
{json.dumps(data, ensure_ascii=False)}
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
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
    start = content.find("{")
    if start < 0:
        raise ValidationError({"detail": "翻译结果不是 JSON"})
    value, _ = json.JSONDecoder().raw_decode(content[start:])
    if not isinstance(value, dict):
        raise ValidationError({"detail": "翻译结果不是对象"})
    return {k: value.get(k, v) for k, v in data.items()}, cfg["model"]
