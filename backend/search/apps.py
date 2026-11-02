from django.apps import AppConfig


class SearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "search"
    verbose_name = "搜索索引"

    def ready(self):
        # 注册记录写入后的增量索引信号。
        from search import signals  # noqa: F401
