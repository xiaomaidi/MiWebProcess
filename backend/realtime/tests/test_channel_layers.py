"""Channel Layer 配置 helper 与 check_realtime_channels 命令测试（无需真实 Redis）。"""
from __future__ import annotations

import os
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from config.settings import (
    DEFAULT_CHANNEL_LAYER_CAPACITY,
    DEFAULT_CHANNEL_LAYER_EXPIRY,
    _env_int,
    build_caches,
    build_channel_layers,
    channel_layer_dependencies,
)

REDIS_URL = "redis://wpuser:s3cr3t-pass@127.0.0.1:6379/3"
REDIS_LAYER = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
            "capacity": 1500,
            "expiry": 60,
        },
    }
}
INMEMORY_LAYER = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}


class ChannelLayerSettingsHelperTests(SimpleTestCase):
    def test_no_redis_url_uses_inmemory(self):
        layers = build_channel_layers(None)
        self.assertEqual(
            layers["default"]["BACKEND"],
            "channels.layers.InMemoryChannelLayer",
        )
        self.assertNotIn("CONFIG", layers["default"])

    def test_fake_redis_url_uses_channels_redis_without_connecting(self):
        # helper 是纯函数：只构造配置，不 import channels_redis / 不连接 Redis。
        layers = build_channel_layers(REDIS_URL, capacity=123, expiry=45)
        default = layers["default"]
        self.assertEqual(default["BACKEND"], "channels_redis.core.RedisChannelLayer")
        self.assertEqual(default["CONFIG"]["hosts"], [REDIS_URL])
        self.assertEqual(default["CONFIG"]["capacity"], 123)
        self.assertEqual(default["CONFIG"]["expiry"], 45)

    def test_defaults_are_sane(self):
        layers = build_channel_layers("redis://127.0.0.1:6379/0")
        config = layers["default"]["CONFIG"]
        self.assertEqual(config["capacity"], DEFAULT_CHANNEL_LAYER_CAPACITY)
        self.assertEqual(config["expiry"], DEFAULT_CHANNEL_LAYER_EXPIRY)
        self.assertGreater(config["capacity"], 0)
        self.assertGreater(config["expiry"], 0)

    def test_capacity_and_expiry_env_parsing(self):
        with mock.patch.dict(
            os.environ,
            {"CHANNEL_LAYER_CAPACITY": "2000", "CHANNEL_LAYER_EXPIRY": "30"},
            clear=False,
        ):
            self.assertEqual(_env_int("CHANNEL_LAYER_CAPACITY", 1500), 2000)
            self.assertEqual(_env_int("CHANNEL_LAYER_EXPIRY", 60), 30)

    def test_invalid_or_non_positive_env_falls_back(self):
        for value in ("not-an-int", "0", "-5", "   "):
            with mock.patch.dict(os.environ, {"CHANNEL_LAYER_CAPACITY": value}, clear=False):
                self.assertEqual(
                    _env_int("CHANNEL_LAYER_CAPACITY", 1500),
                    1500,
                    msg=f"value={value!r}",
                )

    def test_caches_follow_redis_url_with_locmem_fallback(self):
        locmem = build_caches(None)
        self.assertEqual(
            locmem["default"]["BACKEND"],
            "django.core.cache.backends.locmem.LocMemCache",
        )
        redis_cache = build_caches("redis://127.0.0.1:6379/1")
        self.assertEqual(
            redis_cache["default"]["BACKEND"],
            "django.core.cache.backends.redis.RedisCache",
        )
        self.assertEqual(
            redis_cache["default"]["LOCATION"],
            "redis://127.0.0.1:6379/1",
        )

    def test_dependency_detection_returns_booleans(self):
        deps = channel_layer_dependencies()
        self.assertEqual(set(deps), {"channels_redis", "redis"})
        self.assertTrue(all(isinstance(value, bool) for value in deps.values()))

    def test_asgi_application_still_builds_with_locmem(self):
        from config.asgi import application

        self.assertIn("http", application.application_mapping)
        self.assertIn("websocket", application.application_mapping)


