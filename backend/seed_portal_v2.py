import json
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.test import Client

from appcore.models import App

DATA = json.loads(Path(__file__).with_name("portal_seed_data.json").read_text(encoding="utf-8"))

c = Client()
r = c.post("/api/auth/token/", data={"username": "admin", "password": "admin123"}, content_type="application/json")
assert r.status_code == 200, r.content
H = {"HTTP_AUTHORIZATION": f"Bearer {r.json()['access']}"}

App.objects.filter(code="demo-portal").delete()
r = c.post("/api/apps/", data={"name": "游民资讯门户", "code": "demo-portal"}, content_type="application/json", **H)
assert r.status_code in (200, 201), r.content
app = r.json()
app_id = app["id"]
print("app", app_id, app["code"])


def create_model(name, fields, is_public=True):
    r = c.post(
        f"/api/apps/{app_id}/models/",
        data={"name": name, "fields": fields, "is_public": is_public},
        content_type="application/json",
        **H,
    )
    assert r.status_code in (200, 201), r.content
    return r.json()["id"]


category_model = create_model(
    "portal_category",
    [
        {"name": "name", "type": "string", "required": True, "label": "分类名称"},
        {"name": "slug", "type": "string", "required": True, "label": "分类 slug"},
        {"name": "sort", "type": "number", "label": "排序"},
        {"name": "color", "type": "string", "label": "颜色"},
    ],
)
author_model = create_model(
    "portal_author",
    [
        {"name": "name", "type": "string", "required": True, "label": "作者"},
        {"name": "avatar", "type": "string", "label": "头像"},
        {"name": "bio", "type": "string", "label": "简介"},
    ],
)
article_model = create_model(
    "portal_article",
    [
        {"name": "title", "type": "string", "required": True, "label": "标题"},
        {"name": "slug", "type": "string", "required": True, "label": "slug"},
        {"name": "summary", "type": "string", "label": "摘要"},
        {"name": "content", "type": "string", "label": "正文 HTML"},
        {"name": "cover", "type": "string", "label": "封面"},
        {"name": "category", "type": "string", "required": True, "label": "分类 slug"},
        {"name": "author", "type": "string", "label": "作者"},
        {"name": "tags", "type": "json", "label": "标签"},
        {"name": "published_at", "type": "date", "label": "发布时间"},
        {"name": "status", "type": "string", "label": "状态"},
        {"name": "featured", "type": "boolean", "label": "焦点推荐"},
        {"name": "views", "type": "number", "label": "阅读量"},
    ],
)
print("models", category_model, author_model, article_model)

for row in DATA["categories"]:
    rr = c.post(f"/api/models/{category_model}/records/", data={"data": row}, content_type="application/json", **H)
    assert rr.status_code == 201, rr.content
for row in DATA["authors"]:
    rr = c.post(f"/api/models/{author_model}/records/", data={"data": row}, content_type="application/json", **H)
    assert rr.status_code == 201, rr.content
for row in DATA["articles"]:
    payload = dict(row)
    payload["status"] = "published"
    rr = c.post(f"/api/models/{article_model}/records/", data={"data": payload}, content_type="application/json", **H)
    assert rr.status_code == 201, (row["slug"], rr.content[:500])
print("articles", len(DATA["articles"]))

nav_links = [
    {"label": "首页", "path": "home"},
    {"label": "游戏", "path": "news/games"},
    {"label": "电竞", "path": "news/esports"},
    {"label": "硬件", "path": "news/hardware"},
    {"label": "评测", "path": "news/reviews"},
    {"label": "文化", "path": "news/culture"},
]


def node(nid, ntype, props=None, children=None, style=None, events=None):
    out = {"id": nid, "type": ntype, "componentVersion": "2.0.0", "props": props or {}, "children": children or []}
    if style:
        out["style"] = style
    if events:
        out["events"] = events
    return out


def page_schema(nodes, title):
    return {
        "schemaVersion": 2,
        "rootId": "root",
        "nodes": nodes,
        "layout": {"mode": "flow", "width": 1200, "height": 900},
        "variables": {},
        "meta": {
            "title": title,
            "lang": "zh-CN",
            "seo": {"description": title, "ogImage": "https://picsum.photos/seed/portal-1/900/520"},
        },
    }


nav_props = {
    "brand": "游民资讯",
    "homePath": "home",
    "sticky": True,
    "showSearch": True,
    "searchPath": "search",
    "searchText": "搜索",
    "links": nav_links,
}

