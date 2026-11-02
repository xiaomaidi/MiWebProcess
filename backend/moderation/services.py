"""内容审核服务：送审、通过、驳回、撤回与发布联动。"""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from core.permissions import get_app_role
from datamodels.models import DataModel, DataRecord
from moderation.models import ContentReview, ContentReviewEvent
from wp_utils import broadcast_to_app, is_platform_admin_full

DEFAULT_REVIEW_ROLES = ("owner",)
STATUS_FIELD = "status"


# ---------------------------------------------------------------- 权限

def review_roles(model: DataModel) -> set[str]:
    roles = model.review_roles if isinstance(model.review_roles, list) else []
    roles = [r for r in roles if r in ("viewer", "editor", "owner")]
    return set(roles or DEFAULT_REVIEW_ROLES)


def can_review(user, model: DataModel) -> bool:
    if is_platform_admin_full(user):
        return True
    role = get_app_role(user, model.app)
    return bool(role) and role in review_roles(model)


def has_status_field(model: DataModel) -> bool:
    return any(isinstance(f, dict) and f.get("name") == STATUS_FIELD for f in (model.fields or []))


# ---------------------------------------------------------------- 工具

def record_title(record: DataRecord) -> str:
    data = record.data or {}
    for key in ("title", "name", "subject", "code"):
        value = data.get(key)
        if value:
            return str(value)[:300]
    return f"记录 #{record.id}"


def active_review(record: DataRecord) -> ContentReview | None:
    return record.reviews.filter(status="pending").order_by("-id").first()


def _event(review: ContentReview, action: str, actor, comment: str = "", from_status: str = "", to_status: str = ""):
    ContentReviewEvent.objects.create(
        review=review, action=action, actor=actor, comment=comment or "",
        from_status=from_status, to_status=to_status,
    )


def _set_record_status(record: DataRecord, status: str, *, extra: dict | None = None) -> None:
    data = dict(record.data or {})
    data[STATUS_FIELD] = status
    if extra:
        data.update(extra)
    record.data = data
    record.save(update_fields=["data", "updated_at"])


def _after_publish(record: DataRecord) -> None:
    """发布/下线后同步搜索索引与实时通知（失败不影响审核事务）。"""
    try:
        from search.services import index_record

        index_record(record)
    except Exception:
        pass
    try:
        data = record.data or {}
        broadcast_to_app(
            record.model.app_id,
            {
                "type": "content_reviewed",
                "payload": {
                    "record_id": record.id, "model_id": record.model_id,
                    "status": data.get("status"), "title": record_title(record),
                },
                "extra": {"topic": f"content/{record.model_id}/reviewed"},
            },
        )
    except Exception:
        pass


# ---------------------------------------------------------------- 状态流转

def submit(record: DataRecord, *, user, comment: str = "", force: bool = False) -> ContentReview:
    """提交审核：记录进入 pending，创建/复用待审单。"""
    model = record.model
    if not model.review_required and not force:
        raise ValidationError({"detail": "该数据模型未开启内容审核"})
    with transaction.atomic():
        review = active_review(record)
        revision = (record.reviews.order_by("-revision").values_list("revision", flat=True).first() or 0) + 1
        if review is None:
            review = ContentReview.objects.create(
                app=model.app, model=model, record=record, status="pending",
                revision=revision, title=record_title(record),
                snapshot=record.data or {}, submitted_by=user,
            )
            _event(review, "submit", user, comment or "提交审核", "", "pending")
        else:
            review.title = record_title(record)
            review.snapshot = record.data or {}
            review.submitted_by = user
            review.submitted_at = timezone.now()
            review.save(update_fields=["title", "snapshot", "submitted_by", "submitted_at", "updated_at"])
            _event(review, "resubmit", user, comment or "重新送审", "pending", "pending")
        if has_status_field(model) and (record.data or {}).get(STATUS_FIELD) != "pending":
            _set_record_status(record, "pending")
    broadcast_to_app(
        model.app_id,
        {
            "type": "review_submitted",
            "payload": {"review_id": review.id, "record_id": record.id, "title": review.title},
            "extra": {"topic": f"content/{model.id}/review"},
        },
    )
    return review


def approve(review: ContentReview, *, user, comment: str = "") -> ContentReview:
    if review.status != "pending":
        raise ValidationError({"detail": f"审核单已结束（{review.get_status_display()}）"})
    if not can_review(user, review.model):
        raise PermissionDenied("没有该内容的审核权限")
    with transaction.atomic():
        review.status = "approved"
        review.reviewed_by = user
        review.reviewed_at = timezone.now()
        review.comment = comment or "审核通过"
        review.save(update_fields=["status", "reviewed_by", "reviewed_at", "comment", "updated_at"])
        _event(review, "approve", user, review.comment, "pending", "approved")
        record = review.record
        if has_status_field(review.model):
            _set_record_status(record, "published", extra={"published_at": timezone.now().isoformat()})
        record.updated_by = user
        record.save(update_fields=["updated_by", "updated_at"])
    _after_publish(review.record)
    return review


