"""最小 DSH 兼容服务，用于验证平台全自动建站的 DSH 接入。

这不是 DeepSeek Harness 本体，而是 DSH 的外部契约样例：
POST /build -> MiWebProcess 蓝图
GET  /health -> 健康检查

生产环境应把 /build 换成真正的 DSH Agent，返回同样的蓝图结构。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


REAL = False


def _blueprint(prompt: str) -> dict:
    topic = (prompt or "内容站点").strip()[:60]
    name = topic if topic.endswith(("站", "台", "系统")) else f"{topic}站"
    now = datetime.now(timezone.utc)
    items = []
    for index, title in enumerate([
        f"{name}正式上线：从 0 到 1 的建站实践",
        f"{name}趋势观察：今年值得关注的五个变化",
        f"深度解析：{name}背后的产品思路",
        f"新手入门指南：快速掌握{name}",
    ], start=1):
        items.append({
            "title": title,
            "summary": f"围绕「{topic}」的精选内容与实践建议。",
            "content": (
                f"本文围绕「{topic}」展开，先给出结论，再拆解方法："
                "明确目标用户、梳理信息层级、用可复用组件搭出首屏与内容区，最后通过数据验证效果。\n\n"
                "建议从一个最小可用首页开始，逐步补充列表、详情和关于页面。"
            ),
            "category": "资讯",
            "tags": f"{topic},资讯",
            "author": "DSH 编辑部",
            "published_at": now.isoformat(),
        })
    return {
        "site": {
            "name": name,
            "tagline": f"关于{topic}，这里有你需要的一切",
            "description": f"{name}聚焦{topic}，提供精选内容、深度解读与实用指南。",
            "theme": "light",
            "highlights": [
                {"title": "精选内容", "text": "围绕核心主题持续更新。"},
                {"title": "清晰导航", "text": "首页、列表、详情和关于页形成完整路径。"},
                {"title": "持续迭代", "text": "所有页面都可继续在设计器中调整。"},
            ],
        },
        "content": {"model": "article", "label": "内容", "items": items},
        "about": {
            "title": f"关于{name}",
            "sections": [
                {"heading": "我们是谁", "body": f"{name}是一个专注于{topic}的内容站点。"},
                {"heading": "我们在做什么", "body": "把分散信息整理成清晰结构：列表浏览、详情阅读、搜索直达。"},
                {"heading": "联系我们", "body": "欢迎通过站点导航中的入口联系我们。"},
            ],
        },
        "workflow": {"name": "内容发布审批", "description": "编辑提交内容后由应用所有者审核发布。"},
        "contact": {
            "email": "hello@example.com", "phone": "+86 400-000-0000",
            "address": "中国 · 上海", "hours": "工作日 09:00 - 18:00",
            "intro": "欢迎通过以下方式联系我们。",
        },
        "pricing": {
            "title": "价格方案",
            "plans": [
                {"name": "基础版", "price": "¥0", "period": "/月", "features": ["基础页面", "社区支持"]},
                {"name": "专业版", "price": "¥199", "period": "/月", "features": ["全部组件", "优先支持"]},
            ],
        },
        "docs": {
            "title": "文档中心",
            "sections": [
                {"heading": "快速开始", "body": "创建应用后由 DSH 生成页面和内容。"},
                {"heading": "发布", "body": "发布后生成不可变快照，可回滚。"},
            ],
        },
        "pages": [
            {"kind": "home", "name": "首页", "path": "home"},
            {"kind": "list", "name": "资讯", "path": "news", "category": "资讯", "title": "最新资讯"},
            {"kind": "detail", "name": "文章详情", "path": "article/:id", "list_path": "news"},
            {"kind": "about", "name": "关于我们", "path": "about"},
            {"kind": "contact", "name": "联系我们", "path": "contact"},
            {"kind": "search", "name": "站内搜索", "path": "search"},
        ],
        "warnings": [],
    }




def _find_chart(schema: dict) -> tuple[str, dict] | tuple[None, None]:
    for node_id, node in (schema.get("nodes") or {}).items():
        if isinstance(node, dict) and node.get("type") == "wp-echarts":
            return node_id, node
    return None, None


def _bar_option(node: dict) -> dict | None:
    option = node.get("props", {}).get("option") or {}
    series = (option.get("series") or [{}])[0]
    kind = str(series.get("type") or node.get("props", {}).get("chartType") or "")
    if kind == "pie":
        data = series.get("data") or []
        names = [str(x.get("name") or "") for x in data if isinstance(x, dict)]
        values = [x.get("value") for x in data if isinstance(x, dict)]
        title = "访问量"
    elif kind in ("line", "bar"):
        names = (option.get("xAxis") or {}).get("data") or []
        values = series.get("data") or []
        title = str(series.get("name") or "数据")
    else:
        return None
    return {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": {"type": "category", "data": names},
        "yAxis": {"type": "value", "name": title},
        "series": [{
            "type": "bar", "name": title, "data": values, "barWidth": "48%",
            "itemStyle": {"borderRadius": [4, 4, 0, 0]},
        }],
    }


def task_proposal(goal: str, page: dict | None) -> dict:
    schema = (page or {}).get("schema") or {}
    node_id, node = _find_chart(schema)
    if node_id and ("柱状" in goal or "bar" in goal.lower()):
        option = _bar_option(node)
        if option:
            return {
                "kind": "page_patch",
                "summary": f"把图表 {node_id} 改为柱状图",
                "ops": [{"op": "update_node", "node_id": node_id, "props": {"chartType": "bar", "option": option, "height": 300}}],
            }
    return {
        "kind": "page_patch",
        "summary": "DSH 已分析页面，但没有可执行的确定性修改",
        "ops": [],
    }




def _extract_json(text: str):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def _real_dsh(prompt: str, timeout: int = 300) -> dict:
    exe = shutil.which("dsh") or "dsh"
    env = dict(os.environ)
    env.setdefault("DSH_NO_UPDATE_CHECK", "1")
    cmd = [exe, "--profile", "headless", "-"]
    result = subprocess.run(
        cmd, env=env, input=prompt, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "DSH failed")[-800:])
    data = _extract_json(result.stdout)
    if not isinstance(data, dict):
        raise ValueError("DSH 没有返回 JSON")
    return data


def _build_prompt(prompt: str) -> str:
    return f"""你是 MiWebProcess 的 DSH 建站 Agent。
