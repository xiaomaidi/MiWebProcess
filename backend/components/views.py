import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, parser_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.audit import write_audit_log
from wp_utils import is_platform_admin_full, paginate_items

from .models import ComponentMeta, ComponentVersion
from .services import invalidate_registry_cache
from .serializers import (
    ComponentCreateSerializer,
    ComponentEnableSerializer,
    ComponentMetaSerializer,
    ComponentUpdateSerializer,
)


def _snapshot(component: ComponentMeta, changelog: str = "") -> ComponentVersion:
    meta = ComponentMetaSerializer(component).data
    version, _ = ComponentVersion.objects.update_or_create(
        component=component,
        version=component.version,
        defaults={"meta_snapshot": meta, "changelog": changelog},
    )
    return version


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def component_list(request):
    """GET/POST /api/components/。列表默认仅返回启用组件。"""
    if request.method == "GET":
        qs = ComponentMeta.objects.all()
        enabled_raw = (request.query_params.get("enabled") or "1").strip().lower()
        if enabled_raw in ("1", "true", "yes", ""):
            qs = qs.filter(is_enabled=True)
        category = (request.query_params.get("category") or "").strip()
        if category:
            qs = qs.filter(category=category)
        ctype = (request.query_params.get("type") or "").strip()
        if ctype:
            qs = qs.filter(type=ctype)
        origin = (request.query_params.get("origin") or "").strip().lower()
        if origin == "builtin":
            qs = qs.filter(is_builtin=True)
        elif origin in ("custom", "user"):
            qs = qs.filter(is_custom=True)
        q = (request.query_params.get("q") or "").strip()
        if q:
            from django.db.models import Q

            qs = qs.filter(Q(name__icontains=q) | Q(label__icontains=q))
        return paginate_items(request, qs.order_by("type", "name"), ComponentMetaSerializer)

    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可创建自定义组件"}, status=403)
    serializer = ComponentCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    component = ComponentMeta.objects.create(**serializer.validated_data)
    _snapshot(component, changelog="create")
    write_audit_log(
        user=request.user,
        action="component.create",
        object_type="component",
        object_id=str(component.id),
        request=request,
    )
    return Response(ComponentMetaSerializer(component).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def component_detail(request, pk):
    """GET/PUT/PATCH/DELETE /api/components/{id}/"""
    component = ComponentMeta.objects.filter(pk=pk).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    if request.method == "GET":
        if not component.is_enabled and not is_platform_admin_full(request.user):
            return Response({"detail": "组件已禁用"}, status=404)
        return Response(ComponentMetaSerializer(component).data)
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可修改组件"}, status=403)
    if request.method in ("PUT", "PATCH"):
        serializer = ComponentUpdateSerializer(component, data=request.data, partial=(request.method == "PATCH"))
        serializer.is_valid(raise_exception=True)
        changed_version = False
        for field, value in serializer.validated_data.items():
            if getattr(component, field) != value:
                setattr(component, field, value)
                if field == "version":
                    changed_version = True
        component.save()
        if changed_version:
            _snapshot(component, changelog="update")
        write_audit_log(
            user=request.user,
            action="component.update",
            object_type="component",
            object_id=str(component.id),
            request=request,
        )
        return Response(ComponentMetaSerializer(component).data)
    # DELETE：仅允许删除自定义组件
    if component.is_builtin:
        return Response({"detail": "内置组件不可删除，只能禁用"}, status=400)
    if component.source_url:
        removed = False
        media_root = getattr(settings, "MEDIA_ROOT", "")
        if media_root:
            folder = Path(media_root) / "custom-components" / component.name
            if folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
                removed = True
        if not removed:
            rel_path = component.source_url
            if rel_path.startswith(settings.MEDIA_URL):
                rel_path = rel_path[len(settings.MEDIA_URL):]
            rel_path = rel_path.lstrip("/")
            if rel_path and default_storage.exists(rel_path):
                default_storage.delete(rel_path)
    component.delete()
    write_audit_log(
        user=request.user,
        action="component.delete",
        object_type="component",
        object_id=str(pk),
        request=request,
    )
    return Response(status=204)


def _toggle(request, pk, enabled: bool):
    component = ComponentMeta.objects.filter(pk=pk).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可启用/禁用组件"}, status=403)
    component.is_enabled = enabled
    component.save(update_fields=["is_enabled", "updated_at"])
    write_audit_log(
        user=request.user,
        action=f"component.{'enable' if enabled else 'disable'}",
        object_type="component",
        object_id=str(component.id),
        request=request,
    )
    return Response(ComponentMetaSerializer(component).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_enable(request, pk):
    """POST /api/components/{id}/enable/"""
    return _toggle(request, pk, True)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_disable(request, pk):
    """POST /api/components/{id}/disable/"""
    return _toggle(request, pk, False)


def _version_dict(component: ComponentMeta, v) -> dict:
    return {
        "id": v.id,
        "component": component.id,
        "name": component.name,
        "version": v.version,
        "meta": v.meta_snapshot,
        "changelog": v.changelog,
        "created_at": v.created_at,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def component_versions(request, name):
    """GET /api/components/{name}/versions/（兼容按名称）"""
    component = ComponentMeta.objects.filter(name=name).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    return paginate_items(request, component.versions.all(), lambda v: _version_dict(component, v))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def component_versions_by_id(request, pk):
    """GET /api/components/{id}/versions/?page=1&size=20"""
    component = ComponentMeta.objects.filter(pk=pk).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    return paginate_items(request, component.versions.all(), lambda v: _version_dict(component, v))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def component_version_source(request, pk, version):
    """GET /api/components/{id}/versions/{version}/source/ → 自定义组件源码"""
    component = ComponentMeta.objects.filter(pk=pk).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    if component.is_builtin:
        return Response({"detail": "内置组件没有源码"}, status=404)
    v = component.versions.filter(version=version).first()
    if v is None:
        return Response({"detail": "版本不存在"}, status=404)
    source = (v.meta_snapshot or {}).get("source")
    if not source:
        return Response({"detail": "该版本没有保存源码"}, status=404)
    return Response({"component": component.name, "version": version, "source": source})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_custom_create(request):
    """POST /api/components/custom/ {name,label,source}（Vue SFC 源码）"""
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可创建自定义组件"}, status=403)
    serializer = ComponentCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    component = ComponentMeta.objects.create(**serializer.validated_data)
    meta = ComponentMetaSerializer(component).data
    source = request.data.get("source")
    if source:
        meta["source"] = source
    version, _ = ComponentVersion.objects.update_or_create(
        component=component,
        version=component.version,
        defaults={"meta_snapshot": meta, "changelog": "create (custom)"},
    )
    write_audit_log(
        user=request.user,
        action="component.create_custom",
        object_type="component",
        object_id=str(component.id),
        request=request,
    )
    return Response(ComponentMetaSerializer(component).data, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def component_import(request):
    """POST /api/components/import/

    导入预构建的 Vue Web Component（ESM），由平台运行时动态加载。
    表单字段：file, name, label, tag, version, props_schema, events, default_props。
    """
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可导入组件"}, status=403)
    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "请上传组件 JS 文件"}, status=400)
    if not str(upload.name or "").lower().endswith(".js"):
        return Response({"detail": "只支持 .js 文件"}, status=400)
    if int(getattr(upload, "size", 0) or 0) > 8 * 1024 * 1024:
        return Response({"detail": "组件文件不能超过 8MB"}, status=400)

    name = str(request.data.get("name") or "").strip()
    tag = str(request.data.get("tag") or "").strip()
    version = str(request.data.get("version") or "1.0.0").strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", name):
        return Response({"detail": "name 必须是小写字母开头，只含小写字母/数字/短横线"}, status=400)
    if not re.fullmatch(r"wp-widget-[a-z0-9-]+", tag):
        return Response({"detail": "tag 必须以 wp-widget- 开头，只含小写字母/数字/短横线"}, status=400)
    if not re.fullmatch(r"[0-9A-Za-z._-]{1,32}", version):
        return Response({"detail": "version 格式不正确"}, status=400)

    def _json_field(key, default):
        raw = request.data.get(key)
        if raw in (None, ""):
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(str(raw))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{key} 必须是合法 JSON") from exc

    try:
        props_schema = _json_field("props_schema", {"type": "object", "properties": {}})
        events = _json_field("events", [])
        default_props = _json_field("default_props", {})
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    if not isinstance(props_schema, dict):
        return Response({"detail": "props_schema 必须是对象"}, status=400)
    if not isinstance(events, list):
        return Response({"detail": "events 必须是数组"}, status=400)
    if not isinstance(default_props, dict):
        return Response({"detail": "default_props 必须是对象"}, status=400)

    label = str(request.data.get("label") or name).strip() or name
    rel_path = f"custom-components/{name}/{version}/index.js"
    if default_storage.exists(rel_path):
        default_storage.delete(rel_path)
    saved_name = default_storage.save(rel_path, upload)
    source_url = f"{settings.MEDIA_URL.rstrip('/')}/{saved_name.lstrip('/')}"

    component = ComponentMeta.objects.filter(name=name).first()
    if component is not None and component.is_builtin:
        default_storage.delete(saved_name)
        return Response({"detail": "不能覆盖内置组件"}, status=400)
    if component is None:
        component = ComponentMeta(name=name)
        created = True
    else:
        created = False
    component.label = label
    component.type = "custom"
    component.category = "custom"
    component.version = version
    component.props_schema = props_schema
    component.default_props = default_props
    component.events = events
    component.source = "custom"
    component.element = tag
    component.source_url = source_url
    component.is_custom = True
    component.is_enabled = True
    component.save()
    _snapshot(component, changelog="import web component")
    invalidate_registry_cache()
    write_audit_log(
        user=request.user,
        action="component.import",
        object_type="component",
        object_id=str(component.id),
        after=ComponentMetaSerializer(component).data,
        request=request,
    )
    return Response(
        ComponentMetaSerializer(component).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_compile(request):
    """POST /api/components/compile/

    在线编写 Vue SFC → 服务端 Vite 构建 → 注册为 Web Component。
    仅平台管理员可用；不做沙箱，适合内部可信开发。
    """
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可在线编译组件"}, status=403)
    source = str(request.data.get("source") or "").strip()
    if not source:
        return Response({"detail": "source 不能为空"}, status=400)
    if len(source.encode("utf-8")) > 200 * 1024:
        return Response({"detail": "组件源码不能超过 200KB"}, status=400)
    name = str(request.data.get("name") or "").strip()
    tag = str(request.data.get("tag") or "").strip()
    version = str(request.data.get("version") or "1.0.0").strip()
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", name):
        return Response({"detail": "name 必须是小写字母开头，只含小写字母/数字/短横线"}, status=400)
    if not re.fullmatch(r"wp-widget-[a-z0-9-]+", tag):
        return Response({"detail": "tag 必须以 wp-widget- 开头，只含小写字母/数字/短横线"}, status=400)
    if not re.fullmatch(r"[0-9A-Za-z._-]{1,32}", version):
        return Response({"detail": "version 格式不正确"}, status=400)

    def _json_field(key, default):
        raw = request.data.get(key)
        if raw in (None, ""):
            return default
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(str(raw))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"{key} 必须是合法 JSON") from exc

    try:
        props_schema = _json_field("props_schema", {"type": "object", "properties": {}})
        events = _json_field("events", [])
        default_props = _json_field("default_props", {})
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=400)
    if not isinstance(props_schema, dict) or not isinstance(events, list) or not isinstance(default_props, dict):
        return Response({"detail": "props_schema/default_props 必须是对象，events 必须是数组"}, status=400)

    frontend = Path(settings.BASE_DIR).parent / "frontend"
    vite_bin = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    node_bin = shutil.which("node")
    if not vite_bin.exists() or not node_bin:
        return Response({"detail": "服务端未找到 Node/Vite 构建环境"}, status=500)

    tmp_root = frontend / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="wp-component-", dir=str(tmp_root)))
    try:
        (workdir / "Widget.ce.vue").write_text(source, encoding="utf-8")
        entry = (
            "import { defineCustomElement } from 'vue';\n"
            "import Comp from './Widget.ce.vue';\n"
            f"const tag = {json.dumps(tag)};\n"
            "if (!customElements.get(tag)) {\n"
            "  customElements.define(tag, defineCustomElement(Comp, { shadowRoot: false }));\n"
            "}\n"
        )
        (workdir / "entry.js").write_text(entry, encoding="utf-8")
        config = (
            "import { defineConfig } from 'vite';\n"
            "import vue from '@vitejs/plugin-vue';\n"
            "export default defineConfig({\n"
            "  plugins: [vue()],\n"
            "  define: {\n"
            "    'process.env.NODE_ENV': JSON.stringify('production'),\n"
            "    'process.env': '{}',\n"
            "    global: 'globalThis',\n"
            "  },\n"
            "  build: {\n"
            "    lib: { entry: 'entry.js', formats: ['es'], fileName: () => 'widget.js' },\n"
            "    outDir: 'dist', emptyOutDir: true, cssCodeSplit: false, minify: true,\n"
            "  },\n"
            "});\n"
        )
        (workdir / "vite.config.mjs").write_text(config, encoding="utf-8")
        proc = subprocess.run(
            [node_bin, str(vite_bin), "build", "--config", "vite.config.mjs"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "构建失败").strip()
            match = re.search(r"Widget\.ce\.vue:(\d+):(\d+)", detail)
            return Response({
                "detail": f"组件编译失败：{detail[-1200:]}",
                "line": int(match.group(1)) if match else 0,
                "column": int(match.group(2)) if match else 0,
            }, status=400)
        js_path = workdir / "dist" / "widget.js"
        if not js_path.exists():
            return Response({"detail": "构建没有生成 widget.js"}, status=400)
        bundle = js_path.read_text(encoding="utf-8")
        css_path = workdir / "dist" / "style.css"
        if css_path.exists():
            css = css_path.read_text(encoding="utf-8")
            bundle = (
                "const __wpStyle = document.createElement('style');\n"
                f"__wpStyle.textContent = {json.dumps(css)};\n"
                "document.head.appendChild(__wpStyle);\n"
                + bundle
            )
        raw = bundle.encode("utf-8")
        if len(raw) > 8 * 1024 * 1024:
            return Response({"detail": "构建产物超过 8MB"}, status=400)
    except subprocess.TimeoutExpired:
        return Response({"detail": "组件编译超时（60 秒）"}, status=400)
    except Exception as exc:  # noqa: BLE001
        return Response({"detail": f"组件编译失败：{exc}"}, status=400)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    rel_path = f"custom-components/{name}/{version}/index.js"
    if default_storage.exists(rel_path):
        default_storage.delete(rel_path)
    saved_name = default_storage.save(rel_path, ContentFile(raw))
    source_url = f"{settings.MEDIA_URL.rstrip('/')}/{saved_name.lstrip('/')}"
    label = str(request.data.get("label") or name).strip() or name
    component = ComponentMeta.objects.filter(name=name).first()
    if component is not None and component.is_builtin:
        default_storage.delete(saved_name)
        return Response({"detail": "不能覆盖内置组件"}, status=400)
    if component is None:
        component = ComponentMeta(name=name)
        created = True
    else:
        created = False
    component.label = label
    component.type = "custom"
    component.category = "custom"
    component.version = version
    component.props_schema = props_schema
    component.default_props = default_props
    component.events = events
    component.source = "custom"
    component.element = tag
    component.source_url = source_url
    component.is_custom = True
    component.is_enabled = True
    component.save()
    _snapshot(component, changelog="compile web component")
    invalidate_registry_cache()
    write_audit_log(
        user=request.user,
        action="component.compile",
        object_type="component",
        object_id=str(component.id),
        after=ComponentMetaSerializer(component).data,
        request=request,
    )
    return Response(
        ComponentMetaSerializer(component).data,
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_ai_draft(request):
    """POST /api/components/ai-draft/ → 根据描述生成 Vue SFC 草稿。"""
    from ai.providers import chat_config, is_configured
    from ai.usage import record_usage
    from wp_utils import http_request

    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可使用 AI 生成组件"}, status=403)
    prompt = str(request.data.get("prompt") or "").strip()
    if not prompt:
        return Response({"detail": "请填写组件描述"}, status=400)
    if len(prompt) > 2000:
        return Response({"detail": "描述不能超过 2000 字"}, status=400)
    name = str(request.data.get("name") or "").strip() or "ai-widget"
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", name):
        name = "ai-widget-" + str(abs(hash(prompt)) % 100000)
    tag = str(request.data.get("tag") or "").strip() or f"wp-widget-{name}"
    if not re.fullmatch(r"wp-widget-[a-z0-9-]+", tag):
        tag = f"wp-widget-{name}"
    current_source = str(request.data.get("current_source") or "").strip()
    if len(current_source.encode("utf-8")) > 200 * 1024:
        return Response({"detail": "当前源码过大"}, status=400)

    system = """你是 Vue 3 组件开发助手。请生成一个可独立编译的 Vue 单文件组件（SFC），用于平台自定义 Web Component。
要求：
1. 只返回 JSON，不要 Markdown 代码围栏，不要解释。
2. JSON 字段：name, label, tag, source, props_schema, events。
3. source 必须是完整 SFC：<template>、<script setup lang="ts">、<style scoped>。
4. 组件只能使用 Vue 内置能力；不要使用 Element Plus、路由、Pinia、图片外链和平台内部 API。
5. 不要访问 localStorage、window.location、document.cookie。
6. 所有可配置内容做成 defineProps 属性，并在 props_schema 中声明。
7. tag 必须以 wp-widget- 开头。
8. 设计要简洁、自适应、可在普通页面中渲染。
"""
    user = f"组件需求：\n{prompt}\n\n建议 name：{name}\n建议 tag：{tag}\n"
    if current_source:
        user += f"\n在现有组件基础上修改，保持可用：\n{current_source[:12000]}\n"
    provider = "local"
    model = "local-component"
    warnings: list[str] = []
    draft = None
    if is_configured():
        cfg = chat_config()
        provider = cfg.get("provider_name") or "llm"
        model = cfg.get("model") or ""
        try:
            status_code, text = http_request(
                f"{cfg['base_url']}/chat/completions",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {cfg['api_key']}",
                },
                body=json.dumps({
                    "model": cfg["model"],
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 3000,
                    "response_format": {"type": "json_object"},
                }, ensure_ascii=False).encode("utf-8"),
                timeout=90,
            )
            if status_code >= 400:
                raise ValueError(f"LLM HTTP {status_code}")
            payload = json.loads(text)
            content = payload["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*", "", content.strip())
            content = re.sub(r"\s*```$", "", content)
            start, end = content.find("{"), content.rfind("}")
            draft = json.loads(content[start:end + 1] if start >= 0 and end > start else content)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"AI 生成失败，已使用本地模板：{type(exc).__name__}: {exc}")
            draft = None
    else:
        warnings.append("未配置 AI Provider，使用本地组件模板")
    if not isinstance(draft, dict) or "<template" not in str(draft.get("source") or ""):
        safe_prompt = prompt.replace("<", "&lt;").replace(">", "&gt;")[:80]
        draft = {
            "name": name,
            "label": "AI 组件",
            "tag": tag,
            "source": f"""<template>
  <section class="ai-widget">
    <h3>{{{{ title }}}}</h3>
    <p>{safe_prompt}</p>
  </section>
</template>

<script setup lang="ts">
withDefaults(defineProps<{{ title?: string }}>(), {{ title: "AI 组件" }});
</script>

<style scoped>
.ai-widget {{ border: 1px solid #dcdfe6; border-radius: 8px; padding: 16px; background: #fff; }}
.ai-widget h3 {{ margin: 0 0 8px; }}
</style>""",
            "props_schema": {"type": "object", "properties": {"title": {"type": "string", "title": "标题", "default": "AI 组件"}}},
            "events": [],
        }
    source = str(draft.get("source") or "").strip()
    if "<template" not in source or "</template>" not in source:
        return Response({"detail": "AI 没有返回有效的 Vue SFC"}, status=400)
    out = {
        "name": str(draft.get("name") or name)[:64],
        "label": str(draft.get("label") or "AI 组件")[:80],
        "tag": str(draft.get("tag") or tag)[:80],
        "source": source,
        "props_schema": draft.get("props_schema") if isinstance(draft.get("props_schema"), dict) else {"type": "object", "properties": {}},
        "events": draft.get("events") if isinstance(draft.get("events"), list) else [],
    }
    record_usage(
        user=request.user, app=None, action="component_draft", provider=provider,
        model=model, prompt=prompt, response=json.dumps(out, ensure_ascii=False),
        success=bool(out["source"]), error="; ".join(warnings),
    )
    return Response({"draft": out, "provider": provider, "model": model, "warnings": warnings})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_upgrade(request, pk):
    """POST /api/components/{id}/upgrade/ {version, source?, changelog?}

    记录新版本，并把所有应用草稿 schema 中该组件的 componentVersion 更新。
    """
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可升级组件"}, status=403)
    component = ComponentMeta.objects.filter(pk=pk).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    new_version = str(request.data.get("version") or "").strip()
    if not new_version:
        return Response({"detail": "version 必填"}, status=400)
    if component.versions.filter(version=new_version).exists():
        return Response({"detail": f"版本 {new_version} 已存在"}, status=400)
    meta = ComponentMetaSerializer(component).data
    source = request.data.get("source")
    if source:
        meta["source"] = source
    changelog = str(request.data.get("changelog") or "")
    component.version = new_version
    component.save(update_fields=["version", "updated_at"])
    ComponentVersion.objects.create(component=component, version=new_version, meta_snapshot=meta, changelog=changelog)
    # 更新所有草稿页面 schema 中引用该组件的 componentVersion
    from pages.models import Page

    updated_pages = 0
    for page in Page.objects.select_related("app").iterator():
        schema = page.schema or {}
        nodes = schema.get("nodes") or {}
        changed = False
        for node in nodes.values():
            if isinstance(node, dict) and node.get("type") == component.name:
                node["componentVersion"] = new_version
                changed = True
        if changed:
            page.save(update_fields=["schema", "updated_at"])
            updated_pages += 1
    write_audit_log(
        user=request.user,
        action="component.upgrade",
        object_type="component",
        object_id=str(component.id),
        request=request,
    )
    return Response({"component": component.name, "version": new_version, "updated_pages": updated_pages})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def component_rollback(request, pk, version):
    """POST /api/components/{id}/versions/{version}/rollback/ → 回滚组件元数据与入口。"""
    if not is_platform_admin_full(request.user):
        return Response({"detail": "仅平台管理员可回滚组件"}, status=403)
    component = ComponentMeta.objects.filter(pk=pk).first()
    if component is None:
        return Response({"detail": "组件不存在"}, status=404)
    target = component.versions.filter(version=version).first()
    if target is None:
        return Response({"detail": "版本不存在"}, status=404)
    snap = target.meta_snapshot or {}
    if snap.get("is_builtin"):
        return Response({"detail": "不能回滚到内置组件版本"}, status=400)
    if snap.get("source_url"):
        rel_path = str(snap["source_url"])
        if rel_path.startswith(settings.MEDIA_URL):
            rel_path = rel_path[len(settings.MEDIA_URL):]
        rel_path = rel_path.lstrip("/")
        if not default_storage.exists(rel_path):
            return Response({"detail": "该版本构建文件不存在，无法回滚"}, status=400)
    fields = (
        "label", "type", "category", "props_schema", "style_schema", "default_props",
        "events", "slots", "accept_children", "source", "element", "is_container",
        "is_form_field", "default_children", "actions_supported", "icon", "source_url",
    )
    for field in fields:
        if field in snap:
            setattr(component, field, snap[field])
    component.version = version
    component.is_custom = True
    component.is_enabled = True
    component.save()
    invalidate_registry_cache()
    write_audit_log(
        user=request.user,
        action="component.rollback",
        object_type="component",
        object_id=str(component.id),
        after=ComponentMetaSerializer(component).data,
        request=request,
    )
    return Response(ComponentMetaSerializer(component).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def component_registry(request):
    """GET /api/components/registry/ → 设计器组件注册表（内置 + 自定义启用组件）。"""
    from .services import COMPONENT_CATEGORIES

    components = ComponentMeta.objects.filter(is_enabled=True).order_by("type", "name")
    out = [
        {
            "name": c.name,
            "label": c.label,
            "type": c.type,
            "category": c.category,
            "version": c.version,
            "icon": c.icon,
            "source": c.source,
            "element": c.element,
            "source_url": c.source_url,
            "is_container": c.is_container,
            "is_form_field": c.is_form_field,
            "default_children": c.default_children or [],
            "actions_supported": c.actions_supported or [],
            "props_schema": c.props_schema,
            "style_schema": c.style_schema,
            "default_props": c.default_props,
            "events": c.events,
            "provides": c.provides or [],
            "consumes": c.consumes or [],
            "payload_schema": c.payload_schema or {},
            "slots": c.slots,
            "accept_children": c.accept_children,
            "accepts": c.accept_children,
        }
        for c in components
    ]
    return Response(
        {
            "version": "2.0.0",
            "schemaVersion": 2,
            "categories": COMPONENT_CATEGORIES,
            "components": out,
        }
    )
