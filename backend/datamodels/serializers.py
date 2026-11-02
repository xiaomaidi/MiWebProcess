from rest_framework import serializers


class DataModelSerializer(serializers.ModelSerializer):
    app_id = serializers.IntegerField(source="app.id", read_only=True)

    class Meta:
        from datamodels.models import DataModel

        model = DataModel
        fields = (
            "id", "app_id", "name", "fields", "indexes", "is_public", "row_owner_field",
            "workflow_definition_id",
            "data_scope", "dept_field", "action_roles", "review_required", "review_roles",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class DataRecordSerializer(serializers.ModelSerializer):
    model_id = serializers.IntegerField(source="model.id", read_only=True)
    model_name = serializers.CharField(source="model.name", read_only=True)

    class Meta:
        from datamodels.models import DataRecord

        model = DataRecord
        fields = ("id", "model_id", "model_name", "data", "created_at", "updated_at")
        read_only_fields = fields


class ReportSubscriptionSerializer(serializers.ModelSerializer):
    model_name = serializers.CharField(source="model.name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.username", read_only=True, default="")

    class Meta:
        from datamodels.models import ReportSubscription

        model = ReportSubscription
        fields = (
            "id", "app_id", "model_id", "model_name", "name", "config", "frequency",
            "recipients", "enabled", "last_run_at", "created_by", "created_by_name",
            "created_at", "updated_at",
        )
        read_only_fields = ("id", "app_id", "model_id", "model_name", "last_run_at", "created_by", "created_by_name", "created_at", "updated_at")


class RecordWriteSerializer(serializers.Serializer):
    data = serializers.DictField()
