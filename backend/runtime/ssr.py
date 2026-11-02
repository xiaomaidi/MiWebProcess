"""服务端渲染（SSR）与水合快照。

流程：
1. 后端构造与 ``runtime_page`` 完全一致的页面数据（``build_page_payload``）；
2. 调用 Node 侧的 SSR 产物 ``frontend/dist-ssr/entry-server.js`` 渲染出 HTML；
3. 把 HTML 与 ``window.__WP_SSR__``（页面数据 + 预取内容）写进完整文档；
4. 浏览器端 ``main.ts`` 检测到 ``__WP_SSR__`` 后用 ``createSSRApp`` 水合，避免二次请求与闪屏。

Node 不可用、SSR 产物缺失或渲染失败时自动返回 ``None``，由调用方回退到
现有的 SEO 模板，平台功能不受影响。
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger("runtime.ssr")


def bundle_dir() -> Path:
    return Path(getattr(settings, "SSR_BUNDLE_DIR", "") or "")


def node_bin() -> str:
    return str(getattr(settings, "SSR_NODE_BIN", "") or "node")


def renderer_script() -> Path:
    frontend = Path(settings.BASE_DIR).parent / "frontend" if hasattr(settings, "BASE_DIR") else bundle_dir().parent
    return frontend / "scripts" / "ssr-render.mjs"


def ssr_available() -> bool:
    return (bundle_dir() / "entry-server.js").exists()


def _asset_tags() -> tuple[str, str]:
    """从已构建的 dist/index.html 提取 CSS/JS 标签；未构建时回退 Vite 开发入口。"""
    index = Path(settings.BASE_DIR).parent / "frontend" / "dist" / "index.html"
    if index.exists():
        try:
            html = index.read_text(encoding="utf-8")
            import re

            styles = re.findall(r'<link[^>]+rel="stylesheet"[^>]*>', html)
            scripts = re.findall(r'<script[^>]+src="[^"]+"[^>]*></script>', html)
            if scripts:
                return _prefix_assets("\n".join(styles)), _prefix_assets("\n".join(scripts))
        except Exception:
            logger.exception("parse dist/index.html failed")
    return "", '<script type="module" src="/src/main.ts"></script>'


def _prefix_assets(html: str) -> str:
    """给 /assets/... 加可配置前缀（CDN 或 Vite 开发服务器）。"""
    base = str(getattr(settings, "SSR_ASSET_BASE", "") or "").rstrip("/")
    if not base:
        return html
    return html.replace('href="/', f'href="{base}/').replace('src="/', f'src="{base}/')


def _html_escape(text) -> str:
    from django.utils.html import escape

    return escape(str(text or ""))


def _build_document(app, page_path: str, body: str, payload: dict, prefetch: dict) -> str:
    schema = (payload.get("page_version") or {}).get("schema") or {}
    meta = schema.get("meta") or {}
    title = str(meta.get("title") or (payload.get("page") or {}).get("name") or app.name)
    description = str(meta.get("description") or (schema.get("seo") or {}).get("description") or "")
    lang = str(meta.get("lang") or "zh-CN")
    base = str(getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    canonical = f"{base}/run/{app.code}/{page_path}".rstrip("/")
    styles, scripts = _asset_tags()
    jsonld = _article_jsonld(prefetch, canonical)
    jsonld_tag = f'<script type="application/ld+json">{jsonld}</script>' if jsonld else ""
    state = json.dumps(
        {"url": f"/run/{app.code}/{page_path}".rstrip("/"), "payload": payload, "prefetch": prefetch},
        ensure_ascii=False,
        default=str,
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="{_html_escape(lang)}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{_html_escape(title)}</title>
<meta name="description" content="{_html_escape(description)}" />
<link rel="canonical" href="{_html_escape(canonical)}" />
<meta property="og:title" content="{_html_escape(title)}" />
<meta property="og:description" content="{_html_escape(description)}" />
<meta property="og:url" content="{_html_escape(canonical)}" />
{jsonld_tag}
{styles}
</head>
<body>
<div id="app" data-server-rendered="true">{body}</div>
<script>window.__WP_SSR__={state};</script>
{scripts}
</body>
</html>
"""


