from django.urls import path

from realtime import views

urlpatterns = [
    path("channels/", views.channel_list_create, name="realtime-channels"),
    path("channels/<int:pk>/", views.channel_detail, name="realtime-channel-detail"),
    path("channels/<int:pk>/publish/", views.channel_publish, name="realtime-channel-publish"),
    path("channels/<int:pk>/messages/", views.channel_messages, name="realtime-channel-messages"),
    path("messages/", views.app_messages, name="realtime-messages"),
    path("publish/", views.publish_by_topic, name="realtime-publish"),
    path("status/", views.realtime_status, name="realtime-status"),
    path("cleanup/", views.realtime_cleanup, name="realtime-cleanup"),
]
