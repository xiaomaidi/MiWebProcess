"""应用级服务：通知模板、API Token、Webhook、定时任务，以及开放数据 API。"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from accounts.models import User
from appcore.modules import module_for_model, require_module
from appcore.models import (
    ApiToken, App, NotificationLog, NotificationTemplate, ScheduledJob, WebhookDelivery, WebhookEndpoint,
)
from datamodels.models import DataModel, DataRecord
from wp_utils import get_app, require_app_role, validate_outbound_url


def _app(request, app_id: int, role: str = "viewer") -> App:
    app = get_app(app_id)
    require_app_role(request.user, app, role)
    return app


def _iso(value):
    return value.isoformat() if value else None


def _template_payload(item: NotificationTemplate) -> dict:
    return {
        "id": item.id, "key": item.key, "name": item.name, "channel": item.channel,
        "subject": item.subject, "content": item.content, "enabled": item.enabled,
        "variables": item.variables or [], "updated_at": _iso(item.updated_at),
    }


def _log_payload(item: NotificationLog) -> dict:
    return {
        "id": item.id, "channel": item.channel, "recipient": item.recipient,
        "subject": item.subject, "content": item.content, "status": item.status, "read_at": _iso(item.read_at),
        "error": item.error, "created_at": _iso(item.created_at),
    }


def _render(text: str, payload: dict) -> str:
    out = str(text or "")
    for key, value in (payload or {}).items():
        out = out.replace("{{" + str(key) + "}}", str(value))
    return out


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def app_messages(request, app_id: int):
    app = _app(request, app_id, "viewer")
    require_module(app, "notifications")
    qs = app.notification_logs.filter(
        models.Q(recipient="") | models.Q(recipient=request.user.username)
    ).order_by("-created_at")[:200]
    return Response({"results": [_log_payload(item) for item in qs]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def app_message_read(request, app_id: int, pk: int):
    app = _app(request, app_id, "viewer")
    require_module(app, "notifications")
    item = get_object_or_404(NotificationLog, app=app, pk=pk)
    if item.recipient and item.recipient != request.user.username:
        raise PermissionDenied("无权操作该消息")
    item.read_at = timezone.now()
    item.save(update_fields=["read_at"])
    return Response(_log_payload(item))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def notification_templates(request, app_id: int):
    app = _app(request, app_id, "viewer" if request.method == "GET" else "editor")
    require_module(app, "notifications")
    if request.method == "GET":
        return Response({"results": [_template_payload(item) for item in app.notification_templates.all()]})
    key = str(request.data.get("key") or "").strip()
    name = str(request.data.get("name") or "").strip()
    if not key or not name:
        raise ValidationError({"detail": "key 和 name 必填"})
    item, created = NotificationTemplate.objects.update_or_create(
        app=app, key=key,
        defaults={
            "name": name,
            "channel": str(request.data.get("channel") or "inapp"),
            "subject": str(request.data.get("subject") or ""),
            "content": str(request.data.get("content") or ""),
            "enabled": bool(request.data.get("enabled", True)),
            "variables": request.data.get("variables") or [],
        },
    )
    return Response(_template_payload(item), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def notification_template_detail(request, app_id: int, pk: int):
    item = get_object_or_404(NotificationTemplate.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "viewer" if request.method == "GET" else "editor")
    require_module(item.app, "notifications")
    if request.method == "GET":
        return Response(_template_payload(item))
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    for key in ("key", "name", "channel", "subject", "content"):
        if key in request.data:
            setattr(item, key, str(request.data[key] or ""))
    if "enabled" in request.data:
        item.enabled = bool(request.data["enabled"])
    if "variables" in request.data:
        item.variables = request.data["variables"] or []
    item.save()
    return Response(_template_payload(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_template_send(request, app_id: int, pk: int):
    item = get_object_or_404(NotificationTemplate.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "editor")
    require_module(item.app, "notifications")
    payload = request.data.get("payload") or {}
    recipient = str(request.data.get("recipient") or "").strip()
    subject = _render(item.subject, payload)
    content = _render(item.content, payload)
    error = ""
    status_value = "sent"
    try:
        if item.channel == "email":
            if not recipient:
                raise ValueError("邮件通知需要 recipient")
            send_mail(subject or item.name, content, None, [recipient], fail_silently=False)
        # 站内信/Webhook 先落通知日志，外部投递由 Webhook 服务处理。
    except Exception as exc:  # noqa: BLE001
        status_value = "failed"
        error = str(exc)
    log = NotificationLog.objects.create(
        app=item.app, template=item, channel=item.channel, recipient=recipient,
        subject=subject, content=content, status=status_value, error=error,
        payload=payload, created_by=request.user,
    )
    return Response(_log_payload(log), status=status.HTTP_201_CREATED if status_value == "sent" else status.HTTP_502_BAD_GATEWAY)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notification_logs(request, app_id: int):
    app = _app(request, app_id, "viewer")
    require_module(app, "notifications")
    return Response({"results": [_log_payload(item) for item in app.notification_logs.all()[:100]]})


# ---------------------------------------------------------------- API Token
def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token_payload(item: ApiToken) -> dict:
    return {
        "id": item.id, "name": item.name, "prefix": item.prefix,
        "scopes": item.scopes or [], "enabled": item.enabled,
        "expires_at": _iso(item.expires_at), "last_used_at": _iso(item.last_used_at),
        "created_at": _iso(item.created_at),
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def api_tokens(request, app_id: int):
    app = _app(request, app_id, "viewer" if request.method == "GET" else "owner")
    require_module(app, "api")
    if request.method == "GET":
        return Response({"results": [_token_payload(item) for item in app.api_tokens.all()]})
    name = str(request.data.get("name") or "").strip()
    if not name:
        raise ValidationError({"detail": "name 必填"})
    scopes = request.data.get("scopes") or ["records:read"]
    if not isinstance(scopes, list):
        raise ValidationError({"detail": "scopes 必须是数组"})
    days = int(request.data.get("expires_days") or 0)
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    token = f"mwp_{app.id}_{prefix}_{secret}"
    item = ApiToken.objects.create(
        app=app, name=name[:120], prefix=prefix, token_hash=_token_hash(token),
        scopes=[str(x) for x in scopes], expires_at=timezone.now() + timedelta(days=days) if days else None,
        created_by=request.user,
    )
    return Response({**_token_payload(item), "token": token}, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def api_token_detail(request, app_id: int, pk: int):
    item = get_object_or_404(ApiToken.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "owner")
    require_module(item.app, "api")
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if "enabled" in request.data:
        item.enabled = bool(request.data["enabled"])
    if "name" in request.data:
        item.name = str(request.data["name"] or "")[:120]
    item.save()
    return Response(_token_payload(item))


# ---------------------------------------------------------------- Webhook
def _webhook_payload(item: WebhookEndpoint) -> dict:
    return {
        "id": item.id, "name": item.name, "url": item.url, "events": item.events or [],
        "enabled": item.enabled, "last_status": item.last_status,
        "last_delivery_at": _iso(item.last_delivery_at), "created_at": _iso(item.created_at),
    }


def _delivery_payload(item: WebhookDelivery) -> dict:
    return {
        "id": item.id, "event": item.event, "status_code": item.status_code,
        "ok": item.ok, "response": item.response[:500], "error": item.error,
        "created_at": _iso(item.created_at),
    }


def deliver_webhook(endpoint: WebhookEndpoint, event: str, payload: dict) -> WebhookDelivery:
    body = json.dumps({"event": event, "app_id": endpoint.app_id, "payload": payload}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-WP-Event": event}
    if endpoint.secret:
        headers["X-WP-Signature"] = "sha256=" + hmac.new(endpoint.secret.encode(), body, hashlib.sha256).hexdigest()
    status_code = None
    response_text = ""
    error = ""
    ok = False
    try:
        req = urllib.request.Request(endpoint.url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            status_code = resp.status
            response_text = resp.read(1000).decode("utf-8", errors="replace")
            ok = 200 <= status_code < 300
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    delivery = WebhookDelivery.objects.create(
        endpoint=endpoint, event=event, payload=payload, status_code=status_code,
        ok=ok, response=response_text, error=error,
    )
    endpoint.last_status = "success" if ok else "failed"
    endpoint.last_delivery_at = timezone.now()
    endpoint.save(update_fields=["last_status", "last_delivery_at", "updated_at"])
    return delivery


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def webhooks(request, app_id: int):
    app = _app(request, app_id, "viewer" if request.method == "GET" else "editor")
    require_module(app, "api")
    if request.method == "GET":
        return Response({"results": [_webhook_payload(item) for item in app.webhooks.all()]})
    name = str(request.data.get("name") or "").strip()
    url = str(request.data.get("url") or "").strip()
    if not name or not url:
        raise ValidationError({"detail": "name 和 url 必填"})
    if not url.startswith(("http://", "https://")):
        raise ValidationError({"detail": "url 必须是 http/https"})
    validate_outbound_url(url)
    item = WebhookEndpoint.objects.create(
        app=app, name=name[:160], url=url[:500],
        secret=str(request.data.get("secret") or "")[:120],
        events=request.data.get("events") or [],
        enabled=bool(request.data.get("enabled", True)),
        created_by=request.user,
    )
    return Response(_webhook_payload(item), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def webhook_detail(request, app_id: int, pk: int):
    item = get_object_or_404(WebhookEndpoint.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "editor")
    require_module(item.app, "api")
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    for key in ("name", "url"):
        if key in request.data:
            setattr(item, key, str(request.data[key] or ""))
    if "events" in request.data:
        item.events = request.data["events"] or []
    if "enabled" in request.data:
        item.enabled = bool(request.data["enabled"])
    if "secret" in request.data:
        item.secret = str(request.data["secret"] or "")[:120]
    item.save()
    return Response(_webhook_payload(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def webhook_test(request, app_id: int, pk: int):
    item = get_object_or_404(WebhookEndpoint.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "editor")
    require_module(item.app, "api")
    delivery = deliver_webhook(item, "webhook.test", {"message": "MiWebProcess webhook test"})
    return Response(_delivery_payload(delivery))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def webhook_deliveries(request, app_id: int, pk: int):
    item = get_object_or_404(WebhookEndpoint.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "viewer")
    require_module(item.app, "api")
    return Response({"results": [_delivery_payload(x) for x in item.deliveries.all()[:50]]})


# ---------------------------------------------------------------- Scheduled Job
def _job_payload(item: ScheduledJob) -> dict:
    return {
        "id": item.id, "name": item.name, "code": item.code, "handler": item.handler,
        "cron": item.cron, "enabled": item.enabled, "payload": item.payload,
        "last_run_at": _iso(item.last_run_at), "last_status": item.last_status,
        "last_error": item.last_error, "created_at": _iso(item.created_at),
    }


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def scheduled_jobs(request, app_id: int):
    app = _app(request, app_id, "viewer" if request.method == "GET" else "editor")
    require_module(app, "workflow")
    if request.method == "GET":
        return Response({"results": [_job_payload(item) for item in app.scheduled_jobs.all()]})
    name = str(request.data.get("name") or "").strip()
    code = str(request.data.get("code") or "").strip()
    if not name or not code:
        raise ValidationError({"detail": "name 和 code 必填"})
    item, created = ScheduledJob.objects.update_or_create(
        app=app, code=code,
        defaults={
            "name": name[:160], "handler": str(request.data.get("handler") or "noop"),
            "cron": str(request.data.get("cron") or "0 2 * * *"),
            "payload": request.data.get("payload") or {},
            "enabled": bool(request.data.get("enabled", True)),
            "created_by": request.user,
        },
    )
    return Response(_job_payload(item), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def scheduled_job_detail(request, app_id: int, pk: int):
    item = get_object_or_404(ScheduledJob.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "editor")
    require_module(item.app, "api")
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    for key in ("name", "handler", "cron"):
        if key in request.data:
            setattr(item, key, str(request.data[key] or ""))
    if "payload" in request.data:
        item.payload = request.data["payload"] or {}
    if "enabled" in request.data:
        item.enabled = bool(request.data["enabled"])
    item.save()
    return Response(_job_payload(item))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def scheduled_job_run(request, app_id: int, pk: int):
    item = get_object_or_404(ScheduledJob.objects.select_related("app"), pk=pk)
    _app(request, item.app_id, "editor")
    require_module(item.app, "workflow")
    result = {"ok": True}
    try:
        if item.handler == "webhook.test":
            endpoint = item.app.webhooks.filter(enabled=True).first()
            if endpoint is None:
                raise ValueError("没有启用的 Webhook")
            delivery = deliver_webhook(endpoint, "job.webhook.test", {"job": item.code})
            result = {"ok": delivery.ok, "delivery_id": delivery.id}
        elif item.handler == "notification.test":
            log = NotificationLog.objects.create(
                app=item.app, channel="inapp", recipient="job", subject=f"定时任务 {item.name}",
                content=json.dumps(item.payload or {}, ensure_ascii=False), status="sent",
            )
            result = {"ok": True, "log_id": log.id}
        item.last_status = "success" if result.get("ok") else "failed"
        item.last_error = "" if result.get("ok") else str(result)
    except Exception as exc:  # noqa: BLE001
        item.last_status = "failed"
        item.last_error = str(exc)
        result = {"ok": False, "error": str(exc)}
    item.last_run_at = timezone.now()
    item.save(update_fields=["last_run_at", "last_status", "last_error", "updated_at"])
    return Response({**result, "job": _job_payload(item)})


# ---------------------------------------------------------------- Open Records API
def _open_token(request, app_code: str):
    raw = request.headers.get("X-API-Key") or ""
    auth = request.headers.get("Authorization") or ""
    if not raw and auth.lower().startswith("bearer "):
        raw = auth[7:].strip()
    if not raw.startswith(f"mwp_") or not raw:
        raise PermissionDenied("缺少应用 API Token")
    token = ApiToken.objects.select_related("app").filter(token_hash=_token_hash(raw), enabled=True).first()
    if token is None or token.app.code != app_code:
        raise PermissionDenied("API Token 无效")
    if token.expires_at and token.expires_at < timezone.now():
        raise PermissionDenied("API Token 已过期")
    token.last_used_at = timezone.now()
    token.save(update_fields=["last_used_at"])
    return token


def _require_scope(token: ApiToken, scope: str):
    if scope not in (token.scopes or []):
        raise PermissionDenied(f"Token 缺少权限：{scope}")


def _dispatch_event(app, event: str, payload: dict) -> None:
    for endpoint in app.webhooks.filter(enabled=True):
        events = endpoint.events or []
        if events and event not in events:
            continue
        try:
            deliver_webhook(endpoint, event, payload)
        except Exception:
            pass


def _record_payload(record: DataRecord) -> dict:
    return {"id": record.id, "data": record.data, "created_at": _iso(record.created_at), "updated_at": _iso(record.updated_at)}


def _open_model(app_code: str, model_id: int) -> DataModel:
    model = get_object_or_404(DataModel.objects.select_related("app"), pk=model_id)
    if model.app.code != app_code:
        raise PermissionDenied("模型不属于该应用")
    require_module(model.app, module_for_model(model.name))
    return model


@api_view(["GET", "POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def open_records(request, app_code: str, model_id: int):
    token = _open_token(request, app_code)
    model = _open_model(app_code, model_id)
    if request.method == "GET":
        _require_scope(token, "records:read")
        rows = model.records.order_by("-id")[:100]
        return Response({"results": [_record_payload(x) for x in rows], "count": model.records.count()})
    _require_scope(token, "records:write")
    data = request.data.get("data", request.data)
    if not isinstance(data, dict):
        raise ValidationError({"detail": "data 必须是对象"})
    record = DataRecord.objects.create(model=model, data=data, created_by=token.created_by, updated_by=token.created_by)
    _dispatch_event(model.app, "record.created", _record_payload(record))
    return Response(_record_payload(record), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@authentication_classes([])
@permission_classes([AllowAny])
def open_record_detail(request, app_code: str, model_id: int, pk: int):
    token = _open_token(request, app_code)
    model = _open_model(app_code, model_id)
    record = get_object_or_404(DataRecord, model=model, pk=pk)
    if request.method == "GET":
        _require_scope(token, "records:read")
        return Response(_record_payload(record))
    _require_scope(token, "records:write")
    if request.method == "DELETE":
        record.delete()
        _dispatch_event(model.app, "record.deleted", {"id": record.id, "model_id": model.id})
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = request.data.get("data", request.data)
    if not isinstance(data, dict):
        raise ValidationError({"detail": "data 必须是对象"})
    record.data = {**(record.data or {}), **data}
    record.updated_by = token.created_by
    record.save(update_fields=["data", "updated_by", "updated_at"])
    _dispatch_event(model.app, "record.updated", _record_payload(record))
    return Response(_record_payload(record))
