from rest_framework import serializers


class PageSerializer(serializers.ModelSerializer):
    app_id = serializers.IntegerField(source="app.id", read_only=True)
    owner_id = serializers.IntegerField(source="app.owner_id", read_only=True)

    class Meta:
        from pages.models import Page

        model = Page
        fields = (
            "id",
            "app_id",
            "owner_id",
            "name",
            "path",
            "type",
            "status",
            "version",
            "schema_version",
            "thumbnail_url",
            "current_version_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "status", "version", "schema_version", "created_at", "updated_at")


class PageVersionSerializer(serializers.ModelSerializer):
    page_id = serializers.IntegerField(source="page.id", read_only=True)
    publisher_id = serializers.IntegerField(source="publisher.id", read_only=True)

    class Meta:
        from pages.models import PageVersion

        model = PageVersion
        fields = (
            "id",
            "page_id",
            "version",
            "schema",
            "schema_version",
            "publisher_id",
            "published_at",
            "changelog",
        )


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        from pages.models import Asset

        model = Asset
        fields = ("id", "app", "name", "url", "type", "uploaded_by", "created_at")
        read_only_fields = fields
