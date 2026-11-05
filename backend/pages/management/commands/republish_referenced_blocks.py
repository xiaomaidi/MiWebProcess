"""检查/补发页面引用的可复用区块。

用法示例::

    python manage.py republish_referenced_blocks --app demo
    python manage.py republish_referenced_blocks --app 12 --include-drafts
    python manage.py republish_referenced_blocks --dry-run

命令只发布 ``wp-block`` 引用的区块页面，不会重新发布宿主页面，也不会触发应用
release；因此可用于修复“宿主页已发布但区块仍是草稿”的线上数据。
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from pages.block_publish import MAX_BLOCK_DEPTH, auto_publish_referenced_blocks, check_block_references
from pages.models import Page


class Command(BaseCommand):
    help = "检查页面 wp-block 引用并自动发布引用的区块（默认扫描已发布页面）"

    def add_arguments(self, parser):
        parser.add_argument("--app", default="", help="应用 id 或 code；缺省扫描全部应用")
        parser.add_argument("--page", type=int, default=0, help="仅处理指定页面 id")
        parser.add_argument(
            "--include-drafts",
            action="store_true",
            help="同时处理草稿页面（默认仅处理已发布页面）",
        )
        parser.add_argument("--dry-run", action="store_true", help="只检查引用，不创建 PageVersion")
        parser.add_argument(
            "--max-depth",
            type=int,
            default=MAX_BLOCK_DEPTH,
            help=f"区块嵌套深度上限（默认 {MAX_BLOCK_DEPTH}）",
        )

    def handle(self, *args, **options):
        from appcore.models import App

        app_param = str(options.get("app") or "").strip()
        page_id = int(options.get("page") or 0)
        include_drafts = bool(options.get("include_drafts"))
        dry_run = bool(options.get("dry_run"))
        max_depth = int(options.get("max_depth") or MAX_BLOCK_DEPTH)

        pages = Page.objects.select_related("app").exclude(type="fragment")
        if app_param:
            if app_param.isdigit():
                app = App.objects.filter(pk=int(app_param)).first()
            else:
                app = App.objects.filter(code=app_param).first()
            if app is None:
                raise CommandError(f"应用不存在: {app_param}")
            pages = pages.filter(app=app)
        if page_id:
            pages = pages.filter(pk=page_id)
        if not include_drafts:
            pages = pages.filter(status="published")
        pages = pages.order_by("app_id", "id")

        totals = {
            "pages": 0,
            "published": 0,
            "skipped": 0,
            "missing": 0,
            "cycles": 0,
            "depth_limited": 0,
        }
        for page in pages.iterator():
            totals["pages"] += 1
            if dry_run:
                graph = check_block_references(page.app, page.schema or {}, max_depth=max_depth)
                published = []
                skipped = []
                warnings = [
                    str(entry.get("message"))
                    for bucket in ("missing", "cycles", "depth_limited")
                    for entry in graph.get(bucket, [])
                    if entry.get("message")
                ]
                missing = graph.get("missing") or []
                cycles = graph.get("cycles") or []
                depth_limited = graph.get("depth_limited") or []
            else:
                report = auto_publish_referenced_blocks(page, None, max_depth=max_depth)
                published = report.get("published") or []
                skipped = report.get("skipped") or []
                warnings = report.get("warnings") or []
                missing = report.get("missing") or []
                cycles = report.get("cycles") or []
                depth_limited = report.get("depth_limited") or []

            totals["published"] += len(published)
            totals["skipped"] += len(skipped)
            totals["missing"] += len(missing)
            totals["cycles"] += len(cycles)
            totals["depth_limited"] += len(depth_limited)
            if not (published or skipped or warnings):
                continue
            prefix = "[dry-run] " if dry_run else ""
            self.stdout.write(self.style.MIGRATE_HEADING(f"{prefix}{page.app.code}/{page.path} (page {page.id})"))
            for item in published:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  published block {item.get('code')} "
                        f"v{item.get('version')} → {item.get('page_path')}"
                    )
                )
            for item in skipped:
                self.stdout.write(f"  skipped block {item.get('code')}: {item.get('reason')}")
            for message in warnings:
                self.stdout.write(self.style.WARNING(f"  warning: {message}"))

        summary = (
            "pages={pages} published={published} skipped={skipped} "
            "missing={missing} cycles={cycles} depth_limited={depth_limited}"
        ).format(**totals)
        if dry_run:
            self.stdout.write(self.style.SUCCESS(f"dry-run done: {summary}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"republish done: {summary}"))
