"""设计器锁 WebSocket 路由；由 ``realtime.routing`` 汇总到 ASGI。"""
from django.urls import re_path

from .lock_consumer import DesignerLockConsumer

websocket_urlpatterns = [
    re_path(r"^ws/designer-lock/(?P<page_id>\d+)/$", DesignerLockConsumer.as_asgi()),
]
