"""发布业务：bundle 编译 / 存储 / 激活 / 回滚 / 灰度。"""
from __future__ import annotations

import json

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from releases.models import Release, ReleaseTask


def compile_bundle(app) -> dict:
    """把已发布页面的 PageVersion 快照汇总为 bundle。"""
    pages: dict = {}
    for page in app.pages.all():
        last = page.versions.order_by("-version").first()
        if last is None:
            continue
        pages[page.path] = {
            "schema": last.schema,
            "schemaVersion": last.schema_version,
            "version": last.version,
        }
    return {
        "app": {"id": app.id, "name": app.name, "code": app.code},
        "pages": pages,
    }


def store_bundle(app, release: Release, bundle: dict) -> str:
    """bundle JSON → 对象存储（MinIO/local），返回可访问 URL。"""
    key = f"releases/{app.code}/{release.version}/bundle.json"
    body = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
    # 删除/重建应用会复用同名 release 版本目录；storage 默认会生成后缀，必须覆盖旧文件。
    if default_storage.exists(key):
        default_storage.delete(key)
    default_storage.save(key, ContentFile(body, name="bundle.json"))
    from django.conf import settings

    url = f"{settings.MEDIA_URL}{key}"
    return url


def get_active_release(app) -> Release | None:
    return Release.objects.filter(app=app, status="active").order_by("-version").first()


def _broadcast_task_update(app_id: int, task_id: int, status: str) -> None:
    """WS 通知（API.md §9）：{"type":"task_update","task_id":..,"status":..,"ts":..}。"""
    try:
        from wp_utils import broadcast_to_app

        broadcast_to_app(
            app_id,
            {
                "type": "task_update",
                "payload": {"task_id": task_id, "status": status},
                "extra": {"task_id": task_id, "status": status},
            },
        )
    except Exception:
        pass


def _mark_done(release: Release, task: ReleaseTask, message: str) -> None:
    task.status = "done"
    task.log = message
    task.save(update_fields=["status", "log", "updated_at"])
    release.status = "active"
    release.traffic_ratio = 100
    release.error = ""
    release.save(update_fields=["status", "traffic_ratio", "error", "updated_at"])
    _broadcast_task_update(release.app_id, task.id, "success")


def _mark_failed(release: Release, task: ReleaseTask, err: str) -> None:
    task.status = "failed"
    task.log = err
    task.save(update_fields=["status", "log", "updated_at"])
    release.status = "failed"
    release.error = err
    release.save(update_fields=["status", "error", "updated_at"])
    _broadcast_task_update(release.app_id, task.id, "failed")


def run_compile_pipeline(release_id: int) -> bool:
    """同步执行发布流水线（celery 任务体；不可用时内联调用同一函数）。"""
    release = Release.objects.select_related("app").get(id=release_id)
    task = ReleaseTask.objects.filter(release=release).order_by("-created_at").first()
    if task is None:
        task = ReleaseTask.objects.create(release=release)
    task.status = "running"
    task.save(update_fields=["status", "updated_at"])
    release.status = "releasing"
    release.save(update_fields=["status", "updated_at"])
    try:
        bundle = compile_bundle(release.app)
        if not bundle["pages"]:
            raise RuntimeError("没有可发布的已发布页面")
        page_versions = {}
        for page in release.app.pages.all():
            last = page.versions.order_by("-version").first()
            if last is not None:
                page_versions[str(page.id)] = last.id
        release.page_versions = page_versions
        release.bundle_url = store_bundle(release.app, release, bundle)
        release.save(update_fields=["bundle_url", "page_versions", "updated_at"])
        old_active = get_active_release(release.app)
        if old_active and old_active.id != release.id:
            old_active.status = "rollback"
            old_active.traffic_ratio = 0
            old_active.save(update_fields=["status", "traffic_ratio", "updated_at"])
        release.previous_release = old_active
        _mark_done(release, task, f"published pages={len(bundle['pages'])}")
        _clear_runtime_cache(release.app.code)
        return True
    except Exception as e:  # noqa: BLE001
        _mark_failed(release, task, f"{type(e).__name__}: {e}")
        return False


def schedule_release_for_app(app, changelog: str = "", trigger: str = "manual", user=None) -> tuple[Release, str]:
    """创建 pending 发布并调度；celery 不可用时同步内联执行。"""
    last = Release.objects.filter(app=app).order_by("-version").first()
    version = (last.version + 1) if last else 1
    release = Release.objects.create(
        app=app,
        version=version,
        status="pending",
        changelog=changelog or "",
        created_by=user,
    )
    ReleaseTask.objects.create(release=release)
    try:
        from releases.tasks import compile_release_task

        compile_release_task.delay(release.id)
        return release, "queued"
    except Exception:
        run_compile_pipeline(release.id)
        return release, "inline"


def activate_release(release: Release) -> Release:
    """手动把已有 bundle 的发布设为 active。"""
    if not release.bundle_url:
        raise ValueError("该发布没有 bundle，无法激活")
    old_active = get_active_release(release.app)
    if old_active and old_active.id != release.id:
        old_active.status = "rollback"
        old_active.traffic_ratio = 0
        old_active.save(update_fields=["status", "traffic_ratio", "updated_at"])
    release.previous_release = old_active
    release.status = "active"
    release.traffic_ratio = 100
    release.error = ""
    release.save()
    _clear_runtime_cache(release.app.code)
    return release


def rollback_release(release: Release) -> Release:
    """把当前 active 流量清零，重新激活其 previous_release。"""
    target = release.previous_release
    if target is None:
        raise ValueError("没有可回滚到的上一个发布")
    active = get_active_release(release.app)
    if active and active.id != target.id:
        active.status = "rollback"
        active.traffic_ratio = 0
        active.save(update_fields=["status", "traffic_ratio", "updated_at"])
    if release.id != target.id:
        release.status = "rollback"
        release.traffic_ratio = 0
        release.save(update_fields=["status", "traffic_ratio", "updated_at"])
    target.status = "active"
    target.traffic_ratio = 100
    target.error = ""
    target.save(update_fields=["status", "traffic_ratio", "error", "updated_at"])
    _clear_runtime_cache(release.app.code)
    return target


def _clear_runtime_cache(app_code: str) -> None:
    try:
        from django.core.cache import cache

        cache.delete_many([f"runtime_bundle:{app_code}", f"runtime_bundle:{app_code}:latest"])
    except Exception:
        pass
