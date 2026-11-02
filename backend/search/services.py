"""搜索索引服务：构建、增量更新、查询与建议。"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db.models import Count, Q
from django.utils import timezone

from datamodels.models import DataModel, DataRecord
from search.models import SearchDocument

TEXT_FIELDS = (
    "title", "name", "subject", "summary", "description", "content", "body", "tags", "category",
)
TITLE_FIELDS = ("title", "name", "subject")
SUMMARY_FIELDS = ("summary", "description")
MAX_BODY = 4000
ARTICLE_PATTERN_CACHE = "search:article_pattern:{app_id}"


def strip_html(value) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", str(value or ""))
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", text).strip()


def _field_text(data: dict, names: tuple[str, ...]) -> str:
    for name in names:
        value = (data or {}).get(name)
        if value:
            return strip_html(value)
    return ""


def _status_of(model: DataModel, data: dict) -> str:
    fields = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    if "status" in fields:
        return str((data or {}).get("status") or "")
    return ""


def _article_pattern(app_id: int) -> str:
    """从生效发布中找 article-detail 详情页路径模板（如 article/:id）。"""
    key = ARTICLE_PATTERN_CACHE.format(app_id=app_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    pattern = "article/{id}"
    try:
        from appcore.models import App
        from releases.services import get_active_release

        app = App.objects.filter(id=app_id).first()
        release = get_active_release(app) if app else None
        if release is not None and release.bundle_url:
            from django.conf import settings

            path = release.bundle_url
            if settings.MEDIA_URL and path.startswith(settings.MEDIA_URL):
                path = path[len(settings.MEDIA_URL):]
            with default_storage.open(path, "rb") as fh:
                bundle = json.loads(fh.read().decode("utf-8"))
            for page_path, page_data in (bundle.get("pages") or {}).items():
                if ":id" not in page_path:
                    continue
                for node in ((page_data or {}).get("schema") or {}).get("nodes", {}).values():
                    if isinstance(node, dict) and node.get("type") == "article-detail":
                        pattern = page_path
                        break
                if pattern != "article/{id}":
                    break
    except Exception:
        pass
    cache.set(key, pattern, 60)
    return pattern


def build_payload(record: DataRecord) -> dict:
    model = record.model
    data = record.data or {}
    title = _field_text(data, TITLE_FIELDS) or f"记录 #{record.id}"
    summary = _field_text(data, SUMMARY_FIELDS)[:300]
    body = strip_html(" ".join(str(data.get(name) or "") for name in TEXT_FIELDS if data.get(name)))[:MAX_BODY]
    status = _status_of(model, data)
    pattern = _article_pattern(model.app_id)
    url_path = pattern.replace(":id", str(record.id)).replace("{id}", str(record.id)).strip("/")
    is_published = (status == "published") if status else True
    digest = hashlib.sha1(f"{title}|{summary}|{body}|{status}".encode("utf-8")).hexdigest()
    return {
        "app_id": model.app_id,
        "model_id": model.id,
        "record_id": record.id,
        "title": title[:300],
        "summary": summary,
        "body": body,
        "url_path": url_path[:300],
        "model_name": model.name,
        "record_status": status[:40],
        "is_public": bool(model.is_public),
        "is_published": is_published,
        "content_hash": digest,
    }


def index_record(record: DataRecord, *, force: bool = False) -> SearchDocument | None:
    """写入/更新单条记录的索引。索引失败不应影响业务写入。"""
    try:
        payload = build_payload(record)
        doc = SearchDocument.objects.filter(
            app_id=payload["app_id"], model_id=payload["model_id"], record_id=payload["record_id"]
        ).first()
        if doc is not None and doc.content_hash == payload["content_hash"] and not force:
            return doc
        if doc is None:
            doc = SearchDocument.objects.create(**payload)
        else:
            for key, value in payload.items():
                setattr(doc, key, value)
            doc.save()
        return doc
    except Exception:
        import logging

        logging.getLogger("search").exception("index_record failed for record %s", getattr(record, "id", None))
        return None


def remove_record(record: DataRecord) -> None:
    SearchDocument.objects.filter(model_id=record.model_id, record_id=record.id).delete()


def rebuild_app(app, *, batch_size: int = 500) -> dict:
    """全量重建某应用的索引（先删后建，返回统计）。"""
    deleted, _ = SearchDocument.objects.filter(app=app).delete()
    created = 0
    rows: list[SearchDocument] = []
    for record in DataRecord.objects.filter(model__app=app).select_related("model").iterator(chunk_size=batch_size):
        payload = build_payload(record)
        rows.append(SearchDocument(**payload))
        if len(rows) >= batch_size:
            SearchDocument.objects.bulk_create(rows, ignore_conflicts=True)
            created += len(rows)
            rows.clear()
    if rows:
        SearchDocument.objects.bulk_create(rows, ignore_conflicts=True)
        created += len(rows)
    from django.core.cache import cache as _cache

    _cache.delete(ARTICLE_PATTERN_CACHE.format(app_id=app.id))
    return {"deleted": deleted, "created": created, "app_id": app.id, "app_code": app.code}


def rebuild_all() -> dict:
    from appcore.models import App

    total = {"deleted": 0, "created": 0, "apps": []}
    for app in App.objects.all():
        result = rebuild_app(app)
        total["deleted"] += result["deleted"]
        total["created"] += result["created"]
        total["apps"].append({"id": app.id, "code": app.code, **result})
    return total


# ---------------------------------------------------------------- 查询

def _query_terms(q: str) -> list[str]:
    text = str(q or "").strip().lower()
    if not text:
        return []
    if " " in text:
        return [t for t in re.split(r"\s+", text) if t]
    return [text]


def _bigrams(text: str) -> list[str]:
    chars = [c for c in text if not c.isspace()]
    if len(chars) <= 2:
        return ["".join(chars)] if chars else []
    return ["".join(chars[i:i + 2]) for i in range(len(chars) - 1)]


def _snippet(body: str, term: str, size: int = 90) -> str:
    if not body:
        return ""
    index = body.lower().find(term.lower())
    if index < 0:
        return body[:size] + ("…" if len(body) > size else "")
    start = max(0, index - size // 3)
    end = min(len(body), start + size)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return f"{prefix}{body[start:end]}{suffix}"


def _score(doc: SearchDocument, terms: list[str], phrase: str) -> float:
    title = (doc.title or "").lower()
    summary = (doc.summary or "").lower()
    body = (doc.body or "").lower()
    score = float(doc.score_base or 0)
    if phrase and phrase in title:
        score += 40
    elif phrase and phrase in summary:
        score += 14
    elif phrase and phrase in body:
        score += 6
    for term in terms:
        if not term:
            continue
        if term in title:
            score += 12
        if term in summary:
            score += 5
        if term in body:
            score += 2
    if doc.is_published:
        score += 3
    age = timezone.now() - (doc.updated_at or timezone.now())
    if age < timedelta(days=7):
        score += 2
    return score


def search_documents(
    app, q: str, *, model_id: int | None = None, limit: int = 20, offset: int = 0,
    include_private: bool = False, base_url: str = "",
):
    """返回 {count, results, q, took_ms}；结果按相关度排序。"""
    started = timezone.now()
    phrase = str(q or "").strip()
    if not phrase:
        return {"q": "", "count": 0, "results": []}
    qs = SearchDocument.objects.filter(app=app)
    if not include_private:
        qs = qs.filter(is_public=True, is_published=True)
    if model_id:
        qs = qs.filter(model_id=model_id)

    terms = _query_terms(phrase)
    lowered = phrase.lower()

    def _filter(rows_qs, needles):
        query = Q()
        for needle in needles:
            query |= Q(title__icontains=needle) | Q(summary__icontains=needle) | Q(body__icontains=needle)
        return rows_qs.filter(query)

    candidates = list(_filter(qs, terms)[:500])
    if len(candidates) < limit and not " " in phrase and len(phrase) > 2:
        grams = _bigrams(lowered)
        extra = [d for d in _filter(qs, grams)[:500] if d.id not in {c.id for c in candidates}]
        for doc in extra:
            haystack = f"{doc.title} {doc.summary} {doc.body}".lower()
            matched = sum(1 for g in grams if g in haystack)
            if matched >= max(1, int(len(grams) * 0.6)):
                candidates.append(doc)

    scored = [(doc, _score(doc, terms, lowered)) for doc in candidates]
    scored.sort(key=lambda pair: (pair[1], pair[0].updated_at), reverse=True)
    total = len(scored)
    window = scored[offset: offset + limit]
    results = []
    for doc, score in window:
        results.append({
            "type": "article",
            "id": doc.record_id,
            "record_id": doc.record_id,
            "model_id": doc.model_id,
            "model_name": doc.model_name,
            "title": doc.title,
            "summary": doc.summary,
            "snippet": _snippet(doc.body or doc.summary, lowered),
            "score": round(score, 2),
            "status": doc.record_status,
            "url": f"{base_url}/run/{app.code}/{doc.url_path}" if base_url else f"/run/{app.code}/{doc.url_path}",
            "updated_at": doc.updated_at,
        })
    took = int((timezone.now() - started).total_seconds() * 1000)
    return {"q": phrase, "count": total, "results": results, "took_ms": took}


def suggest(app, q: str, *, limit: int = 8) -> list[dict]:
    phrase = str(q or "").strip()
    if not phrase:
        return []
    rows = SearchDocument.objects.filter(
        app=app, is_public=True, is_published=True, title__icontains=phrase
    ).order_by("-updated_at")[:limit]
    return [{"id": d.record_id, "title": d.title, "url_path": d.url_path, "model_id": d.model_id} for d in rows]


def stats(app) -> dict:
    qs = SearchDocument.objects.filter(app=app)
    models = qs.values("model_id", "model_name").annotate(count=Count("id")).order_by("-count")
    last = qs.order_by("-updated_at").values_list("updated_at", flat=True).first()
    return {
        "app_id": app.id,
        "documents": qs.count(),
        "published": qs.filter(is_published=True, is_public=True).count(),
        "models": list(models),
        "last_indexed_at": last,
    }