只输出一个 JSON 对象，不要 Markdown，不要解释。
JSON 结构必须是：
{{"blueprint": {{
  "site": {{"name":"站点名","tagline":"一句话","description":"描述","theme":"light","highlights":[]}},
  "content": {{"model":"article","label":"内容","items":[]}},
  "about": {{"title":"关于","sections":[]}},
  "workflow": {{"name":"内容发布审批","description":""}},
  "contact": {{}},
  "pricing": {{"title":"价格方案","plans":[]}},
  "docs": {{"title":"文档中心","sections":[]}},
  "pages": [
    {{"kind":"home","name":"首页","path":"home"}},
    {{"kind":"list","name":"资讯","path":"news","category":"资讯","title":"最新资讯"}},
    {{"kind":"detail","name":"文章详情","path":"article/:id","list_path":"news"}},
    {{"kind":"about","name":"关于我们","path":"about"}},
    {{"kind":"contact","name":"联系我们","path":"contact"}},
    {{"kind":"search","name":"站内搜索","path":"search"}}
  ]
}}}}
用户需求：{prompt}
"""


def _task_prompt(goal: str, page: dict | None) -> str:
    return f"""你是 MiWebProcess 的 DSH 页面 Agent。
只输出一个 JSON 对象，不要 Markdown，不要解释。
结构：{{"proposals":[{{"kind":"page_patch","summary":"说明","ops":[{{"op":"update_node","node_id":"节点id","props":{{}}}}]}}]}}
页面 schema：{json.dumps(page or {{}}, ensure_ascii=False)[:30000]}
用户目标：{goal}
要求：
1. 只修改必要节点；
2. 节点 id 必须来自页面 schema；
3. 图表使用 wp-echarts 完整 option；
4. 无法安全修改则返回 proposals: []。
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/") == "/health":
            self._send(200, {"ok": True, "service": "dsh-real" if REAL else "dsh-stub", "version": "1.0", "real": REAL})
        elif self.path.rstrip("/") == "/status":
            self._send(200, {"real": REAL, "mode": "real" if REAL else "stub", "provider": "dsh" if REAL else "stub"})
        else:
            self._send(404, {"detail": "not found"})

    def do_POST(self):
        path = self.path.rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send(400, {"detail": "invalid json"})
            return
        if path == "/build":
            prompt = str(body.get("prompt") or "内容站点")
            if REAL:
                try:
                    data = _real_dsh(_build_prompt(prompt))
                    if not isinstance(data.get("blueprint"), dict):
                        raise ValueError("DSH build 缺少 blueprint")
                    self._send(200, {"blueprint": data["blueprint"], "provider": "dsh", "model": "deepseek-harness", "warnings": []})
                    return
                except Exception as exc:  # noqa: BLE001
                    self._send(502, {"detail": f"DSH build 失败：{type(exc).__name__}: {exc}"})
                    return
            self._send(200, {
                "blueprint": _blueprint(prompt),
                "provider": "dsh-stub",
                "model": "dsh-stub-blueprint",
                "warnings": ["这是 DSH 兼容样例；生产环境请替换为真实 DSH"],
            })
            return
        if path == "/tasks":
            if REAL:
                try:
                    data = _real_dsh(_task_prompt(str(body.get("goal") or ""), body.get("page")))
                    proposals = data.get("proposals") or []
                    if not isinstance(proposals, list):
                        raise ValueError("DSH task 缺少 proposals")
                    self._send(200, {"proposals": proposals, "provider": "dsh", "model": "deepseek-harness"})
                    return
                except Exception as exc:  # noqa: BLE001
                    self._send(502, {"detail": f"DSH task 失败：{type(exc).__name__}: {exc}"})
                    return
            self._send(200, {
                "proposals": [task_proposal(str(body.get("goal") or ""), body.get("page"))],
                "provider": "dsh-stub",
                "model": "dsh-stub-agent",
            })
            return
        self._send(404, {"detail": "not found"})

    def log_message(self, fmt, *args):
        print(f"[dsh] {self.address_string()} {fmt % args}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--task-file", default="")
    parser.add_argument("--real", action="store_true", help="使用本机 dsh headless 作为真实 Agent")
    args = parser.parse_args()
    global REAL
    REAL = bool(args.real)
    if args.task_file:
        with open(args.task_file, "r", encoding="utf-8-sig") as fh:
            payload = json.load(fh)
        if REAL:
            data = _real_dsh(_task_prompt(str(payload.get("goal") or ""), payload.get("page")))
            print(json.dumps(data, ensure_ascii=False), flush=True)
        else:
            print(json.dumps({
                "proposals": [task_proposal(str(payload.get("goal") or ""), payload.get("page"))],
                "provider": "dsh-stub",
                "model": "dsh-stub-agent",
            }, ensure_ascii=False), flush=True)
        return
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"DSH stub listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
