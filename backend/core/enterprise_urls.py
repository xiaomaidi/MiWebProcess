"""企业运维控制台 URL（新增，独立挂载）。

集成步骤（唯一需要修改的既有文件是 config/urls.py）：

    path("api/enterprise/", include("core.enterprise_urls")),

之后即可访问：
    GET  /api/enterprise/overview/
    GET  /api/enterprise/backups/
    POST /api/enterprise/backups/

无需新增 INSTALLED_APPS（core 已在其中），无需迁移。
"""
from django.urls import path

from core import enterprise_views

urlpatterns = [
    path("overview/", enterprise_views.overview, name="enterprise-overview"),
    path("backups/", enterprise_views.backups, name="enterprise-backups"),
]
