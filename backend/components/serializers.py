from rest_framework import serializers

from .models import ComponentMeta


class ComponentMetaSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComponentMeta
        fields = (
            "id",
            "name",
            "label",
            "type",
            "category",
            "version",
            "props_schema",
            "style_schema",
            "default_props",
            "events",
            "provides",
            "consumes",
            "payload_schema",
            "slots",
            "accept_children",
            "source",
            "element",
            "is_container",
            "is_form_field",
            "default_children",
            "actions_supported",
            "icon",
            "is_builtin",
            "is_custom",
            "is_enabled",
            "source_url",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "is_builtin", "is_custom", "created_at", "updated_at")


class ComponentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComponentMeta
        fields = (
            "name",
            "label",
            "type",
            "category",
            "version",
            "props_schema",
            "style_schema",
            "default_props",
            "events",
            "provides",
            "consumes",
            "payload_schema",
            "slots",
            "accept_children",
            "source",
            "element",
            "is_container",
            "is_form_field",
            "default_children",
            "actions_supported",
            "icon",
            "is_enabled",
            "source_url",
        )

    def validate_name(self, value):
        if ComponentMeta.objects.filter(name=value).exists():
            raise serializers.ValidationError("组件名已存在")
        return value

    def validate(self, attrs):
        attrs["is_custom"] = True
        return attrs


class ComponentUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComponentMeta
        fields = (
            "label",
            "type",
            "category",
            "version",
            "props_schema",
            "style_schema",
            "default_props",
            "events",
            "provides",
            "consumes",
            "payload_schema",
            "slots",
            "accept_children",
            "source",
            "element",
            "is_container",
            "is_form_field",
            "default_children",
            "actions_supported",
            "icon",
            "is_enabled",
            "source_url",
        )


class ComponentEnableSerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField()
