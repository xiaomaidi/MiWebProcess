"""通知中心路由（挂在 /api/notifications/ 下）。

`config/urls.py` 需要增加一行（本次改动不改 config，交由上层集成）：

    path("api/notifications/", include("collab.notification_urls")),

为了让本地在没有改 config 时也能用，`collab/urls.py` 同时把它挂在
`/api/collab/notifications/` 下（前端会优先请求 /api/notifications/，
404 时回退到 /api/collab/notifications/）。
"""
from django.urls import path

from . import views

urlpatterns = [
    path("read-all/", views.notifications_read_all, name="notifications-read-all"),
    path("<int:pk>/read/", views.notification_read, name="notification-read"),
    path("", views.notifications_feed, name="notifications-list"),
]
