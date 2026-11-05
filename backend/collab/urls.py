from django.urls import include, path

from . import views

urlpatterns = [
    path("pages/<int:page_id>/comments/", views.page_comments, name="page-comments"),
    path("comments/<int:pk>/", views.comment_detail, name="comment-detail"),
    # 通知中心：正式对外路径是 /api/notifications/（见 collab/notification_urls.py），
    # 这里同时挂在 /api/collab/notifications/ 以便未改 config/urls.py 时也可用。
    path("notifications/", include("collab.notification_urls")),
]