home_nodes = {
    "root": node("root", "wp-canvas", {}, ["main"]),
    "main": node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#ffffff"}, ["nav", "hero", "featured", "latestRow", "foot"]),
    "nav": node("nav", "site-nav", nav_props),
    "hero": node("hero", "ElContainer", {"direction": "vertical", "background": "#17181c", "padding": 42}, ["heroRow"]),
    "heroRow": node("heroRow", "ElRow", {"gutter": 24, "align": "middle"}, ["heroText", "heroCta"]),
    "heroText": node("heroText", "ElCol", {"span": 16}, ["heroTitle", "heroSub", "heroTags"]),
    "heroTitle": node("heroTitle", "ElText", {"text": "在这里，读懂游戏与玩家文化", "size": "large", "tag": "h1"}, [], {"color": "#ffffff", "fontSize": "36px", "fontWeight": "800", "margin": "0 0 12px", "lineHeight": "1.3"}),
    "heroSub": node("heroSub", "ElText", {"text": "游戏资讯、深度评测、电竞前线与硬件指南 —— 每天更新。", "type": "info"}, [], {"color": "#c9cdd4", "fontSize": "15px", "margin": "0 0 20px"}),
    "heroTags": node("heroTags", "ElSpace", {"size": "default", "wrap": True}, ["heroTag1", "heroTag2", "heroTag3"]),
    "heroTag1": node("heroTag1", "ElTag", {"text": "黑神话 DLC", "type": "danger", "effect": "dark"}),
    "heroTag2": node("heroTag2", "ElTag", {"text": "TI14 决赛", "type": "primary", "effect": "dark"}),
    "heroTag3": node("heroTag3", "ElTag", {"text": "RTX 5090 评测", "type": "success", "effect": "dark"}),
    "heroCta": node("heroCta", "ElCol", {"span": 8}, ["heroBtn"]),
    "heroBtn": node("heroBtn", "ElButton", {"text": "进入游戏频道", "type": "danger", "size": "large"}, [], {"float": "right"}, {"click": [{"kind": "navigate", "params": {"path": "news/games"}}]}),
    "featured": node("featured", "content-list", {"dataModelId": article_model, "mode": "grid", "heading": "焦点推荐", "filters": {"featured": True, "status": "published"}, "pageSize": 3, "showPagination": False, "showSearch": False, "hrefPattern": "article/{id}"}, [], {"padding": "28px 24px 6px"}),
    "latestRow": node("latestRow", "ElRow", {"gutter": 24}, ["latestCol", "sideCol"], {"padding": "8px 24px 28px"}),
    "latestCol": node("latestCol", "ElCol", {"span": 16}, ["latest"]),
    "latest": node("latest", "content-list", {"dataModelId": article_model, "mode": "list", "heading": "最新资讯", "filters": {"status": "published"}, "pageSize": 6, "showPagination": False, "showSearch": False, "hrefPattern": "article/{id}"}),
    "sideCol": node("sideCol", "ElCol", {"span": 8}, ["ranking"]),
    "ranking": node("ranking", "content-list", {"dataModelId": article_model, "mode": "ranking", "heading": "热门排行", "filters": {"status": "published"}, "pageSize": 5, "showPagination": False, "showSearch": False, "hrefPattern": "article/{id}"}),
    "foot": node("foot", "ElText", {"text": "© 2026 游民资讯 · 演示站点 · 内容仅用于产品演示", "type": "info"}, [], {"textAlign": "center", "padding": "22px", "color": "#86909c", "fontSize": "12px"}),
}

category_nodes = {
    "root": node("root", "wp-canvas", {}, ["main"]),
    "main": node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#f7f8fa"}, ["nav", "body"]),
    "nav": node("nav", "site-nav", nav_props),
    "body": node("body", "ElContainer", {"direction": "vertical", "padding": 24, "background": "#ffffff"}, ["list"], {"maxWidth": "1200px", "width": "100%", "margin": "24px auto", "minHeight": "70vh"}),
    "list": node("list", "content-list", {"dataModelId": article_model, "categoryModelId": category_model, "categoryField": "category", "categoryBasePath": "news", "showCategoryTabs": True, "mode": "list", "heading": "资讯频道", "pageSize": 8, "showSearch": True, "filters": {"status": "published"}, "hrefPattern": "article/{id}"}),
}

detail_nodes = {
    "root": node("root", "wp-canvas", {}, ["main"]),
    "main": node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#ffffff"}, ["nav", "body"]),
    "nav": node("nav", "site-nav", nav_props),
    "body": node("body", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#ffffff"}, ["detail"], {"maxWidth": "900px", "width": "100%", "margin": "0 auto"}),
    "detail": node("detail", "article-detail", {"dataModelId": article_model, "lookup": "id", "showRelated": True, "relatedLimit": 4, "categoryPathPrefix": "news", "articlePath": "article/{id}", "backPath": "home"}),
}

search_nodes = {
    "root": node("root", "wp-canvas", {}, ["main"]),
    "main": node("main", "ElContainer", {"direction": "vertical", "padding": 0, "background": "#f7f8fa"}, ["nav", "body"]),
    "nav": node("nav", "site-nav", nav_props),
    "body": node("body", "ElContainer", {"direction": "vertical", "padding": 24, "background": "#ffffff"}, ["search"], {"maxWidth": "1000px", "width": "100%", "margin": "24px auto", "minHeight": "70vh"}),
    "search": node("search", "content-list", {"dataModelId": article_model, "mode": "list", "heading": "站内搜索", "pageSize": 10, "showSearch": True, "searchPlaceholder": "搜索标题、摘要或标签…", "filters": {"status": "published"}, "hrefPattern": "article/{id}"}),
}


def create_page(name, path, schema):
    r = c.post(f"/api/apps/{app_id}/pages/", data={"name": name, "path": path, "type": "page"}, content_type="application/json", **H)
    assert r.status_code in (200, 201), (path, r.status_code, r.content[:500])
    page = r.json()
    r = c.put(f"/api/pages/{page['id']}/schema/", data={"schema": schema}, content_type="application/json", **H)
    assert r.status_code == 200, (path, r.content[:800])
    r = c.post(f"/api/pages/{page['id']}/publish/", data={"changelog": "portal seed"}, content_type="application/json", **H)
    assert r.status_code == 200, (path, r.content[:800])
    print("page", path, page["id"])
    return page


create_page("首页", "home", page_schema(home_nodes, "游民资讯 · 游戏玩家的每日资讯"))
create_page("资讯频道", "news/:category", page_schema(category_nodes, "资讯频道 · 游民资讯"))
create_page("文章详情", "article/:id", page_schema(detail_nodes, "文章详情 · 游民资讯"))
create_page("搜索", "search", page_schema(search_nodes, "搜索 · 游民资讯"))

r = c.post(f"/api/apps/{app_id}/releases/", data={"changelog": "portal launch"}, content_type="application/json", **H)
print("release", r.status_code, r.content[:200])
print("PORTAL_APP", app_id, "ARTICLES", article_model, "CATEGORIES", category_model)
