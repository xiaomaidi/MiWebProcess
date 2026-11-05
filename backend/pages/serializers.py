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


class PageBlockSerializer(serializers.ModelSerializer):
    """区块列表/详情：默认不含 schema，详情由 PageBlockDetailSerializer 补充。"""

    app_id = serializers.IntegerField(source="app.id", read_only=True)
    page_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)

    class Meta:
        from pages.models import PageBlock

        model = PageBlock
        fields = (
            "id",
            "app_id",
            "name",
            "code",
            "description",
            "page_id",
            "version",
            "created_by_id",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class PageBlockDetailSerializer(PageBlockSerializer):
    """详情：额外返回区块 schema（{rootId, nodes}）与节点数。"""

    schema = serializers.SerializerMethodField()
    root_id = serializers.SerializerMethodField()
    node_count = serializers.SerializerMethodField()
    backing_page = serializers.SerializerMethodField()
    latest_version = serializers.SerializerMethodField()
    version_count = serializers.SerializerMethodField()
    latest_version_detail = serializers.SerializerMethodField()

    class Meta(PageBlockSerializer.Meta):
        fields = PageBlockSerializer.Meta.fields + (
            "schema",
            "root_id",
            "node_count",
            "backing_page",
            "latest_version",
            "version_count",
            "latest_version_detail",
        )

    def _schema(self, obj) -> dict:
        from pages.block_services import block_schema

        return block_schema(obj)

    def _latest(self, obj):
        latest = getattr(obj, "_wp_latest_block_version", None)
        if latest is None:
            latest = obj.versions.order_by("-version").first()
            try:
                obj._wp_latest_block_version = latest
            except Exception:
                pass
        return latest

    def get_schema(self, obj) -> dict:
        if not self.context.get("include_schema", True):
            return {}
        return self._schema(obj)

    def get_root_id(self, obj) -> str:
        return str(self._schema(obj).get("rootId") or "")

    def get_node_count(self, obj) -> int:
        return len(self._schema(obj).get("nodes") or {})

    def get_backing_page(self, obj) -> dict | None:
        page = obj.page if obj.page_id else None
        if page is None:
            return None
        return {
            "id": page.id,
            "name": page.name,
            "path": page.path,
            "type": page.type,
            "status": page.status,
            "version": page.version,
        }

    def get_latest_version(self, obj) -> int:
        """最新版本号（没有历史时为 0），与 ``version_count`` 一起供区块详情展示。"""
        latest = self._latest(obj)
        return int(latest.version) if latest is not None else 0

    def get_version_count(self, obj) -> int:
        count = obj.versions.count()
        return int(count)

    def get_latest_version_detail(self, obj) -> dict | None:
        latest = self._latest(obj)
        return PageBlockVersionSerializer(latest).data if latest is not None else None


class PageBlockVersionSerializer(serializers.ModelSerializer):
    """区块版本快照（详情含 snapshot；列表按需使用同一序列化器）。"""

    block_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(source="created_by.id", read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        from pages.models import PageBlockVersion

        model = PageBlockVersion
        fields = (
            "id",
            "block_id",
            "version",
            "snapshot",
            "changelog",
            "created_by_id",
            "created_by_name",
            "created_at",
        )
        read_only_fields = fields

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.username if obj.created_by_id and obj.created_by else ""


class AssetSerializer(serializers.ModelSerializer):
    class Meta:
        from pages.models import Asset

        model = Asset
        fields = ("id", "app", "name", "url", "type", "uploaded_by", "created_at")
        read_only_fields = fields