def reject(review: ContentReview, *, user, comment: str = "") -> ContentReview:
    if review.status != "pending":
        raise ValidationError({"detail": f"审核单已结束（{review.get_status_display()}）"})
    if not can_review(user, review.model):
        raise PermissionDenied("没有该内容的审核权限")
    if not str(comment or "").strip():
        raise ValidationError({"detail": "驳回需要填写原因"})
    with transaction.atomic():
        review.status = "rejected"
        review.reviewed_by = user
        review.reviewed_at = timezone.now()
        review.comment = comment
        review.save(update_fields=["status", "reviewed_by", "reviewed_at", "comment", "updated_at"])
        _event(review, "reject", user, comment, "pending", "rejected")
        if has_status_field(review.model):
            _set_record_status(review.record, "rejected")
    try:
        from search.services import remove_record

        remove_record(review.record)
    except Exception:
        pass
    return review


def withdraw(review: ContentReview, *, user) -> ContentReview:
    if review.status != "pending":
        raise ValidationError({"detail": "只能撤回待审核的内容"})
    if not (is_platform_admin_full(user) or review.submitted_by_id == user.id):
        raise PermissionDenied("只有提交人可以撤回")
    with transaction.atomic():
        review.status = "cancelled"
        review.reviewed_by = user
        review.reviewed_at = timezone.now()
        review.comment = "提交人撤回"
        review.save(update_fields=["status", "reviewed_by", "reviewed_at", "comment", "updated_at"])
        _event(review, "withdraw", user, "提交人撤回", "pending", "cancelled")
        if has_status_field(review.model):
            _set_record_status(review.record, "draft")
    return review


# ---------------------------------------------------------------- 写入钩子

def after_record_write(model: DataModel, record: DataRecord, *, user, is_new: bool = False) -> ContentReview | None:
    """记录创建/更新后调用：审核人直接发布，其他人自动送审。"""
    if not model.review_required or not has_status_field(model):
        return None
    status = (record.data or {}).get(STATUS_FIELD)
    if can_review(user, model):
        # 审核人可直接保存任意状态；仅当内容处于待审/已驳回时才代为通过。
        if status in ("pending", "rejected"):
            review = active_review(record)
            if review is None:
                review = ContentReview.objects.create(
                    app=model.app, model=model, record=record, status="pending",
                    revision=1, title=record_title(record), snapshot=record.data or {},
                    submitted_by=user,
                )
            return approve(review, user=user, comment="审核人直接发布")
        return None
    return submit(record, user=user, comment="内容保存后自动送审")


def pending_reviews(user, *, app_id: int | None = None):
    """审核人看到全部待审；普通成员只看到自己提交的。"""
    qs = ContentReview.objects.select_related("model", "record", "submitted_by", "reviewed_by", "app")
    if app_id:
        qs = qs.filter(app_id=app_id)
    else:
        qs = qs.filter(app__members__user=user).distinct()
    if not is_platform_admin_full(user):
        qs = qs.filter(record__model__in=DataModel.objects.filter(app__members__user=user))
    return qs


def reviewable(user, review: ContentReview) -> bool:
    return can_review(user, review.model) or review.submitted_by_id == user.id or is_platform_admin_full(user)


def serialize_review(review: ContentReview, *, include_snapshot: bool = True) -> dict:
    record = review.record
    return {
        "id": review.id,
        "app_id": review.app_id,
        "model_id": review.model_id,
        "model_name": review.model.name if review.model_id else "",
        "record_id": review.record_id,
        "status": review.status,
        "status_label": review.get_status_display(),
        "revision": review.revision,
        "title": review.title,
        "snapshot": review.snapshot if include_snapshot else {},
        "record_data": (record.data or {}) if include_snapshot and record else {},
        "submitted_by": review.submitted_by_id,
        "submitted_by_name": review.submitted_by.username if review.submitted_by_id else "",
        "submitted_at": review.submitted_at,
        "reviewed_by": review.reviewed_by_id,
        "reviewed_by_name": review.reviewed_by.username if review.reviewed_by_id else "",
        "reviewed_at": review.reviewed_at,
        "comment": review.comment,
        "can_approve": False,
        "created_at": review.created_at,
        "updated_at": review.updated_at,
    }


def serialize_review_for(user, review: ContentReview) -> dict:
    include = can_review(user, review.model) or is_platform_admin_full(user) or review.submitted_by_id == user.id
    payload = serialize_review(review, include_snapshot=include)
    payload["can_approve"] = review.status == "pending" and can_review(user, review.model)
    payload["can_withdraw"] = (
        review.status == "pending"
        and (is_platform_admin_full(user) or review.submitted_by_id == user.id)
    )
    payload["events"] = [
        {
            "id": e.id,
            "action": e.action,
            "from_status": e.from_status,
            "to_status": e.to_status,
            "actor": e.actor.username if e.actor_id else "",
            "comment": e.comment,
            "created_at": e.created_at,
        }
        for e in review.events.select_related("actor").all()
    ]
    return payload
