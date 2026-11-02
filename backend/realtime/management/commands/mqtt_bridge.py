"""MQTT 桥接进程：python manage.py mqtt_bridge [--check]"""
from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError

from realtime.mqtt import broker_config, get_bridge, is_available


class Command(BaseCommand):
    help = "运行 MQTT ↔ WebSocket 桥接（需要 MQTT_ENABLED=1 与 MQTT_BROKER_URL）"

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="只检查配置与依赖后退出")

    def handle(self, *args, **options):
        cfg = broker_config()
        self.stdout.write(
            f"MQTT broker={cfg['url'] or '(未配置)'} enabled={cfg['enabled']} paho={'已安装' if is_available() else '未安装'}"
        )
        if options.get("check"):
            return
        if not is_available():
            raise CommandError("未安装 paho-mqtt：pip install paho-mqtt")
        bridge = get_bridge()
        if not bridge.start():
            raise CommandError(f"连接失败：{bridge.last_error}")
        self.stdout.write(self.style.SUCCESS("桥接已启动，Ctrl+C 退出"))
        try:
            while True:
                time.sleep(5)
                status = bridge.status()
                if not status["connected"]:
                    self.stderr.write(f"[warn] 连接断开：{status['last_error']}")
        except KeyboardInterrupt:
            bridge.stop()
            self.stdout.write("已停止")
