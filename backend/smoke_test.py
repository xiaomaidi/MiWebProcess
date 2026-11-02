"""webprocess 后端冒烟测试：端到端跑通核心 API。

运行（backend 目录下）：
    $env:USE_SQLITE="1"; python smoke_test.py

步骤（每步 PASS/FAIL）：
  1  创建超管并获取 JWT
  2  refresh token
  3  创建应用
  4  添加应用成员
  5  创建页面
  6  PUT 合法 schema（4 节点，内置组件）
  7  GET schema
  8  发布页面（严格校验 → 版本快照）
  9  运行时 bundle（active release）
 10  运行时单页 schema
 11  创建数据模型
 12  写入记录
 13  记录列表（{count, results, page, size}）
 14  组件注册表（34 个内置组件）
 15  发布列表（含 active）
 16  审计日志
退出码：0 = 全部通过；1 = 有失败。
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("USE_SQLITE", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import django

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def main() -> int:
    client = Client()
    User = get_user_model()
    stamp = int(time.time())
    username = f"smoke_admin_{stamp}"
    password = "smoke-pass-123"
    User.objects.create_superuser(username, f"smoke_{stamp}@example.com", password)

    def auth_headers(token: str) -> dict:
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # 1. 获取 JWT
    r = client.post("/api/auth/token/", data={"username": username, "password": password}, content_type="application/json")
    ok = r.status_code == 200 and "access" in r.json() and "refresh" in r.json()
    step("1 auth/token 获取 JWT", ok, f"status={r.status_code} body={r.content[:200]!r}")
    if not ok:
        return 1
    token = r.json()["access"]
    H = auth_headers(token)

    # 2. refresh
    r = client.post("/api/auth/token/refresh/", data={"refresh": r.json()["refresh"]}, content_type="application/json")
    step("2 auth/token/refresh", r.status_code == 200 and "access" in r.json(), f"status={r.status_code}")

    # 3. 创建应用
    app_code = f"smokeapp_{stamp}"
    r = client.post("/api/apps/", data={"name": f"Smoke App {stamp}", "code": app_code, "description": "smoke test app"}, content_type="application/json", **H)
    ok = r.status_code in (200, 201) and "id" in r.json()
    step("3 创建应用 POST /api/apps/", ok, f"status={r.status_code} body={r.content[:200]!r}")
    if not ok:
        return 1
    app = r.json()
    app_id = app["id"]

    # 4. 成员
    member = User.objects.create_user(f"smoke_member_{stamp}", f"member_{stamp}@example.com", password)
    r = client.post(f"/api/apps/{app_id}/members/", data={"user": member.id, "role": "editor"}, content_type="application/json", **H)
    step("4 添加成员 POST /api/apps/{id}/members/", r.status_code in (200, 201), f"status={r.status_code} body={r.content[:200]!r}")

    # 5. 创建页面
    r = client.post(f"/api/apps/{app_id}/pages/", data={"name": "Home", "path": "home", "type": "page"}, content_type="application/json", **H)
    ok = r.status_code in (200, 201) and "id" in r.json()
    step("5 创建页面 POST /api/apps/{id}/pages/", ok, f"status={r.status_code} body={r.content[:200]!r}")
    if not ok:
        return 1
    page_id = r.json()["id"]

    # 6. PUT 合法 schema（4 节点，内置组件名）
    schema = {
        "schemaVersion": 1,
        "rootId": "n1",
        "layout": {"mode": "flow"},
        "variables": {"greeting": {"value": "Hello MiWebProcess", "scope": "page"}},
        "nodes": {
            "n1": {"id": "n1", "type": "wp-container", "componentVersion": "1.0.0", "props": {}, "children": ["n2", "n3", "n4"]},
            "n2": {"id": "n2", "type": "wp-heading", "componentVersion": "1.0.0", "props": {"text": "{{greeting}}"}},
            "n3": {"id": "n3", "type": "wp-button", "componentVersion": "1.0.0", "props": {"label": "Go"}},
            "n4": {"id": "n4", "type": "wp-input", "componentVersion": "1.0.0", "props": {"placeholder": "输入"}},
        },
    }
    r = client.put(f"/api/pages/{page_id}/schema/", data={"schema": schema}, content_type="application/json", **H)
    step("6 PUT 页面 schema（4 节点）", r.status_code == 200 and "page" in r.json(), f"status={r.status_code} body={r.content[:300]!r}")

    # 7. GET schema
    r = client.get(f"/api/pages/{page_id}/schema/", **H)
    ok = r.status_code == 200 and (r.json().get("schema") or {}).get("rootId") == "n1"
    step("7 GET 页面 schema", ok, f"status={r.status_code}")

    # 8. 发布页面
    r = client.post(f"/api/pages/{page_id}/publish/", data={"changelog": "smoke publish"}, content_type="application/json", **H)
    ok = r.status_code == 200
    step("8 发布页面 POST /api/pages/{id}/publish/", ok, f"status={r.status_code} body={r.content[:300]!r}")
    if not ok:
        print("发布失败，后续运行时步骤依赖它；继续尝试以暴露真实状态。")

    # 9. 运行时 bundle
    r = client.get(f"/api/runtime/{app_code}/", **H)
    ok = r.status_code == 200 and isinstance(r.json().get("pages"), dict) and "home" in r.json().get("pages", {})
    step("9 运行时 bundle GET /api/runtime/{app_code}/", ok, f"status={r.status_code} body={r.content[:300]!r}")

    # 10. 运行时单页
    r = client.get(f"/api/runtime/{app_code}/home", **H)
    ok = r.status_code == 200
    step("10 运行时单页 GET /api/runtime/{app_code}/home", ok, f"status={r.status_code} body={r.content[:200]!r}")

    # 11. 数据模型
    r = client.post(
        f"/api/apps/{app_id}/models/",
        data={"code": "product", "name": "产品", "fields": [
            {"name": "title", "type": "string", "required": True},
            {"name": "price", "type": "number"},
        ]},
        content_type="application/json",
        **H,
    )
    ok = r.status_code in (200, 201) and "id" in r.json()
    step("11 创建数据模型 POST /api/apps/{id}/models/", ok, f"status={r.status_code} body={r.content[:300]!r}")
    if not ok:
        return 1
    model_id = r.json()["id"]

    # 12. 写入记录
    r1 = client.post(f"/api/models/{model_id}/records/", data={"data": {"title": "A", "price": 10}}, content_type="application/json", **H)
    r2 = client.post(f"/api/models/{model_id}/records/", data={"data": {"title": "B", "price": 20}}, content_type="application/json", **H)
    step("12 写入记录 POST /api/models/{id}/records/", r1.status_code in (200, 201) and r2.status_code in (200, 201),
         f"r1={r1.status_code} r2={r2.status_code} body={r1.content[:200]!r}")

    # 13. 记录列表（API.md 分页形状）
    r = client.get(f"/api/models/{model_id}/records/", **H)
    body = r.json()
    ok = r.status_code == 200 and set(body.keys()) >= {"count", "results", "page", "size"} and body["count"] == 2
    step("13 记录列表 GET /api/models/{id}/records/", ok, f"status={r.status_code} keys={sorted(body.keys()) if isinstance(body, dict) else body}")

    # 14. 组件注册表（v2 全量，>= 100）
    r = client.get("/api/components/registry/", **H)
    comps = (r.json() or {}).get("components") or []
    step("14 组件注册表 GET /api/components/registry/", r.status_code == 200 and len(comps) >= 100, f"status={r.status_code} count={len(comps)}")

    # 15. 发布列表
    r = client.get(f"/api/apps/{app_id}/releases/", **H)
    body = r.json()
    releases = body.get("results") if isinstance(body, dict) and "results" in body else []
    step("15 发布列表 GET /api/apps/{id}/releases/", r.status_code == 200 and len(releases) >= 1, f"status={r.status_code} count={len(releases)}")

    # 16. 审计日志
    r = client.get(f"/api/audit-logs/?app_id={app_id}", **H)
    ok = r.status_code == 200 and isinstance(r.json(), dict) and "results" in r.json()
    step("16 审计日志 GET /api/audit-logs/", ok, f"status={r.status_code} body={r.content[:200]!r}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} 步通过")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
