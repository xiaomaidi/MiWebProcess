import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client
from workflow.models import WorkflowInstance

c = Client()
r = c.post("/api/auth/token/", data={"username": "admin", "password": "admin123"}, content_type="application/json")
H = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access']}"}
app_id, page_id = 29, 36

WorkflowInstance.objects.all().delete()

nodes = [
    {"id": "start", "name": "发起", "type": "start"},
    {"id": "dept", "name": "部门审批", "type": "approval", "assignee_role": "editor", "mode": "all"},
    {"id": "amount_condition", "name": "金额 > 20000", "type": "condition",
     "condition": {"field": "amount", "operator": "gt", "value": 20000}, "false_next": "end"},
    {"id": "finance", "name": "财务会签", "type": "approval", "mode": "all",
     "approvers": [{"assignee_role": "owner"}, {"assignee_role": "editor"}]},
    {"id": "end", "name": "结束", "type": "end", "on_approve": {"status": "已审批"}, "on_reject": {"status": "已驳回"}},
]

defs = c.get(f"/api/workflows/definitions/?app_id={app_id}", **H).json()
existing = next((d for d in defs if d.get("code") == "purchase_approval_v2"), None)
if existing:
    r = c.put(f"/api/workflows/definitions/{existing['id']}/", data={"name": "采购订单审批 v2", "description": "部门审批后按金额进入财务会签", "nodes": nodes}, content_type="application/json", **H)
    definition_id = existing["id"]
else:
    r = c.post("/api/workflows/definitions/", data={"app_id": app_id, "name": "采购订单审批 v2", "code": "purchase_approval_v2", "description": "部门审批后按金额进入财务会签", "nodes": nodes}, content_type="application/json", **H)
    assert r.status_code in (200, 201), r.content
    definition_id = r.json()["id"]
print("definition", definition_id, r.status_code)
r = c.post(f"/api/workflows/definitions/{definition_id}/publish/", data={}, content_type="application/json", **H)
assert r.status_code == 200, r.content

schema = c.get(f"/api/pages/{page_id}/schema/", **H).json()["schema"]
schema["nodes"]["approval"]["props"]["definitionId"] = definition_id
r = c.put(f"/api/pages/{page_id}/schema/", data={"schema": schema}, content_type="application/json", **H)
assert r.status_code == 200, r.content
r = c.post(f"/api/pages/{page_id}/publish/", data={"changelog": "workflow v2"}, content_type="application/json", **H)
assert r.status_code == 200, r.content
r = c.post(f"/api/apps/{app_id}/releases/", data={"changelog": "workflow v2"}, content_type="application/json", **H)
print("page", page_id, "release", r.status_code)
print("WORKFLOW_V2", definition_id)
