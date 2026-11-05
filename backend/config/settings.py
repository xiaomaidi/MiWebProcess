"""MiWebProcess Django 项目配置。

环境变量驱动（.env 不强制），支持：
- USE_SQLITE=1：本地无 PostgreSQL 时降级为 SQLite（仅开发验证用）。
- REDIS_URL：缺省时缓存/Channels/Celery 全部降级为本地内存 + eager 任务。
- USE_S3=1 + S3_ENDPOINT_URL/S3_ACCESS_KEY/...：媒体存储切到 MinIO/S3。
"""
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    """轻量 .env 读取：已存在的环境变量优先（不覆盖 shell/容器注入）。"""
    if not path.exists():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except OSError:
        pass


_load_env_file(BASE_DIR / ".env")


def _env(key: str, default=None):
    return os.environ.get(key, default)


def _env_bool(key: str, default: bool = False) -> bool:
    v = os.environ.get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


SECRET_KEY = _env("SECRET_KEY", "dev-insecure-secret-key-change-me")
DEBUG = _env_bool("DEBUG", True)
ALLOWED_HOSTS = [h.strip() for h in _env("ALLOWED_HOSTS", "*").split(",") if h.strip()]

# 市场组件代码签名密钥（HMAC-SHA256）。
# 生产环境必须单独配置 >= 32 字节随机值：MARKET_SIGNING_KEY=<random-secret>。
# 未配置时回退到 SECRET_KEY（仅为开发兼容）：轮换 SECRET_KEY 会使历史签名失效，
# 且 SECRET_KEY 还用于 Django 会话/CSRF，不应长期复用为签名密钥。
# 该值不会通过任何 API 返回；修改后需对市场组件重新签名。
MARKET_SIGNING_KEY = _env("MARKET_SIGNING_KEY", "")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "corsheaders",
    "channels",
    "core",
    "accounts",
    # 企业 SSO（OpenID Connect）：应用级 Provider 配置 + 公开登录流程
    "enterprise_sso",
    "collab",
    "market",
    "appcore",
    "pages",
    "components",
    "datasources",
    "datamodels",
    "releases",
    "audit",
    "runtime",
    "realtime",
    "workflow",
    "ai",
    "org",
    "moderation",
    "search",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SensitiveDataMiddleware",
]

ROOT_URLCONF = "config.urls"

# 自定义用户模型（accounts.User：username + email + is_platform_admin）
AUTH_USER_MODEL = "accounts.User"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ---------------------------------------------------------------- 数据库
if _env_bool("USE_SQLITE", False):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": _env("POSTGRES_DB", "webprocess"),
            "USER": _env("POSTGRES_USER", "webprocess"),
            "PASSWORD": _env("POSTGRES_PASSWORD", "webprocess"),
            "HOST": _env("POSTGRES_HOST", "127.0.0.1"),
            "PORT": _env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

# ---------------------------------------------------------------- 缓存 / Redis
REDIS_URL = _env("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": "wp",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.RedisChannelLayer",
            "CONFIG": {"hosts": [REDIS_URL]},
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "wp-cache",
        }
    }
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

# WebSocket 路由（config.asgi 的 ProtocolTypeRouter 使用 realtime.routing）
WS_URL_PATTERN = r"^ws/(?P<app_id>\d+)/$"
# SEO / 分享链接使用的站点根地址；生产环境通过环境变量覆盖。
FRONTEND_URL = _env("FRONTEND_URL", "http://localhost:5173")

# 出站请求 SSRF 防护。默认拒绝内网/回环/链路本地/保留地址；
# 如需本地 Ollama 等，显式加入 SSRF_ALLOWED_HOSTS。
SSRF_ALLOWED_HOSTS = [
    item.strip() for item in str(_env("SSRF_ALLOWED_HOSTS", "") or "").split(",") if item.strip()
]
SSRF_ALLOW_PRIVATE = _env_bool("SSRF_ALLOW_PRIVATE", False)

# ---------------------------------------------------------------- 实时 / MQTT
# 未启用或未安装 paho-mqtt 时自动降级为纯 WebSocket，不影响平台其他功能。
MQTT_ENABLED = _env_bool("MQTT_ENABLED", False)
MQTT_BROKER_URL = _env("MQTT_BROKER_URL", "")
MQTT_USERNAME = _env("MQTT_USERNAME", "")
MQTT_PASSWORD = _env("MQTT_PASSWORD", "")
MQTT_CLIENT_ID = _env("MQTT_CLIENT_ID", "")
REALTIME_KEEP_MESSAGES = int(_env("REALTIME_KEEP_MESSAGES", "500"))

