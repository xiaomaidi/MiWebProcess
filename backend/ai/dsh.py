"""DSH 高级执行器客户端：全自动建站蓝图生成。"""
from __future__ import annotations

import json
import urllib.request

from django.conf import settings


def configured() -> bool:
    return bool(str(getattr(settings, "DSH_AGENT_URL", "") or "").strip())


def _post(path: str, payload: dict, timeout: int = 300) -> dict:
    url = str(getattr(settings, "DSH_AGENT_URL", "")).rstrip("/") + path
    headers = {"Content-Type": "application/json"}
    token = str(getattr(settings, "DSH_AGENT_TOKEN", "") or "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def build_blueprint(prompt: str, options: dict) -> dict:
    """调用 DSH 生成 MiWebProcess 蓝图。

    约定：POST {DSH_AGENT_URL}/build
    {prompt, options, schema: "miwebprocess-blueprint-v1"}
    返回：{blueprint: {...}, provider, model, warnings}
    """
    data = _post("/build", {
        "prompt": prompt,
        "options": options or {},
        "schema": "miwebprocess-blueprint-v1",
        "capabilities": {
            "pages": True,
            "models": True,
            "workflow": True,
            "publish": True,
        },
    })
    blueprint = data.get("blueprint")
    if not isinstance(blueprint, dict):
        raise ValueError("DSH 返回缺少 blueprint")
    if not isinstance(blueprint.get("site"), dict):
        raise ValueError("DSH blueprint 缺少 site")
    return {
        "blueprint": blueprint,
        "provider": str(data.get("provider") or "dsh"),
        "model": str(data.get("model") or "dsh-agent"),
        "warnings": data.get("warnings") or [],
    }
