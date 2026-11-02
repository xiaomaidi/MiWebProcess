"""WebSocket 路由（config/asgi.py 引用 websocket_urlpatterns）。"""
import re

from django.urls import re_path

from realtime.consumers import AppWebSocket

websocket_urlpatterns = [
    re_path(r"^ws/(?P<app_id>\d+)/$", AppWebSocket.as_asgi()),
]
