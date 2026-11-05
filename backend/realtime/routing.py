"""WebSocket 路由（config/asgi.py 引用 websocket_urlpatterns）。"""
import re

from django.urls import re_path

from collab.lock_routing import websocket_urlpatterns as designer_lock_urlpatterns
from pages.schema_consumer import websocket_urlpatterns as designer_schema_urlpatterns
from pages.schema_ops_consumer import websocket_urlpatterns as designer_ops_urlpatterns
from realtime.consumers import AppWebSocket

websocket_urlpatterns = [
    re_path(r"^ws/(?P<app_id>\d+)/$", AppWebSocket.as_asgi()),
    *designer_lock_urlpatterns,
    *designer_schema_urlpatterns,
    *designer_ops_urlpatterns,
]
