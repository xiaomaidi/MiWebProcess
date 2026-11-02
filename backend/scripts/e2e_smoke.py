"""最小 E2E 冒烟：登录、应用列表、运行时页面、组件注册表。"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django

django.setup()
from django.test import Client


def main() -> int:
    client = Client()
    token_res = client.post(
        "/api/auth/token/",
        data=json.dumps({"username": "admin", "password": "admin123"}),
        content_type="application/json",
    )
    assert token_res.status_code == 200, token_res.content[:300]
    token = token_res.json()["access"]
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
    checks = [
        ("/api/apps/?page=1&size=5", 200),
        ("/api/components/registry/", 200),
        ("/api/runtime/auto-site-f632/custom-demo", 200),
    ]
    for path, expected in checks:
        response = client.get(path, **headers)
        print(f"{path} -> {response.status_code}")
        assert response.status_code == expected, response.content[:500]
    print("E2E smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
