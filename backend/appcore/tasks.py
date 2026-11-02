from __future__ import annotations

from celery import shared_task
from django.core.management import call_command


@shared_task(name="appcore.tasks.run_due_app_jobs")
def run_due_app_jobs():
    """Celery Beat 每分钟触发：执行到期的应用级定时任务。"""
    call_command("run_app_jobs")
    return "ok"
