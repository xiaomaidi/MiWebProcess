from django.apps import AppConfig


class ReleasesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"

    name = "releases"

    def ready(self):
        # 确保 celery app 与 tasks 注册（无 broker 时仅 import，不连接）
        try:
            from config import celery_app  # noqa: F401
        except Exception:
            pass
