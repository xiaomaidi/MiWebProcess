"""数据模型 / 记录 REST 端点。"""
from __future__ import annotations

import csv

from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import snapshot_instance, write_audit_log
from appcore.modules import module_for_model, require_module
from core.permissions import get_app_role, is_platform_admin
from datamodels.models import DATA_SCOPES, DataModel, DataRecord, ReportSubscription
from datamodels.serializers import DataModelSerializer, DataRecordSerializer, ReportSubscriptionSerializer
from datamodels.services import (
    apply_row_scope,
    can_access_record,
    default_department_value,
    dynamic_query,
    guard_department_assignment,
    paginate_rows,
    require_action,
    validate_data,
    validate_fields_spec,
    visible_data,
)
from wp_utils import get_app, paginate_items, require_app_role


def _audit(request, action: str, object_type: str, before=None, after=None, app_id=None, object_id=None):
    write_audit_log(
        user=request.user,
        action=action,
        object_type=object_type,
        object_id=object_id,
        app_id=app_id,
        before=before,
        after=after,
        request=request,
    )


def _data_scope(value) -> str:
    scope = str(value or "all")
    if scope not in DATA_SCOPES:
        raise ValidationError({"detail": f"data_scope 必须是 {DATA_SCOPES} 之一"})
    return scope


