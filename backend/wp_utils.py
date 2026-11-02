"""通用工具：分页 / 应用权限 / 频道广播 / 数据源转换 / 轻量 HTTP 客户端。

非 Django app 的纯工具模块，供各业务 app 复用。
"""
from __future__ import annotations

import json
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlencode, urlparse

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from core.pagination import WPPagination
from core.permissions import ROLE_ORDER, get_app_role, is_platform_admin


def is_platform_admin_full(user) -> bool:
    """平台管理员：superuser 或 is_platform_admin 标志。"""
    return bool(getattr(user, "is_authenticated", False)) and bool(
        getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False)
    )


def app_model():
    from appcore.models import App

    return App


def get_app(app_id: int):
    return get_object_or_404(app_model(), pk=app_id)


def require_app_role(user, app, min_role: str = "viewer") -> str:
    """校验用户在 app 内的角色，返回实际角色；平台管理员返回 "owner"。"""
    if is_platform_admin(user):
        return "owner"
    role = get_app_role(user, app)
    if role is None:
        raise PermissionDenied("您不是该应用的成员")
    if ROLE_ORDER.get(role, 0) < ROLE_ORDER.get(min_role, 0):
        raise PermissionDenied(f"需要 {min_role} 及以上权限")
    return role


def paginate(request, queryset, serializer_class) -> Response:
    """docs/API.md 分页：?page=1&size=20 → {count, results, page, size}"""
    paginator = WPPagination()
    page = paginator.paginate_queryset(queryset, request, view=None)
    return paginator.get_paginated_response(serializer_class(page, many=True).data)


def paginate_items(request, queryset, serializer_class) -> Response:
    """列表端点分页：?page=1&size=20 → {count, results, page, size}（docs/API.md）。

    serializer_class 可以是 DRF 序列化器类或逐项可调用（如 lambda item: dict）。
    """
    from rest_framework.exceptions import ValidationError

    try:
        page = max(int(request.query_params.get("page") or 1), 1)
        page_size = int(request.query_params.get("size") or request.query_params.get("page_size") or 20)
    except (TypeError, ValueError):
        raise ValidationError({"detail": "page/size 必须是整数"})
    page_size = max(1, min(page_size, 100))
    total = queryset.count()
    start = (page - 1) * page_size
    rows = list(queryset[start : start + page_size])
    if isinstance(serializer_class, type):
        results = serializer_class(rows, many=True).data
    else:  # 可调用（逐项序列化）
        results = [serializer_class(row) for row in rows]
    return Response({"count": total, "results": results, "page": page, "size": page_size})


