import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client

from appcore.models import App

c = Client()
r = c.post("/api/auth/token/", data={"username": "admin", "password": "admin123"}, content_type="application/json")
assert r.status_code == 200, r.content
H = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access']}"}

App.objects.filter(code="demo-erp").delete()
r = c.post("/api/apps/", data={"name": "ERP 业务系统", "code": "demo-erp"}, content_type="application/json", **H)
assert r.status_code in (200, 201), r.content
app = r.json()
app_id = app["id"]
print("app", app_id)


def create_model(name, fields):
    r = c.post(
        f"/api/apps/{app_id}/models/",
        data={"name": name, "fields": fields, "is_public": False},
        content_type="application/json",
        **H,
    )
    assert r.status_code in (200, 201), r.content
    return r.json()["id"]


order_model = create_model(
    "erp_order",
    [
        {"name": "order_no", "type": "string", "required": True, "label": "订单号"},
        {"name": "customer", "type": "string", "required": True, "label": "客户"},
        {"name": "status", "type": "string", "label": "状态"},
        {"name": "amount", "type": "number", "label": "订单金额"},
        {"name": "order_date", "type": "date", "label": "下单日期"},
        {"name": "owner", "type": "string", "label": "负责人"},
        {"name": "remark", "type": "string", "label": "备注"},
    ],
)
item_model = create_model(
    "erp_order_item",
    [
        {"name": "order_id", "type": "number", "required": True, "label": "订单 ID"},
        {"name": "product", "type": "string", "required": True, "label": "产品"},
        {"name": "quantity", "type": "number", "label": "数量"},
        {"name": "price", "type": "number", "label": "单价"},
        {"name": "amount", "type": "number", "label": "小计"},
        {"name": "remark", "type": "string", "label": "备注"},
    ],
)
print("models", order_model, item_model)

orders = [
    {"order_no": "PO-2026-001", "customer": "星海科技", "status": "待审批", "amount": 12800, "order_date": "2026-10-20", "owner": "王采购", "remark": "首批办公设备"},
    {"order_no": "PO-2026-002", "customer": "云图网络", "status": "已审批", "amount": 45600, "order_date": "2026-10-22", "owner": "李采购", "remark": "服务器扩容"},
    {"order_no": "PO-2026-003", "customer": "远山制造", "status": "已完成", "amount": 8600, "order_date": "2026-10-24", "owner": "王采购", "remark": "车间耗材补货"},
]
order_ids = []
for row in orders:
    rr = c.post(f"/api/models/{order_model}/records/", data={"data": row}, content_type="application/json", **H)
    assert rr.status_code == 201, rr.content
    order_ids.append(rr.json()["id"])

items = [
    (order_ids[0], "ThinkPad X1 Carbon", 4, 3200, 12800, "i7/32G/1T"),
    (order_ids[1], "Dell PowerEdge R760", 2, 22800, 45600, "双路银牌"),
    (order_ids[1], "万兆交换机", 2, 0, 0, "随服务器赠送"),
    (order_ids[2], "工业手套", 200, 18, 3600, "M 码"),
    (order_ids[2], "切削液", 50, 100, 5000, "20L/桶"),
]
for order_id, product, qty, price, amount, remark in items:
    row = {"order_id": order_id, "product": product, "quantity": qty, "price": price, "amount": amount, "remark": remark}
    rr = c.post(f"/api/models/{item_model}/records/", data={"data": row}, content_type="application/json", **H)
    assert rr.status_code == 201, rr.content
print("orders", len(orders), "items", len(items))


def node(nid, ntype, props=None, children=None, style=None, events=None):
    out = {"id": nid, "type": ntype, "componentVersion": "2.0.0", "props": props or {}, "children": children or []}
    if style:
        out["style"] = style
    if events:
        out["events"] = events
    return out


def schema(nodes, title):
    return {
        "schemaVersion": 2,
        "rootId": "root",
        "nodes": nodes,
        "layout": {"mode": "flow", "width": 1200, "height": 900},
        "variables": {},
        "meta": {"title": title, "lang": "zh-CN", "seo": {"description": title}},
    }


nav = {
    "brand": "ERP 工作台",
    "homePath": "erp/orders",
    "sticky": True,
    "showSearch": False,
    "links": [{"label": "采购订单", "path": "erp/orders"}],
}

