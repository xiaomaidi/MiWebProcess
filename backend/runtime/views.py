"""运行时端点：对外提供 active 发布 bundle 与页面 schema。

- GET /api/runtime/                      → 404（需要 app_code）
- GET /api/runtime/{app_code}/           → active 发布 bundle（带缓存）
- GET /api/runtime/{app_code}/{path}/    → 指定页面 schema；?draft=1（JWT）返回草稿
"""
from __future__ import annotations

import json
import re

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from appcore.models import App, AppMember
from releases.models import Release
from releases.services import get_active_release
from wp_utils import is_platform_admin_full

BUNDLE_CACHE_KEY = "runtime_bundle:{app_code}"
BUNDLE_TTL = 600


def _public_cache(response, max_age: int = 60):
    """公开运行时内容允许 CDN/浏览器短缓存；草稿/私有接口不要调用。"""
    response["Cache-Control"] = f"public, max-age={max_age}, stale-while-revalidate=300"
    return response


def _get_app_by_code(app_code: str) -> App:
    from django.shortcuts import get_object_or_404

    return get_object_or_404(App.objects.select_related("owner"), code=app_code)


def _select_release(app: App) -> Release | None:
    """active release；灰度：traffic_ratio<100 且存在 previous 时按比例随机取前/后版本。"""
    import random

    release = get_active_release(app)
    if release is None:
        return None
    if release.traffic_ratio < 100 and release.previous_release_id:
        prev = Release.objects.filter(id=release.previous_release_id).first()
        if prev is not None and prev.bundle_url and random.random() * 100 > release.traffic_ratio:
            return prev
    return release