def broadcast_to_app(app_id: int, message: dict[str, Any], sender: str = "") -> None:
    """向 app 房间广播（尽力而为，失败不影响业务）。

    线上消息格式：{"type", "payload", "from", "ts"}；
    message["extra"] 中的字段会平铺到顶层（API.md §9 的顶层字段）。
    """
    if not app_id:
        return
    wire = {
        "type": message.get("type", "message"),
        "payload": message.get("payload", {}),
        "from": sender or "",
        "ts": int(time.time() * 1000),
    }
    extra = message.get("extra")
    if isinstance(extra, dict):
        wire.update(extra)
    try:
        import asyncio

        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        if layer is None:
            return
        coro = layer.group_send(
            f"app_{app_id}",
            {"type": "app_broadcast", "message": json.dumps(wire, ensure_ascii=False, default=str)},
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            loop.create_task(coro)
        else:
            # 同步上下文（普通视图 / eager celery）：一次性事件循环
            asyncio.run(coro)
    except Exception:
        pass  # 广播失败不阻塞业务


def broadcast_draft_saved(app_id: int, page_id: int, version: int, username: str = "") -> None:
    broadcast_to_app(
        app_id,
        {
            "type": "draft_saved",
            "payload": {"page_id": page_id, "user": username, "version": version},
            "extra": {"page_id": page_id, "user": username, "version": version},
        },
        sender=username,
    )


_PATH_TOKEN_RE = re.compile(r"([^\.\[\]]+)|\[(\d+|\*)\]")


def get_json_path(obj: Any, path: str | None) -> Any:
    """轻量路径取值：a.b、a[0].b、a.list[*]、$.a.b。"""
    if not path:
        return obj
    text = str(path).strip()
    if text.startswith("$"):
        text = text[1:].lstrip(".")
    tokens: list[str] = []
    for match in _PATH_TOKEN_RE.finditer(text):
        tokens.append(match.group(1) or match.group(2) or "")
    value = obj
    for index, token in enumerate(tokens):
        if token == "*":
            if not isinstance(value, list):
                return None
            rest = ".".join(tokens[index + 1:])
            if rest:
                return [get_json_path(item, rest) for item in value]
            return value
        if token.isdigit():
            if not isinstance(value, list):
                return None
            pos = int(token)
            if pos >= len(value):
                return None
            value = value[pos]
            continue
        if not isinstance(value, dict):
            return None
        value = value.get(token)
    return value


def apply_transform(data: Any, transform: dict | None) -> Any:
    """数据源 transform：{"filter": {...}, "sort": "field:desc", "limit": n, "map": {"target": "source.path"}, "keys": [...]}。

    支持字段子集、过滤（= / != / > / < / >= / <=）、排序、截断、重命名。
    """
    if not transform or not isinstance(data, list):
        return data
    rows = list(data)
    flt = transform.get("filter")
    if isinstance(flt, dict):
        def _keep(row: dict) -> bool:
            for field, expected in flt.items():
                op, target = "=", expected
                if isinstance(expected, dict):
                    for k, v in expected.items():
                        op, target = k, v
                        break
                if not _compare(row.get(field), op, target):
                    return False
            return True

        rows = [r for r in rows if isinstance(r, dict) and _keep(r)]
    sort = transform.get("sort")
    if isinstance(sort, str) and ":" in sort:
        field, direction = sort.rsplit(":", 1)
        reverse = direction.strip().lower() == "desc"
        rows.sort(key=lambda r: (r.get(field) is None, r.get(field)) if isinstance(r, dict) else (True, None), reverse=reverse)
    limit = transform.get("limit")
    if isinstance(limit, int) and limit >= 0:
        rows = rows[:limit]
    mapping = transform.get("map")
    if isinstance(mapping, dict):
        renamed = []
        for r in rows:
            if not isinstance(r, dict):
                renamed.append(r)
                continue
            nr = dict(r)
            for target, source in mapping.items():
                nr[target] = get_json_path(r, str(source))
            renamed.append(nr)
        rows = renamed
    keys = transform.get("keys")
    if isinstance(keys, list):
        rows = [{k: r.get(k) for k in keys} for r in rows if isinstance(r, dict)]
    return rows


def _compare(value: Any, op: str, target: Any) -> bool:
    try:
        if op == "=":
            return value == target
        if op == "!=":
            return value != target
        if op == ">":
            return value is not None and value > target
        if op == "<":
            return value is not None and value < target
        if op == ">=":
            return value is not None and value >= target
        if op == "<=":
            return value is not None and value <= target
    except TypeError:
        return False
    return False


def _host_allowed(host: str) -> bool:
    from core.security import get_security_config

    allowed = get_security_config().get("ssrf_allowed_hosts") or []
    host = host.lower().rstrip(".")
    for item in allowed:
        item = str(item or "").lower().strip().lstrip(".")
        if not item:
            continue
        if host == item or host.endswith(f".{item}"):
            return True
    return False


def validate_outbound_url(url: str) -> str:
    """校验数据源/AI 等出站 URL，阻止内网、回环、链路本地和元数据地址。"""
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError("仅允许 http/https 出站地址")
    if parsed.username or parsed.password:
        raise ValidationError("出站地址不能包含用户名或密码")
    host = parsed.hostname.lower().rstrip(".")
    from core.security import get_security_config

    allow_private = bool(get_security_config().get("ssrf_allow_private"))
    if _host_allowed(host):
        return raw
    if host in ("localhost", "localhost.localdomain") or host.endswith(".local"):
        raise ValidationError("禁止访问本机或内网地址")
    try:
        infos = socket.getaddrinfo(
            host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise ValidationError(f"无法解析出站域名: {host}") from exc
    for info in infos:
        ip_text = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError:
            continue
        if ip.is_multicast or ip.is_unspecified:
            raise ValidationError("禁止访问组播或未指定地址")
        if ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValidationError("禁止访问回环、链路本地或保留地址")
        if ip.is_private and not allow_private:
            raise ValidationError("禁止访问内网地址")
    return raw


def http_request(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: bytes | None = None,
    timeout: float = 5.0,
) -> tuple[int, str]:
    """urllib 实现的最小 HTTP 客户端（requirements 无 httpx/requests）。"""
    validate_outbound_url(url)
    req = urllib.request.Request(url, data=body, method=method.upper())
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return e.code, text
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ValidationError(f"HTTP 请求失败: {e}") from e


def render_template(text: str, params: dict) -> str:
    """替换 {{name}} 与 {name} 占位符。"""
    out = text
    for k, v in (params or {}).items():
        sval = str(v)
        out = out.replace("{{%s}}" % k, sval).replace("{%s}" % k, sval)
    return out


def build_query_string(params: dict) -> str:
    flat = {}
    for k, v in (params or {}).items():
        if isinstance(v, (dict, list)):
            flat[k] = json.dumps(v, ensure_ascii=False)
        else:
            flat[k] = v
    return urlencode(flat)