list_nodes = {
    "root": node("root", "wp-canvas", {}, ["main"]),
    "main": node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#f5f7fa"}, ["nav", "body"]),
    "nav": node("nav", "site-nav", nav),
    "body": node("body", "ElContainer", {"direction": "vertical", "padding": 24, "background": "#ffffff"}, ["head", "table"], {"maxWidth": "1200px", "width": "100%", "margin": "24px auto", "minHeight": "70vh"}),
    "head": node("head", "ElText", {"text": "采购订单", "size": "large", "tag": "h2"}, [], {"fontSize": "24px", "fontWeight": "700", "margin": "0 0 18px"}),
    "table": node("table", "ElTable", {
        "dataModelId": order_model,
        "remote": True,
        "showPagination": True,
        "pageSize": 10,
        "showSearch": True,
        "searchPlaceholder": "搜索订单号 / 客户…",
        "exportable": True,
        "exportName": "采购订单.csv",
        "rowKey": "id",
        "columns": [
            {"key": "order_no", "label": "订单号", "minWidth": 140, "cellType": "text"},
            {"key": "customer", "label": "客户", "minWidth": 150, "cellType": "text"},
            {"key": "status", "label": "状态", "width": 100, "cellType": "tag", "tagType": "success"},
            {"key": "amount", "label": "金额", "width": 120, "cellType": "text", "prefix": "¥"},
            {"key": "order_date", "label": "下单日期", "width": 120, "cellType": "text"},
            {"key": "owner", "label": "负责人", "width": 100, "cellType": "text"},
            {"key": "actions", "label": "操作", "width": 90, "cellType": "button", "buttonText": "查看", "navigatePattern": "erp/orders/{id}"},
        ],
    }),
}

detail_nodes = {
    "root": node("root", "wp-canvas", {}, ["main"]),
    "main": node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#f5f7fa"}, ["nav", "body"]),
    "nav": node("nav", "site-nav", nav),
    "body": node("body", "ElContainer", {"direction": "vertical", "padding": 24, "background": "transparent"}, ["orderCard", "itemCard"], {"maxWidth": "1100px", "width": "100%", "margin": "24px auto", "minHeight": "70vh"}),
    "orderCard": node("orderCard", "ElCard", {"title": "订单信息", "shadow": "never", "padding": 20}, ["orderForm"]),
    "orderForm": node("orderForm", "auto-form", {"modelId": order_model, "mode": "edit", "recordId": "{{route.id}}", "fieldColumns": 2, "labelPosition": "top", "submitText": "保存订单", "showReset": False, "successMessage": "订单已保存"}),
    "itemCard": node("itemCard", "ElCard", {"title": "订单明细", "shadow": "never", "padding": 20}, ["items"], {"marginTop": "16px"}),
    "items": node("items", "relation-table", {
        "modelId": item_model,
        "foreignKey": "order_id",
        "parentId": "{{route.id}}",
        "title": "",
        "addText": "新增明细",
        "columns": [
            {"prop": "product", "label": "产品", "minWidth": 180},
            {"prop": "quantity", "label": "数量", "width": 90},
            {"prop": "price", "label": "单价", "width": 110},
            {"prop": "amount", "label": "小计", "width": 120},
            {"prop": "remark", "label": "备注", "minWidth": 140},
        ],
    }),
}


def create_page(name, path, schema_obj):
    r = c.post(f"/api/apps/{app_id}/pages/", data={"name": name, "path": path, "type": "page"}, content_type="application/json", **H)
    assert r.status_code in (200, 201), (path, r.content[:500])
    page = r.json()
    r = c.put(f"/api/pages/{page['id']}/schema/", data={"schema": schema_obj}, content_type="application/json", **H)
    assert r.status_code == 200, (path, r.content[:800])
    r = c.post(f"/api/pages/{page['id']}/publish/", data={"changelog": "erp seed"}, content_type="application/json", **H)
    assert r.status_code == 200, (path, r.content[:800])
    print("page", path, page["id"])
    return page


create_page("采购订单", "erp/orders", schema(list_nodes, "采购订单 · ERP 工作台"))
create_page("订单详情", "erp/orders/:id", schema(detail_nodes, "订单详情 · ERP 工作台"))

r = c.post(f"/api/apps/{app_id}/releases/", data={"changelog": "erp launch"}, content_type="application/json", **H)
print("release", r.status_code, r.content[:200])
print("ERP_APP", app_id, "ORDER_MODEL", order_model, "ITEM_MODEL", item_model)
