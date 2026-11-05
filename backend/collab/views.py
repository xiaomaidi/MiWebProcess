from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.models import NotificationLog
from core.permissions import get_app_role
from pages.models import Page
from wp_utils import broadcast_to_app, require_app_role

from .models import PageComment

User = get_user_model()

# @username 片段：前面不能是 ASCII 标识符或 @（避免把邮箱 a@b.com 当提及），
# 用户名允许 Django 的 Unicode 字符（字母/数字/._@+-），因此中文用户名也可被提及。
_MENTION_RE = re.compile(r"(?<![A-Za-z0-9_@])@([\w.@+\-]{1,150})")
# 句末标点等不属于用户名，按“最长可解析前缀”回退。
_MENTION_TRAILING = ".+-@"
MAX_MENTION_TOKENS = 100
MAX_MENTIONS = 50
NOTIFY_EXCERPT = 1000

COMMENT_EVENT_TOPIC = "designer-comments/{page_id}"


def _clean_mentions(value) -> list[dict]:
    """归一化 mentions JSON：只保留 id/username/display_name，绝不外泄邮箱。"""
    rows: list[dict] = []
    seen: set[str] = set()
    for entry in value or []:
        if isinstance(entry, str):
            username = entry.strip()
            display_name = username
            user_id = None
        elif isinstance(entry, dict):
            username = str(entry.get("username") or "").strip()
            display_name = str(
                entry.get("display_name") or entry.get("name") or username
            ).strip() or username
            raw_id = entry.get("id")
            try:
                user_id = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                user_id = None
        else:
            continue
        if not username or username in seen:
            continue
        seen.add(username)
        rows.append({"id": user_id, "username": username, "display_name": display_name})
    return rows


