"""组织架构：部门树 + 部门成员。

部门是平台级资源（跨应用共享），通过物化路径 ``path``（形如 ``/1/4/9/``）
支持 O(1) 子树判定，避免递归查询。应用通过 ``App.department`` 与
``App.department_visible`` 允许部门成员获得只读访问。
"""
from django.conf import settings
from django.db import models


class Department(models.Model):
    """部门（可无限层级）。"""

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    # 物化路径：父路径 + 自身 id + "/"；根部门为 "/<id>/"
    path = models.CharField(max_length=500, blank=True, default="", db_index=True)
    level = models.IntegerField(default=0)
    sort = models.IntegerField(default=0)
    leader = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="leading_departments",
    )
    description = models.CharField(max_length=500, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_departments"
        ordering = ("sort", "id")
        indexes = [models.Index(fields=["parent", "sort"])]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        parent_path = self.parent.path if self.parent_id and self.parent else ""
        level = (self.parent.level + 1) if self.parent_id and self.parent else 0
        expected = f"{parent_path}{self.id}/"
        if self.path != expected or self.level != level:
            self.path = expected
            self.level = level
            super().save(update_fields=["path", "level"])

    @property
    def ancestor_ids(self) -> list[int]:
        return [int(part) for part in (self.path or "").strip("/").split("/") if part.isdigit()]

    def display_path(self) -> str:
        names = []
        node = self
        seen = set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            names.append(node.name)
            node = node.parent
        return " / ".join(reversed(names))


class DepartmentMember(models.Model):
    """部门成员：leader 可管理子部门并查看整棵子树的数据。"""

    ROLE_CHOICES = (
        ("leader", "负责人"),
        ("member", "成员"),
    )

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="department_memberships"
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    title = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "wp_department_members"
        unique_together = (("department", "user"),)
        indexes = [models.Index(fields=["user", "department"])]

    def __str__(self):
        return f"{self.user} @ {self.department} ({self.role})"
