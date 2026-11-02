"""webprocess 新特性验收：组织权限 / 内容审核 / 搜索索引 / MQTT-WebSocket /
截图级 AI 视觉评审 / AI 多轮 Agent。

运行（backend 目录下）：
    $env:USE_SQLITE="1"; python feature_test.py

与 smoke_test.py 互补：smoke 验证基础 CRUD 与发布链路，本文件验证 v3 能力。
退出码：0 = 全部通过；1 = 有失败。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import time

os.environ.setdefault("USE_SQLITE", "1")
os.environ.setdefault("AUTOBUILD_SCREENSHOT", "0")
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
    password = "feature-pass-123"

    def mk(username: str, **extra):
        return User.objects.create_user(f"{username}_{stamp}", f"{username}_{stamp}@example.com", password, **extra)

    admin = User.objects.create_superuser(f"ft_admin_{stamp}", f"ft_admin_{stamp}@example.com", password)
    editor = mk("ft_editor")
    leader = mk("ft_leader")
    outsider = mk("ft_outsider")

    def headers(user) -> dict:
        r = client.post(
            "/api/auth/token/",
            data={"username": user.username, "password": password},
            content_type="application/json",
        )
        token = r.json().get("access") if r.status_code == 200 else ""
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    H_ADMIN = headers(admin)
    H_EDITOR = headers(editor)
    H_LEADER = headers(leader)
    H_OUT = headers(outsider)

    def call(method: str, path: str, data=None, h=None):
        kwargs = {"content_type": "application/json", **(h or H_ADMIN)}
        if method == "GET":
            return client.get(path, **kwargs)
        if method == "POST":
            return client.post(path, data=data or {}, **kwargs)
        if method == "PUT":
            return client.put(path, data=data or {}, **kwargs)
        if method == "PATCH":
            return client.patch(path, data=data or {}, **kwargs)
        return client.delete(path, **kwargs)

    # ---------------------------------------------------------------- 应用
    app_code = f"ftapp_{stamp}"
    r = call("POST", "/api/apps/", {"name": f"Feature {stamp}", "code": app_code, "description": "feature test"})
    step("01 创建应用", r.status_code in (200, 201), f"status={r.status_code} {r.content[:200]!r}")
    if r.status_code not in (200, 201):
        return 1
    app_id = r.json()["id"]
    for user, role in ((editor, "editor"), (leader, "editor"), (outsider, "viewer")):
        call("POST", f"/api/apps/{app_id}/members/", {"user": user.id, "role": role})

    # ---------------------------------------------------------------- 组织架构
    r = call("POST", "/api/org/departments/", {"name": "总部", "code": f"HQ{stamp}"})
    step("02 创建根部门", r.status_code in (200, 201), f"status={r.status_code} {r.content[:200]!r}")
    root_id = r.json().get("id") if r.status_code in (200, 201) else None
    r = call("POST", "/api/org/departments/", {"name": "华东大区", "code": f"EAST{stamp}", "parent_id": root_id})
    ok = r.status_code in (200, 201) and r.json().get("level") == 1
    step("03 创建子部门（level/path）", ok, f"status={r.status_code} {r.content[:200]!r}")
    east_id = r.json().get("id") if ok else None
    r = call("POST", f"/api/org/departments/{east_id}/members/", {"user_id": leader.id, "role": "leader"})
    step("04 设置部门负责人", r.status_code in (200, 201) and r.json().get("role") == "leader", f"status={r.status_code}")
    r = call("POST", f"/api/org/departments/{east_id}/members/", {"user_id": editor.id, "role": "member"})
    step("05 添加部门成员", r.status_code in (200, 201), f"status={r.status_code}")
    r = call("GET", "/api/org/me/", h=H_EDITOR)
    ok = r.status_code == 200 and east_id in r.json().get("visible_department_ids", [])
    step("06 我的组织范围（成员）", ok, f"status={r.status_code} {r.content[:200]!r}")
    r = call("GET", "/api/org/me/", h=H_LEADER)
    ok = r.status_code == 200 and east_id in r.json().get("managed_department_ids", [])
    step("07 我的组织范围（负责人）", ok, f"status={r.status_code}")

    # ---------------------------------------------------------------- 部门数据范围
    r = call("POST", f"/api/apps/{app_id}/models/", {
        "name": "dept_note", "fields": [
            {"name": "title", "type": "string", "required": True},
            {"name": "dept", "type": "string"},
            {"name": "status", "type": "string"},
        ], "data_scope": "dept", "dept_field": "dept", "is_public": True,
    })
    ok = r.status_code in (200, 201) and r.json().get("data_scope") == "dept"
    step("08 创建部门数据范围模型", ok, f"status={r.status_code} {r.content[:200]!r}")
    dept_model_id = r.json().get("id") if ok else None
    r = call("POST", f"/api/models/{dept_model_id}/records/", {
        "data": {"title": "华东周报", "dept": str(east_id), "status": "published"},
    })
    step("09 管理员写入部门记录", r.status_code in (200, 201), f"status={r.status_code} {r.content[:200]!r}")
    dept_record_id = r.json().get("id") if r.status_code in (200, 201) else None
    r = call("GET", f"/api/models/{dept_model_id}/records/", h=H_EDITOR)
    ok = r.status_code == 200 and r.json().get("count") == 1
    step("10 同部门成员可见", ok, f"status={r.status_code} body={r.content[:200]!r}")
    r = call("GET", f"/api/models/{dept_model_id}/records/", h=H_OUT)
    ok = r.status_code == 200 and r.json().get("count") == 0
    step("11 其他部门成员不可见", ok, f"status={r.status_code} body={r.content[:200]!r}")

    # ---------------------------------------------------------------- 内容审核
    r = call("POST", f"/api/apps/{app_id}/models/", {
        "name": "news", "fields": [
            {"name": "title", "type": "string", "required": True},
            {"name": "summary", "type": "string"},
            {"name": "content", "type": "string"},
            {"name": "status", "type": "string"},
        ], "is_public": True, "review_required": True, "review_roles": ["owner"],
    })
    ok = r.status_code in (200, 201) and r.json().get("review_required") is True
    step("12 创建审核模型", ok, f"status={r.status_code} {r.content[:200]!r}")
    news_model_id = r.json().get("id") if ok else None
    r = call("POST", f"/api/models/{news_model_id}/records/", {
        "data": {"title": "秋季新品发布", "summary": "新品摘要", "content": "这是正文内容，包含秋季与新品关键词。", "status": "draft"},
    }, h=H_EDITOR)
    ok = r.status_code in (200, 201) and (r.json().get("data") or {}).get("status") == "pending"
    step("13 编辑提交后进入待审", ok, f"status={r.status_code} body={r.content[:300]!r}")
    record_id = r.json().get("id") if r.status_code in (200, 201) else None
    r = call("GET", f"/api/moderation/reviews/?app_id={app_id}&status=pending", h=H_ADMIN)
    ok = r.status_code == 200 and r.json().get("count", 0) >= 1
    step("14 管理员审核队列", ok, f"status={r.status_code} body={r.content[:300]!r}")
    review_id = r.json()["results"][0]["id"] if ok else None
    r = call("POST", f"/api/moderation/reviews/{review_id}/approve/", {"comment": "内容合规"})
    ok = r.status_code == 200 and r.json().get("status") == "approved"
    step("15 审核通过", ok, f"status={r.status_code} {r.content[:300]!r}")
    r = call("GET", f"/api/models/{news_model_id}/records/{record_id}/")
    ok = r.status_code == 200 and (r.json().get("data") or {}).get("status") == "published"
    step("16 通过后自动发布", ok, f"status={r.status_code} body={r.content[:300]!r}")
    r = call("GET", f"/api/moderation/summary/?app_id={app_id}")
    ok = r.status_code == 200 and r.json().get("counts", {}).get("approved", 0) >= 1
    step("17 审核汇总", ok, f"status={r.status_code}")

    # ---------------------------------------------------------------- 搜索索引
    call("POST", "/api/search/rebuild/", {"app_id": app_id})
    r = call("GET", f"/api/search/?app_id={app_id}&q=秋季")
    ok = r.status_code == 200 and r.json().get("count", 0) >= 1
    step("18 搜索命中", ok, f"status={r.status_code} body={r.content[:300]!r}")
    r = call("GET", f"/api/search/stats/?app_id={app_id}")
    ok = r.status_code == 200 and r.json().get("documents", 0) >= 1
    step("19 索引统计", ok, f"status={r.status_code} body={r.content[:300]!r}")
    r = call("GET", f"/api/search/suggest/?app_id={app_id}&q=秋季")
    ok = r.status_code == 200 and len(r.json().get("results") or []) >= 1
    step("20 搜索联想", ok, f"status={r.status_code}")
    r = client.get(f"/api/runtime/{app_code}/search/?q=秋季")
    ok = r.status_code in (200, 404)
    step("21 运行时搜索可用（无发布时 404）", ok, f"status={r.status_code}")

    # ---------------------------------------------------------------- 实时通道
    r = call("POST", "/api/realtime/channels/", {
        "app_id": app_id, "name": "设备遥测", "kind": "both",
        "topic": "devices/+/telemetry", "description": "测试通道",
    })
    ok = r.status_code in (200, 201) and r.json().get("topic") == "devices/+/telemetry"
    step("22 创建实时通道", ok, f"status={r.status_code} {r.content[:300]!r}")
    channel_id = r.json().get("id") if ok else None
    r = call("POST", f"/api/realtime/channels/{channel_id}/publish/", {"payload": {"temp": 23.5, "device": "d1"}})
    ok = r.status_code == 200 and r.json().get("ok") is True
    step("23 发布实时消息", ok, f"status={r.status_code} {r.content[:300]!r}")
    r = call("GET", f"/api/realtime/channels/{channel_id}/messages/", h=H_EDITOR)
    ok = r.status_code == 200 and r.json().get("count", 0) >= 1
    step("24 消息留存", ok, f"status={r.status_code}")
    r = call("GET", "/api/realtime/status/")
    ok = r.status_code == 200 and "connected" in r.json()
    step("25 MQTT 状态（降级可用）", ok, f"status={r.status_code} body={r.content[:200]!r}")

    # ---------------------------------------------------------------- 页面 + AI
    r = call("POST", f"/api/apps/{app_id}/pages/", {"name": "首页", "path": "home", "type": "page"})
    page_id = r.json().get("id") if r.status_code in (200, 201) else None
    schema = {
        "schemaVersion": 2, "rootId": "root", "layout": {"mode": "flow", "width": 1200, "height": 800},
        "variables": {}, "meta": {"title": "首页", "description": "测试"},
        "nodes": {
            "root": {"id": "root", "type": "wp-canvas", "componentVersion": "2.0.0", "props": {}, "children": ["h1", "btn"]},
            "h1": {"id": "h1", "type": "wp-heading", "componentVersion": "2.0.0", "props": {"content": "旧标题"}, "children": []},
            "btn": {"id": "btn", "type": "wp-button", "componentVersion": "2.0.0", "props": {"text": "旧按钮"}, "children": []},
        },
    }
    r = call("PUT", f"/api/pages/{page_id}/schema/", {"schema": schema})
    step("26 页面 schema 保存", r.status_code == 200, f"status={r.status_code}")

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (900, 640), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    draw.rectangle([60, 60, 840, 220], fill="#1e3a8a")
    draw.rectangle([60, 280, 420, 560], fill="#dbeafe")
    draw.rectangle([470, 280, 840, 560], fill="#ffffff")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    r = call("POST", "/api/ai/design/visual-review/", {
        "app_id": app_id, "image": data_uri, "schema": schema, "page_name": "首页",
    })
    body = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and 0 <= body.get("score", -1) <= 100 and isinstance(body.get("metrics"), dict)
    step("27 截图级视觉评审", ok, f"status={r.status_code} body={r.content[:300]!r}")

    r = call("POST", "/api/ai/agent/conversations/", {"app_id": app_id, "page_id": page_id, "title": "改标题"})
    ok = r.status_code in (200, 201) and r.json().get("page_id") == page_id
    step("28 创建 Agent 会话", ok, f"status={r.status_code} {r.content[:200]!r}")
    conversation_id = r.json().get("id") if ok else None
    r = call("POST", f"/api/ai/agent/conversations/{conversation_id}/messages/", {"message": "把首屏标题改成「秋季新品」"})
    body = r.json() if r.status_code == 200 else {}
    assistant = body.get("assistant_message") or {}
    proposal = assistant.get("proposal") or {}
    ok = r.status_code == 200 and proposal.get("kind") == "page_patch" and proposal.get("ops")
    step("29 Agent 生成补丁提案", ok, f"status={r.status_code} body={r.content[:400]!r}")
    r = call("POST", f"/api/ai/agent/conversations/{conversation_id}/apply/", {"message_id": assistant.get("id")})
    ok = r.status_code == 200 and r.json().get("ok") is True
    step("30 应用 Agent 补丁", ok, f"status={r.status_code} {r.content[:300]!r}")
    r = call("GET", f"/api/pages/{page_id}/schema/")
    nodes = (r.json().get("schema") or {}).get("nodes") or {}
    ok = "秋季新品" in str((nodes.get("h1") or {}).get("props", {}).get("content", ""))
    step("31 页面已更新", ok, f"content={(nodes.get('h1') or {}).get('props')}")

    # ---------------------------------------------------------------- 工作流部门审批人
    definition = {
        "app_id": app_id, "name": "部门审批流", "code": f"dept_flow_{stamp}",
        "description": "部门负责人审批",
        "nodes": [
            {"id": "start", "type": "start", "name": "开始"},
            {"id": "dept", "type": "approval", "name": "部门审批", "assignee_type": "dept_leader", "mode": "any"},
            {"id": "end", "type": "end", "name": "结束"},
        ],
    }
    r = call("POST", "/api/workflows/definitions/", definition)
    ok = r.status_code in (200, 201)
    step("32 创建部门审批流程", ok, f"status={r.status_code} {r.content[:300]!r}")
    definition_id = r.json().get("id") if ok else None
    call("POST", f"/api/workflows/definitions/{definition_id}/publish/", {})
    r = call("POST", f"/api/workflows/definitions/{definition_id}/start/", {
        "title": "部门报销", "business_model_id": dept_model_id, "business_record_id": dept_record_id,
        "data": {"dept": str(east_id), "amount": 1000},
    }, h=H_EDITOR)
    ok = r.status_code in (200, 201) and r.json().get("status") == "running"
    step("33 发起流程", ok, f"status={r.status_code} {r.content[:300]!r}")
    r = call("GET", "/api/workflows/tasks/?status=pending", h=H_LEADER)
    rows = r.json() if r.status_code == 200 and isinstance(r.json(), list) else []
    ok = r.status_code == 200 and any(row.get("assignee") == leader.id for row in rows)
    step("34 部门负责人收到待办", ok, f"status={r.status_code} body={r.content[:400]!r}")

    # ---------------------------------------------------------------- SSR 水合
    from runtime.ssr import ssr_available

    r = call("POST", f"/api/pages/{page_id}/publish/", {"changelog": "feature ssr"})
    step("35 发布页面（生成发布包）", r.status_code == 200, f"status={r.status_code} {r.content[:300]!r}")
    if ssr_available():
        r = call("POST", f"/api/runtime/{app_code}/ssr/rebuild/", {})
        generated = r.json().get("generated") if r.status_code == 200 else []
        step("36 生成 SSR 快照", r.status_code == 200 and len(generated or []) >= 1,
             f"status={r.status_code} {r.content[:300]!r}")
        r = client.get(f"/api/runtime/{app_code}/prerender/home/")
        ok = r.status_code == 200 and b"data-server-rendered" in r.content and b"__WP_SSR__" in r.content
        step("37 SSR 页面包含水合状态", ok, f"status={r.status_code} len={len(r.content)}")
    else:
        step("36 生成 SSR 快照（跳过：未构建 dist-ssr）", True, "")
        step("37 SSR 页面包含水合状态（跳过）", True, "")

    r = client.get(f"/api/runtime/{app_code}/search/?q=%E7%A7%8B%E5%AD%A3")
    ok = r.status_code == 200 and r.json().get("count", 0) >= 1
    step("38 运行时搜索命中索引", ok, f"status={r.status_code} body={r.content[:300]!r}")

    # ---------------------------------------------------------------- AI 全自动建站
    r = call("POST", "/api/ai/autobuild/", {
        "prompt": "做一个独立游戏评测站，包含首页、评测列表、文章详情、关于我们和站内搜索，清爽浅色风",
        "sync": True,
        "options": {
            "use_llm": False, "generate_ssr": False, "sample_content": True,
            "create_workflow": True, "create_realtime": True, "publish": True,
        },
    })
    body = r.json() if r.status_code == 200 else {}
    result = body.get("result") or {}
    ok = r.status_code == 200 and body.get("status") == "success"
    step("39 全自动建站任务完成", ok, f"status={r.status_code} body={r.content[:400]!r}")
    code = result.get("app_code") or ""
    ok = bool(code) and len(result.get("pages") or []) >= 5 and result.get("records", 0) >= 3
    step("40 自动生成应用/动态页面/示例内容", ok, f"result={json.dumps(result, ensure_ascii=False)[:400]}")
    r = client.get(f"/api/runtime/{code}/home" if code else "/api/runtime/")
    ok = r.status_code == 200 and "schema" in (r.json().get("page_version") or {})
    step("41 自动建站可访问", ok, f"status={r.status_code} code={code}")
    r = client.get(f"/api/runtime/{code}/search/?q=%E8%AF%84%E6%B5%8B" if code else "/api/runtime/")
    ok = r.status_code == 200 and r.json().get("count", 0) >= 1
    step("42 自动建站站内搜索", ok, f"status={r.status_code} body={r.content[:200]!r}")
    r = call("GET", f"/api/ai/autobuild/{body.get('id')}/")
    ok = r.status_code == 200 and r.json().get("status") == "success"
    step("43 建站任务可查询", ok, f"status={r.status_code}")
    model_id = result.get("model_id")
    r = client.get(f"/api/runtime/{code}/content/{model_id}/report/?group_by=category&metrics=count&limit=5" if code and model_id else "/api/runtime/")
    ok = r.status_code == 200 and isinstance(r.json().get("rows"), list)
    step("44 公开聚合报表", ok, f"status={r.status_code} body={r.content[:200]!r}")
    r = call("POST", "/api/ai/autobuild/plan/", {
        "prompt": "做一个企业官网，包含首页、产品、关于和搜索",
        "options": {"use_llm": False},
    })
    plan = r.json() if r.status_code == 200 else {}
    ok = r.status_code == 200 and any(page.get("kind") == "home" for page in plan.get("pages") or [])
    step("45 建站前页面计划", ok, f"status={r.status_code} body={r.content[:200]!r}")
    first_page = (result.get("pages") or [{}])[0]
    page_id = first_page.get("id")
    r = call("POST", f"/api/ai/pages/{page_id}/regenerate/", {"kind": "about", "publish": False})
    ok = r.status_code == 200 and r.json().get("ok") is True
    step("46 单页 AI 重新生成", ok, f"status={r.status_code} body={r.content[:200]!r}")
    r = call("GET", f"/api/pages/{page_id}/versions/")
    versions = r.json().get("results") if r.status_code == 200 else []
    version = (versions or [{}])[0].get("version")
    r = call("POST", f"/api/pages/{page_id}/versions/{version}/rollback/", {})
    ok = r.status_code == 200
    step("47 页面版本回滚", ok, f"status={r.status_code} body={r.content[:200]!r}")

    r = call("POST", "/api/ai/autobuild/", {
        "prompt": "做一个在线表单站，包含首页、在线表单、关于和搜索",
        "sync": True,
        "options": {
            "use_llm": False, "generate_ssr": False, "sample_content": True,
            "create_workflow": False, "create_realtime": False, "publish": True,
        },
    })
    form_body = r.json() if r.status_code == 200 else {}
    form_result = form_body.get("result") or {}
    form_page = next((p for p in form_result.get("pages") or [] if p.get("kind") == "form"), {})
    ok = r.status_code == 200 and form_body.get("status") == "success" and bool(form_page.get("path"))
    step("48 公开表单建站", ok, f"status={r.status_code} pages={form_result.get('pages')!r}")
    form_code = form_result.get("app_code") or ""
    form_model = form_result.get("model_id")
    challenge = client.get(f"/api/runtime/{form_code}/content/{form_model}/challenge/" if form_code and form_model else "/api/runtime/")
    challenge_body = challenge.json() if challenge.status_code == 200 else {}
    question = str(challenge_body.get("question") or "")
    answer = ""
    if "+" in question:
        left, right = question.replace("= ?", "").split("+", 1)
        answer = str(int(left.strip()) + int(right.strip()))
    r = client.post(
        f"/api/runtime/{form_code}/content/{form_model}/submit/" if form_code and form_model else "/api/runtime/",
        data=json.dumps({
            "title": "公开表单测试", "summary": "匿名提交", "content": "测试内容", "_hp": "",
            "_captcha_token": challenge_body.get("token") or "", "_captcha_answer": answer,
        }),
        content_type="application/json",
    )
    ok = r.status_code == 201 and r.json().get("status") in ("pending", "received")
    step("49 公开表单提交", ok, f"status={r.status_code} body={r.content[:200]!r}")
    r = call("GET", f"/api/ai/pages/{page_id}/diff/")
    ok = r.status_code == 200 and isinstance(r.json().get("summary"), dict)
    step("50 AI 变更差异", ok, f"status={r.status_code} body={r.content[:200]!r}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n{passed}/{len(RESULTS)} 步通过")
    return 0 if passed == len(RESULTS) else 1

if __name__ == "__main__":
    sys.exit(main())
