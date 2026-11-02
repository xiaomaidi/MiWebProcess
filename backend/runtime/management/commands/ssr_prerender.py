"""生成 SSR / SSG 快照：python manage.py ssr_prerender [--app code] [--output dir]

依赖前端 SSR 产物：
    cd frontend
    vite build                 # 生成 dist/（CSS/JS 资源）
    vite build --ssr src/ssr/entry-server.ts --outDir dist-ssr
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from appcore.models import App
from pages.models import Page
from runtime.ssr import page_targets, ssr_available, write_snapshot


class Command(BaseCommand):
    help = "用前端 SSR 产物生成静态页面（HTML + 水合状态）"

    def add_arguments(self, parser):
        parser.add_argument("--app", dest="app_code", help="只处理指定应用 code")
        parser.add_argument("--output", dest="output", help="输出目录（默认 settings.PRERENDER_DIR）")
        parser.add_argument("--page", dest="page", help="只渲染指定页面路径")

    def handle(self, *args, **options):
        if not ssr_available():
            raise CommandError(
                "未找到 SSR 产物。请先执行：cd frontend && vite build --ssr src/ssr/entry-server.ts --outDir dist-ssr"
            )
        output = Path(options.get("output") or settings.PRERENDER_DIR)
        output.mkdir(parents=True, exist_ok=True)
        apps = App.objects.all()
        if options.get("app_code"):
            apps = apps.filter(code=options["app_code"])
            if not apps.exists():
                raise CommandError(f"应用不存在: {options['app_code']}")
        manifest = []
        for app in apps:
            pages = Page.objects.filter(app=app, status="published")
            if options.get("page"):
                pages = pages.filter(path=options["page"])
            for page in pages:
                for target in page_targets(page):
                    result = write_snapshot(app, target, output)
                    if result is None:
                        self.stderr.write(f"[skip] {app.code}/{target} 渲染失败")
                        continue
                    manifest.append({"app": app.code, **result})
                    self.stdout.write(self.style.SUCCESS(f"[ok] {app.code}/{target} ({result['bytes']} bytes)"))
        (output / "manifest.json").write_text(
            json.dumps({"generated_at": datetime.now().isoformat(), "items": manifest}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.stdout.write(self.style.SUCCESS(f"完成：{len(manifest)} 个页面 → {output}"))
