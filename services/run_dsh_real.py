"""启动真实 DSH HTTP 服务；从平台 Provider 读取 Key，不打印密钥。"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django  # noqa: E402

django.setup()

from ai.crypto import decrypt_secret  # noqa: E402
from ai.models import AiProvider  # noqa: E402

key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not key:
    provider = AiProvider.objects.filter(provider_type="deepseek", enabled=True).first()
    if provider is None or not provider.api_key:
        print("没有可用的 DeepSeek Provider，请先在平台配置 AI Provider。", flush=True)
        sys.exit(1)
    key = decrypt_secret(provider.api_key)

env = dict(os.environ)
env["DEEPSEEK_API_KEY"] = key
env["DSH_NO_UPDATE_CHECK"] = "1"
os.chdir(ROOT)
subprocess.run(
    [sys.executable, str(ROOT / "services" / "dsh_service.py"), "--host", "127.0.0.1", "--port", "9000", "--real"],
    env=env,
)
