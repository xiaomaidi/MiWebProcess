from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from components.models import ComponentMeta, ComponentVersion
from components.registry import load_registry
from components.serializers import ComponentMetaSerializer
from components.services import invalidate_registry_cache


class Command(BaseCommand):
    help = "加载 shared/component-registry.json（v2）内置组件到 ComponentMeta（按 name 幂等更新）"

    def add_arguments(self, parser):
        parser.add_argument("--registry", type=str, default=None, help="可选：自定义 registry JSON 路径")

    def handle(self, *args, **options):
        if options.get("registry"):
            path = Path(options["registry"])
        else:
            path = Path(settings.BASE_DIR).parent / "shared" / "component-registry.json"
        if not path.exists():
            self.stderr.write(f"registry file not found: {path}")
            return
        registry = load_registry(path)
        components = registry.get("components", [])
        created = 0
        updated = 0
        for entry in components:
            name = entry.get("name")
            if not name:
                continue
            defaults = {
                "label": entry.get("label", name),
                "type": entry.get("type", "basic"),
                "category": entry.get("category", ""),
                "version": entry.get("version", "2.0.0"),
                "icon": entry.get("icon", ""),
                "source": entry.get("source", "element-plus"),
                "element": entry.get("element", name),
                "is_container": bool(entry.get("is_container", False)),
                "is_form_field": bool(entry.get("is_form_field", False)),
                "default_children": entry.get("default_children", []) or [],
                "actions_supported": entry.get("actions_supported", []) or [],
                "props_schema": entry.get("props_schema", {}) or {},
                "style_schema": entry.get("style_schema", {}) or {},
                "default_props": entry.get("default_props", {}) or {},
                "events": entry.get("events", []) or [],
                "slots": entry.get("slots", []) or [],
                "accept_children": entry.get("accept_children", []) or [],
                "is_builtin": True,
                "is_custom": False,
                "is_enabled": True,
            }
            obj, was_created = ComponentMeta.objects.update_or_create(name=name, defaults=defaults)
            # 版本快照：同一版本只写一次，内容变化时覆盖（seed 是幂等的）。
            meta = ComponentMetaSerializer(obj).data
            ComponentVersion.objects.update_or_create(
                component=obj,
                version=obj.version,
                defaults={"meta_snapshot": meta, "changelog": "seed registry v2"},
            )
            if was_created:
                created += 1
            else:
                updated += 1
        total_builtin = ComponentMeta.objects.filter(is_builtin=True).count()
        invalidate_registry_cache()
        self.stdout.write(
            self.style.SUCCESS(
                "seed_builtin_components: "
                f"registry={registry.get('version')} file={path.name} "
                f"created={created} updated={updated} builtin_total={total_builtin}"
            )
        )
