"""可选的浏览器验证：Edge headless + CDP，截图并收集控制台错误。"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken

import websockets


def _edge_path() -> str:
    configured = str(getattr(settings, "AGENT_BROWSER_PATH", "") or "").strip()
    if configured and Path(configured).exists():
        return configured
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return ""


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def _cdp(ws, method: str, params: dict | None = None) -> dict:
    await ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
    while True:
        data = json.loads(await ws.recv())
        if data.get("id") == 1:
            return data


async def _capture(ws_url: str, page_url: str, token: str, screenshot_path: Path, frontend: str) -> dict:
    errors: list[str] = []
    console: list[str] = []
    async with websockets.connect(ws_url, max_size=40_000_000) as ws:
        await _cdp(ws, "Runtime.enable")
        await _cdp(ws, "Page.enable")
        await _cdp(ws, "Log.enable")
        await _cdp(ws, "Emulation.setDeviceMetricsOverride", {
            "width": 1440, "height": 1000, "deviceScaleFactor": 1, "mobile": False,
        })
        await ws.send(json.dumps({"id": 10, "method": "Page.navigate", "params": {"url": frontend + "/login"}}))
        await asyncio.sleep(1.5)
        await ws.send(json.dumps({
            "id": 11, "method": "Runtime.evaluate",
            "params": {"expression": f"localStorage.setItem('wp_token', {json.dumps(token)});"},
        }))
        await asyncio.sleep(0.4)
        await ws.send(json.dumps({"id": 12, "method": "Page.navigate", "params": {"url": page_url}}))
        deadline = time.time() + 12
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            data = json.loads(raw)
            method = data.get("method")
            params = data.get("params") or {}
            if method == "Runtime.exceptionThrown":
                desc = (((params.get("exceptionDetails") or {}).get("exception") or {}).get("description")
                        or (params.get("exceptionDetails") or {}).get("text"))
                if desc:
                    errors.append(str(desc)[:500])
            elif method == "Log.entryAdded":
                entry = params.get("entry") or {}
                if entry.get("level") == "error":
                    url = str(entry.get("url") or "")
                    if "favicon" in url.lower():
                        continue
                    errors.append(str(entry.get("text") or "")[:500])
            elif method == "Runtime.consoleAPICalled":
                if params.get("type") == "error":
                    args = params.get("args") or []
                    console.append(" ".join(str(a.get("value") or a.get("description") or "") for a in args)[:500])
            elif method == "Page.loadEventFired":
                pass
        await asyncio.sleep(2)
        info = await _cdp(ws, "Runtime.evaluate", {
            "expression": "JSON.stringify({path:location.pathname,title:document.title,text:document.body.innerText.slice(0,200),charts:document.querySelectorAll('.wp-echarts-canvas canvas').length,chartErrors:document.querySelectorAll('.wp-echarts-error').length,errors:[...document.querySelectorAll('.el-message--error')].map(e=>e.innerText)})",
            "returnByValue": True,
        })
        raw_value = (((info.get("result") or {}).get("result") or {}).get("value")) or "{}"
        try:
            page_info = json.loads(raw_value)
        except json.JSONDecodeError:
            page_info = {}
        shot = await _cdp(ws, "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        b64 = (shot.get("result") or {}).get("data")
        if b64:
            screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot_path.write_bytes(base64.b64decode(b64))
    return {"page": page_info, "errors": errors[:20], "console": console[:20]}


def verify_page(page, user, *, prefix: str = "verify", draft: bool = True) -> dict:
    """返回 {available, ok, screenshot, errors}；浏览器缺失时 available=False。"""
    edge = _edge_path()
    if not edge:
        return {"available": False, "ok": False, "error": "未找到浏览器，可配置 AGENT_BROWSER_PATH"}
    from django.conf import settings as django_settings

    frontend = str(getattr(django_settings, "AGENT_FRONTEND_URL", "http://127.0.0.1:5173")).rstrip("/")
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="wp-agent-verify-")
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-sandbox", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/json/version", timeout=1).read()
                break
            except Exception:
                time.sleep(0.25)
        # 创建页面 target；兼容不同 Edge 版本
        req = urllib.request.Request(base + "/json/new?about:blank", method="PUT")
        target = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))
        ws_url = target["webSocketDebuggerUrl"]
        access = str(RefreshToken.for_user(user).access_token)
        media_root = Path(django_settings.MEDIA_ROOT)
        filename = f"{prefix}-{page.id}-{int(time.time())}.png"
        shot_path = media_root / "agent_verify" / filename
        url = f"{frontend}/run/{page.app.code}/{page.path}" + ("?draft=1" if draft else "")
        result = asyncio.run(_capture(ws_url, url, access, shot_path, frontend))
        info = result.get("page") or {}
        errors = list(result.get("errors") or []) + list(info.get("errors") or [])
        if info.get("chartErrors"):
            errors.append(f"发现 {info['chartErrors']} 个图表错误")
        if not info.get("text"):
            errors.append("页面正文为空")
        return {
            "available": True,
            "ok": not errors and int(info.get("charts", 0)) >= 0,
            "screenshot": f"{django_settings.MEDIA_URL.rstrip('/')}/agent_verify/{filename}",
            "page": info,
            "errors": errors[:20],
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        shutil.rmtree(profile, ignore_errors=True)
