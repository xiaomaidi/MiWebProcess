"""公开 SSO 登录流程路由（挂载于 /api/auth/sso/）。"""
from django.urls import path

from enterprise_sso import views

urlpatterns = [
    path("<str:app_code>/providers/", views.public_providers, name="sso_public_providers"),
    path("<str:app_code>/<str:provider_slug>/start/", views.start, name="sso_start"),
    path("<str:app_code>/<str:provider_slug>/callback/", views.callback, name="sso_callback"),
]
