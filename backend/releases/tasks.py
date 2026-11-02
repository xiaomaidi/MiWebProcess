"""Celery 任务：发布 bundle 编译。

由 config.celery_app 的 autodiscover_tasks() 自动注册；
无 broker/worker 时由 releases.services 内联执行同一段逻辑。
"""
from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def compile_release_task(self, release_id: int):
    from releases.services import run_compile_pipeline

    ok = run_compile_pipeline(release_id)
    if not ok:
        raise self.retry(exc=RuntimeError(f"release {release_id} failed"))
    return {"release_id": release_id, "ok": True}