# ---------------------------------------------------------------- SSR / 静态预渲染
# 前端 SSR 产物目录（vite build --ssr，输出 frontend/dist-ssr）。
SSR_BUNDLE_DIR = _env("SSR_BUNDLE_DIR", str(BASE_DIR.parent / "frontend" / "dist-ssr"))
# 预渲染 HTML 输出目录（可直接由 Nginx 静态托管）。
PRERENDER_DIR = _env("PRERENDER_DIR", str(BASE_DIR / "static_prerender"))
SSR_ENABLED = _env_bool("SSR_ENABLED", True)
SSR_NODE_BIN = _env("SSR_NODE_BIN", "node")
# SSR 渲染时组件拉取公开数据的后端地址（服务端到服务端）。
SSR_API_BASE = _env("SSR_API_BASE", "http://127.0.0.1:8000")
# 快照 HTML 中静态资源前缀：默认同源（Nginx 托管 dist）；开发可设为 http://localhost:5173
SSR_ASSET_BASE = _env("SSR_ASSET_BASE", "")

# 建站后自动评审：结构评审始终执行；截图评审需要本机 Chrome/Edge 与可访问的前端地址
AUTOBUILD_SCREENSHOT = _env_bool("AUTOBUILD_SCREENSHOT", True)
AUTOBUILD_BROWSER = _env("AUTOBUILD_BROWSER", "")

# 公开表单提交通知：应用所有者邮箱（需配置 EMAIL_HOST）+ 可选 IM Webhook
FORM_NOTIFY_WEBHOOK = _env("FORM_NOTIFY_WEBHOOK", "")

# ---------------------------------------------------------------- AI Copilot
# OpenAI-compatible API；未配置 Key 时自动使用本地模板生成器。
AI_API_KEY = _env("AI_API_KEY", "")
AI_BASE_URL = _env("AI_BASE_URL", "https://api.deepseek.com/v1")
AI_MODEL = _env("AI_MODEL", "deepseek-chat")
# 截图评审可用多模态模型；留空时按默认模型名自动识别
AI_VISION_MODEL = _env("AI_VISION_MODEL", "")

# ---------------------------------------------------------------- Celery
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
CELERY_TASK_ALWAYS_EAGER = not bool(REDIS_URL)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_TIME_LIMIT = 300
CELERY_TASK_DEFAULT_QUEUE = "default"
DSH_AGENT_URL = os.environ.get("DSH_AGENT_URL", "").strip()
DSH_AGENT_TOKEN = os.environ.get("DSH_AGENT_TOKEN", "").strip()
DSH_AGENT_TIMEOUT = int(os.environ.get("DSH_AGENT_TIMEOUT", "300"))
DSH_AGENT_RETRIES = int(os.environ.get("DSH_AGENT_RETRIES", "2"))
AGENT_DAILY_TASK_LIMIT = int(os.environ.get("AGENT_DAILY_TASK_LIMIT", "50"))
AGENT_DAILY_TOKEN_LIMIT = int(os.environ.get("AGENT_DAILY_TOKEN_LIMIT", "200000"))
AGENT_BROWSER_PATH = os.environ.get("AGENT_BROWSER_PATH", "").strip()
AGENT_FRONTEND_URL = os.environ.get("AGENT_FRONTEND_URL", "http://127.0.0.1:5173").strip()
AGENT_AUTO_VERIFY = os.environ.get("AGENT_AUTO_VERIFY", "1") not in ("0", "false", "False", "")
DSH_SANDBOX_MODE = os.environ.get("DSH_SANDBOX_MODE", "http").strip().lower()
DSH_SANDBOX_COMMAND = os.environ.get("DSH_SANDBOX_COMMAND", "").strip()
DSH_SANDBOX_IMAGE = os.environ.get("DSH_SANDBOX_IMAGE", "").strip()
DSH_SANDBOX_NETWORK = os.environ.get("DSH_SANDBOX_NETWORK", "none")
DSH_SANDBOX_MEMORY = os.environ.get("DSH_SANDBOX_MEMORY", "1g")
DSH_SANDBOX_CPUS = os.environ.get("DSH_SANDBOX_CPUS", "1")
DSH_SANDBOX_TIMEOUT = int(os.environ.get("DSH_SANDBOX_TIMEOUT", "300"))

CELERY_BEAT_SCHEDULE = {
    "app-scheduled-jobs": {
        "task": "appcore.tasks.run_due_app_jobs",
        "schedule": 60.0,
    },
}

# ---------------------------------------------------------------- DRF / JWT
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "anon": "3000/min",
        "user": "6000/min",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=1),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "MiWebProcess API",
    "DESCRIPTION": "免代码低代码网页开发系统 API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------- 静态 / 媒体
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

USE_S3 = _env_bool("USE_S3", False)
S3_ENDPOINT_URL = _env("S3_ENDPOINT_URL")
S3_ACCESS_KEY = _env("S3_ACCESS_KEY")
S3_SECRET_KEY = _env("S3_SECRET_KEY")
S3_BUCKET = _env("S3_BUCKET", "webprocess")

# ---------------------------------------------------------------- CORS / 日志
CORS_ALLOWED_ORIGINS = [
    o.strip()
    for o in _env("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "[%(levelname)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": _env("LOG_LEVEL", "INFO")},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
