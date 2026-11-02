"""数据源 REST 端点：CRUD / test / query。"""
from __future__ import annotations

import hashlib
import json
import time

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import snapshot_instance, write_audit_log
from datasources.executor import decode_secrets, encode_secrets, execute_external_db, list_external_schema, run_datasource
from datasources.models import Datasource
from datasources.serializers import DatasourceSerializer
from wp_utils import get_app, paginate_items, require_app_role

QUERY_CACHE_TTL = 60


def _cache_key(ds: Datasource, params: dict) -> str:
    raw = json.dumps(params, sort_keys=True, default=str)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"ds_query:{ds.id}:{ds.updated_at.isoformat()}:{digest}"


def _audit(request, action: str, before=None, after=None, app_id=None, object_id=None):
    write_audit_log(
        user=request.user,
        action=action,
        object_type="datasource",
        object_id=object_id,
        app_id=app_id,
        before=before,
        after=after,
        request=request,
    )


def _validate_payload(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    dtype = data.get("type")
    if not name:
        raise ValidationError({"detail": "name 必填"})
    if dtype not in dict(Datasource.TYPE_CHOICES):
        raise ValidationError({"detail": f"type 必须是 {dict(Datasource.TYPE_CHOICES).keys()}"})
    config = data.get("config") or {}
    transform = data.get("transform") or {}
    if not isinstance(config, dict):
        raise ValidationError({"detail": "config 必须是对象"})
    if not isinstance(transform, dict):
        raise ValidationError({"detail": "transform 必须是对象"})
    if dtype == "rest" and not (config.get("url") or "").strip():
        raise ValidationError({"detail": "rest 数据源需要 config.url"})
    if dtype == "sql" and not (config.get("query") or "").strip():
        raise ValidationError({"detail": "sql 数据源需要 config.query"})
    if dtype in ("mysql", "postgres", "sqlserver"):
        if not str(config.get("host") or "").strip() or not str(config.get("database") or "").strip():
            raise ValidationError({"detail": f"{dtype} 数据源需要 config.host 和 config.database"})
        if not str(config.get("query") or "").strip():
            raise ValidationError({"detail": f"{dtype} 数据源需要 config.query"})
    if dtype == "static" and "data" not in config:
        raise ValidationError({"detail": "static 数据源需要 config.data"})
    if dtype == "websocket":
        url = str(config.get("url") or "").strip()
        if not url:
            raise ValidationError({"detail": "websocket 数据源需要 config.url"})
        if not url.startswith(("ws://", "wss://")):
            raise ValidationError({"detail": "WebSocket URL 必须以 ws:// 或 wss:// 开头"})
        if not isinstance(config.get("subscribe", {}), (dict, str)):
            raise ValidationError({"detail": "subscribe 必须是对象或字符串"})
    return {"name": name, "type": dtype, "config": config, "transform": transform}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def datasource_list_create(request):
    """GET/POST /api/datasources/"""
    if request.method == "GET":
        qs = Datasource.objects.all().select_related("app", "created_by")
        app_id = request.query_params.get("app_id")
        if app_id:
            app = get_app(app_id)
            require_app_role(request.user, app, "viewer")
            qs = qs.filter(app=app)
        else:
            qs = qs.filter(app__members__user=request.user).distinct()
        return paginate_items(request, qs.order_by("-created_at"), DatasourceSerializer)

    app_id = request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(app_id)
    require_app_role(request.user, app, "editor")
    payload = _validate_payload(request.data)
    if Datasource.objects.filter(app=app, name=payload["name"]).exists():
        raise ValidationError({"detail": f"数据源 {payload['name']} 已存在"})
    ds = Datasource.objects.create(
        app=app,
        name=payload["name"],
        type=payload["type"],
        config=encode_secrets(payload["config"]),
        transform=payload["transform"],
        created_by=request.user,
    )
    _audit(request, "datasource.create", after=snapshot_instance(ds), app_id=app.id, object_id=ds.id)
    return Response(DatasourceSerializer(ds).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def datasource_detail(request, pk):
    ds = get_object_or_404(Datasource.objects.select_related("app"), pk=pk)
    if request.method == "GET":
        require_app_role(request.user, ds.app, "viewer")
        return Response(DatasourceSerializer(ds).data)
    require_app_role(request.user, ds.app, "editor")
    before = snapshot_instance(ds)
    if request.method == "DELETE":
        ds.delete()
        _audit(request, "datasource.delete", before=before, app_id=ds.app_id, object_id=ds.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    payload = _validate_payload(request.data)
    if Datasource.objects.filter(app=ds.app, name=payload["name"]).exclude(id=ds.id).exists():
        raise ValidationError({"detail": f"数据源 {payload['name']} 已存在"})
    ds.name = payload["name"]
    ds.type = payload["type"]
    # config 增量合并：`***` 占位保留原值
    merged = dict(ds.config or {})
    for k, v in (payload["config"] or {}).items():
        if v == "***" and k in merged:
            continue
        merged[k] = v
    ds.config = encode_secrets(merged)
    ds.transform = payload["transform"]
    ds.save()
    _audit(request, "datasource.update", before=before, after=snapshot_instance(ds), app_id=ds.app_id, object_id=ds.id)
    return Response(DatasourceSerializer(ds).data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_datasource_root(request, app_id):
    """GET/POST /api/apps/{app_id}/datasources/"""
    app = get_app(app_id)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        qs = Datasource.objects.filter(app=app).select_related("app", "created_by")
        return paginate_items(request, qs.order_by("-created_at"), DatasourceSerializer)
    require_app_role(request.user, app, "editor")
    payload = _validate_payload(request.data)
    if Datasource.objects.filter(app=app, name=payload["name"]).exists():
        raise ValidationError({"detail": f"数据源 {payload['name']} 已存在"})
    ds = Datasource.objects.create(
        app=app,
        name=payload["name"],
        type=payload["type"],
        config=encode_secrets(payload["config"]),
        transform=payload["transform"],
        created_by=request.user,
    )
    _audit(request, "datasource.create", after=snapshot_instance(ds), app_id=app.id, object_id=ds.id)
    return Response(DatasourceSerializer(ds).data, status=status.HTTP_201_CREATED)


def _touch_test_result(ds: Datasource, result: dict) -> None:
    ds.last_test_at = timezone.now()
    if result["ok"]:
        ds.last_error = ""
        if ds.status == "error":
            ds.status = "active"
    else:
        ds.last_error = str(result.get("error") or f"status={result.get('status')}")[:2000]
        ds.status = "error"
    ds.save(update_fields=["last_test_at", "last_error", "status", "updated_at"])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def datasource_schema(request, pk):
    ds = get_object_or_404(Datasource.objects.select_related("app"), pk=pk)
    require_app_role(request.user, ds.app, "editor")
    if ds.type not in ("postgres", "mysql", "sqlserver"):
        raise ValidationError({"detail": "该数据源没有可浏览的数据库结构"})
    tables = list_external_schema(ds.type, decode_secrets(ds.config or {}))
    return Response({"type": ds.type, "tables": tables})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def datasource_run_sql(request, pk):
    ds = get_object_or_404(Datasource.objects.select_related("app"), pk=pk)
    require_app_role(request.user, ds.app, "editor")
    sql = str(request.data.get("sql") or "").strip().rstrip(";")
    if not sql:
        raise ValidationError({"detail": "sql 必填"})
    if ds.type not in ("postgres", "mysql", "sqlserver"):
        raise ValidationError({"detail": "该数据源不支持 SQL 查询构建器"})
    cfg = dict(decode_secrets(ds.config or {}))
    cfg["query"] = sql
    try:
        data = execute_external_db(ds.type, cfg, request.data.get("params") or {})
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": str(exc)})
    return Response({"data": data, "count": len(data)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def datasource_test(request, pk):
    """POST /api/datasources/{id}/test/ → 实际执行一次并记录结果 → {ok, message, latency_ms}"""
    ds = get_object_or_404(Datasource.objects.select_related("app"), pk=pk)
    require_app_role(request.user, ds.app, "editor")
    start = time.perf_counter()
    result = run_datasource(ds, request.data.get("params") or {}, is_test=True)
    latency_ms = int((time.perf_counter() - start) * 1000)
    _touch_test_result(ds, result)
    _audit(request, "datasource.test", after={"ok": result["ok"], "error": result["error"]}, app_id=ds.app_id, object_id=ds.id)
    message = result["error"] or (f"ok (status={result['status']})" if result["ok"] else f"status={result['status']}")
    return Response({"ok": bool(result["ok"]), "message": str(message), "latency_ms": latency_ms})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def datasource_query(request, pk):
    """POST /api/datasources/{id}/query/ {params?} → {data, from_cache, cached_at}（结果缓存 60s）"""
    ds = get_object_or_404(Datasource.objects.select_related("app"), pk=pk)
    require_app_role(request.user, ds.app, "viewer")
    params = request.data.get("params") or {}
    if not isinstance(params, dict):
        raise ValidationError({"detail": "params 必须是对象"})
    cfg = decode_secrets(ds.config or {})
    method = str(cfg.get("method") or "GET").upper()
    cacheable = not (ds.type == "rest" and method != "GET")
    key = _cache_key(ds, params)
    if cacheable:
        hit = cache.get(key)
        if hit is not None:
            return Response({"data": hit["data"], "from_cache": True, "cached_at": hit["cached_at"]})
    result = run_datasource(ds, params, is_test=False)
    if not result["ok"]:
        _touch_test_result(ds, result)
        return Response(
            status=status.HTTP_502_BAD_GATEWAY,
            data={"ok": False, "error": result["error"], "data": None, "from_cache": False, "cached_at": None},
        )
    cached_at = timezone.now().isoformat()
    if cacheable:
        cache.set(key, {"data": result["data"], "cached_at": cached_at}, QUERY_CACHE_TTL)
    return Response({"data": result["data"], "from_cache": False, "cached_at": cached_at})
