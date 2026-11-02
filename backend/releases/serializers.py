from rest_framework import serializers

from releases.models import Release, ReleaseTask


class ReleaseTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReleaseTask
        fields = ("id", "status", "log", "created_at", "updated_at")


class ReleaseSerializer(serializers.ModelSerializer):
    app_code = serializers.CharField(source="app.code", read_only=True)
    task = serializers.SerializerMethodField()

    class Meta:
        model = Release
        fields = (
            "id",
            "app",
            "app_code",
            "version",
            "status",
            "traffic_ratio",
            "previous_release",
            "bundle_url",
            "error",
            "changelog",
            "task",
            "created_by",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_task(self, obj) -> dict | None:
        task = obj.tasks.order_by("-created_at").first()
        if task is None:
            return None
        return ReleaseTaskSerializer(task).data
