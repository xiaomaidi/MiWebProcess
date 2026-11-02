"""重建搜索索引：python manage.py rebuild_search_index [--app code] [--all]"""
from django.core.management.base import BaseCommand, CommandError

from appcore.models import App
from search.services import rebuild_all, rebuild_app


class Command(BaseCommand):
    help = "重建搜索索引（默认重建全部应用）"

    def add_arguments(self, parser):
        parser.add_argument("--app", dest="app_code", help="只重建指定应用 code")
        parser.add_argument("--all", action="store_true", help="重建全部应用（默认行为）")

    def handle(self, *args, **options):
        app_code = options.get("app_code")
        if app_code:
            app = App.objects.filter(code=app_code).first()
            if app is None:
                raise CommandError(f"应用不存在: {app_code}")
            result = rebuild_app(app)
            self.stdout.write(self.style.SUCCESS(f"{app.code}: 删除 {result['deleted']}，写入 {result['created']}"))
            return
        result = rebuild_all()
        self.stdout.write(
            self.style.SUCCESS(f"完成：{len(result['apps'])} 个应用，删除 {result['deleted']}，写入 {result['created']}")
        )