def _payload(item: PageComment, warnings: list[dict] | None = None) -> dict:
    mentions = _clean_mentions(item.mentions)
    data = {
        "id": item.id,
        "page_id": item.page_id,
        "node_id": item.node_id,
        "body": item.body,
        "mentions": mentions,
        "mention_usernames": [m["username"] for m in mentions],
        "author": item.author.username if item.author else "",
        "author_id": item.author_id,
        "resolved": item.resolved,
        "resolved_by": item.resolved_by.username if item.resolved_by else "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }
    if warnings:
        data["warnings"] = warnings
    return data


def _page(page_id: int) -> Page:
    return get_object_or_404(Page.objects.select_related("app"), pk=page_id)


def _mention_variants(raw: str) -> list[str]:
    """`alice.` → ["alice.", "alice"]，便于在句末标点后识别提及。"""
    variants = [raw]
    trimmed = raw
    while trimmed and trimmed[-1] in _MENTION_TRAILING:
        trimmed = trimmed[:-1]
        if trimmed:
            variants.append(trimmed)
    return variants


def _has_app_access(user, app) -> bool:
    """提及对象必须有应用访问权（平台管理员 / owner / 成员 / 部门可见）。"""
    if getattr(user, "is_superuser", False) or getattr(user, "is_platform_admin", False):
        return True
    if getattr(app, "owner_id", None) and app.owner_id == user.id:
        return True
    try:
        return get_app_role(user, app) is not None
    except Exception:  # pragma: no cover - 权限查询异常按无权限处理
        return False


def _resolve_mentions(body: str, app) -> tuple[list[dict], list[dict]]:
    """解析 @username，返回 (有效提及, 警告)。

    文本原样保留；无效提及只产生警告，不落库、不通知。用户名大小写不敏感匹配。
    """
    raw_tokens: list[str] = []
    for match in _MENTION_RE.finditer(body or ""):
        raw = match.group(1)
        if raw and raw not in raw_tokens:
            raw_tokens.append(raw)
        if len(raw_tokens) >= MAX_MENTION_TOKENS:
            break
    if not raw_tokens:
        return [], []

    variant_map = {raw: _mention_variants(raw) for raw in raw_tokens}
    all_variants = {variant for variants in variant_map.values() for variant in variants}
    candidates = {user.username: user for user in User.objects.filter(username__in=all_variants)}
    missing = [variant for variant in all_variants if variant not in candidates]
    if missing:
        # 大小写不敏感回退；数量有限（受 MAX_MENTION_TOKENS 约束）。
        query = Q()
        for variant in missing[: MAX_MENTION_TOKENS * 2]:
            query |= Q(username__iexact=variant)
        by_lower = {user.username.lower(): user for user in User.objects.filter(query)}
        for variant in missing:
            user = by_lower.get(variant.lower())
            if user is not None:
                candidates[variant] = user

    mentions: list[dict] = []
    warnings: list[dict] = []
    seen_usernames: set[str] = set()
    for raw in raw_tokens:
        user = next((candidates[v] for v in variant_map[raw] if v in candidates), None)
        if user is None:
            warnings.append({
                "token": f"@{raw}",
                "code": "unknown_user",
                "message": f"用户 @{raw} 不存在",
            })
            continue
        if not user.is_active:
            warnings.append({
                "token": f"@{raw}",
                "code": "inactive_user",
                "message": f"用户 @{user.username} 已停用，未发送通知",
            })
            continue
        if not _has_app_access(user, app):
            warnings.append({
                "token": f"@{raw}",
                "code": "no_app_access",
                "message": f"用户 @{user.username} 无权访问该应用，未发送通知",
            })
            continue
        if user.username in seen_usernames:
            continue
        seen_usernames.add(user.username)
        mentions.append({
            "id": user.id,
            "username": user.username,
            "display_name": user.get_full_name() or user.username,
        })
        if len(mentions) >= MAX_MENTIONS:
            break
    return mentions, warnings


def _notify_mentions(item: PageComment, mentions: list[dict], actor) -> int:
    """为被提及用户创建站内信 NotificationLog（跳过作者自己与重复项）。"""
    if not mentions:
        return 0
    page = item.page
    page_name = getattr(page, "name", "") or ""
    author_name = getattr(actor, "username", "") or ""
    seen: set[str] = set()
    recipients: list[dict] = []
    for mention in mentions:
        username = str(mention.get("username") or "")
        if not username or username in seen:
            continue
        if actor is not None and mention.get("id") == getattr(actor, "id", None):
            continue
        seen.add(username)
        recipients.append(mention)
    if not recipients:
        return 0
    subject = f"{author_name} 在页面「{page_name}」的评论中提到了你"[:240]
    excerpt = (item.body or "")[:NOTIFY_EXCERPT]
    content = f"{author_name}：{excerpt}"[:NOTIFY_EXCERPT + 40]
    base_payload = {
        "kind": "comment_mention",
        "app_id": item.app_id,
        "page_id": item.page_id,
        "page_name": page_name,
        "comment_id": item.id,
        "node_id": item.node_id,
        "author": author_name,
        "author_id": getattr(actor, "id", None) if actor else None,
        "body": excerpt,
    }
    NotificationLog.objects.bulk_create([
        NotificationLog(
            app_id=item.app_id,
            channel="inapp",
            recipient=mention["username"],
            subject=subject,
            content=content,
            status="sent",
            payload={**base_payload, "mention_username": mention["username"]},
            created_by=actor,
        )
        for mention in recipients
    ])
    return len(recipients)


def _event_key(event_type: str, comment_id, comment: dict | None = None) -> str:
    """确定性事件键：同一变更无论来自 REST 广播还是前端 WS 回显都只应用一次。"""
    if event_type == "comment_deleted":
        return f"comment_deleted:{comment_id}"
    stamp = ""
    if isinstance(comment, dict):
        stamp = str(comment.get("updated_at") or comment.get("created_at") or "")
    return f"{event_type}:{comment_id}:{stamp}"


def _broadcast_comment(event_type: str, *, app_id: int, page_id: int, comment: dict, actor) -> None:
    """通过既有 `/ws/{app_id}/` 中继广播评论事件（topic=designer-comments/{pageId}）。"""
    if not app_id or not page_id or not isinstance(comment, dict):
        return
    comment_id = comment.get("id")
    topic = COMMENT_EVENT_TOPIC.format(page_id=page_id)
    event_key = _event_key(event_type, comment_id, comment)
    payload = {
        "topic": topic,
        "page_id": page_id,
        "comment_id": comment_id,
        "event_key": event_key,
        "comment": comment,
    }
    broadcast_to_app(
        app_id,
        {
            "type": event_type,
            "payload": payload,
            "extra": {
                "topic": topic,
                "page_id": page_id,
                "comment_id": comment_id,
                "event_key": event_key,
            },
        },
        sender=getattr(actor, "username", "") if actor else "",
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def page_comments(request, page_id: int):
    page = _page(page_id)
    require_app_role(request.user, page.app, "viewer" if request.method == "GET" else "editor")
    if request.method == "GET":
        qs = page.comments.select_related("author", "resolved_by").all()
        if request.query_params.get("resolved") in ("0", "false"):
            qs = qs.filter(resolved=False)
        return Response({"results": [_payload(item) for item in qs[:200]]})
    body = str(request.data.get("body") or "").strip()
    if not body:
        raise ValidationError({"detail": "评论内容不能为空"})
    if len(body) > 4000:
        raise ValidationError({"detail": "评论不能超过 4000 字"})
    mentions, warnings = _resolve_mentions(body, page.app)
    item = PageComment.objects.create(
        app=page.app, page=page,
        node_id=str(request.data.get("node_id") or "")[:120],
        body=body, author=request.user, mentions=mentions,
    )
    notified = _notify_mentions(item, mentions, request.user)
    response_payload = _payload(item, warnings)
    if notified:
        response_payload["notified_count"] = notified
    _broadcast_comment(
        "comment_created",
        app_id=page.app_id,
        page_id=page.id,
        comment=_payload(item),
        actor=request.user,
    )
    return Response(response_payload, status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def comment_detail(request, pk: int):
    item = get_object_or_404(PageComment.objects.select_related("page__app", "author"), pk=pk)
    require_app_role(request.user, item.page.app, "viewer")
    if request.method == "DELETE":
        if item.author_id != request.user.id:
            require_app_role(request.user, item.page.app, "editor")
        snapshot = _payload(item)
        app_id, page_id = item.app_id, item.page_id
        item.delete()
        _broadcast_comment(
            "comment_deleted",
            app_id=app_id,
            page_id=page_id,
            comment=snapshot,
            actor=request.user,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)

    # 正文/节点修改需要作者本人或编辑权限；解决/重新打开沿用原有 viewer 权限。
    edited = "body" in request.data or "node_id" in request.data
    if edited and item.author_id != request.user.id:
        require_app_role(request.user, item.page.app, "editor")

    warnings: list[dict] | None = None
    body_changed = "body" in request.data
    previous = {m["username"] for m in _clean_mentions(item.mentions)}
    if body_changed:
        body = str(request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"detail": "评论内容不能为空"})
        item.body = body[:4000]
        mentions, warnings = _resolve_mentions(item.body, item.page.app)
        item.mentions = mentions
    if "resolved" in request.data:
        item.resolved = bool(request.data.get("resolved"))
        item.resolved_by = request.user if item.resolved else None
        item.resolved_at = timezone.now() if item.resolved else None
    if "node_id" in request.data:
        item.node_id = str(request.data.get("node_id") or "")[:120]
    item.save()

    notified = 0
    if body_changed:
        newly = [m for m in _clean_mentions(item.mentions) if m["username"] not in previous]
        notified = _notify_mentions(item, newly, request.user)
    response_payload = _payload(item, warnings)
    if notified:
        response_payload["notified_count"] = notified
    event_type = "comment_updated"
    if "resolved" in request.data:
        event_type = "comment_resolved" if item.resolved else "comment_updated"
    _broadcast_comment(
        event_type,
        app_id=item.app_id,
        page_id=item.page_id,
        comment=_payload(item),
        actor=request.user,
    )
    return Response(response_payload)
