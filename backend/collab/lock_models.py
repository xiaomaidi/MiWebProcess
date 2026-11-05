"""服务端权威的设计器节点锁。

该模型刻意放在独立模块（而非 ``collab/models.py``），由 ``lock_service`` /
``lock_consumer`` 显式导入注册；迁移见 ``migrations/0002_designer_lock.py``。
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class DesignerLock(models.Model):
    """页面某个 schema 节点的编辑锁。

    - 唯一约束 ``(page, node_id)``：同一节点至多一条锁记录。
    - ``expires_at`` 之前锁有效；过期记录视为空闲，可被其他会话抢占。
    - ``session_id`` 是浏览器端为「每个页面」持久化的会话标识，用于断线重连
      后识别「自己的锁」。
    """

    page = models.ForeignKey(
        "pages.Page",
        on_delete=models.CASCADE,
        related_name="designer_locks",
    )
    node_id = models.CharField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="designer_locks",
    )
    session_id = models.UUIDField()
    acquired_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        app_label = "collab"
        db_table = "wp_designer_locks"
        ordering = ("page_id", "node_id")
        constraints = [
            models.UniqueConstraint(
                fields=("page", "node_id"),
                name="uniq_designer_lock_page_node",
            ),
        ]
        indexes = [
            models.Index(fields=("page", "expires_at"), name="wp_deslock_page_exp_idx"),
            models.Index(fields=("expires_at",), name="wp_deslock_expires_idx"),
            models.Index(fields=("session_id",), name="wp_deslock_session_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover - 便于 admin/日志
        return f"lock(page={self.page_id}, node={self.node_id}, user={self.user_id})"
