"""DSH 执行沙箱状态与容器运行约定。

平台不强依赖 Docker；没有 Docker 时使用外部 DSH HTTP 或内置 Agent。
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings


def sandbox_status() -> dict:
    image = str(getattr(settings, "DSH_SANDBOX_IMAGE", "") or "").strip()
    docker = shutil.which("docker") or ""
    return {
        "docker_available": bool(docker),
        "docker_path": docker,
        "image": image,
        "mode": str(getattr(settings, "DSH_SANDBOX_MODE", "http")),
        "container_ready": bool(docker and image),
        "network": str(getattr(settings, "DSH_SANDBOX_NETWORK", "none")),
        "memory": str(getattr(settings, "DSH_SANDBOX_MEMORY", "1g")),
        "cpus": str(getattr(settings, "DSH_SANDBOX_CPUS", "1")),
        "timeout": int(getattr(settings, "DSH_SANDBOX_TIMEOUT", 300)),
        "workspace": "/workspace",
    }


def _parse_json_output(text: str) -> dict:
    value = str(text or "").strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        start = value.rfind("{")
        if start >= 0:
            return json.loads(value[start:])
        raise


def run_task_sandbox(payload: dict) -> dict:
    """在进程或容器中执行 DSH 任务，返回 {proposals,...}。"""
    mode = str(getattr(settings, "DSH_SANDBOX_MODE", "http") or "http").lower()
    if mode not in ("process", "docker"):
        raise ValueError("当前不是容器/进程沙箱模式")
    workspace = tempfile.mkdtemp(prefix="wp-dsh-sandbox-")
    task_file = Path(workspace) / "task.json"
    task_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
    }
    try:
        if mode == "docker":
            cmd = container_command(int(payload.get("task_id") or 0), workspace)
        else:
            command = str(getattr(settings, "DSH_SANDBOX_COMMAND", "") or "").strip()
            if not command:
                raise ValueError("未配置 DSH_SANDBOX_COMMAND")
            if "{task_file}" in command:
                command = command.replace("{task_file}", str(task_file))
                cmd = shlex.split(command, posix=False)
            else:
                cmd = shlex.split(command, posix=False)
                cmd.append(str(task_file))
        result = subprocess.run(
            cmd, cwd=workspace, env=env, capture_output=True, text=True,
            timeout=int(getattr(settings, "DSH_SANDBOX_TIMEOUT", 300)),
        )
        if result.returncode != 0:
            raise RuntimeError(f"沙箱退出码 {result.returncode}: {(result.stderr or '')[-500:]}")
        data = _parse_json_output(result.stdout)
        proposals = data.get("proposals") or []
        if not isinstance(proposals, list):
            raise ValueError("沙箱返回 proposals 格式错误")
        return {"proposals": proposals, "provider": "dsh-sandbox", "model": data.get("model") or "dsh-sandbox"}
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def container_command(task_id: int, workspace: str) -> list[str]:
    """生成 DSH 容器命令；镜像和入口由运维配置。"""
    image = str(getattr(settings, "DSH_SANDBOX_IMAGE", "") or "").strip()
    if not image:
        raise ValueError("未配置 DSH_SANDBOX_IMAGE")
    return [
        "docker", "run", "--rm",
        "--network", str(getattr(settings, "DSH_SANDBOX_NETWORK", "none")),
        "--memory", str(getattr(settings, "DSH_SANDBOX_MEMORY", "1g")),
        "--cpus", str(getattr(settings, "DSH_SANDBOX_CPUS", "1")),
        "-v", f"{Path(workspace).resolve()}:/workspace",
        "-w", "/workspace",
        image,
        "--task", f"/workspace/task-{task_id}.json",
    ]