def _article_jsonld(prefetch: dict, canonical: str) -> str:
    """文章详情预取数据 → schema.org Article JSON-LD（保留原 SEO 行为）。"""
    if not isinstance(prefetch, dict):
        return ""
    record = None
    for key, value in prefetch.items():
        if str(key).startswith("article:") and isinstance(value, dict) and value.get("record"):
            record = value["record"]
            break
    if not isinstance(record, dict):
        return ""
    data = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": record.get("title") or record.get("name") or "",
        "description": record.get("summary") or record.get("description") or "",
        "image": record.get("cover") or record.get("image") or None,
        "datePublished": record.get("published_at") or None,
        "author": {"@type": "Person", "name": record.get("author")} if record.get("author") else None,
        "mainEntityOfPage": canonical,
    }
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def render_page_html(app, page_path: str, *, prefetch: bool = True) -> tuple[str, dict] | None:
    """渲染单页，返回 (完整 HTML, 元信息)；失败返回 None。"""
    if not ssr_available():
        return None
    try:
        from runtime.views import build_page_payload
    except Exception:
        return None
    try:
        payload = build_page_payload(app, page_path)
    except Exception:
        return None

    # 内联状态只保留运行态渲染所需字段：组件注册表体积大且客户端运行时不使用。
    light_payload = {
        **payload,
        "registry": {},
        "config": {"components": [], "datasources": (payload.get("config") or {}).get("datasources", [])},
    }

    job = {
        "url": f"/run/{app.code}/{page_path}".rstrip("/"),
        "payload": light_payload,
        "apiBase": str(getattr(settings, "SSR_API_BASE", "") or "http://127.0.0.1:8000"),
        "prefetch": bool(prefetch),
    }
    script = renderer_script()
    if not script.exists():
        return None
    with tempfile.TemporaryDirectory(prefix="wp-ssr-") as tmp:
        job_path = Path(tmp) / "job.json"
        out_path = Path(tmp) / "out.html"
        pre_path = Path(tmp) / "prefetch.json"
        job_path.write_text(json.dumps(job, ensure_ascii=False, default=str), encoding="utf-8")
        cmd = [node_bin(), str(script), str(job_path), str(out_path), str(pre_path)]
        try:
            proc = subprocess.run(
                cmd, cwd=str(script.parent.parent), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SSR 渲染进程启动失败: %s", exc)
            return None
        if proc.returncode != 0 or not out_path.exists():
            logger.warning("SSR 渲染失败(%s): %s", proc.returncode, (proc.stderr or "")[:800])
            return None
        body = out_path.read_text(encoding="utf-8")
        prefetch_data = {}
        if pre_path.exists():
            try:
                prefetch_data = json.loads(pre_path.read_text(encoding="utf-8"))
            except Exception:
                prefetch_data = {}
    html = _build_document(app, page_path, body, light_payload, prefetch_data)
    return html, {"payload": light_payload, "prefetch": prefetch_data, "bytes": len(html)}


def _article_model_id(page) -> int | None:
    for node in ((page.schema or {}).get("nodes") or {}).values():
        if isinstance(node, dict) and node.get("type") == "article-detail":
            try:
                return int((node.get("props") or {}).get("dataModelId") or 0) or None
            except (TypeError, ValueError):
                return None
    return None


def page_targets(page) -> list[str]:
    """静态页返回自身；article/:id 返回每个已发布记录的具体路径。"""
    if ":" not in page.path:
        return [page.path]
    model_id = _article_model_id(page)
    if not model_id:
        return []
    from datamodels.models import DataModel, DataRecord

    model = DataModel.objects.filter(app_id=page.app_id, id=model_id).first()
    if model is None:
        return []
    fields = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    paths = []
    for record in DataRecord.objects.filter(model=model):
        if "status" in fields and (record.data or {}).get("status") != "published":
            continue
        paths.append(page.path.replace(":id", str(record.id)))
    return paths


def write_snapshot(app, page_path: str, output_dir: Path) -> dict | None:
    result = render_page_html(app, page_path)
    if result is None:
        return None
    html, meta = result
    target = output_dir / app.code / page_path.strip("/") / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return {"path": page_path, "file": str(target), "bytes": meta["bytes"]}
