import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client

c = Client()
r = c.post("/api/auth/token/", data={"username": "admin", "password": "admin123"}, content_type="application/json")
H = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access']}"}
app_id, order_model, item_model = 29, 28, 29

nav_links = [{"label": "采购订单", "path": "erp/orders"}, {"label": "经营报表", "path": "erp/reports"}]
for page_id in (35, 36):
    schema = c.get(f"/api/pages/{page_id}/schema/", **H).json()["schema"]
    if "nav" in schema["nodes"]:
        schema["nodes"]["nav"].setdefault("props", {})["links"] = nav_links
        r = c.put(f"/api/pages/{page_id}/schema/", data={"schema": schema}, content_type="application/json", **H)
        assert r.status_code == 200, r.content
        r = c.post(f"/api/pages/{page_id}/publish/", data={"changelog": "reports nav"}, content_type="application/json", **H)
        assert r.status_code == 200, r.content

schema = {
    "schemaVersion": 2,
    "rootId": "root",
    "nodes": {
        "root": {"id": "root", "type": "wp-canvas", "componentVersion": "2.0.0", "props": {}, "children": ["main"]},
        "main": {"id": "main", "type": "ElContainer", "componentVersion": "2.0.0", "props": {"direction": "vertical", "padding": 0, "background": "#f5f7fa"}, "children": ["nav", "body"]},
        "nav": {"id": "nav", "type": "site-nav", "componentVersion": "2.0.0", "props": {"brand": "ERP 工作台", "homePath": "erp/orders", "sticky": True, "showSearch": False, "links": nav_links}, "children": []},
        "body": {"id": "body", "type": "ElContainer", "componentVersion": "2.0.0", "props": {"direction": "vertical", "padding": 24, "background": "transparent"}, "children": ["head", "orderCard", "itemCard"], "style": {"maxWidth": "1100px", "width": "100%", "margin": "24px auto", "minHeight": "70vh"}},
        "head": {"id": "head", "type": "ElText", "componentVersion": "2.0.0", "props": {"text": "经营报表", "size": "large", "tag": "h2"}, "children": [], "style": {"fontSize": "24px", "fontWeight": "700", "margin": "0 0 18px"}},
        "orderCard": {"id": "orderCard", "type": "ElCard", "componentVersion": "2.0.0", "props": {"title": "采购订单按状态", "shadow": "never", "padding": 20}, "children": ["orderReport"]},
        "orderReport": {"id": "orderReport", "type": "report-table", "componentVersion": "2.0.0", "props": {"dataModelId": order_model, "groupBy": "status", "groupLabel": "状态", "metrics": "count,sum:amount", "title": "采购订单按状态", "exportable": True}, "children": []},
        "itemCard": {"id": "itemCard", "type": "ElCard", "componentVersion": "2.0.0", "props": {"title": "采购明细按产品", "shadow": "never", "padding": 20}, "children": ["itemReport"], "style": {"marginTop": "16px"}},
        "itemReport": {"id": "itemReport", "type": "report-table", "componentVersion": "2.0.0", "props": {"dataModelId": item_model, "groupBy": "product", "groupLabel": "产品", "metrics": "sum:quantity,sum:amount", "title": "采购明细按产品", "exportable": True}, "children": []},
    },
    "layout": {"mode": "flow", "width": 1200, "height": 900},
    "variables": {},
    "meta": {"title": "经营报表 · ERP 工作台", "lang": "zh-CN", "seo": {"description": "采购订单按状态、采购明细按产品聚合报表"}},
}

r = c.post(f"/api/apps/{app_id}/pages/", data={"name": "经营报表", "path": "erp/reports", "type": "page"}, content_type="application/json", **H)
assert r.status_code in (200, 201), r.content
page = r.json()
r = c.put(f"/api/pages/{page['id']}/schema/", data={"schema": schema}, content_type="application/json", **H)
assert r.status_code == 200, r.content
r = c.post(f"/api/pages/{page['id']}/publish/", data={"changelog": "reports"}, content_type="application/json", **H)
assert r.status_code == 200, r.content
r = c.post(f"/api/apps/{app_id}/releases/", data={"changelog": "reports page"}, content_type="application/json", **H)
print("page", page["id"], "release", r.status_code)