def _workflow_definition_id(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError({"detail": "workflow_definition_id 必须是整数"})


def _action_roles(value) -> dict:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise ValidationError({"detail": "action_roles 必须是对象"})
    return {
        str(action): [r for r in roles if r in ("viewer", "editor", "owner")]
        for action, roles in value.items()
        if isinstance(roles, list)
    }


def _review_roles(value) -> list:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise ValidationError({"detail": "review_roles 必须是数组"})
    return [r for r in value if r in ("viewer", "editor", "owner")]


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def model_list_create(request):
    """GET/POST /api/models/"""
    if request.method == "GET":
        qs = DataModel.objects.all().select_related("app")
        app_id = request.query_params.get("app_id")
        if app_id:
            app = get_app(app_id)
            require_app_role(request.user, app, "viewer")
            qs = qs.filter(app=app)
        else:
            qs = qs.filter(app__members__user=request.user).distinct()
        return paginate_items(request, qs.order_by("-created_at"), DataModelSerializer)

    app_id = request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(app_id)
    require_app_role(request.user, app, "editor")
    name = (request.data.get("name") or "").strip()
    if not name:
        raise ValidationError({"detail": "name 必填"})
    if DataModel.objects.filter(app=app, name=name).exists():
        raise ValidationError({"detail": f"模型 {name} 已存在"})
    fields = validate_fields_spec(request.data.get("fields") or [], app=app)
    indexes = request.data.get("indexes") or []
    if not isinstance(indexes, list):
        raise ValidationError({"detail": "indexes 必须是数组"})
    model = DataModel.objects.create(
        app=app, name=name, fields=fields, indexes=indexes,
        is_public=bool(request.data.get("is_public", False)),
        row_owner_field=str(request.data.get("row_owner_field") or "")[:80],
        workflow_definition_id=_workflow_definition_id(request.data.get("workflow_definition_id")),
        data_scope=_data_scope(request.data.get("data_scope")),
        dept_field=str(request.data.get("dept_field") or "dept")[:80],
        action_roles=_action_roles(request.data.get("action_roles")),
        review_required=bool(request.data.get("review_required", False)),
        review_roles=_review_roles(request.data.get("review_roles")),
        created_by=request.user,
    )
    _audit(request, "model.create", "datamodel", after=snapshot_instance(model), app_id=app.id, object_id=model.id)
    return Response(DataModelSerializer(model).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def model_detail(request, pk):
    model = get_object_or_404(DataModel.objects.select_related("app"), pk=pk)
    if request.method == "GET":
        require_app_role(request.user, model.app, "viewer")
        return Response(DataModelSerializer(model).data)
    require_app_role(request.user, model.app, "editor")
    before = snapshot_instance(model)
    if request.method == "DELETE":
        model.delete()
        _audit(request, "model.delete", "datamodel", before=before, app_id=model.app_id, object_id=model.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    name = request.data.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise ValidationError({"detail": "name 不能为空"})
        if DataModel.objects.filter(app=model.app, name=name).exclude(id=model.id).exists():
            raise ValidationError({"detail": f"模型 {name} 已存在"})
        model.name = name
    fields = request.data.get("fields")
    if fields is not None:
        model.fields = validate_fields_spec(fields, app=model.app)
    indexes = request.data.get("indexes")
    if indexes is not None:
        if not isinstance(indexes, list):
            raise ValidationError({"detail": "indexes 必须是数组"})
        model.indexes = indexes
    if "is_public" in request.data:
        model.is_public = bool(request.data.get("is_public"))
    if "row_owner_field" in request.data:
        model.row_owner_field = str(request.data.get("row_owner_field") or "")[:80]
    if "workflow_definition_id" in request.data:
        model.workflow_definition_id = _workflow_definition_id(request.data.get("workflow_definition_id"))
    if "data_scope" in request.data:
        model.data_scope = _data_scope(request.data.get("data_scope"))
    if "dept_field" in request.data:
        model.dept_field = str(request.data.get("dept_field") or "dept")[:80]
    if "action_roles" in request.data:
        model.action_roles = _action_roles(request.data.get("action_roles"))
    if "review_required" in request.data:
        model.review_required = bool(request.data.get("review_required"))
    if "review_roles" in request.data:
        model.review_roles = _review_roles(request.data.get("review_roles"))
    model.save()
    _audit(request, "model.update", "datamodel", before=before, after=snapshot_instance(model), app_id=model.app_id, object_id=model.id)
    return Response(DataModelSerializer(model).data)


def _get_model_for_records(model_id: int) -> DataModel:
    return get_object_or_404(DataModel.objects.select_related("app"), pk=model_id)


def _scope_context(user, app):
    return get_app_role(user, app), is_platform_admin(user)


def _record_accessible(model: DataModel, record: DataRecord, user, admin: bool) -> bool:
    return can_access_record(model, record.data or {}, user, admin=admin)


def _apply_review_flow(model: DataModel, record: DataRecord, user, *, is_new: bool = False) -> None:
    """审核模型写入后的状态流转；审核失败不阻塞记录保存。"""
    if not model.review_required:
        return
    try:
        from moderation.services import after_record_write

        after_record_write(model, record, user=user, is_new=is_new)
        record.refresh_from_db()
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger("moderation").exception("after_record_write failed for record %s", record.id)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def record_list_create(request, model):
    """GET/POST /api/records/{model}/"""
    model_obj = _get_model_for_records(model)
    require_module(model_obj.app, module_for_model(model_obj.name))
    if request.method == "GET":
        require_app_role(request.user, model_obj.app, "viewer")
        role, admin = _scope_context(request.user, model_obj.app)
        require_action(model_obj, role, "view", admin=admin)
        # 注意：dict(QueryDict) 会把值变成列表，需逐项取标量
        params = {k: request.query_params.get(k) for k in request.query_params}
        rows = dynamic_query(model_obj, params)
        rows = apply_row_scope(model_obj, rows, request.user, admin=admin)
        rows = [{**row, "data": visible_data(model_obj, row.get("data") or {}, role, admin=admin)} for row in rows]
        return Response(paginate_rows(rows, request))
    require_app_role(request.user, model_obj.app, "editor")
    role, admin = _scope_context(request.user, model_obj.app)
    require_action(model_obj, role, "create", admin=admin)
    data = request.data.get("data")
    if not isinstance(data, dict):
        raise ValidationError({"detail": "data 必须是对象"})
    cleaned = validate_data(model_obj, data, partial=False, user=request.user, role=role, admin=admin)
    guard_department_assignment(model_obj, cleaned, request.user, admin=admin)
    if (model_obj.data_scope or "all") in ("dept", "dept_and_children"):
        dept_field = (model_obj.dept_field or "dept").strip() or "dept"
        if not cleaned.get(dept_field):
            default_dept = default_department_value(request.user, model_obj)
            if default_dept:
                cleaned[dept_field] = default_dept
    record = DataRecord.objects.create(model=model_obj, data=cleaned, created_by=request.user, updated_by=request.user)
    try:
        from appcore.events import emit_event
        emit_event(model_obj.app, "record.created", {"id": record.id, "model_id": model_obj.id, "data": cleaned})
    except Exception:
        pass
    _audit(request, "record.create", "datamodel_record", after={"data": cleaned}, app_id=model_obj.app_id, object_id=record.id)
    _apply_review_flow(model_obj, record, request.user, is_new=True)
    payload = DataRecordSerializer(record).data
    payload["data"] = visible_data(model_obj, record.data or {}, role, admin=admin)
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def record_report(request, model):
    """GET /api/models/{model}/records/report/?group_by=status&metrics=count,sum:amount"""
    from datamodels.services import dynamic_query

    model_obj = _get_model_for_records(model)
    require_app_role(request.user, model_obj.app, "viewer")
    role, admin = _scope_context(request.user, model_obj.app)
    require_action(model_obj, role, "view", admin=admin)
    params = {k: request.query_params.get(k) for k in request.query_params}
    group_by = str(params.pop("group_by", "") or "").strip()
    group_by2 = str(params.pop("group_by2", "") or "").strip()
    metrics_raw = str(params.pop("metrics", "count") or "count")
    limit = min(500, max(1, int(params.pop("limit", 200) or 200)))
    rows = apply_row_scope(model_obj, dynamic_query(model_obj, params), request.user, admin=admin)

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
            if fn in ("count", "count_distinct") and field is None:
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
    out_rows.sort(key=lambda r: (-int(r.get("count", 0)), str(r.get("key", "")), str(r.get("key2", ""))))
    out_rows = out_rows[:limit]

    def metric_alias() -> str:
        for fn, field in metrics:
            if field and fn in ("sum", "avg", "min", "max", "count_distinct"):
                return f"{fn}_{field}"
        return "count"

    cross = None
    cross_columns: list[str] = []
    if group_by2:
        alias = metric_alias()
        columns = sorted({str(r.get("key2", "")) for r in out_rows})
        cross_columns = [c for c in columns if c] or [""]
        matrix: dict[str, dict] = {}
        for r in out_rows:
            key = str(r.get("key", ""))
            row = matrix.setdefault(key, {"key": key})
            row[str(r.get("key2", ""))] = r.get(alias)
        cross = list(matrix.values())

    return Response(
        {
            "group_by": group_by,
            "group_by2": group_by2,
            "metrics": metrics_raw,
            "cross_metric": metric_alias() if group_by2 else "",
            "cross_columns": cross_columns,
            "cross": cross,
            "count": len(rows),
            "rows": out_rows,
            "fields": [f.get("name") for f in (model_obj.fields or []) if isinstance(f, dict)],
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def record_revert(request, model, pk: int):
    """把记录回滚到某条审计日志的 before.data。"""
    from audit.models import AuditLog
    from datamodels.models import DataRecord

    model_obj = _get_model_for_records(model)
    require_app_role(request.user, model_obj.app, "editor")
    role, admin = _scope_context(request.user, model_obj.app)
    require_action(model_obj, role, "update", admin=admin)
    record = get_object_or_404(DataRecord, model=model_obj, pk=pk)
    audit_id = request.data.get("audit_id")
    if not audit_id:
        raise ValidationError({"detail": "audit_id 必填"})
    log = AuditLog.objects.filter(
        id=audit_id, object_type="datamodel_record", object_id=str(pk), app=model_obj.app,
    ).first()
    if log is None:
        raise ValidationError({"detail": "审计记录不存在"})
    before = (log.before or {}).get("data")
    if not isinstance(before, dict):
        raise ValidationError({"detail": "该审计记录没有可回滚的数据"})
    record.data = validate_data(
        model_obj, before, partial=False, exclude_pk=record.id,
        user=request.user, role=role, admin=admin,
    )
    record.updated_by = request.user
    record.save()
    _audit(request, "record.revert", "datamodel_record", after={"data": record.data}, app_id=model_obj.app_id, object_id=record.id)
    payload = DataRecordSerializer(record).data
    payload["data"] = visible_data(model_obj, record.data or {}, role, admin=admin)
    return Response(payload)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def report_subscription_list(request, model):
    from datamodels.services import dynamic_query

    model_obj = _get_model_for_records(model)
    require_module(model_obj.app, module_for_model(model_obj.name))
    if request.method == "GET":
        require_app_role(request.user, model_obj.app, "viewer")
        rows = ReportSubscription.objects.filter(app=model_obj.app, model=model_obj)
        return Response(ReportSubscriptionSerializer(rows, many=True).data)
    require_app_role(request.user, model_obj.app, "editor")
    serializer = ReportSubscriptionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    sub = serializer.save(app=model_obj.app, model=model_obj, created_by=request.user)
    return Response(ReportSubscriptionSerializer(sub).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def report_subscription_detail(request, pk: int):
    sub = get_object_or_404(ReportSubscription.objects.select_related("app", "model"), pk=pk)
    require_app_role(request.user, sub.app, "viewer")
    if request.method == "GET":
        return Response(ReportSubscriptionSerializer(sub).data)
    require_app_role(request.user, sub.app, "editor")
    if request.method == "DELETE":
        sub.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    serializer = ReportSubscriptionSerializer(sub, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_subscription_run(request, pk: int):
    from django.utils import timezone
    from datamodels.services import dynamic_query

    sub = get_object_or_404(ReportSubscription.objects.select_related("app", "model"), pk=pk)
    require_app_role(request.user, sub.app, "viewer")
    config = sub.config or {}
    params = dict(config.get("filters") or {})
    rows = dynamic_query(sub.model, params)
    sub.last_run_at = timezone.now()
    sub.save(update_fields=["last_run_at", "updated_at"])
    return Response({"ok": True, "count": len(rows), "subscription": ReportSubscriptionSerializer(sub).data})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def record_publish(request, model, pk: int):
    """发布 / 下线 / 定时发布内容记录。"""
    import datetime as dt

    from django.utils import timezone
    from datamodels.models import DataRecord

    model_obj = _get_model_for_records(model)
    require_app_role(request.user, model_obj.app, "editor")
    role, admin = _scope_context(request.user, model_obj.app)
    require_action(model_obj, role, "update", admin=admin)
    record = get_object_or_404(DataRecord, model=model_obj, pk=pk)
    field_names = {f.get("name") for f in (model_obj.fields or []) if isinstance(f, dict)}
    if "status" not in field_names:
        raise ValidationError({"detail": "模型没有 status 字段，无法发布"})
    action = str(request.data.get("action") or "publish")
    if model_obj.review_required and action == "publish":
        from moderation.services import can_review, serialize_review_for, submit as submit_review

        if not can_review(request.user, model_obj):
            review = submit_review(record, user=request.user, comment="申请发布")
            return Response(
                {"detail": "内容已提交审核，审核通过后自动发布", "review": serialize_review_for(request.user, review)},
                status=status.HTTP_202_ACCEPTED,
            )
    data = dict(record.data or {})
    if action == "schedule":
        raw = request.data.get("published_at")
        if not raw:
            raise ValidationError({"detail": "定时发布需要 published_at"})
        try:
            due = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError({"detail": "published_at 格式不正确"})
        if timezone.is_naive(due):
            due = timezone.make_aware(due)
        data["status"] = "scheduled"
        data["published_at"] = due.isoformat()
    elif action == "unpublish":
        data["status"] = "draft"
        data["published_at"] = None
    else:
        data["status"] = "published"
        data["published_at"] = timezone.now().isoformat()
    record.data = data
    record.save(update_fields=["data", "updated_at"])
    return Response(DataRecordSerializer(record).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def record_export(request, model):
    """GET /api/models/{model}/records/export/ → 当前筛选结果的 CSV。"""
    from datamodels.services import dynamic_query

    model_obj = _get_model_for_records(model)
    require_app_role(request.user, model_obj.app, "viewer")
    role, admin = _scope_context(request.user, model_obj.app)
    require_action(model_obj, role, "export", admin=admin)
    params = {k: request.query_params.get(k) for k in request.query_params}
    rows = apply_row_scope(model_obj, dynamic_query(model_obj, params), request.user, admin=admin)
    field_names = [
        f.get("name") for f in (model_obj.fields or [])
        if isinstance(f, dict) and (admin or not (f.get("read_roles") or []) or role in (f.get("read_roles") or []))
    ]
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="model-{model_obj.id}.csv"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(["id", *field_names])
    for row in rows:
        data = visible_data(model_obj, row.get("data") or {}, role, admin=admin)
        values = []
        for value in [row.get("id"), *[data.get(name) for name in field_names]]:
            text = "" if value is None else str(value)
            # 防 CSV 公式注入
            if text.startswith(("=", "+", "-", "@")):
                text = "'" + text
            values.append(text)
        writer.writerow(values)
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def record_batch_delete(request, model):
    """POST /api/models/{model}/records/batch/ 或 /api/records/{model}/batch/ → {ids: []} 批量删除"""
    model_obj = _get_model_for_records(model)
    require_app_role(request.user, model_obj.app, "editor")
    role, admin = _scope_context(request.user, model_obj.app)
    require_action(model_obj, role, "delete", admin=admin)
    ids = request.data.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ValidationError({"detail": "ids 必须是非空数组"})
    qs = DataRecord.objects.filter(model=model_obj, id__in=ids)
    before_ids = list(qs.values_list("id", flat=True))
    deleted, _ = qs.delete()
    _audit(request, "record.batch_delete", "datamodel_record", before={"ids": before_ids}, app_id=model_obj.app_id, object_id=model_obj.id)
    return Response({"deleted": deleted})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def app_model_root(request, app_id):
    """GET/POST /api/apps/{app_id}/models/"""
    app = get_app(app_id)
    if request.method == "GET":
        require_app_role(request.user, app, "viewer")
        qs = DataModel.objects.filter(app=app).select_related("app")
        return paginate_items(request, qs.order_by("-created_at"), DataModelSerializer)
    require_app_role(request.user, app, "editor")
    name = (request.data.get("name") or "").strip()
    if not name:
        raise ValidationError({"detail": "name 必填"})
    if DataModel.objects.filter(app=app, name=name).exists():
        raise ValidationError({"detail": f"模型 {name} 已存在"})
    fields = validate_fields_spec(request.data.get("fields") or [], app=app)
    indexes = request.data.get("indexes") or []
    if not isinstance(indexes, list):
        raise ValidationError({"detail": "indexes 必须是数组"})
    model = DataModel.objects.create(
        app=app, name=name, fields=fields, indexes=indexes,
        is_public=bool(request.data.get("is_public", False)),
        row_owner_field=str(request.data.get("row_owner_field") or "")[:80],
        workflow_definition_id=_workflow_definition_id(request.data.get("workflow_definition_id")),
        data_scope=_data_scope(request.data.get("data_scope")),
        dept_field=str(request.data.get("dept_field") or "dept")[:80],
        action_roles=_action_roles(request.data.get("action_roles")),
        review_required=bool(request.data.get("review_required", False)),
        review_roles=_review_roles(request.data.get("review_roles")),
        created_by=request.user,
    )
    _audit(request, "model.create", "datamodel", after=snapshot_instance(model), app_id=app.id, object_id=model.id)
    return Response(DataModelSerializer(model).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def record_detail(request, model, pk):
    """GET/PUT/PATCH/DELETE /api/records/{model}/{pk}/"""
    model_obj = _get_model_for_records(model)
    require_module(model_obj.app, module_for_model(model_obj.name))
    role, admin = _scope_context(request.user, model_obj.app)
    if request.method == "GET":
        require_app_role(request.user, model_obj.app, "viewer")
        require_action(model_obj, role, "view", admin=admin)
        record = DataRecord.objects.filter(model=model_obj, id=pk).first()
        if record is None or not _record_accessible(model_obj, record, request.user, admin):
            return Response(status=status.HTTP_404_NOT_FOUND)
        payload = DataRecordSerializer(record).data
        payload["data"] = visible_data(model_obj, record.data or {}, role, admin=admin)
        return Response(payload)
    require_app_role(request.user, model_obj.app, "editor")
    require_action(model_obj, role, "delete" if request.method == "DELETE" else "update", admin=admin)
    record = DataRecord.objects.filter(model=model_obj, id=pk).first()
    if record is None or not _record_accessible(model_obj, record, request.user, admin):
        return Response(status=status.HTTP_404_NOT_FOUND)
    before = snapshot_instance(record)
    if request.method == "DELETE":
        old_payload = {"id": record.id, "model_id": model_obj.id, "data": record.data or {}}
        record.delete()
        try:
            from appcore.events import emit_event
            emit_event(model_obj.app, "record.deleted", old_payload)
        except Exception:
            pass
        _audit(request, "record.delete", "datamodel_record", before=before, app_id=model_obj.app_id, object_id=record.id)
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = request.data.get("data")
    if not isinstance(data, dict):
        raise ValidationError({"detail": "data 必须是对象"})
    partial = request.method == "PATCH"
    merged = dict(record.data or {})
    merged.update(data)
    cleaned = validate_data(
        model_obj, merged, partial=partial, exclude_pk=record.id,
        user=request.user, role=role, admin=admin,
    )
    guard_department_assignment(model_obj, cleaned, request.user, admin=admin)
    record.data = cleaned
    record.updated_by = request.user
    record.save()
    try:
        from appcore.events import emit_event
        emit_event(model_obj.app, "record.updated", {"id": record.id, "model_id": model_obj.id, "data": cleaned})
    except Exception:
        pass
    _audit(request, "record.update", "datamodel_record", before=before, after={"data": cleaned}, app_id=model_obj.app_id, object_id=record.id)
    _apply_review_flow(model_obj, record, request.user)
    payload = DataRecordSerializer(record).data
    payload["data"] = visible_data(model_obj, record.data or {}, role, admin=admin)
    return Response(payload)
