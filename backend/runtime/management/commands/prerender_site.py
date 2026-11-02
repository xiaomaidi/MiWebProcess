"""静态预渲染：把公开页面和已发布文章输出为静态 HTML。

用法：
    python manage.py prerender_site --app demo-portal --output static_prerender
"""
from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from appcore.models import App
from datamodels.models import DataModel, DataRecord
from runtime.views import _article_node, _article_path_pattern, _bundle_for_app


class Command(BaseCommand):
    help = "生成公开页面/文章的静态 HTML（SEO 预渲染）"

    def add_arguments(self, parser):
        parser.add_argument("--app", required=True, help="应用 code，例如 demo-portal")
        parser.add_argument("--output", default="static_prerender", help="输出目录")

    def handle(self, *args, **options):
        code = options["app"]
        output = os.path.abspath(options["output"])
        app = App.objects.filter(code=code).first()
        if app is None:
            raise CommandError(f"应用不存在: {code}")
        bundle = _bundle_for_app(app)
        if bundle is None:
            raise CommandError("应用没有生效发布，无法预渲染")

        paths: list[str] = []
        for path in (bundle.get("pages") or {}):
            if ":" in path or "*" in path:
                continue
            paths.append(path.strip("/"))

        article_pattern = _article_path_pattern(bundle)
        article_model_ids = set()
        if article_pattern:
            for page_data in bundle["pages"].values():
                node = _article_node(page_data)
                try:
                    article_model_ids.add(int((node or {}).get("props", {}).get("dataModelId") or 0))
                except (TypeError, ValueError):
                    pass
            for model in DataModel.objects.filter(app=app, id__in=article_model_ids, is_public=True):
                fields = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
                for record in DataRecord.objects.filter(model=model):
                    if "status" in fields and (record.data or {}).get("status") != "published":
                        continue
                    paths.append(article_pattern.replace(":id", str(record.id)).strip("/"))

        client = Client()
        written = 0
        for path in sorted(set(paths)):
            resp = client.get(f"/api/runtime/{code}/prerender/{path}/")
            if resp.status_code != 200:
                self.stderr.write(f"skip {path}: HTTP {resp.status_code}")
                continue
            target_dir = os.path.join(output, *[p for p in path.split("/") if p])
            os.makedirs(target_dir, exist_ok=True)
            with open(os.path.join(target_dir, "index.html"), "w", encoding="utf-8") as fh:
                fh.write(resp.content.decode("utf-8"))
            written += 1
        self.stdout.write(self.style.SUCCESS(f"prerendered {written} pages -> {output}"))
