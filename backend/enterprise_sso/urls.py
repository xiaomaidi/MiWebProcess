"""应用级 SSO 配置 API 路由（挂载于 /api/apps/<app_id>/sso/）。"""
from django.urls import path

from enterprise_sso import views

urlpatterns = [
    path("providers/", views.provider_list_create, name="sso_provider_list"),
    path("providers/<int:pk>/", views.provider_detail, name="sso_provider_detail"),
]
