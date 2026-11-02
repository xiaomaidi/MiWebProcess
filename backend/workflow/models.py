from django.conf import settings
from django.db import models


class WorkflowDefinition(models.Model):
    """应用级审批流程定义。nodes 为有序节点数组（start/approval/condition/end）。"""

    STATUS_CHOICES = (("draft", "草稿"), ("published", "已发布"), ("archived", "已归档"))

    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="workflows")
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=80)
    description = models.CharField(max_length=500, blank=True, default="")
    nodes = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    version = models.IntegerField(default=1)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_workflow_definitions"
        unique_together = (("app", "code"),)
        ordering = ("-updated_at",)

    def __str__(self):
        return f"{self.app_id}/{self.code}"


class WorkflowInstance(models.Model):
    STATUS_CHOICES = (
        ("running", "审批中"),
        ("approved", "已通过"),
        ("rejected", "已驳回"),
        ("cancelled", "已撤回"),
    )

    definition = models.ForeignKey(WorkflowDefinition, on_delete=models.PROTECT, related_name="instances")
    app = models.ForeignKey("appcore.App", on_delete=models.CASCADE, related_name="workflow_instances")
    business_model_id = models.IntegerField(null=True, blank=True)
    business_record_id = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=300, blank=True, default="")
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    current_node_id = models.CharField(max_length=80, blank=True, default="")
    current_index = models.IntegerField(default=0)
    initiator = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_workflow_instances"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["app", "status"])]


class WorkflowTask(models.Model):
    STATUS_CHOICES = (
        ("pending", "待处理"),
        ("approved", "已同意"),
        ("rejected", "已驳回"),
        ("transferred", "已转办"),
        ("cancelled", "已取消"),
    )

    instance = models.ForeignKey(WorkflowInstance, on_delete=models.CASCADE, related_name="tasks")
    node_id = models.CharField(max_length=80)
    node_name = models.CharField(max_length=120, blank=True, default="")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assignee_role = models.CharField(max_length=20, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    comment = models.TextField(blank=True, default="")
    action_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    due_at = models.DateTimeField(null=True, blank=True)
    remind_count = models.IntegerField(default=0)
    last_reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "wp_workflow_tasks"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["assignee", "status"]), models.Index(fields=["instance", "status"])]
