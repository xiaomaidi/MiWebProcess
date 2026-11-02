"""应用事件总线：Webhook + 通知模板 + 站内信日志。"""
from __future__ import annotations

import json

from appcore.models import NotificationLog, NotificationTemplate


def _render(text: str, payload: dict) -> str:
    out = str(text or "")
    for key, value in (payload or {}).items():
        out = out.replace("{{" + str(key) + "}}", str(value))
    return out


def emit_event(app, event: str, payload: dict) -> None:
    if app is None:
        return
    from appcore.service_views import deliver_webhook

    # Webhook
    for endpoint in app.webhooks.filter(enabled=True):
        events = endpoint.events or []
        if events and event not in events:
            continue
        try:
            deliver_webhook(endpoint, event, payload)
        except Exception:
            pass

    # 站内信 / 通知模板：模板 key 可写 workflow.approved 或 workflow_approved
    normalized = event.replace(".", "_")
    for template in NotificationTemplate.objects.filter(app=app, enabled=True):
        if template.key not in (event, normalized, "*"):
            continue
        try:
            log = NotificationLog.objects.create(
                app=app, template=template, channel=template.channel, recipient="",
                subject=_render(template.subject, payload),
                content=_render(template.content, payload),
                status="sent", payload=payload,
            )
        except Exception:
            continue