class CheckRealtimeChannelsCommandTests(SimpleTestCase):
    def test_inmemory_output_has_no_redis_hosts(self):
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=INMEMORY_LAYER):
            call_command("check_realtime_channels", stdout=out)
        text = out.getvalue()
        self.assertIn("channels.layers.InMemoryChannelLayer", text)
        self.assertIn("single ASGI process only", text)
        self.assertIn("(none; no external broker)", text)

    def test_redis_output_masks_password(self):
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=REDIS_LAYER):
            call_command("check_realtime_channels", stdout=out)
        text = out.getvalue()
        self.assertIn("channels_redis.core.RedisChannelLayer", text)
        self.assertIn("wpuser:***@127.0.0.1:6379/3", text)
        self.assertIn("capacity: 1500", text)
        self.assertIn("expiry  : 60", text)
        self.assertNotIn("s3cr3t-pass", text)

    def test_redis_output_masks_sensitive_query_parameters(self):
        config = {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {
                    "hosts": ["redis://127.0.0.1:6379/0?password=query-secret&ssl_cert_reqs=none"],
                },
            }
        }
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=config):
            call_command("check_realtime_channels", stdout=out)
        text = out.getvalue()
        self.assertNotIn("query-secret", text)
        self.assertIn("password=***", text)
        self.assertIn("ssl_cert_reqs=none", text)

    def test_without_ping_does_not_touch_redis(self):
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=REDIS_LAYER):
            with mock.patch("redis.from_url") as from_url:
                call_command("check_realtime_channels", stdout=out)
        from_url.assert_not_called()

    def test_ping_success(self):
        fake_client = mock.Mock()
        fake_client.ping.return_value = True
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=REDIS_LAYER):
            with mock.patch("redis.from_url", return_value=fake_client) as from_url:
                call_command("check_realtime_channels", "--ping", stdout=out)
        text = out.getvalue()
        self.assertIn("PING redis://wpuser:***@127.0.0.1:6379/3 OK", text)
        self.assertNotIn("s3cr3t-pass", text)
        fake_client.ping.assert_called_once()
        args, kwargs = from_url.call_args
        self.assertEqual(args[0], REDIS_URL)
        self.assertEqual(kwargs["socket_connect_timeout"], 3.0)
        self.assertEqual(kwargs["socket_timeout"], 3.0)

    def test_ping_warns_when_redis_is_too_old_for_resp3(self):
        fake_client = mock.Mock()
        fake_client.ping.return_value = True
        fake_client.info.return_value = {"redis_version": "5.0.14"}
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=REDIS_LAYER):
            with mock.patch("redis.from_url", return_value=fake_client):
                call_command("check_realtime_channels", "--ping", stdout=out)
        text = out.getvalue()
        self.assertIn("Redis 5.0.14", text)
        self.assertIn("RESP3", text)
        self.assertNotIn("s3cr3t-pass", text)

    def test_ping_failure_is_nonzero_and_does_not_leak_password(self):
        out, err = StringIO(), StringIO()
        secret_error = f"connection refused for {REDIS_URL}"
        with override_settings(CHANNEL_LAYERS=REDIS_LAYER):
            with mock.patch("redis.from_url", side_effect=RuntimeError(secret_error)):
                with self.assertRaises(CommandError):
                    call_command(
                        "check_realtime_channels",
                        "--ping",
                        stdout=out,
                        stderr=err,
                    )
        combined = out.getvalue() + err.getvalue()
        self.assertIn("FAILED", err.getvalue())
        self.assertIn("***", err.getvalue())
        self.assertNotIn("s3cr3t-pass", combined)

    def test_ping_skipped_for_inmemory(self):
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=INMEMORY_LAYER):
            with mock.patch("redis.from_url") as from_url:
                call_command("check_realtime_channels", "--ping", stdout=out)
        from_url.assert_not_called()
        self.assertIn("Ping skipped", out.getvalue())

    def test_ping_without_hosts_fails(self):
        config = {
            "default": {
                "BACKEND": "channels_redis.core.RedisChannelLayer",
                "CONFIG": {"hosts": []},
            }
        }
        with override_settings(CHANNEL_LAYERS=config):
            with self.assertRaises(CommandError):
                call_command("check_realtime_channels", "--ping", stdout=StringIO())

    def test_legacy_backend_is_flagged(self):
        config = {
            "default": {
                "BACKEND": "channels.layers.RedisChannelLayer",
                "CONFIG": {"hosts": ["redis://127.0.0.1:6379/0"]},
            }
        }
        out = StringIO()
        with override_settings(CHANNEL_LAYERS=config):
            call_command("check_realtime_channels", stdout=out)
        self.assertIn("removed in Channels 4", out.getvalue())
