from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from appcore.models import ScheduledJob


def _match_part(expr: str, value: int) -> bool:
    expr = str(expr or "*").strip()
    if expr in ("*", "?"):
        return True
    for chunk in expr.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.startswith("*/"):
            try:
                step = int(chunk[2:])
            except ValueError:
                continue
            if step > 0 and value % step == 0:
                return True
        elif "-" in chunk:
            try:
                a, b = [int(x) for x in chunk.split("-", 1)]
            except ValueError:
                continue
            if a <= value <= b:
                return True
        else:
            try:
                if int(chunk) == value:
                    return True
            except ValueError:
                continue
    return False


def cron_matches(cron: str, now: datetime) -> bool:
    parts = str(cron or "").split()
    if len(parts) != 5:
        return False
    minute, hour, day, month, weekday = parts
    # Python weekday: Monday=0; cron: Sunday=0.
    cron_weekday = (now.weekday() + 1) % 7
    return (
        _match_part(minute, now.minute)
        and _match_part(hour, now.hour)
        and _match_part(day, now.day)
        and _match_part(month, now.month)
        and _match_part(weekday, cron_weekday)
    )


class Command(BaseCommand):
    help = "执行到期的应用级定时任务；建议由系统 cron 每分钟调用一次。"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="忽略 cron 时间匹配，执行全部启用的任务")

    def handle(self, *args, **options):
        from appcore.service_views import scheduled_job_run
        from rest_framework.test import APIRequestFactory

        now = timezone.localtime()
        ran = 0
        for job in ScheduledJob.objects.select_related("app").filter(enabled=True):
            if not options["force"] and not cron_matches(job.cron, now):
                continue
            if job.last_run_at and timezone.localtime(job.last_run_at).strftime("%Y%m%d%H%M") == now.strftime("%Y%m%d%H%M"):
                continue
            request = APIRequestFactory().post("/")
            request.user = job.created_by or job.app.owner
            try:
                scheduled_job_run(request, job.app_id, job.id)
                ran += 1
            except Exception as exc:  # noqa: BLE001
                job.last_status = "failed"
                job.last_error = str(exc)
                job.last_run_at = timezone.now()
                job.save(update_fields=["last_status", "last_error", "last_run_at", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"run_app_jobs: executed={ran}"))
