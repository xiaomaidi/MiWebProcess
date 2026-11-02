"""创建演示数据：超管 admin/admin123 + 示例应用 demo-shop（页面/模型/记录）。幂等，可重复运行。

运行（backend 目录下）：
    python seed_demo.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

User = get_user_model()
client = Client()

# 1. 超管（幂等）
SUPERUSER = ("admin", "admin123")
u, created = User.objects.get_or_create(
    username=SUPERUSER[0], defaults={"email": "admin@example.com"}
)
if created:
    u.set_password(SUPERUSER[1])
    u.is_superuser = True
    u.save()
    print(f"[OK] superuser created: {SUPERUSER[0]} / {SUPERUSER[1]}")
else:
    print(f"[OK] superuser exists: {SUPERUSER[0]}")

r = client.post(
    "/api/auth/token/", data={"username": SUPERUSER[0], "password": SUPERUSER[1]}, content_type="application/json"
)
assert r.status_code == 200, f"token failed: {r.status_code} {r.content[:200]}"
H = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access']}"}

# 2. 示例应用（幂等）
APP_CODE = "demo-shop"
apps = client.get("/api/apps/?code=" + APP_CODE, **H).json()
app_list = apps.get("results") if isinstance(apps, dict) and "results" in apps else apps
app = next((a for a in app_list if a.get("code") == APP_CODE), None) if isinstance(app_list, list) else None
if app is None:
    r = client.post(
        "/api/apps/",
        data={"name": "Demo Shop", "code": APP_CODE, "description": "演示应用：页面/模型/记录示例"},
        content_type="application/json",
        **H,
    )
    assert r.status_code in (200, 201), f"app create failed: {r.status_code} {r.content[:300]}"
    app = r.json()
    print(f"[OK] app created: {APP_CODE} (id={app['id']})")
else:
    print(f"[OK] app exists: {APP_CODE} (id={app['id']})")
app_id = app["id"]

# 3. 示例页面 + schema + 发布（幂等：没有则创建并发布一次）
pages = client.get(f"/api/apps/{app_id}/pages/", **H).json()
page_list = pages.get("results") if isinstance(pages, dict) and "results" in pages else pages
page = next((p for p in page_list if p.get("path") == "home"), None) if isinstance(page_list, list) else None
if page is None:
    r = client.post(
        f"/api/apps/{app_id}/pages/", data={"name": "首页", "path": "home", "type": "page"}, content_type="application/json", **H
    )
    assert r.status_code in (200, 201), f"page create failed: {r.status_code} {r.content[:300]}"
    page = r.json()
    print(f"[OK] page created: home (id={page['id']})")
else:
    print(f"[OK] page exists: home (id={page['id']})")
page_id = page["id"]

schema = {
    "schemaVersion": 1,
    "rootId": "n1",
    "layout": {"mode": "flow"},
    "variables": {
        "greeting": {"value": "Welcome to MiWebProcess Demo Shop", "scope": "page"},
    },
    "nodes": {
        "n1": {"id": "n1", "type": "wp-container", "componentVersion": "1.0.0", "props": {}, "children": ["n2", "n3", "n4"]},
        "n2": {"id": "n2", "type": "wp-heading", "componentVersion": "1.0.0", "props": {"text": "{{greeting}}"}},
        "n3": {
            "id": "n3",
            "type": "wp-container",
            "componentVersion": "1.0.0",
            "props": {},
            "children": ["n5"],
        },
        "n4": {"id": "n4", "type": "wp-button", "componentVersion": "1.0.0", "props": {"label": "Get started"}},
        "n5": {"id": "n5", "type": "wp-text", "componentVersion": "1.0.0", "props": {"text": "Edit me in the designer."}},
    },
}
r = client.put(f"/api/pages/{page_id}/schema/", data={"schema": schema}, content_type="application/json", **H)
assert r.status_code == 200, f"schema put failed: {r.status_code} {r.content[:300]}"
print(f"[OK] draft schema saved")

r = client.post(f"/api/pages/{page_id}/publish/", data={"changelog": "demo seed publish"}, content_type="application/json", **H)
if r.status_code == 200:
    print(f"[OK] page published")
else:
    print(f"[WARN] publish: {r.status_code} {r.content[:200]}")

# 4. 数据模型 + 记录（幂等：按 code 查找）
models = client.get(f"/api/apps/{app_id}/models/", **H).json()
model_list = models.get("results") if isinstance(models, dict) and "results" in models else models
model = next((m for m in model_list if m.get("code") == "product"), None) if isinstance(model_list, list) else None
if model is None:
    r = client.post(
        f"/api/apps/{app_id}/models/",
        data={
            "code": "product",
            "name": "产品",
            "fields": [
                {"name": "title", "type": "string", "required": True},
                {"name": "price", "type": "number"},
                {"name": "stock", "type": "number"},
            ],
        },
        content_type="application/json",
        **H,
    )
    assert r.status_code in (200, 201), f"model create failed: {r.status_code} {r.content[:300]}"
    model = r.json()
    print(f"[OK] model created: product (id={model['id']})")
else:
    print(f"[OK] model exists: product (id={model['id']})")
model_id = model["id"]

r = client.get(f"/api/models/{model_id}/records/", **H).json()
count = r.get("count", 0)
if count == 0:
    for item in (
        {"title": "机械键盘", "price": 499, "stock": 12},
        {"title": "无线鼠标", "price": 199, "stock": 30},
        {"title": "USB-C 拓展坞", "price": 329, "stock": 8},
    ):
        rr = client.post(f"/api/models/{model_id}/records/", data={"data": item}, content_type="application/json", **H)
        assert rr.status_code in (200, 201), f"record create failed: {rr.status_code} {rr.content[:200]}"
    print(f"[OK] 3 records seeded")
else:
    print(f"[OK] records already present: {count}")

print("\nDemo ready:")
print(f"  login:      admin / admin123")
print(f"  designer:   /design/<appId={app_id}>/<pageId={page_id}>")
print(f"  runtime:    /run/{APP_CODE}/home")
print(f"  preview:    /preview/<appId={app_id}>/<pageId={page_id}>")
