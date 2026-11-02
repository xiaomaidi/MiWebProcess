"""持久化 AI 建站任务：Celery worker 可重启后续跑。"""
from __future__ import annotations

from celery import shared_task


@shared_task(bind=True, max_retries=2, default_retry_delay=15)
def run_autobuild_job(self, job_id: int):
    from ai.autobuild import run_job

    try:
        run_job(job_id)
        return {"job_id": job_id, "ok": True}
    except Exception as exc:  # noqa: BLE001
        # run_job 已把失败写回 AiBuildJob；Celery 只记录任务层错误。
        return {"job_id": job_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
