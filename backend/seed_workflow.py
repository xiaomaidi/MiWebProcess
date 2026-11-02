import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client

c = Client()
r = c.post("/api/auth/token/", data={"username": "admin", "password": "admin123"}, content_type="application/json")
assert r.status_code == 200, r.content
H = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access']}"}
app_id = 29
order_model = 28
page_id = 36

r = c.get(f"/api/workflows/definitions/?app_id={app_id}", **H)
existing = [w for w in r.json() if w.get("code") == "purchase_approval"]
if existing:
    definition_id = existing[0]["id"]
    r = c.put(
        f"/api/workflows/definitions/{definition_id}/",
        data={
            "name": "采购订单审批",
            "description": "采购订单提交后依次由部门负责人、财务负责人审批。",
            "nodes": [
                {"id": "start", "name": "发起", "type": "start"},
                {"id": "dept", "name": "部门审批", "type": "approval", "assignee_role": "editor"},
                {"id": "finance", "name": "财务审批", "type": "approval", "assignee_role": "owner"},
                {"id": "end", "name": "结束", "type": "end", "on_approve": {"status": "已审批"}, "on_reject": {"status": "已驳回"}},
            ],
        },
        content_type="application/json",
        **H,
    )
    assert r.status_code == 200, r.content
else:
    r = c.post(
        f"/api/workflows/definitions/",
        data={
            "app_id": app_id,
            "name": "采购订单审批",
            "code": "purchase_approval",
            "description": "采购订单提交后依次由部门负责人、财务负责人审批。",
            "nodes": [
                {"id": "start", "name": "发起", "type": "start"},
                {"id": "dept", "name": "部门审批", "type": "approval", "assignee_role": "editor"},
                {"id": "finance", "name": "财务审批", "type": "approval", "assignee_role": "owner"},
                {"id": "end", "name": "结束", "type": "end", "on_approve": {"status": "已审批"}, "on_reject": {"status": "已驳回"}},
            ],
        },
        content_type="application/json",
        **H,
    )
    assert r.status_code in (200, 201), r.content
    definition_id = r.json()["id"]
r = c.post(f"/api/workflows/definitions/{definition_id}/publish/", data={}, content_type="application/json", **H)
assert r.status_code == 200, r.content
print("definition", definition_id)

schema = c.get(f"/api/pages/{page_id}/schema/", **H).json()["schema"]
nodes = schema["nodes"]
if "approval" not in nodes:
    nodes["approvalCard"] = {
        "id": "approvalCard", "type": "ElCard", "componentVersion": "2.0.0",
        "props": {"title": "审批流程", "shadow": "never", "padding": 20},
        "children": ["approval"],
        "style": {"marginTop": "16px"},
    }
    nodes["approval"] = {
        "id": "approval", "type": "approval-panel", "componentVersion": "2.0.0",
        "props": {
            "definitionId": definition_id,
            "businessModelId": order_model,
            "businessRecordId": "{{route.id}}",
            "title": "采购订单审批",
        },
        "children": [],
    }
    nodes["body"]["children"] = ["orderCard", "itemCard", "approvalCard"]
r = c.put(f"/api/pages/{page_id}/schema/", data={"schema": schema}, content_type="application/json", **H)
assert r.status_code == 200, r.content
r = c.post(f"/api/pages/{page_id}/publish/", data={"changelog": "approval panel"}, content_type="application/json", **H)
assert r.status_code == 200, r.content
r = c.post(f"/api/apps/{app_id}/releases/", data={"changelog": "workflow panel"}, content_type="application/json", **H)
print("release", r.status_code, r.content[:160])
print("WORKFLOW_DEFINITION", definition_id)
