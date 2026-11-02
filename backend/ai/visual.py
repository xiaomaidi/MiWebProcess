"""截图级 AI 视觉评审。

两条路径：
1. 配置了视觉模型（``AI_VISION_MODEL``，或默认模型名包含 vision/gpt-4o/qwen-vl 等）时，
   把截图作为 image_url 发给 OpenAI-compatible 多模态接口，返回结构化问题清单；
2. 未配置时用 Pillow 做像素级体检（留白、对比度、配色、边缘密度、内容分布），
   并把结构评审（``ai.review.review_schema``）的问题合并，保证始终有可用结论。
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.request

from django.conf import settings

from ai.providers import chat_config, is_configured

VISION_HINTS = (
    "vision", "gpt-4o", "gpt-4.1", "gpt-5", "claude-3", "claude-4", "gemini",
    "qwen-vl", "qwen2-vl", "glm-4v", "llava", "internvl", "pixtral", "minicpm-v",
)
MAX_IMAGE_BYTES = 6 * 1024 * 1024


def decode_image(data: str) -> bytes:
    text = str(data or "").strip()
    if not text:
        raise ValueError("截图为空")
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    try:
        raw = base64.b64decode(text, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"截图 base64 解析失败: {exc}") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("截图过大（最大 6MB）")
    return raw


def _lum(pixel) -> float:
    r, g, b = pixel[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def image_metrics(raw: bytes) -> dict:
    """像素级体检：尺寸、留白、对比度、配色、边缘与三分区内容分布。"""
    from PIL import Image, ImageFilter, ImageStat

    image = Image.open(io.BytesIO(raw)).convert("RGB")
    width, height = image.size
    small = image.copy()
    small.thumbnail((360, 360))
    gray = small.convert("L")
    pixels = list(gray.getdata())
    total = max(1, len(pixels))
    blank = sum(1 for value in pixels if value >= 245 or value <= 10) / total
    stat = ImageStat.Stat(gray)
    contrast = float(stat.stddev[0]) if stat.stddev else 0.0
    brightness = float(stat.mean[0]) if stat.mean else 0.0
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_density = float(ImageStat.Stat(edges).mean[0]) if edges else 0.0

    palette = image.convert("P", palette=Image.ADAPTIVE, colors=16)
    counts = palette.getcolors(maxcolors=1 << 20) or []
    counts.sort(reverse=True)
    palette_colors = palette.getpalette() or []
    total_px = max(1, width * height)
    dominant = []
    for count, index in counts[:5]:
        r, g, b = palette_colors[index * 3: index * 3 + 3] or (0, 0, 0)
        dominant.append({"color": f"#{r:02x}{g:02x}{b:02x}", "ratio": round(count / total_px, 3)})

    bands = []
    sw, sh = small.size
    for row in range(3):
        cells = []
        for col in range(3):
            box = (col * sw // 3, row * sh // 3, (col + 1) * sw // 3, (row + 1) * sh // 3)
            if box[2] <= box[0] or box[3] <= box[1]:
                cells.append(0.0)
                continue
            part = gray.crop(box)
            values = list(part.getdata())
            cells.append(round(sum(1 for v in values if v >= 245 or v <= 10) / max(1, len(values)), 3))
        bands.append(cells)

    return {
        "width": width,
        "height": height,
        "aspect_ratio": round(width / max(1, height), 3),
        "blank_ratio": round(blank, 3),
        "contrast": round(contrast, 1),
        "brightness": round(brightness, 1),
        "edge_density": round(edge_density, 2),
        "dominant_colors": dominant,
        "color_count": len(counts),
        "blank_grid": bands,
    }


def heuristic_issues(metrics: dict, schema: dict | None = None) -> list[dict]:
    issues: list[dict] = []

    def add(level: str, category: str, message: str, suggestion: str, region: str = "全屏"):
        issues.append({
            "level": level, "category": category, "message": message,
            "suggestion": suggestion, "region": region,
        })

    blank = float(metrics.get("blank_ratio") or 0)
    contrast = float(metrics.get("contrast") or 0)
    edge = float(metrics.get("edge_density") or 0)
    colors = int(metrics.get("color_count") or 0)
    width = int(metrics.get("width") or 0)
    height = int(metrics.get("height") or 0)

    if blank > 0.7:
        add("error", "layout", f"画面 {int(blank * 100)}% 为纯白/纯黑像素，内容严重不足", "补充首屏信息层级，或检查是否渲染失败")
    elif blank > 0.5:
        add("warning", "layout", f"画面留白约 {int(blank * 100)}%，首屏偏空", "增加主视觉、数据卡片或缩短上下留白")
    if contrast < 18:
        add("warning", "color", f"明暗对比偏低（标准差 {contrast}），文字可能难以辨认", "提高正文与背景的对比度，避免浅灰字叠浅色底")
    if colors and colors < 6:
        add("info", "color", f"主色仅 {colors} 种，视觉层次偏单调", "为强调元素增加一种点缀色或使用层级阴影")
    if edge < 2.2 and blank < 0.7:
        add("warning", "layout", "画面细节密度偏低，缺少视觉锚点", "增加图标、图片或分区标题，避免整屏纯文本")
    if width and height and width / max(1, height) > 2.2:
        add("info", "layout", "画布非常扁平，宽高比过大", "检查画布高度设置，或为桌面/移动端分别评审")
    if width and height and height / max(1, width) > 3.2:
        add("info", "layout", "画布非常狭长，可能只截取了局部", "确认截图区域包含完整页面")

    grid = metrics.get("blank_grid") or []
    if len(grid) == 3:
        names = ["顶部", "中部", "底部"]
        for index, row in enumerate(grid):
            if row and all(cell > 0.92 for cell in row):
                add("warning", "layout", f"{names[index]}区域几乎全空白", f"检查{names[index]}区域是否缺少内容或被错误隐藏", names[index])

    types = [n.get("type") for n in ((schema or {}).get("nodes") or {}).values() if isinstance(n, dict)]
    if types:
        if not any(t in types for t in ("wp-image", "ElImage", "ChartRenderer", "wp-piechart", "wp-barchart")):
            add("info", "content", "页面没有图片或图表类组件", "首屏可加入主视觉或数据图表，提升信息密度")
        if "site-nav" not in types:
            add("info", "content", "页面没有站点导航", "独立站点建议增加 site-nav，便于多页跳转")
    return issues


def _merge(schema_issues: list[dict]) -> list[dict]:
    merged = []
    for issue in schema_issues:
        merged.append({
            "level": issue.get("level", "info"),
            "category": "structure",
            "message": issue.get("message", ""),
            "suggestion": issue.get("suggestion", ""),
            "region": "结构",
        })
    return merged


def score_issues(issues: list[dict]) -> int:
    penalty = 0
    for issue in issues:
        level = issue.get("level")
        penalty += 18 if level == "error" else 8 if level == "warning" else 2
    return max(0, min(100, 100 - penalty))


def vision_model() -> str | None:
    explicit = str(getattr(settings, "AI_VISION_MODEL", "") or "").strip()
    if explicit:
        return explicit
    cfg = chat_config()
    model = str(cfg.get("model") or "").lower()
    if model and any(hint in model for hint in VISION_HINTS):
        return cfg.get("model")
    return None


def _vision_prompt(page_name: str, schema: dict | None, metrics: dict, prompt: str) -> str:
    node_types = [
        {"id": n.get("id"), "type": n.get("type")}
        for n in ((schema or {}).get("nodes") or {}).values() if isinstance(n, dict)
    ][:40]
    return f"""你是资深网页视觉设计师。请评审这张页面截图（页面：{page_name or "未命名"}）。