def _bundle_for_app(app: App) -> dict | None:
    """从对象存储读取生效 release 的 bundle JSON（灰度期间不缓存）。"""
    release = _select_release(app)
    if release is None or not release.bundle_url:
        return None
    grayscale = release.traffic_ratio < 100 and bool(release.previous_release_id)
    # 缓存键必须带 release id：否则新发布后仍会命中旧 bundle，最长 10 分钟。
    bundle_cache_key = f"{BUNDLE_CACHE_KEY.format(app_code=app.code)}:{release.id}"
    if not grayscale:
        cached = cache.get(bundle_cache_key)
        if cached is not None:
            return cached
    key = release.bundle_url
    if settings.MEDIA_URL and key.startswith(settings.MEDIA_URL):
        key = key[len(settings.MEDIA_URL):]
    try:
        with default_storage.open(key, "rb") as fh:
            bundle = json.loads(fh.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    out = {
        "app": {"id": app.id, "name": app.name, "code": app.code},
        "release": {"id": release.id, "version": release.version, "traffic_ratio": release.traffic_ratio},
        "pages": bundle.get("pages", {}),
    }
    if not grayscale:
        cache.set(bundle_cache_key, out, BUNDLE_TTL)
    return out


def _resolve_page_path(pages: dict, path: str):
    """返回 (bundle_key, route_params)。支持 article/:id、news/:category/*splat。"""
    if path in pages:
        return path, {}
    dynamic = [key for key in pages if ":" in key or "*" in key]
    dynamic.sort(key=lambda key: (-len(key), key))
    for key in dynamic:
        parts = []
        for segment in key.strip("/").split("/"):
            if segment.startswith(":") and len(segment) > 1:
                parts.append(f"(?P<{segment[1:]}>[^/]+)")
            elif segment == "*":
                parts.append(r"(?P<splat>.*)")
            else:
                parts.append(re.escape(segment))
        matched = re.fullmatch("/".join(parts), path)
        if matched:
            return key, matched.groupdict()
    return None, {}


def _article_node(page_data: dict):
    for node in ((page_data or {}).get("schema") or {}).get("nodes", {}).values():
        if isinstance(node, dict) and node.get("type") == "article-detail":
            return node
    return None


def _base_url(request) -> str:
    return (request.headers.get("Origin") or settings.FRONTEND_URL).rstrip("/")


def _article_path_pattern(data: dict) -> str | None:
    for path, page_data in (data.get("pages") or {}).items():
        if ":id" in path and _article_node(page_data):
            return path
    return None


def _safe_content(html: str) -> str:
    html = re.sub(r"(?is)<(script|iframe|object|embed)\b.*?</\1>", "", str(html or ""))
    html = re.sub(r"(?is)\son\w+\s*=\s*(['\"]).*?\1", "", html)
    return html


def _render_context(request, app: App, data: dict, page_path: str):
    from datamodels.models import DataModel, DataRecord
    from datamodels.services import publish_due_records

    page_key, route_params = _resolve_page_path(data["pages"], page_path)
    if page_key is None:
        return None
    page_data = data["pages"][page_key]
    base = _base_url(request)
    canonical = f"{base}/run/{app.code}/{page_path.strip('/')}"
    node = _article_node(page_data)
    record = None
    model = None
    if node:
        try:
            model_id = int((node.get("props") or {}).get("dataModelId") or 0)
        except (TypeError, ValueError):
            model_id = 0
        model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
        record_id = route_params.get("id") or route_params.get("pk")
        if model is not None and str(record_id or "").isdigit():
            publish_due_records(model)
            record = DataRecord.objects.filter(model=model, id=int(record_id)).first()
            if record is not None and "status" in {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}:
                if (record.data or {}).get("status") != "published":
                    record = None

    meta = (page_data or {}).get("meta") or {}
    title = str(meta.get("title") or (page_data or {}).get("name") or app.name)
    description = str(meta.get("description") or "")
    image = ""
    author = ""
    published_at = ""
    category = ""
    content = ""
    if record:
        row = record.data or {}
        title = str(row.get("title") or row.get("name") or title)
        description = str(row.get("summary") or row.get("description") or description)
        image = str(row.get("cover") or row.get("image") or "")
        author = str(row.get("author") or "")
        published_at = str(row.get("published_at") or "")
        category = str(row.get("category") or row.get("category_slug") or "")
        content = _safe_content(str(row.get("content") or ""))
    if not content:
        content = f"<p>{description}</p>" if description else ""
    jsonld = ""
    if record:
        import json as _json

        jsonld = _json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": title,
                "description": description,
                "image": image or None,
                "datePublished": published_at or None,
                "author": {"@type": "Person", "name": author} if author else None,
                "mainEntityOfPage": canonical,
            },
            ensure_ascii=False,
        )
    return {
        "lang": "zh-CN",
        "app_name": app.name,
        "title": title,
        "description": description,
        "canonical": canonical,
        "image": image,
        "author": author,
        "published_at": published_at,
        "category": category,
        "content": content,
        "jsonld": jsonld,
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_prerender(request, app_code: str, page_path: str):
    """服务端 SEO HTML：优先返回 SSR 快照（完整水合页），否则回退轻量模板。"""
    app = _get_app_by_code(app_code)
    clean_path = page_path.strip("/")
    snapshot = _snapshot_file(app.code, clean_path)
    if snapshot is not None:
        try:
            return _public_cache(HttpResponse(snapshot.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8"), 60)
        except OSError:
            pass
    data = _bundle_for_app(app)
    if data is None:
        raise NotFound("该应用还没有生效的发布")
    context = _render_context(request, app, data, clean_path)
    if context is None:
        raise NotFound("页面不存在")
    html = render_to_string("runtime/prerender.html", context, request=request)
    return _public_cache(HttpResponse(html, content_type="text/html; charset=utf-8"), 60)


def _snapshot_file(app_code: str, page_path: str):
    """PRERENDER_DIR/{app}/{path}/index.html；阻止路径穿越。"""
    from pathlib import Path

    base = Path(getattr(settings, "PRERENDER_DIR", "")).resolve()
    target = (base / app_code / page_path / "index.html").resolve()
    if base not in target.parents:
        return None
    return target if target.is_file() else None


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def runtime_ssr_rebuild(request, app_code: str):
    """POST /api/runtime/{app_code}/ssr/rebuild/ — 生成该应用页面的 SSR 快照。"""
    from pathlib import Path

    from pages.models import Page
    from runtime.ssr import page_targets, write_snapshot

    app = _get_app_by_code(app_code)
    _require_member(request.user, app, "owner")
    output = Path(getattr(settings, "PRERENDER_DIR", ""))
    results, errors = [], []
    for page in Page.objects.filter(app=app, status="published").exclude(type="fragment")[:50]:
        targets = page_targets(page)
        if not targets:
            continue
        for target in targets:
            try:
                result = write_snapshot(app, target, output)
                if result:
                    results.append(result)
                else:
                    errors.append({"path": target, "error": "SSR 渲染失败（检查前端 dist-ssr 产物）"})
            except Exception as exc:  # noqa: BLE001
                errors.append({"path": target, "error": str(exc)})
    return Response({"ok": not errors, "generated": results, "errors": errors})


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_search(request, app_code: str):
    """公开内容全局搜索（走搜索索引）：标题/摘要/正文，返回可直接跳转的详情 URL。"""
    from search.models import SearchDocument
    from search.services import rebuild_app, search_documents

    app = _get_app_by_code(app_code)
    q = str(request.query_params.get("q") or "").strip()
    base = _base_url(request)
    model_id = request.query_params.get("model_id")
    try:
        page = max(1, int(request.query_params.get("page") or 1))
        size = min(50, max(1, int(request.query_params.get("size") or 20)))
    except (TypeError, ValueError):
        page, size = 1, 20
    if len(q) < 1:
        return _public_cache(Response({"q": q, "count": 0, "results": [], "page": page, "size": size}), 30)
    # 首次访问或重建后为空时惰性建索引，避免老数据搜不到。
    if not SearchDocument.objects.filter(app=app).exists():
        try:
            rebuild_app(app)
        except Exception:
            pass
    data = search_documents(
        app, q, model_id=int(model_id) if model_id else None,
        limit=size, offset=(page - 1) * size, base_url=base,
    )
    return _public_cache(Response({**data, "page": page, "size": size}), 30)


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_suggest(request, app_code: str):
    """公开搜索联想：GET /api/runtime/{app}/search/suggest/?q="""
    from search.services import suggest

    app = _get_app_by_code(app_code)
    base = _base_url(request)
    rows = suggest(app, request.query_params.get("q") or "")
    for row in rows:
        row["url"] = f"{base}/run/{app.code}/{row.pop('url_path', '').strip('/')}"
    return _public_cache(Response({"results": rows}), 30)


def _require_member(user, app: App, min_role: str = "viewer"):
    from core.permissions import ROLE_ORDER, get_app_role

    role = get_app_role(user, app)
    if role is None:
        role = "owner" if is_platform_admin_full(user) else None
    if role is None or ROLE_ORDER.get(role, 0) < ROLE_ORDER.get(min_role, 0):
        raise PermissionDenied("需要应用成员权限")
    return role


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_root(request, app_code: str | None = None):
    """GET /api/runtime/{app_code}/ — 当前生效 bundle（匿名可用）。"""
    if not app_code:
        raise NotFound("缺少 app_code")
    app = _get_app_by_code(app_code)
    data = _bundle_for_app(app)
    if data is None:
        raise NotFound("该应用还没有生效的发布")
    return _public_cache(Response(data), 120)


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_sitemap(request, app_code: str):
    """静态页面 sitemap；动态路由页面由内容列表自行生成链接。"""
    from xml.sax.saxutils import escape

    app = _get_app_by_code(app_code)
    data = _bundle_for_app(app)
    if data is None:
        raise NotFound("该应用还没有生效的发布")
    base = (request.headers.get("Origin") or settings.FRONTEND_URL).rstrip("/")
    urls = []
    for path in sorted(data["pages"].keys()):
        if ":" in path or "*" in path:
            continue
        loc = f"{base}/run/{app.code}/{path.strip('/')}"
        urls.append(f"<url><loc>{escape(loc)}</loc></url>")

    # 内容详情页：从 article/:id 模板的 article-detail 节点反查公开模型记录。
    article_model_ids = set()
    article_pattern = None
    for path, page_data in (data.get("pages") or {}).items():
        if ":id" not in path:
            continue
        for node in ((page_data or {}).get("schema") or {}).get("nodes", {}).values():
            if not isinstance(node, dict) or node.get("type") != "article-detail":
                continue
            try:
                model_id = int((node.get("props") or {}).get("dataModelId") or 0)
            except (TypeError, ValueError):
                model_id = 0
            if model_id:
                article_model_ids.add(model_id)
                article_pattern = article_pattern or path
    if article_model_ids and article_pattern:
        from datamodels.models import DataModel, DataRecord

        for model in DataModel.objects.filter(app=app, id__in=article_model_ids, is_public=True):
            records = DataRecord.objects.filter(model=model)
            for record in records:
                if "status" in {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}:
                    if (record.data or {}).get("status") != "published":
                        continue
                record_id = record.id
                loc = f"{base}/run/{app.code}/{article_pattern.replace(':id', str(record_id)).strip('/')}"
                urls.append(f"<url><loc>{escape(loc)}</loc></url>")

    xml = '<?xml version="1.0" encoding="UTF-8"?>' + '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
    from django.http import HttpResponse

    return _public_cache(HttpResponse(xml, content_type="application/xml; charset=utf-8"), 300)


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_content_list(request, app_code: str, model_id: int):
    """公开内容读取：仅 is_public 数据模型，支持 page/size/sort/search 与字段过滤。"""
    from datamodels.models import DataModel
    from datamodels.services import dynamic_query, paginate_rows, publish_due_records

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    publish_due_records(model)
    params = {k: request.query_params.get(k) for k in request.query_params}
    rows = dynamic_query(model, params)
    field_names = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    if "status" in field_names:
        rows = [r for r in rows if (r.get("data") or {}).get("status") == "published"]
    return _public_cache(Response(paginate_rows(rows, request)), 60)


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_content_report(request, app_code: str, model_id: int):
    """公开聚合：GET /api/runtime/{app}/content/{model}/report/?group_by=&metrics=&limit=。"""
    from datamodels.models import DataModel
    from datamodels.services import dynamic_query, publish_due_records

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    publish_due_records(model)
    params = {k: request.query_params.get(k) for k in request.query_params}
    group_by = str(params.pop("group_by", "") or "").strip()
    group_by2 = str(params.pop("group_by2", "") or "").strip()
    metrics_raw = str(params.pop("metrics", "count") or "count")
    try:
        limit = min(500, max(1, int(params.pop("limit", 200) or 200)))
    except (TypeError, ValueError):
        limit = 200
    rows = dynamic_query(model, params)
    field_names = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    if "status" in field_names:
        rows = [r for r in rows if (r.get("data") or {}).get("status") == "published"]

    metrics: list[tuple[str, str | None]] = []
    for item in metrics_raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            fn, field = item.split(":", 1)
            metrics.append((fn.strip(), field.strip()))
        else:
            metrics.append((item, None))

    def number(value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    groups: dict[tuple[str, str], dict] = {}
    for row in rows:
        data = row.get("data") or {}
        key = str(data.get(group_by, "")) if group_by else "全部"
        key2 = str(data.get(group_by2, "")) if group_by2 else ""
        bucket = groups.setdefault((key, key2), {"key": key, "key2": key2, "count": 0, "_sum": {}, "_values": {}})
        bucket["count"] += 1
        for fn, field in metrics:
            if not field:
                continue
            value = data.get(field)
            n = number(value)
            if fn in ("sum", "avg", "min", "max") and n is not None:
                bucket["_sum"][field] = bucket["_sum"].get(field, 0) + n
                bucket["_values"].setdefault(field, []).append(n)
            if fn == "count_distinct":
                bucket["_values"].setdefault(field, [])
                if value not in bucket["_values"][field]:
                    bucket["_values"][field].append(value)

    out_rows = []
    for bucket in groups.values():
        out = {"key": bucket["key"], "count": bucket["count"]}
        if group_by2:
            out["key2"] = bucket["key2"]
        for fn, field in metrics:
            if fn == "count" and not field:
                out["count"] = bucket["count"]
            elif field and fn in ("sum", "avg", "min", "max", "count_distinct"):
                alias = f"{fn}_{field}"
                if fn == "sum":
                    out[alias] = round(bucket["_sum"].get(field, 0), 2)
                elif fn == "avg":
                    vals = bucket["_values"].get(field, [])
                    out[alias] = round(sum(vals) / len(vals), 2) if vals else 0
                elif fn == "min":
                    vals = bucket["_values"].get(field, [])
                    out[alias] = min(vals) if vals else None
                elif fn == "max":
                    vals = bucket["_values"].get(field, [])
                    out[alias] = max(vals) if vals else None
                elif fn == "count_distinct":
                    out[alias] = len(bucket["_values"].get(field, []))
        out_rows.append(out)
    sort_alias = next((f"{fn}_{field}" for fn, field in metrics
                       if field and fn in ("sum", "avg", "min", "max", "count_distinct")), "")
    if sort_alias:
        out_rows.sort(key=lambda r: (-(float(r.get(sort_alias) or 0)), str(r.get("key", ""))))
    else:
        out_rows.sort(key=lambda r: (-int(r.get("count", 0)), str(r.get("key", "")), str(r.get("key2", ""))))
    out_rows = out_rows[:limit]
    cross_columns: list[str] = []
    cross = None
    if group_by2:
        columns = sorted({str(r.get("key2", "")) for r in out_rows})
        cross_columns = [c for c in columns if c] or [""]
        matrix: dict[str, dict] = {}
        for r in out_rows:
            key = str(r.get("key", ""))
            row = matrix.setdefault(key, {"key": key})
            row[str(r.get("key2", ""))] = r.get("count")
        cross = list(matrix.values())
    return _public_cache(Response({
        "group_by": group_by,
        "group_by2": group_by2,
        "metrics": metrics_raw,
        "cross_metric": sort_alias or "count",
        "cross_columns": cross_columns,
        "cross": cross,
        "count": len(rows),
        "rows": out_rows,
        "fields": [f.get("name") for f in (model.fields or []) if isinstance(f, dict)],
    }), 30)


def _public_form_access(app, model) -> dict:
    from pages.models import Page

    access = {
        "allowed": False, "require_captcha": False, "foreign_key": "", "master_model_id": 0,
        "master_key_field": "id", "forward_datasource_id": 0,
    }
    for page in Page.objects.filter(app=app, status="published"):
        schema = page.schema or {}
        meta = schema.get("meta") or {}
        if not meta.get("allowPublicSubmit"):
            continue
        for node in (schema.get("nodes") or {}).values():
            if not isinstance(node, dict):
                continue
            props = node.get("props") or {}
            if node.get("type") == "auto-form" and int(props.get("modelId") or 0) == model.id:
                access["allowed"] = True
                access["require_captcha"] = access["require_captcha"] or bool(meta.get("requireCaptcha"))
                try:
                    access["forward_datasource_id"] = int(meta.get("forwardDatasourceId") or 0)
                except (TypeError, ValueError):
                    access["forward_datasource_id"] = 0
            if node.get("type") == "public-master-detail":
                for relation in props.get("relations") or []:
                    if isinstance(relation, dict) and int(relation.get("modelId") or 0) == model.id:
                        access["allowed"] = True
                        access["require_captcha"] = access["require_captcha"] or bool(meta.get("requireCaptcha"))
                        access["foreign_key"] = str(relation.get("foreignKey") or "")
                        access["master_model_id"] = int(props.get("masterModelId") or 0)
                        access["master_key_field"] = str(props.get("masterKeyField") or "id")
                        try:
                            access["forward_datasource_id"] = int(meta.get("forwardDatasourceId") or 0)
                        except (TypeError, ValueError):
                            access["forward_datasource_id"] = 0
    return access


def _notify_public_submission(app, model, record) -> None:
    """公开表单提交通知：邮件 + IM Webhook，失败不影响主流程。"""
    from django.conf import settings
    from django.core.mail import send_mail

    owner = getattr(app, "owner", None)
    title = f"[{app.name}] 新的公开提交：{model.name}"
    body = f"记录 ID：{record.id}\n模型：{model.name}\n状态：{(record.data or {}).get('status') or 'received'}\n"
    email = str(getattr(owner, "email", "") or "")
    if email and getattr(settings, "EMAIL_HOST", ""):
        try:
            send_mail(title, body, getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
                      [email], fail_silently=True)
        except Exception:
            pass
    webhook = str(getattr(settings, "FORM_NOTIFY_WEBHOOK", "") or "")
    if webhook:
        import json
        import urllib.request

        payload = {"msgtype": "text", "text": {"content": f"{title}\n{body}"}}
        try:
            request = urllib.request.Request(
                webhook, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(request, timeout=4).close()
        except Exception:
            pass


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_form_challenge(request, app_code: str, model_id: int):
    """GET /api/runtime/{app}/content/{model}/challenge/ — 公开表单算术验证。"""
    import secrets

    from datamodels.models import DataModel

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    access = _public_form_access(app, model)
    if not access["allowed"] or not access["require_captcha"]:
        return Response({"required": False, "token": "", "question": ""})
    a = secrets.randbelow(8) + 1
    b = secrets.randbelow(8) + 1
    token = secrets.token_urlsafe(18)
    cache.set(f"form_captcha:{token}", str(a + b), 300)
    return _public_cache(Response({"required": True, "token": token, "question": f"{a} + {b} = ?"}), 0)


@api_view(["POST"])
@permission_classes([AllowAny])
def runtime_content_submit(request, app_code: str, model_id: int):
    """公开表单提交：仅允许已发布表单页声明的公开模型，默认写入待审核状态。"""
    from datamodels.models import DataRecord, DataModel

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")

    access = _public_form_access(app, model)
    if not access["allowed"]:
        raise PermissionDenied("该表单未开放公开提交")
    if access["require_captcha"]:
        token = str(request.data.get("_captcha_token") or "")
        answer = str(request.data.get("_captcha_answer") or "").strip()
        expected = cache.get(f"form_captcha:{token}") if token else None
        if expected is None or answer != str(expected):
            raise ValidationError({"detail": "验证码错误或已过期，请刷新后重试"})
        cache.delete(f"form_captcha:{token}")

    if str(request.data.get("_hp") or "").strip():
        return Response({"ok": True, "status": "received"}, status=201)

    ip = request.META.get("REMOTE_ADDR") or "unknown"
    key = f"public_submit:{app.id}:{model.id}:{ip}"
    count = int(cache.get(key) or 0)
    if count >= 5:
        raise PermissionDenied("提交过于频繁，请稍后再试")
    cache.set(key, count + 1, 60)

    fields = [field for field in (model.fields or []) if isinstance(field, dict) and field.get("name")]
    allowed_names = {str(field["name"]) for field in fields}
    data: dict = {}
    for field in fields:
        name = str(field["name"])
        if name in ("id", "created_at", "updated_at"):
            continue
        if name in request.data:
            data[name] = request.data.get(name)
        elif field.get("required") and name != "status":
            raise ValidationError({"detail": f"{field.get('label') or name} 必填"})
    if "status" in allowed_names:
        data["status"] = "pending"
    if access["foreign_key"]:
        parent_value = request.data.get(access["foreign_key"])
        if parent_value in (None, ""):
            raise ValidationError({"detail": "缺少主记录标识"})
        data[access["foreign_key"]] = parent_value
        if access["master_model_id"]:
            master_model = DataModel.objects.filter(app=app, id=access["master_model_id"]).first()
            if master_model is not None:
                found = any(
                    str((item.data or {}).get(access["master_key_field"])) == str(parent_value)
                    for item in DataRecord.objects.filter(model=master_model).order_by("-id")[:1000]
                )
                if not found:
                    raise ValidationError({"detail": "主记录不存在或已失效"})
    if not data:
        raise ValidationError({"detail": "没有可提交的字段"})
    for key_name in list(data):
        if key_name not in allowed_names:
            data.pop(key_name, None)
    record = DataRecord.objects.create(model=model, data=data)
    if model.review_required:
        try:
            from moderation.services import submit as submit_review

            submit_review(record, user=None, comment="公开表单提交")
        except Exception:
            pass
    _notify_public_submission(app, model, record)
    try:
        from django.core import signing

        public_token = signing.dumps({"m": model.id, "r": record.id}, salt="public-record")
    except Exception:
        public_token = ""
    try:
        from audit.models import AuditLog

        AuditLog.objects.create(
            username="public", app=app, object_type="datarecord", object_id=str(record.id),
            action="runtime.public_submit", ip=ip,
            after={"model_id": model.id, "model": model.name, "status": data.get("status") or "received"},
        )
    except Exception:
        pass
    forward = {"ok": False, "skipped": True, "error": ""}
    forward_id = int(access.get("forward_datasource_id") or 0)
    if forward_id:
        from datasources.executor import run_datasource
        from datasources.models import Datasource

        datasource = Datasource.objects.filter(
            app=app, id=forward_id, type="rest", status="active",
        ).first()
        params = {
            **data,
            "record_id": record.id,
            "model_id": model.id,
            "request_id": f"{app.code}:{model.id}:{record.id}",
        }
        if datasource is None:
            forward = {"ok": False, "skipped": False, "error": "转发数据源不存在、未启用或不是 REST"}
        else:
            try:
                result = run_datasource(datasource, params, is_test=False)
                forward = {
                    "ok": bool(result.get("ok")),
                    "skipped": False,
                    "status": result.get("status"),
                    "error": "" if result.get("ok") else str(result.get("error") or "第三方返回失败"),
                }
            except Exception as exc:  # noqa: BLE001
                forward = {"ok": False, "skipped": False, "error": str(exc)[:300]}
            try:
                from audit.models import AuditLog

                AuditLog.objects.create(
                    username="public", app=app, object_type="datarecord", object_id=str(record.id),
                    action="runtime.public_forward", ip=ip,
                    after={"datasource_id": forward_id, "ok": forward["ok"], "error": forward.get("error", "")},
                )
            except Exception:
                pass
    return Response({
        "ok": True, "id": record.id, "status": data.get("status") or "received",
        "public_token": public_token, "forward": forward,
    }, status=201)


def _load_public_record(app, model, token: str, record_id: int):
    from django.core import signing

    from datamodels.models import DataRecord

    try:
        payload = signing.loads(token, salt="public-record", max_age=7 * 24 * 3600)
    except Exception as exc:  # noqa: BLE001
        raise PermissionDenied("编辑凭证无效或已过期") from exc
    if int(payload.get("m") or 0) != model.id or int(payload.get("r") or 0) != record_id:
        raise PermissionDenied("编辑凭证与记录不匹配")
    record = DataRecord.objects.filter(model=model, id=record_id).first()
    if record is None:
        raise NotFound("内容不存在")
    if getattr(record, "public_token_revoked", False):
        raise PermissionDenied("编辑凭证已吊销")
    return record


@api_view(["POST"])
@permission_classes([AllowAny])
def runtime_content_update(request, app_code: str, model_id: int, pk: int):
    """公开凭证更新：仅创建者持有的签名 token 可改自己提交的记录。"""
    from datamodels.models import DataModel
    from django.core import signing

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    access = _public_form_access(app, model)
    if not access["allowed"]:
        raise PermissionDenied("该内容未开放公开编辑")
    token = str(request.data.get("public_token") or "")
    record = _load_public_record(app, model, token, pk)
    fields = [field for field in (model.fields or []) if isinstance(field, dict) and field.get("name")]
    allowed_names = {str(field["name"]) for field in fields}
    data = dict(record.data or {})
    for field in fields:
        name = str(field["name"])
        if name in ("id", "created_at", "updated_at"):
            continue
        if name in request.data:
            data[name] = request.data.get(name)
    if "status" in allowed_names:
        data["status"] = "pending"
    record.data = data
    record.updated_by = None
    record.save(update_fields=["data", "updated_at"])
    if model.review_required:
        try:
            from moderation.services import submit as submit_review

            submit_review(record, user=None, comment="公开表单修改")
        except Exception:
            pass
    try:
        from audit.models import AuditLog

        AuditLog.objects.create(
            username="public", app=app, object_type="datarecord", object_id=str(record.id),
            action="runtime.public_update", ip=request.META.get("REMOTE_ADDR") or "unknown",
            after={"model_id": model.id, "model": model.name, "status": data.get("status") or "received"},
        )
    except Exception:
        pass
    return Response({"ok": True, "id": record.id, "public_token": token})


@api_view(["POST"])
@permission_classes([AllowAny])
def runtime_content_delete(request, app_code: str, model_id: int, pk: int):
    """公开凭证删除：仅创建者持有的签名 token 可删自己提交的记录。"""
    from datamodels.models import DataModel

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    access = _public_form_access(app, model)
    if not access["allowed"]:
        raise PermissionDenied("该内容未开放公开删除")
    token = str(request.data.get("public_token") or "")
    record = _load_public_record(app, model, token, pk)
    record_id = record.id
    record.delete()
    try:
        from audit.models import AuditLog

        AuditLog.objects.create(
            username="public", app=app, object_type="datarecord", object_id=str(record_id),
            action="runtime.public_delete", ip=request.META.get("REMOTE_ADDR") or "unknown",
            after={"model_id": model.id, "model": model.name},
        )
    except Exception:
        pass
    return Response({"ok": True, "id": record_id})


@api_view(["POST"])
@permission_classes([AllowAny])
def runtime_content_revoke_token(request, app_code: str, model_id: int, pk: int):
    """POST /api/runtime/{app}/content/{model}/{pk}/revoke-token/ {public_token}"""
    from datamodels.models import DataModel

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    access = _public_form_access(app, model)
    if not access["allowed"]:
        raise PermissionDenied("该内容未开放公开编辑")
    token = str(request.data.get("public_token") or "")
    record = _load_public_record(app, model, token, pk)
    record.public_token_revoked = True
    record.save(update_fields=["public_token_revoked", "updated_at"])
    try:
        from audit.models import AuditLog

        AuditLog.objects.create(
            username="public",
            app=app,
            object_type="datarecord",
            object_id=str(record.id),
            action="runtime.public_token_revoke",
            ip=request.META.get("REMOTE_ADDR") or "unknown",
            after={"model_id": model.id, "model": model.name},
        )
    except Exception:
        pass
    return Response({"ok": True, "id": record.id})


def _mask_join_value(field: str, value):
    if value is None or value == "":
        return value
    text = str(value)
    name = field.lower()
    if "email" in name or "邮箱" in name:
        if "@" in text:
            local, domain = text.split("@", 1)
            return f"{local[:1]}***@{domain}"
        return "***"
    if "phone" in name or "mobile" in name or "手机" in name:
        return text[:3] + "****" + text[-4:] if len(text) >= 8 else "***"
    if "id_card" in name or "identity" in name or "身份证" in name:
        return text[:4] + "**********" + text[-4:] if len(text) >= 10 else "***"
    if "address" in name or "地址" in name or "contact" in name:
        return text[:6] + "****" if len(text) > 6 else "***"
    return "***"


def _apply_join_mask(rows: list[dict], mask_fields: set[str], columns: list[dict]) -> list[dict]:
    import re

    sensitive = re.compile(r"(phone|mobile|email|id_card|identity|address|contact|手机|邮箱|身份证|地址)", re.I)
    fields = {field for field in mask_fields}
    for column in columns:
        prop = str(column.get("prop") or "")
        if sensitive.search(prop):
            fields.add(prop)
    if not fields:
        return rows
    return [
        {key: (_mask_join_value(key, value) if key in fields else value) for key, value in row.items()}
        for row in rows
    ]


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_content_join(request, app_code: str, master_id: int, child_id: int):
    """公开 JOIN 聚合：主表 + 多级子表按业务键合并成宽表，支持筛选/排序/导出。"""
    import csv
    import io
    import json as _json

    from datamodels.models import DataModel, DataRecord
    from pages.models import Page

    app = _get_app_by_code(app_code)
    master = DataModel.objects.filter(app=app, pk=master_id, is_public=True).first()
    child = DataModel.objects.filter(app=app, pk=child_id, is_public=True).first()
    if master is None or child is None:
        raise NotFound("公开内容模型不存在")
    foreign_key = str(request.query_params.get("foreign_key") or "").strip()
    master_key = str(request.query_params.get("master_key") or "id").strip() or "id"
    raw_relations = request.query_params.get("relations")
    steps: list[dict] = []
    if raw_relations:
        try:
            parsed = _json.loads(raw_relations)
            if isinstance(parsed, list):
                steps = [item for item in parsed if isinstance(item, dict) and item.get("modelId") and item.get("foreignKey")]
        except Exception:
            steps = []
    if not steps:
        if not foreign_key:
            raise ValidationError({"detail": "foreign_key 必填"})
        steps = [{"modelId": child.id, "foreignKey": foreign_key, "parentKey": master_key}]
    if not steps[0].get("parentKey"):
        steps[0]["parentKey"] = master_key

    allowed = False
    mask_fields: set[str] = set()
    for page in Page.objects.filter(app=app, status="published"):
        for node in ((page.schema or {}).get("nodes") or {}).values():
            if not isinstance(node, dict) or node.get("type") != "public-master-detail":
                continue
            props = node.get("props") or {}
            if int(props.get("masterModelId") or 0) != master.id:
                continue
            for relation in props.get("relations") or []:
                if int((relation or {}).get("modelId") or 0) == int(steps[0]["modelId"]) and str((relation or {}).get("foreignKey")) == str(steps[0]["foreignKey"]):
                    allowed = True
    if not allowed:
        raise PermissionDenied("该 JOIN 视图未公开")

    # JOIN 页组件上声明的脱敏字段（服务端强制）
    for page in Page.objects.filter(app=app, status="published"):
        for node in ((page.schema or {}).get("nodes") or {}).values():
            if not isinstance(node, dict) or node.get("type") != "public-join-table":
                continue
            props = node.get("props") or {}
            if int(props.get("masterModelId") or 0) == master.id:
                mask_fields.update(str(item) for item in (props.get("maskFields") or []) if item)

    models = [master]
    for step in steps[:3]:
        model = DataModel.objects.filter(app=app, pk=int(step["modelId"]), is_public=True).first()
        if model is None:
            raise ValidationError({"detail": "多级关系中存在不可公开访问的模型"})
        models.append(model)

    columns = [
        {"prop": str(field.get("name")), "label": str(field.get("name"))}
        for field in (master.fields or []) if isinstance(field, dict) and str(field.get("name")) != "content"
    ]
    prefixes = ["child_", "grandchild_", "level3_"]
    for index, model in enumerate(models[1:]):
        prefix = prefixes[index] if index < len(prefixes) else f"level{index + 2}_"
        for field in model.fields or []:
            if isinstance(field, dict) and str(field.get("name")) != "content":
                columns.append({"prop": f"{prefix}{field.get('name')}", "label": f"子表{index + 1}.{field.get('name')}"})

    masters = list(DataRecord.objects.filter(model=master).order_by("-id")[:500])
    rows: list[dict] = [dict(item.data or {}) for item in masters]
    for depth, step in enumerate(steps[:3]):
        model = models[depth + 1]
        parent_key = str(step.get("parentKey") or ("id" if depth == 0 else "id"))
        prefix = prefixes[depth] if depth < len(prefixes) else f"level{depth + 2}_"
        previous_prefix = prefixes[depth - 1] if depth > 0 else ""
        child_rows = list(DataRecord.objects.filter(model=model).order_by("-id")[:2000])
        grouped: dict[str, list[dict]] = {}
        for item in child_rows:
            payload = item.data or {}
            grouped.setdefault(str(payload.get(step["foreignKey"])), []).append(payload)
        child_fields = [
            str(field.get("name")) for field in (model.fields or [])
            if isinstance(field, dict) and str(field.get("name")) != "content"
        ]
        next_rows = []
        for row in rows:
            parent_value = row.get(f"{previous_prefix}{parent_key}" if depth > 0 else parent_key)
            matches = grouped.get(str(parent_value)) or [{}]
            for payload in matches:
                merged = dict(row)
                for field_name in child_fields:
                    merged[f"{prefix}{field_name}"] = payload.get(field_name)
                next_rows.append(merged)
        rows = next_rows[:2000]

    for row in rows:
        for key_name in list(row):
            if key_name == "content" or key_name.endswith("_content"):
                row.pop(key_name, None)

    query = str(request.query_params.get("q") or "").strip().lower()
    if query:
        rows = [row for row in rows if any(query in str(value).lower() for value in row.values())]
    for key, value in request.query_params.items():
        if not key.startswith("filter_"):
            continue
        expression = key[len("filter_"):]
        if not expression:
            continue
        if "__" in expression:
            field, operator = expression.split("__", 1)
        else:
            field, operator = expression, "eq"
        operator = operator.lower()
        wanted = str(value)

        def matches(row):
            actual = row.get(field)
            actual_text = str(actual if actual is not None else "")
            if operator in ("contains", "icontains"):
                return wanted.lower() in actual_text.lower()
            if operator == "startswith":
                return actual_text.startswith(wanted)
            if operator == "in":
                return actual_text in {part.strip() for part in wanted.split(",")}
            if operator == "ne":
                return actual_text != wanted
            if operator in ("gt", "gte", "lt", "lte"):
                try:
                    left, right = float(actual), float(wanted)
                except (TypeError, ValueError):
                    left, right = actual_text, wanted
                return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[operator]
            return actual_text == wanted

        rows = [row for row in rows if matches(row)]

    sort = str(request.query_params.get("sort") or "").strip()
    if sort:
        descending = sort.startswith("-")
        sort_field = sort[1:] if descending else sort

        def sort_key(row):
            value = row.get(sort_field)
            try:
                return (0, float(value))
            except (TypeError, ValueError):
                return (1, str(value or ""))

        rows.sort(key=sort_key, reverse=descending)

    rows = _apply_join_mask(rows, mask_fields, columns)

    if str(request.query_params.get("export") or "") in ("1", "true", "csv"):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([column["label"] for column in columns])
        for row in rows:
            writer.writerow([row.get(column["prop"], "") for column in columns])
        response = HttpResponse("\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="join-export.csv"'
        return response

    total = len(rows)
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    try:
        size = min(200, max(1, int(request.query_params.get("size") or 20)))
    except (TypeError, ValueError):
        size = 20
    start = (page - 1) * size
    return _public_cache(Response({
        "columns": columns,
        "rows": rows[start:start + size],
        "count": len(rows[start:start + size]),
        "total": total,
        "page": page,
        "size": size,
    }), 30)


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_content_detail(request, app_code: str, model_id: int, pk: int):
    from datamodels.models import DataModel, DataRecord
    from datamodels.serializers import DataRecordSerializer
    from datamodels.services import publish_due_records

    app = _get_app_by_code(app_code)
    model = DataModel.objects.filter(app=app, pk=model_id, is_public=True).first()
    if model is None:
        raise NotFound("公开内容模型不存在")
    publish_due_records(model)
    record = DataRecord.objects.filter(model=model, id=pk).first()
    if record is None:
        raise NotFound("内容不存在")
    field_names = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    if "status" in field_names and (record.data or {}).get("status") != "published":
        raise NotFound("内容未发布")
    return _public_cache(Response(DataRecordSerializer(record).data), 60)


def build_page_payload(app: App, page_path: str) -> dict:
    """运行时页面包：发布 bundle 中的 schema + 组件注册表 + 数据源公开配置。

    SSR 快照命令与 ``runtime_page`` 共用，保证服务端渲染与浏览器端拿到同一份数据。
    """
    from components.models import ComponentMeta
    from datasources.models import Datasource
    from datasources.serializers import _mask_config
    from pages.models import Page, PageVersion

    data = _bundle_for_app(app)
    if data is None:
        raise NotFound("该应用还没有生效的发布")
    page_key, route_params = _resolve_page_path(data["pages"], page_path)
    if page_key is None:
        raise NotFound(f"页面 {page_path} 不在当前发布中")
    page_data = data["pages"][page_key]
    if page_data is None:
        raise NotFound(f"页面 {page_path} 不在当前发布中")

    page = Page.objects.filter(app=app, path=page_key).first()
    from appcore.modules import enabled_module_map, module_enabled, module_for_path

    page_meta = (page_data.get("schema") or {}).get("meta") or {}
    page_module = str(page_meta.get("module") or module_for_path(page_key))
    if not module_enabled(app, page_module):
        raise PermissionDenied(f"模块未启用：{page_module}")
    published_at = None
    version = page_data.get("version")
    if page is not None:
        pv = PageVersion.objects.filter(page=page, version=version).order_by("-id").first()
        if pv is not None:
            published_at = pv.published_at
    components_qs = ComponentMeta.objects.filter(is_enabled=True).order_by("type", "name")
    components_out = [
        {
            "name": c.name,
            "label": c.label,
            "type": c.type,
            "category": c.category,
            "version": c.version,
            "icon": c.icon,
            "source": c.source,
            "element": c.element,
            "is_container": c.is_container,
            "is_form_field": c.is_form_field,
            "default_children": c.default_children or [],
            "actions_supported": c.actions_supported or [],
            "props_schema": c.props_schema,
            "style_schema": c.style_schema,
            "default_props": c.default_props,
            "events": c.events,
            "provides": c.provides or [],
            "consumes": c.consumes or [],
            "payload_schema": c.payload_schema or {},
            "slots": c.slots,
            "accept_children": c.accept_children,
        }
        for c in components_qs
    ]
    registry_map = {c["name"]: c["version"] for c in components_out}
    datasources_out = [
        {
            "id": ds.id,
            "name": ds.name,
            "type": ds.type,
            "public_config": _mask_config(ds.config or {}),
        }
        for ds in Datasource.objects.filter(app=app).order_by("id")
    ]
    return {
        "app": {"code": app.code, "name": app.name, "design_tokens": app.design_tokens or {}},
        "page": {
            "id": page.id if page else None,
            "name": page.name if page else page_key,
            "path": page_key,
            "resolved_path": page_path,
            "params": route_params,
        },
        "route_params": route_params,
        "page_version": {
            "version": version,
            "schema": page_data.get("schema"),
            "published_at": published_at,
        },
        "meta": (page_data.get("schema") or {}).get("meta") or {},
        "registry": registry_map,
        "style": (page_data.get("schema") or {}).get("customCss") or "",
        "config": {
            "components": components_out,
            "datasources": datasources_out,
            "modules": enabled_module_map(app),
        },
    }


@api_view(["GET"])
@permission_classes([AllowAny])
def runtime_page(request, app_code: str, page_path: str):
    """GET /api/runtime/{app_code}/{page_path}/ — 页面 schema；?draft=1 需 JWT。"""
    app = _get_app_by_code(app_code)
    if request.query_params.get("draft") in ("1", "true", "yes"):
        # 草稿模式：必须登录且为应用成员（editor 及以上可看未发布草稿）
        if not request.user or not request.user.is_authenticated:
            raise PermissionDenied("draft 模式需要 JWT 认证")
        _require_member(request.user, app, "viewer")
        from pages.models import Page

        page = Page.objects.filter(app=app, path=page_path).first()
        if page is None:
            raise NotFound("页面不存在")
        return Response(
            {
                "app": {"id": app.id, "name": app.name, "code": app.code},
                "path": page.path,
                "draft": True,
                "published": page.status == "published",
                "schema": page.schema,
                "schemaVersion": page.schema_version,
            }
        )
    data = build_page_payload(app, page_path)
    return _public_cache(Response(data), 60)
