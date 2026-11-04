from __future__ import annotations

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from pages.models import Page
from wp_utils import require_app_role

from .models import PageComment


def _payload(item: PageComment) -> dict:
    return {
        "id": item.id,
        "page_id": item.page_id,
        "node_id": item.node_id,
        "body": item.body,
        "author": item.author.username if item.author else "",
        "author_id": item.author_id,
        "resolved": item.resolved,
        "resolved_by": item.resolved_by.username if item.resolved_by else "",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _page(page_id: int) -> Page:
    return get_object_or_404(Page.objects.select_related("app"), pk=page_id)


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
    item = PageComment.objects.create(
        app=page.app, page=page,
        node_id=str(request.data.get("node_id") or "")[:120],
        body=body, author=request.user,
    )
    return Response(_payload(item), status=status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def comment_detail(request, pk: int):
    item = get_object_or_404(PageComment.objects.select_related("page__app", "author"), pk=pk)
    require_app_role(request.user, item.page.app, "viewer" if request.method == "PATCH" else "editor")
    if request.method == "DELETE":
        if item.author_id != request.user.id:
            require_app_role(request.user, item.page.app, "editor")
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if "body" in request.data:
        body = str(request.data.get("body") or "").strip()
        if not body:
            raise ValidationError({"detail": "评论内容不能为空"})
        item.body = body[:4000]
    if "resolved" in request.data:
        item.resolved = bool(request.data.get("resolved"))
        item.resolved_by = request.user if item.resolved else None
        item.resolved_at = timezone.now() if item.resolved else None
    if "node_id" in request.data:
        item.node_id = str(request.data.get("node_id") or "")[:120]
    item.save()
    return Response(_payload(item))
