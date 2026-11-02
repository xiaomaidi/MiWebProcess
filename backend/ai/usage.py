"""AI 用量估算与统计。"""
from __future__ import annotations

from django.db.models import Count, Sum

from ai.models import AiUsageLog


def record_usage(*, user, app, action: str, provider: str, model: str, prompt: str, response: str = "", success: bool = True, error: str = ""):
    prompt_chars = len(str(prompt or ""))
    response_chars = len(str(response or ""))
    AiUsageLog.objects.create(
        user=user,
        app=app,
        action=action,
        provider=str(provider or "")[:120],
        model=str(model or "")[:160],
        prompt_chars=prompt_chars,
        response_chars=response_chars,
        estimated_tokens=max(1, (prompt_chars + response_chars) // 4),
        success=success,
        error=str(error or "")[:500],
    )


def usage_summary(limit: int = 50):
    qs = AiUsageLog.objects.select_related("user", "app")
    totals = qs.aggregate(
        calls=Count("id"),
        tokens=Sum("estimated_tokens"),
        prompt_chars=Sum("prompt_chars"),
        response_chars=Sum("response_chars"),
    )
    by_action = list(qs.values("action").annotate(calls=Count("id"), tokens=Sum("estimated_tokens")).order_by("-calls"))
    recent = [
        {
            "id": row.id,
            "action": row.action,
            "provider": row.provider,
            "model": row.model,
            "estimated_tokens": row.estimated_tokens,
            "success": row.success,
            "user": row.user.username if row.user else "",
            "app": row.app.name if row.app else "",
            "created_at": row.created_at,
        }
        for row in qs[:limit]
    ]
    return {"totals": totals, "by_action": by_action, "recent": recent}