用户补充说明：{prompt or "无"}

页面结构（供参考）：{json.dumps(node_types, ensure_ascii=False)}
像素指标：{json.dumps({k: metrics.get(k) for k in ("width", "height", "blank_ratio", "contrast", "edge_density", "color_count")}, ensure_ascii=False)}

请只输出 JSON：
{{"score": 0-100, "summary": "一句话总评", "issues": [{{"level": "error|warning|info", "category": "layout|color|typography|content|a11y", "message": "问题", "suggestion": "可执行建议", "region": "顶部|中部|底部|左侧|右侧|全屏"}}]}}
评审重点：信息层级、留白与对齐、配色对比、可读性、首屏吸引力、移动端适配。最多 8 条问题。"""


def call_vision(image_data_uri: str, *, page_name: str, schema: dict | None, metrics: dict, prompt: str = "") -> dict:
    cfg = chat_config()
    model = vision_model() or cfg.get("model")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是严格的视觉评审专家，只返回 JSON。"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _vision_prompt(page_name, schema, metrics, prompt)},
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                ],
            },
        ],
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    req = urllib.request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=min(90, cfg.get("timeout") or 60)) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    text = str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    start = text.find("{")
    if start >= 0:
        value, _ = json.JSONDecoder().raw_decode(text[start:])
        if isinstance(value, dict):
            return value
    raise ValueError("视觉模型返回的不是合法 JSON")


def review_screenshot(
    image_data: str, *, schema: dict | None = None, page_name: str = "", prompt: str = "",
) -> dict:
    from ai.review import review_schema

    warnings: list[str] = []
    raw = decode_image(image_data)
    metrics = image_metrics(raw)

    structural = review_schema(schema) if isinstance(schema, dict) and schema.get("nodes") else {"issues": [], "score": 100}
    issues = heuristic_issues(metrics, schema) + _merge(structural.get("issues") or [])

    mode = "heuristic"
    model = ""
    vision_result: dict | None = None
    summary = "基于像素指标与页面结构的本地评审（未配置视觉模型）"
    if is_configured() and vision_model():
        try:
            mime = "image/png"
            if raw[:3] == b"\xff\xd8\xff":
                mime = "image/jpeg"
            data_uri = f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"
            vision = call_vision(data_uri, page_name=page_name, schema=schema, metrics=metrics, prompt=prompt)
            vision_result = vision
            vision_issues = [
                {
                    "level": str(i.get("level") or "info"),
                    "category": str(i.get("category") or "layout"),
                    "message": str(i.get("message") or ""),
                    "suggestion": str(i.get("suggestion") or ""),
                    "region": str(i.get("region") or "全屏"),
                }
                for i in (vision.get("issues") or [])
                if isinstance(i, dict) and i.get("message")
            ]
            issues = vision_issues + _merge(structural.get("issues") or [])
            mode = "vision"
            model = chat_config().get("model") or ""
            summary = str(vision.get("summary") or "视觉模型评审完成")[:300]
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"视觉模型调用失败，已回退像素评审：{exc}")
    elif is_configured():
        warnings.append("当前模型不支持图片输入（可在设置中配置 AI_VISION_MODEL，例如 gpt-4o / qwen-vl-max）")
    else:
        warnings.append("未配置 AI Provider，使用本地像素 + 结构评审")

    score = score_issues(issues)
    if mode == "vision" and isinstance(vision_result, dict):
        try:
            score = int(round(float(vision_result.get("score"))))
        except Exception:
            pass
    return {
        "score": max(0, min(100, score)),
        "summary": summary,
        "issues": issues[:20],
        "metrics": metrics,
        "mode": mode,
        "model": model,
        "warnings": warnings,
    }
