"""内容审核 REST 端点。"""
from __future__ import annotations

from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import write_audit_log
from datamodels.models import DataModel, DataRecord
from moderation.models import ContentReview
from moderation.services import (
    approve,
    can_review,
    pending_reviews,
    reject,
    review_roles,
    serialize_review_for,
    submit,
    withdraw,
)
from wp_utils import get_app, is_platform_admin_full, require_app_role


def _visible_reviews(user, *, app_id: int | None = None):
    qs = pending_reviews(user, app_id=app_id)
    qs = qs.order_by("-submitted_at")
    if is_platform_admin_full(user):
        return qs
    rows = []
    for review in qs[:1000]:
        if can_review(user, review.model) or review.submitted_by_id == user.id:
            rows.append(review)
    return rows


def _paginate(request, rows, serialize):
    try:
        page = max(1, int(request.query_params.get("page") or 1))
        size = min(100, max(1, int(request.query_params.get("size") or 20)))
    except (TypeError, ValueError):
        page, size = 1, 20
    total = len(rows)
    start = (page - 1) * size
    return {"count": total, "results": [serialize(r) for r in rows[start:start + size]], "page": page, "size": size}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def review_list(request):
    """GET /api/moderation/reviews/?app_id=&status=&model_id=&mine=&q="""
    app_id = request.query_params.get("app_id")
    if app_id:
        app = get_app(int(app_id))
        require_app_role(request.user, app, "viewer")
    rows = _visible_reviews(request.user, app_id=int(app_id) if app_id else None)
    status_f = str(request.query_params.get("status") or "").strip()
    if status_f == "active":
        rows = [r for r in rows if r.status == "pending"]
    elif status_f:
        rows = [r for r in rows if r.status == status_f]
    model_id = request.query_params.get("model_id")
    if model_id:
        rows = [r for r in rows if str(r.model_id) == str(model_id)]
    if request.query_params.get("mine") in ("1", "true", "yes"):
        rows = [r for r in rows if r.submitted_by_id == request.user.id]
    q = str(request.query_params.get("q") or "").strip().lower()
    if q:
        rows = [r for r in rows if q in (r.title or "").lower() or q in (r.model.name or "").lower()]
    return Response(_paginate(request, rows, lambda r: serialize_review_for(request.user, r)))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def review_detail(request, pk: int):
    review = get_object_or_404(
        ContentReview.objects.select_related("model", "record", "app", "submitted_by", "reviewed_by"), pk=pk
    )
    require_app_role(request.user, review.app, "viewer")
    if not (can_review(request.user, review.model) or review.submitted_by_id == request.user.id or is_platform_admin_full(request.user)):
        raise PermissionDenied("无权查看该审核单")
    return Response(serialize_review_for(request.user, review))


def _act(request, pk: int, action: str):
    review = get_object_or_404(
        ContentReview.objects.select_related("model", "record", "app"), pk=pk
    )
    require_app_role(request.user, review.app, "viewer")
    comment = str(request.data.get("comment") or request.data.get("reason") or "").strip()
    before = {"status": review.status, "comment": review.comment}
    if action == "approve":
        review = approve(review, user=request.user, comment=comment)
    elif action == "reject":
        review = reject(review, user=request.user, comment=comment)
    else:
        review = withdraw(review, user=request.user)
    write_audit_log(
        user=request.user, action=f"review.{action}", object_type="content_review",
        object_id=review.id, app_id=review.app_id, before=before,
        after={"status": review.status, "comment": review.comment}, request=request,
    )
    review.refresh_from_db()
    return Response(serialize_review_for(request.user, review))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def review_approve(request, pk: int):
    return _act(request, pk, "approve")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def review_reject(request, pk: int):
    return _act(request, pk, "reject")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def review_withdraw(request, pk: int):
    return _act(request, pk, "withdraw")


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def review_submit(request):
    """POST /api/moderation/submit/ {model_id, record_id, comment}"""
    model_id = request.data.get("model_id")
    record_id = request.data.get("record_id")
    if not model_id or not record_id:
        raise ValidationError({"detail": "model_id 与 record_id 必填"})
    model = get_object_or_404(DataModel.objects.select_related("app"), pk=model_id)
    require_app_role(request.user, model.app, "editor")
    record = get_object_or_404(DataRecord, pk=record_id, model=model)
    review = submit(record, user=request.user, comment=str(request.data.get("comment") or ""))
    write_audit_log(
        user=request.user, action="review.submit", object_type="content_review",
        object_id=review.id, app_id=model.app_id, after={"record_id": record.id, "revision": review.revision},
        request=request,
    )
    return Response(serialize_review_for(request.user, review), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def review_batch(request):
    """POST /api/moderation/reviews/batch/ {ids, action: approve|reject, comment}"""
    ids = request.data.get("ids")
    if not isinstance(ids, list) or not ids:
        raise ValidationError({"detail": "ids 必须是非空数组"})
    action = str(request.data.get("action") or "approve")
    if action not in ("approve", "reject"):
        raise ValidationError({"detail": "action 必须是 approve/reject"})
    comment = str(request.data.get("comment") or "").strip()
    results, errors = [], []
    for review in ContentReview.objects.select_related("model", "record", "app").filter(id__in=ids):
        try:
            if action == "approve":
                approve(review, user=request.user, comment=comment)
            else:
                reject(review, user=request.user, comment=comment)
            results.append(review.id)
        except Exception as exc:  # noqa: BLE001
            errors.append({"id": review.id, "error": str(exc)})
    return Response({"ok": not errors, "processed": results, "errors": errors})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def review_summary(request):
    """GET /api/moderation/summary/?app_id= — 队列计数与可审模型。"""
    app_id = request.query_params.get("app_id")
    app = get_app(int(app_id)) if app_id else None
    if app is not None:
        require_app_role(request.user, app, "viewer")
    rows = _visible_reviews(request.user, app_id=app.id if app else None)
    counts = {"pending": 0, "approved": 0, "rejected": 0, "cancelled": 0}
    for review in rows:
        counts[review.status] = counts.get(review.status, 0) + 1
    models_qs = DataModel.objects.filter(review_required=True)
    if app is not None:
        models_qs = models_qs.filter(app=app)
    else:
        models_qs = models_qs.filter(app__members__user=request.user).distinct()
    models = []
    for model in models_qs.select_related("app")[:100]:
        models.append({
            "id": model.id,
            "name": model.name,
            "app_id": model.app_id,
            "app_name": model.app.name,
            "review_roles": sorted(review_roles(model)),
            "can_review": can_review(request.user, model),
            "pending": model.reviews.filter(status="pending").count(),
        })
    return Response({
        "counts": counts,
        "total": len(rows),
        "my_submitted": sum(1 for r in rows if r.submitted_by_id == request.user.id),
        "reviewable_models": models,
        "can_review_any": any(m["can_review"] for m in models),
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def review_policies(request):
    """GET /api/moderation/policies/?app_id= — 模型级审核配置概览。"""
    app_id = request.query_params.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "viewer")
    qs = DataModel.objects.filter(app=app).annotate(pending=Count("reviews", filter=Q(reviews__status="pending")))
    return Response({
        "app_id": app.id,
        "policies": [
            {
                "model_id": m.id,
                "model_name": m.name,
                "review_required": m.review_required,
                "review_roles": sorted(review_roles(m)),
                "pending": m.pending,
            }
            for m in qs.order_by("name")
        ],
    })
