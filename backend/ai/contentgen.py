"""AI 内容草稿：根据栏目/主题生成标题、摘要和正文，供内容模型创建记录。"""
from __future__ import annotations

import json
import re
import urllib.request

from rest_framework.exceptions import ValidationError


def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start < 0:
        raise ValidationError({"detail": "AI 返回的不是 JSON 对象"})
    try:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise ValidationError({"detail": "AI 返回的内容不是合法 JSON"}) from exc
    if not isinstance(value, dict):
        raise ValidationError({"detail": "AI 返回的内容不是对象"})
    return value


def local_content(prompt: str, fields: set[str]) -> dict:
    title = str(prompt or "").strip().replace("\n", " ")[:48] or "AI 内容草稿"
    summary = f"围绕「{title}」整理的 AI 内容草稿，可继续编辑后发布。"
    paragraphs = [
        f"<p>{title} 是近期值得关注的内容方向。本文从背景、现状和后续影响三个角度进行整理。</p>",
        "<h2>背景</h2>",
        "<p>随着相关产品与市场的变化，这一话题正在获得更多关注。团队将持续跟踪并补充最新信息。</p>",
        "<h2>值得关注的点</h2>",
        "<ul><li>核心变化与时间节点</li><li>对用户和业务的实际影响</li><li>后续可验证的信号</li></ul>",
        "<blockquote>本文为 AI 生成草稿，发布前请人工核实事实与数据。</blockquote>",
    ]
    draft = {
        "title": title,
        "summary": summary,
        "content": "".join(paragraphs),
        "tags": "AI,内容草稿",
        "status": "draft",
        "author": "编辑部",
    }
    return {k: v for k, v in draft.items() if k in fields}


def local_batch(prompt: str, fields: set[str], count: int) -> list[dict]:
    angles = ["背景与现状", "关键变化", "用户影响", "行业观察", "后续展望"]
    drafts = []
    for index in range(count):
        angle = angles[index % len(angles)]
        drafts.append(local_content(f"{prompt}（角度：{angle}）", fields))
    return drafts


def call_llm_content(app_name: str, prompt: str, fields: set[str]) -> tuple[dict, str]:
    from ai.providers import chat_config, is_configured

    if not is_configured():
        raise ValidationError({"detail": "未配置可用的 AI Provider"})
    cfg = chat_config()
    api_key = cfg["api_key"]
    base = cfg["base_url"]
    model = cfg["model"]
    user = f"""为内容站点「{app_name}」写一篇中文内容草稿。
主题/要求：{prompt}

只输出 JSON：
{{"title":"标题","summary":"80字内摘要","content":"正文 HTML，包含 h2/p/ul/blockquote","tags":"逗号分隔标签","status":"draft","author":"编辑部"}}
要求：
1. 事实不确定的内容要写成待核实，不要编造具体数据。
2. content 只使用 h2/p/ul/li/blockquote/strong 标签，不要 script/style。
3. 不超过 800 字。
4. 严格执行用户主题。
"""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你只返回严格 JSON。"},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
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
    draft = _extract_json(content)
    allowed = {"title", "summary", "content", "tags", "status", "author", "category", "cover"}
    return {k: v for k, v in draft.items() if k in fields and k in allowed}, model
