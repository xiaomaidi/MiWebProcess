from rest_framework import serializers


class AppSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source="owner.id", read_only=True)
    owner_username = serializers.CharField(source="owner.username", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default="")

    class Meta:
        from appcore.models import App

        model = App
        fields = (
            "id",
            "name",
            "code",
            "description",
            "owner_id",
            "owner_username",
            "department_id",
            "department_name",
            "department_visible",
            "design_tokens",
            "design_tokens_history",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "owner_id", "status", "created_at", "updated_at")


class AppAuthConfigSerializer(serializers.ModelSerializer):
    app_id = serializers.IntegerField(source="app.id", read_only=True)
    app_name = serializers.CharField(source="app.name", read_only=True)
    app_code = serializers.CharField(source="app.code", read_only=True)

    class Meta:
        from appcore.models import AppAuthConfig

        model = AppAuthConfig
        fields = (
            "id", "app_id", "app_name", "app_code",
            "enabled", "require_login", "allow_register", "auto_join", "default_role",
            "invite_required", "invite_code", "login_title", "login_subtitle", "logo_url",
            "theme_color", "redirect_path", "allowed_domains", "created_at", "updated_at",
        )
        read_only_fields = ("id", "app_id", "app_name", "app_code", "created_at", "updated_at")


class AppMemberSerializer(serializers.ModelSerializer):
    app_id = serializers.IntegerField(source="app.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        from appcore.models import AppMember

        model = AppMember
        fields = ("id", "app_id", "user", "username", "role", "created_at")
        read_only_fields = fields
