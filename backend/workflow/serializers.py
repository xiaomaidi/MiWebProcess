from rest_framework import serializers

from workflow.models import WorkflowDefinition, WorkflowInstance, WorkflowTask


class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    app_id = serializers.IntegerField(source="app.id", read_only=True)

    class Meta:
        model = WorkflowDefinition
        fields = (
            "id", "app_id", "name", "code", "description", "nodes", "status", "version",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "status", "version", "created_at", "updated_at")


class WorkflowTaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(source="assignee.username", read_only=True, default="")
    action_by_name = serializers.CharField(source="action_by.username", read_only=True, default="")
    instance_id = serializers.IntegerField(source="instance.id", read_only=True)
    is_overdue = serializers.SerializerMethodField()
    definition_nodes = serializers.JSONField(source="instance.definition.nodes", read_only=True)
    instance_title = serializers.CharField(source="instance.title", read_only=True, default="")
    definition_name = serializers.CharField(source="instance.definition.name", read_only=True, default="")
    app_id = serializers.IntegerField(source="instance.app_id", read_only=True)
    business_model_id = serializers.IntegerField(source="instance.business_model_id", read_only=True)
    business_record_id = serializers.IntegerField(source="instance.business_record_id", read_only=True)

    class Meta:
        model = WorkflowTask
        fields = (
            "id", "instance_id", "instance_title", "definition_name", "app_id",
            "business_model_id", "business_record_id",
            "node_id", "node_name", "assignee", "assignee_name",
            "assignee_role", "status", "comment", "action_by", "action_by_name",
            "due_at", "is_overdue", "remind_count", "last_reminded_at", "definition_nodes",
            "created_at", "updated_at",
        )

    def get_is_overdue(self, obj) -> bool:
        from django.utils import timezone

        return bool(obj.due_at and obj.status == "pending" and obj.due_at < timezone.now())


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    definition_name = serializers.CharField(source="definition.name", read_only=True)
    definition_code = serializers.CharField(source="definition.code", read_only=True)
    initiator_name = serializers.CharField(source="initiator.username", read_only=True, default="")
    tasks = WorkflowTaskSerializer(many=True, read_only=True)

    class Meta:
        model = WorkflowInstance
        fields = (
            "id", "definition", "definition_name", "definition_code", "app",
            "business_model_id", "business_record_id", "title", "data", "status",
            "current_node_id", "current_index", "initiator", "initiator_name",
            "tasks", "created_at", "updated_at",
        )
        read_only_fields = fields
