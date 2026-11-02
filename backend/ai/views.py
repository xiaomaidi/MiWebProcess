from __future__ import annotations

import json
import queue
import re
import threading
import time

from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.http import StreamingHttpResponse
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ai.services import call_llm, call_llm_edit, local_edit, local_generate, local_variants, polish_schema, validate_schema
from ai.agent import apply_proposal, conversation_payload, message_payload, run_turn
from ai.autobuild import DEFAULT_OPTIONS, generate_blueprint, job_payload, start_job
from ai.visual import review_screenshot
from ai.contentgen import call_llm_content, local_batch, local_content
from ai.modelgen import call_llm_model, local_model_draft, normalize_model_draft
from ai.permissions import suggest_permissions
from ai.reportqa import llm_answer, local_answer
from ai.review import review_schema
from ai.sqlgen import generate_sql
from ai.crypto import encrypt_secret
from ai.models import AiBuildJob, AiConversation, AiMessage, AiProvider
from ai.providers import is_configured, provider_payload, status_payload, test_provider
from ai.site import build_site_plan, call_llm_site_meta
from ai.translate import llm_translate, local_translate
from ai.workflowgen import call_llm_workflow, local_workflow, normalize_workflow
from ai.usage import record_usage, usage_summary
from datamodels.models import DataModel
from wp_utils import get_app, is_platform_admin_full, require_app_role


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_status(request):
    return Response(status_payload())


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def permission_suggestions(request):
    app_id = request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    fields = request.data.get("fields")
    model_id = request.data.get("model_id")
    if (not isinstance(fields, list) or not fields) and model_id:
        model = DataModel.objects.filter(app=app, id=int(model_id)).first()
        if model is None:
            raise ValidationError({"detail": "数据模型不存在"})
        fields = model.fields or []
    if not isinstance(fields, list):
        raise ValidationError({"detail": "fields 必须是字段数组"})
    result = suggest_permissions(fields)
    record_usage(user=request.user, app=app, action="permission_suggestions", provider="local", model="permission-rules", prompt=str(model_id or "draft"), response=json.dumps(result, ensure_ascii=False))
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def report_ask(request):
    from datamodels.services import apply_row_scope, dynamic_query

    app_id = request.data.get("app_id")
    model_id = request.data.get("model_id")
    question = str(request.data.get("question") or "").strip()
    if not app_id or not model_id or not question:
        raise ValidationError({"detail": "app_id、model_id、question 必填"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "viewer")
    model = DataModel.objects.filter(app=app, id=int(model_id)).first()
    if model is None:
        raise ValidationError({"detail": "数据模型不存在"})
    rows = dynamic_query(model, {"size": 200})
    rows = apply_row_scope(model, rows, request.user, admin=is_platform_admin_full(request.user))
    provider = "local"
    warnings: list[str] = []
    try:
        if is_configured():
            answer = llm_answer(app.name, question, rows, model.fields or [])
            provider = "llm"
        else:
            answer = local_answer(question, rows, model.fields or [])
            warnings.append("未配置 AI Provider，当前使用本地统计回答。")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"AI 回答失败，已回退本地统计：{exc}")
        answer = local_answer(question, rows, model.fields or [])
        provider = "local-fallback"
    record_usage(user=request.user, app=app, action="report_ask", provider=provider, model="report-qa", prompt=question, response=answer)
    return Response({"answer": answer, "provider": provider, "rows": len(rows), "warnings": warnings})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def design_review(request):
    app_id = request.data.get("app_id")
    schema = request.data.get("schema")
    if not app_id or not isinstance(schema, dict):
        raise ValidationError({"detail": "app_id 和 schema 必填"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "viewer")
    result = review_schema(schema)
    record_usage(user=request.user, app=app, action="design_review", provider="local", model="design-rules", prompt=json.dumps({"nodes": len(schema.get("nodes") or {})}), response=json.dumps(result, ensure_ascii=False))
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def node_draft(request):
    """POST /api/ai/node-draft/ → 针对设计器选中节点生成 props/style/events。"""
    from ai.providers import chat_config, is_configured
    from wp_utils import http_request

    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述想怎么改"})
    if len(prompt) > 1000:
        raise ValidationError({"detail": "描述最多 1000 字"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    key = f"ai_node_draft:{request.user.id}"
    count = int(cache.get(key) or 0)
    if count >= 60:
        raise ValidationError({"detail": "本小时 AI 属性生成次数已达上限"})
    cache.set(key, count + 1, 3600)

    props_schema = request.data.get("props_schema") if isinstance(request.data.get("props_schema"), dict) else {}
    style_schema = request.data.get("style_schema") if isinstance(request.data.get("style_schema"), dict) else {}
    current_props = request.data.get("current_props") if isinstance(request.data.get("current_props"), dict) else {}
    current_style = request.data.get("current_style") if isinstance(request.data.get("current_style"), dict) else {}
    current_events = request.data.get("current_events") if isinstance(request.data.get("current_events"), dict) else {}
    allowed_events = request.data.get("allowed_events") if isinstance(request.data.get("allowed_events"), list) else []
    node_type = str(request.data.get("node_type") or "")
    node_label = str(request.data.get("node_label") or node_type)
    allowed_props = list((props_schema.get("properties") or {}).keys())

    system = """你是 MiWebProcess 页面设计器的节点属性助手。只返回 JSON 对象，不要 Markdown。
返回字段：props、style、events、explanation。
规则：
1. props 只能包含允许的属性键，值要符合对应类型。
2. style 使用 CSS 驼峰属性，例如 color、backgroundColor、fontSize、borderRadius、padding、margin、textAlign。
3. events 只能使用允许的事件名，值是动作步骤数组；不确定时返回空对象。
4. 不要修改组件类型、children、数据绑定结构；不要写 script/iframe/JS 代码。
5. 只修改用户要求的属性，未涉及的保持当前值或不返回。
"""
    user = json.dumps({
        "node_type": node_type,
        "node_label": node_label,
        "allowed_props": allowed_props,
        "props_schema": props_schema,
        "style_schema": style_schema,
        "allowed_events": allowed_events,
        "current_props": current_props,
        "current_style": current_style,
        "current_events": current_events,
        "request": prompt,
    }, ensure_ascii=False)

    warnings: list[str] = []
    provider = "local"
    model_name = "local-node"
    draft: dict = {"props": {}, "style": {}, "events": {}, "explanation": ""}
    if is_configured():
        cfg = chat_config()
        provider = cfg.get("provider_name") or "llm"
        model_name = cfg.get("model") or ""
        try:
            status_code, text = http_request(
                f"{cfg['base_url']}/chat/completions",
                method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {cfg['api_key']}"},
                body=json.dumps({
                    "model": cfg["model"],
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1200,
                    "response_format": {"type": "json_object"},
                }, ensure_ascii=False).encode("utf-8"),
                timeout=60,
            )
            if status_code >= 400:
                raise ValueError(f"LLM HTTP {status_code}")
            payload = json.loads(text)
            content = payload["choices"][0]["message"]["content"]
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.I)
            start, end = content.find("{"), content.rfind("}")
            draft = json.loads(content[start:end + 1] if start >= 0 and end > start else content)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError({"detail": f"AI 属性生成失败：{type(exc).__name__}: {exc}"}) from exc
    else:
        warnings.append("未配置 AI Provider，未修改属性")

    raw_props = draft.get("props") if isinstance(draft.get("props"), dict) else {}
    props: dict = {}
    prop_defs = props_schema.get("properties") or {}
    for name, value in raw_props.items():
        if name not in allowed_props:
            continue
        kind = (prop_defs.get(name) or {}).get("type")
        try:
            if kind == "number":
                value = float(value) if "." in str(value) else int(value)
            elif kind == "boolean":
                value = bool(value)
            elif kind == "string":
                value = str(value)
        except (TypeError, ValueError):
            continue
        props[name] = value
        if len(props) >= 40:
            break
    raw_style = draft.get("style") if isinstance(draft.get("style"), dict) else {}
    style: dict = {}
    for name, value in raw_style.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,40}", str(name)):
            continue
        if isinstance(value, (str, int, float)):
            style[name] = value
        if len(style) >= 30:
            break
    raw_events = draft.get("events") if isinstance(draft.get("events"), dict) else {}
    events: dict = {}
    allowed_event_set = set(str(x) for x in allowed_events)
    for name, value in raw_events.items():
        if name in allowed_event_set and isinstance(value, list):
            events[name] = value

    result = {
        "props": props, "style": style, "events": events,
        "explanation": str(draft.get("explanation") or ""),
        "provider": provider, "model": model_name, "warnings": warnings,
    }
    record_usage(
        user=request.user, app=app, action="node_draft", provider=provider,
        model=model_name, prompt=prompt, response=json.dumps(result, ensure_ascii=False),
        success=True, error="; ".join(warnings),
    )
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def workflow_draft(request):
    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述审批流程"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    key = f"ai_workflow_draft:{request.user.id}"
    count = int(cache.get(key) or 0)
    if count >= 30:
        raise ValidationError({"detail": "本小时 AI 流程生成次数已达上限"})
    cache.set(key, count + 1, 3600)
    provider = "local"
    model_name = "local-workflow-template"
    warnings: list[str] = []
    try:
        if is_configured():
            draft, model_name = call_llm_workflow(app.name, prompt)
            provider = "llm"
        else:
            draft = local_workflow(prompt)
            warnings.append("未配置 AI Provider，当前使用本地流程模板。")
        draft = normalize_workflow(draft)
    except ValidationError as exc:
        detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail
        warnings.append(str(detail))
        draft = normalize_workflow(local_workflow(prompt))
        provider = "local-fallback"
    record_usage(user=request.user, app=app, action="workflow_draft", provider=provider, model=model_name, prompt=prompt, response=json.dumps(draft, ensure_ascii=False), success=bool(draft), error="; ".join(warnings))
    return Response({"draft": draft, "provider": provider, "model": model_name, "warnings": warnings})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def page_variants(request):
    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述你想要的页面"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    models = list(DataModel.objects.filter(app=app).values("id", "name", "fields"))
    variants = local_variants(app.name, prompt, models)
    for item in variants:
        item["schema"] = validate_schema(polish_schema(item["schema"], prompt, app.name), app.name)
    record_usage(user=request.user, app=app, action="page_variants", provider="local", model="local-theme-variants", prompt=prompt, response=json.dumps(variants, ensure_ascii=False))
    return Response({"variants": variants, "provider": "local", "model": "local-theme-variants"})


def _require_ai_admin(request):
    if not is_platform_admin_full(request.user):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("只有平台管理员可以管理 AI Provider")


def _provider_payload_from_request(request, existing: AiProvider | None = None) -> dict:
    data = request.data
    name = str(data.get("name") or "").strip()
    base_url = str(data.get("base_url") or "").strip().rstrip("/")
    model = str(data.get("model") or "").strip()
    provider_type = str(data.get("provider_type") or "custom")
    if not name or not base_url or not model:
        raise ValidationError({"detail": "name、base_url、model 必填"})
    if provider_type not in dict(AiProvider.TYPE_CHOICES):
        raise ValidationError({"detail": "provider_type 不合法"})
    api_key = str(data.get("api_key") or "")
    if existing and api_key in ("", "***"):
        api_key = existing.api_key
    else:
        api_key = encrypt_secret(api_key)
    enabled = bool(data.get("enabled", existing.enabled if existing else True))
    is_default = bool(data.get("is_default", existing.is_default if existing else False))
    return {
        "name": name,
        "provider_type": provider_type,
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "enabled": enabled,
        "is_default": is_default,
        "temperature": float(data.get("temperature", 0.4) or 0.4),
        "timeout": int(data.get("timeout", 90) or 90),
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def ai_usage(request):
    _require_ai_admin(request)
    return Response(usage_summary())


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def providers(request):
    _require_ai_admin(request)
    if request.method == "GET":
        return Response([provider_payload(p) for p in AiProvider.objects.all()])
    payload = _provider_payload_from_request(request)
    if AiProvider.objects.filter(name=payload["name"]).exists():
        raise ValidationError({"detail": "Provider 名称已存在"})
    first = not AiProvider.objects.exists()
    if first:
        payload["is_default"] = True
    provider = AiProvider.objects.create(**payload)
    if provider.is_default:
        AiProvider.objects.exclude(id=provider.id).update(is_default=False)
    return Response(provider_payload(provider), status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def provider_detail(request, pk: int):
    _require_ai_admin(request)
    from django.shortcuts import get_object_or_404

    provider = get_object_or_404(AiProvider, pk=pk)
    if request.method == "GET":
        return Response(provider_payload(provider))
    if request.method == "DELETE":
        was_default = provider.is_default
        provider.delete()
        if was_default:
            nxt = AiProvider.objects.filter(enabled=True).first()
            if nxt:
                nxt.is_default = True
                nxt.save(update_fields=["is_default", "updated_at"])
        return Response(status=204)
    payload = _provider_payload_from_request(request, provider)
    if AiProvider.objects.filter(name=payload["name"]).exclude(id=provider.id).exists():
        raise ValidationError({"detail": "Provider 名称已存在"})
    for key, value in payload.items():
        setattr(provider, key, value)
    provider.save()
    if provider.is_default:
        AiProvider.objects.exclude(id=provider.id).update(is_default=False)
    return Response(provider_payload(provider))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def provider_test(request, pk: int):
    _require_ai_admin(request)
    from django.shortcuts import get_object_or_404
    from django.utils import timezone

    provider = get_object_or_404(AiProvider, pk=pk)
    result = test_provider(provider)
    provider.last_test_at = timezone.now()
    provider.last_error = "" if result["ok"] else str(result["message"])[:2000]
    provider.save(update_fields=["last_test_at", "last_error", "updated_at"])
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def provider_default(request, pk: int):
    _require_ai_admin(request)
    from django.shortcuts import get_object_or_404

    provider = get_object_or_404(AiProvider, pk=pk)
    AiProvider.objects.update(is_default=False)
    provider.is_default = True
    provider.enabled = True
    provider.save(update_fields=["is_default", "enabled", "updated_at"])
    return Response(provider_payload(provider))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def content_draft(request):
    app_id = request.data.get("app_id")
    model_id = request.data.get("model_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id or not model_id:
        raise ValidationError({"detail": "app_id 和 model_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请填写内容主题"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    model = DataModel.objects.filter(app=app, id=int(model_id)).first()
    if model is None:
        raise ValidationError({"detail": "数据模型不存在"})
    fields = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    key = f"ai_content_draft:{request.user.id}"
    count = int(cache.get(key) or 0)
    if count >= 30:
        raise ValidationError({"detail": "本小时 AI 内容生成次数已达上限"})
    cache.set(key, count + 1, 3600)
    provider = "local"
    model_name = "local-content-template"
    warnings: list[str] = []
    try:
        if is_configured():
            draft, model_name = call_llm_content(app.name, prompt, fields)
            provider = "llm"
        else:
            draft = local_content(prompt, fields)
            warnings.append("未配置 AI Provider，当前使用本地内容模板。")
    except ValidationError as exc:
        detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail
        warnings.append(str(detail))
        draft = local_content(prompt, fields)
        provider = "local-fallback"
    record_usage(user=request.user, app=app, action="content_draft", provider=provider, model=model_name, prompt=prompt, response=json.dumps(draft, ensure_ascii=False), success=bool(draft), error="; ".join(warnings))
    return Response({"draft": draft, "provider": provider, "model": model_name, "warnings": warnings})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def datasource_sql(request):
    from datasources.executor import decode_secrets, list_external_schema
    from datasources.models import Datasource

    datasource_id = request.data.get("datasource_id")
    question = str(request.data.get("question") or "").strip()
    if not datasource_id or not question:
        raise ValidationError({"detail": "datasource_id 和 question 必填"})
    ds = Datasource.objects.select_related("app").filter(id=int(datasource_id)).first()
    if ds is None:
        raise ValidationError({"detail": "数据源不存在"})
    require_app_role(request.user, ds.app, "editor")
    if ds.type not in ("postgres", "mysql", "sqlserver"):
        raise ValidationError({"detail": "该数据源不支持 AI SQL"})
    tables = list_external_schema(ds.type, decode_secrets(ds.config or {}))
    description = "\n".join(
        f'{t["schema"]}.{t["name"]}: ' + ", ".join(f'{c["name"]}({c["type"]})' for c in t["columns"])
        for t in tables
    )
    sql, model = generate_sql(question, tables, description)
    record_usage(user=request.user, app=ds.app, action="datasource_sql", provider="llm" if model != "local-sql-template" else "local", model=model, prompt=question, response=sql)
    return Response({"sql": sql, "model": model, "tables": len(tables)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def translate_content(request):
    app_id = request.data.get("app_id")
    data = request.data.get("data")
    target_lang = str(request.data.get("target_lang") or "en").strip()
    if not app_id or not isinstance(data, dict):
        raise ValidationError({"detail": "app_id 和 data 必填"})
    if len(json.dumps(data, ensure_ascii=False)) > 60_000:
        raise ValidationError({"detail": "内容过长，暂不支持翻译"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    provider = "local"
    model_name = "local-noop"
    warnings: list[str] = []
    try:
        if is_configured():
            translated, model_name = llm_translate(app.name, data, target_lang)
            provider = "llm"
        else:
            translated = local_translate(data, target_lang)
            warnings.append("未配置 AI Provider，无法执行真实翻译。")
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"翻译失败：{exc}")
        translated = local_translate(data, target_lang)
        provider = "local-fallback"
    record_usage(user=request.user, app=app, action="translate_content", provider=provider, model=model_name, prompt=json.dumps(data, ensure_ascii=False), response=json.dumps(translated, ensure_ascii=False), error="; ".join(warnings))
    return Response({"data": translated, "provider": provider, "warnings": warnings, "target_lang": target_lang})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def content_batch(request):
    app_id = request.data.get("app_id")
    model_id = request.data.get("model_id")
    prompt = str(request.data.get("prompt") or "").strip()
    try:
        count = min(5, max(1, int(request.data.get("count") or 3)))
    except (TypeError, ValueError):
        count = 3
    if not app_id or not model_id:
        raise ValidationError({"detail": "app_id 和 model_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请填写内容主题"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    model = DataModel.objects.filter(app=app, id=int(model_id)).first()
    if model is None:
        raise ValidationError({"detail": "数据模型不存在"})
    fields = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    key = f"ai_content_batch:{request.user.id}"
    calls = int(cache.get(key) or 0)
    if calls >= 10:
        raise ValidationError({"detail": "本小时批量内容次数已达上限"})
    cache.set(key, calls + 1, 3600)
    drafts = []
    provider = "local"
    model_name = "local-content-template"
    warnings: list[str] = []
    if is_configured():
        provider = "llm"
        model_name = chat_config_model_name()
        angles = ["背景与现状", "关键变化", "用户影响", "行业观察", "后续展望"]
        for index in range(count):
            try:
                draft, model_name = call_llm_content(app.name, f"{prompt}（角度：{angles[index % len(angles)]}）", fields)
                drafts.append(draft)
            except ValidationError as exc:
                warnings.append(str(exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail))
                drafts.extend(local_batch(prompt, fields, count - len(drafts)))
                provider = "local-fallback"
                break
    else:
        drafts = local_batch(prompt, fields, count)
        warnings.append("未配置 AI Provider，当前使用本地内容模板。")
    record_usage(user=request.user, app=app, action="content_batch", provider=provider, model=model_name, prompt=prompt, response=json.dumps(drafts, ensure_ascii=False), success=bool(drafts), error="; ".join(warnings))
    return Response({"drafts": drafts, "provider": provider, "model": model_name, "warnings": warnings})


def chat_config_model_name() -> str:
    from ai.providers import chat_config

    return chat_config()["model"]


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def model_draft(request):
    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述业务数据"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    key = f"ai_model_draft:{request.user.id}"
    count = int(cache.get(key) or 0)
    if count >= 30:
        raise ValidationError({"detail": "本小时 AI 建模次数已达上限"})
    cache.set(key, count + 1, 3600)
    provider = "local"
    model_name = "local-model-template"
    warnings: list[str] = []
    try:
        if is_configured():
            draft, model_name = call_llm_model(app.name, prompt)
            provider = "llm"
        else:
            draft = local_model_draft(prompt)
            warnings.append("未配置 AI Provider，当前使用本地字段模板。")
        draft = normalize_model_draft(draft, app)
    except ValidationError as exc:
        detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail
        warnings.append(str(detail))
        draft = normalize_model_draft(local_model_draft(prompt), app)
        provider = "local-fallback"
    record_usage(user=request.user, app=app, action="model_draft", provider=provider, model=model_name, prompt=prompt, response=json.dumps(draft, ensure_ascii=False), success=bool(draft), error="; ".join(warnings))
    return Response({
        "draft": draft,
        "provider": provider,
        "model": model_name,
        "warnings": warnings,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def site_plan(request):
    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述你想要的站点"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    from pages.models import Page

    models = list(DataModel.objects.filter(app=app).values("id", "name", "fields"))
    existing = set(Page.objects.filter(app=app).values_list("path", flat=True))
    site_meta = None
    warnings: list[str] = []
    if is_configured():
        try:
            site_meta = call_llm_site_meta(app.name, prompt)
        except ValidationError as exc:
            detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail
            warnings.append(f"AI 站点规划失败，已使用模板：{detail}")
    plan = build_site_plan(app.name, prompt, models, existing, site_meta)
    plan["warnings"] = warnings + list(plan.get("warnings") or [])
    for page in plan["pages"]:
        page["schema"] = validate_schema(polish_schema(page["schema"], prompt, app.name), app.name)
    record_usage(user=request.user, app=app, action="site_plan", provider="llm" if site_meta else "local", model="site-plan", prompt=prompt, response=json.dumps(plan, ensure_ascii=False), error="; ".join(warnings))
    return Response(plan)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def edit_page(request):
    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    source = request.data.get("schema")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述修改要求"})
    if not isinstance(source, dict):
        raise ValidationError({"detail": "schema 必须是页面对象"})
    if len(prompt) > 3000:
        raise ValidationError({"detail": "描述过长，最多 3000 字"})
    if len(json.dumps(source, ensure_ascii=False)) > 300_000:
        raise ValidationError({"detail": "页面过大，暂不支持 AI 修改"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")

    key = f"ai_page_edit:{request.user.id}"
    count = int(cache.get(key) or 0)
    if count >= 40:
        raise ValidationError({"detail": "本小时 AI 修改次数已达上限，请稍后再试"})
    cache.set(key, count + 1, 3600)

    warnings: list[str] = []
    provider = "local"
    model_name = "local-edit"
    changed = False
    result = source
    try:
        if is_configured():
            candidate, model_name = call_llm_edit(app.name, prompt, source)
            candidate = validate_schema(polish_schema(candidate, prompt, app.name), app.name)
            result = candidate
            provider = "llm"
            changed = True
        else:
            result, changed, local_warnings = local_edit(source, prompt)
            warnings.extend(local_warnings)
            result = validate_schema(polish_schema(result, prompt, app.name), app.name)
    except ValidationError as exc:
        detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail
        warnings.append(f"模型修改失败，已回退到本地编辑：{detail}")
        result, changed, local_warnings = local_edit(source, prompt)
        warnings.extend(local_warnings)
        result = validate_schema(polish_schema(result, prompt, app.name), app.name)
        provider = "local-fallback"

    record_usage(user=request.user, app=app, action="page_edit", provider=provider, model=model_name, prompt=prompt, response=json.dumps(result, ensure_ascii=False), success=changed, error="; ".join(warnings))
    return Response({
        "schema": result,
        "provider": provider,
        "model": model_name,
        "changed": changed,
        "warnings": warnings,
        "summary": {
            "title": (result.get("meta") or {}).get("title") or "",
            "nodes": len(result.get("nodes") or {}),
        },
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def generate_page(request):
    app_id = request.data.get("app_id")
    prompt = str(request.data.get("prompt") or "").strip()
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    if not prompt:
        raise ValidationError({"detail": "请描述你想要的页面"})
    if len(prompt) > 3000:
        raise ValidationError({"detail": "描述过长，最多 3000 字"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")

    # 简单的按用户限流，避免误触造成大量模型调用。
    key = f"ai_page_gen:{request.user.id}"
    count = int(cache.get(key) or 0)
    if count >= 30:
        raise ValidationError({"detail": "本小时 AI 生成次数已达上限，请稍后再试"})
    cache.set(key, count + 1, 3600)

    models = list(DataModel.objects.filter(app=app).values("id", "name", "fields"))
    warnings: list[str] = []
    provider = "local"
    model_name = "local-template"
    try:
        if is_configured():
            schema, model_name = call_llm(app.name, prompt, models)
            provider = "llm"
            schema = validate_schema(polish_schema(schema, prompt, app.name), app.name)
        else:
            schema = validate_schema(polish_schema(local_generate(app.name, prompt, models), prompt, app.name), app.name)
            warnings.append("未配置 AI Provider，当前使用本地模板生成；配置后可切换到模型生成。")
    except ValidationError as exc:
        detail = exc.detail.get("detail") if isinstance(exc.detail, dict) else exc.detail
        warnings.append(str(detail))
        schema = validate_schema(polish_schema(local_generate(app.name, prompt, models), prompt, app.name), app.name)
        provider = "local-fallback"

    record_usage(user=request.user, app=app, action="page_generate", provider=provider, model=model_name, prompt=prompt, response=json.dumps(schema, ensure_ascii=False), success=True, error="; ".join(warnings))
    return Response({
        "schema": schema,
        "provider": provider,
        "model": model_name,
        "warnings": warnings,
        "summary": {
            "title": (schema.get("meta") or {}).get("title") or "",
            "nodes": len(schema.get("nodes") or {}),
        },
    })


# ---------------------------------------------------------------- 截图级视觉评审

def _ai_rate_limit(user, action: str, limit: int = 30, ttl: int = 3600) -> None:
    key = f"ai_rl:{action}:{getattr(user, 'id', 0)}"
    count = int(cache.get(key) or 0)
    if count >= limit:
        raise ValidationError({"detail": f"{action} 调用次数已达上限，请稍后再试"})
    cache.set(key, count + 1, ttl)


def _load_page_schema(app, page_id, schema):
    if isinstance(schema, dict) and schema.get("nodes"):
        return schema, ""
    if page_id:
        from pages.models import Page

        page = Page.objects.filter(app=app, id=page_id).first()
        if page is not None:
            return page.schema or {}, page.name
    return schema if isinstance(schema, dict) else {}, ""


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def visual_review(request):
    """POST /api/ai/design/visual-review/ {app_id, image, schema?, page_id?, page_name?, prompt?}"""
    app_id = request.data.get("app_id")
    image = request.data.get("image")
    if not app_id or not image:
        raise ValidationError({"detail": "app_id 与 image（data URL 或 base64）必填"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "viewer")
    _ai_rate_limit(request.user, "visual_review", limit=20)
    schema, page_name = _load_page_schema(app, request.data.get("page_id"), request.data.get("schema"))
    page_name = str(request.data.get("page_name") or page_name or "")
    prompt = str(request.data.get("prompt") or "")[:1000]
    try:
        result = review_screenshot(image, schema=schema, page_name=page_name, prompt=prompt)
    except ValueError as exc:
        raise ValidationError({"detail": str(exc)}) from exc
    record_usage(
        user=request.user, app=app, action="visual_review",
        provider=result.get("mode") or "heuristic",
        model=result.get("model") or "pillow-metrics",
        prompt=f"image_chars={len(str(image))}; {prompt}",
        response=json.dumps({"score": result.get("score"), "issues": len(result.get("issues") or [])}, ensure_ascii=False),
        error="; ".join(result.get("warnings") or []),
    )
    return Response({**result, "page_name": page_name})


# ---------------------------------------------------------------- AI 多轮 Agent

def _conversation_or_404(request, pk: int) -> AiConversation:
    from django.shortcuts import get_object_or_404

    conversation = get_object_or_404(
        AiConversation.objects.select_related("app", "user"), pk=pk
    )
    require_app_role(request.user, conversation.app, "viewer")
    return conversation


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def agent_conversations(request):
    """GET/POST /api/ai/agent/conversations/"""
    if request.method == "GET":
        app_id = request.query_params.get("app_id")
        if not app_id:
            raise ValidationError({"detail": "app_id 必填"})
        app = get_app(int(app_id))
        require_app_role(request.user, app, "viewer")
        qs = AiConversation.objects.filter(app=app, user=request.user).order_by("-updated_at")
        if request.query_params.get("all") in ("1", "true", "yes") and is_platform_admin_full(request.user):
            qs = AiConversation.objects.filter(app=app).order_by("-updated_at")
        return Response({"count": qs.count(), "results": [conversation_payload(c) for c in qs[:50]]})

    app_id = request.data.get("app_id")
    if not app_id:
        raise ValidationError({"detail": "app_id 必填"})
    app = get_app(int(app_id))
    require_app_role(request.user, app, "editor")
    page_id = request.data.get("page_id")
    if page_id:
        from pages.models import Page

        if not Page.objects.filter(app=app, id=page_id).exists():
            raise ValidationError({"detail": "页面不存在"})
    conversation = AiConversation.objects.create(
        app=app, user=request.user, page_id=page_id or None,
        title=str(request.data.get("title") or "")[:200],
        context={"page_id": page_id} if page_id else {},
    )
    return Response(conversation_payload(conversation, with_messages=True), status=201)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def agent_conversation_detail(request, pk: int):
    conversation = _conversation_or_404(request, pk)
    if request.method == "GET":
        return Response(conversation_payload(conversation, with_messages=True))
    if not (conversation.user_id == request.user.id or is_platform_admin_full(request.user)):
        raise ValidationError({"detail": "只能修改自己的会话"})
    if request.method == "DELETE":
        conversation.delete()
        return Response(status=204)
    if "title" in request.data:
        conversation.title = str(request.data.get("title") or "")[:200]
    if "page_id" in request.data:
        conversation.page_id = request.data.get("page_id") or None
    conversation.save()
    return Response(conversation_payload(conversation, with_messages=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_message(request, pk: int):
    """POST /api/ai/agent/conversations/{id}/messages/ {message}"""
    conversation = _conversation_or_404(request, pk)
    require_app_role(request.user, conversation.app, "editor")
    if conversation.user_id not in (None, request.user.id) and not is_platform_admin_full(request.user):
        raise ValidationError({"detail": "只能在自己的会话中对话"})
    text = str(request.data.get("message") or "").strip()
    if not text:
        raise ValidationError({"detail": "message 不能为空"})
    if len(text) > 4000:
        raise ValidationError({"detail": "消息过长（最多 4000 字）"})
    _ai_rate_limit(request.user, "agent", limit=120)
    result = run_turn(conversation, text, request.user)
    provider = result["assistant_message"].get("provider") or "local"
    record_usage(
        user=request.user, app=conversation.app, action="agent_chat",
        provider=provider, model=result["assistant_message"].get("model") or "local-agent",
        prompt=text, response=result["assistant_message"].get("content") or "",
    )
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_message_stream(request, pk: int):
    """POST /api/ai/agent/conversations/{id}/messages/stream/ — SSE 流式输出。"""
    from django.db import close_old_connections

    conversation = _conversation_or_404(request, pk)
    require_app_role(request.user, conversation.app, "editor")
    if conversation.user_id not in (None, request.user.id) and not is_platform_admin_full(request.user):
        raise ValidationError({"detail": "只能在自己的会话中对话"})
    text = str(request.data.get("message") or "").strip()
    if not text:
        raise ValidationError({"detail": "message 不能为空"})
    if len(text) > 4000:
        raise ValidationError({"detail": "消息过长（最多 4000 字）"})
    _ai_rate_limit(request.user, "agent", limit=120)
    stop_key = f"agent_stop:{conversation.id}"
    cache.delete(stop_key)

    def event(name: str, payload: dict) -> str:
        return "data: " + json.dumps(
            {"type": name, **payload}, ensure_ascii=False, cls=DjangoJSONEncoder
        ) + "\n\n"

    def stream():
        events: queue.Queue = queue.Queue()

        def worker():
            try:
                result = run_turn(
                    conversation,
                    text,
                    request.user,
                    on_event=events.put,
                    on_token=lambda value: events.put({"type": "delta", "text": value}),
                    should_stop=lambda: bool(cache.get(stop_key)),
                )
                events.put({"type": "finished", "result": result})
            except Exception as exc:  # noqa: BLE001
                events.put({"type": "worker_error", "message": f"{type(exc).__name__}: {exc}"})
            finally:
                close_old_connections()

        threading.Thread(target=worker, daemon=True, name=f"agent-stream-{conversation.id}").start()
        try:
            yield event("status", {"text": "正在分析页面与工具调用…"})
            result = None
            while True:
                item = events.get()
                if item.get("type") == "worker_error":
                    yield event("error", {"message": item.get("message") or "AI 助手请求失败"})
                    return
                if item.get("type") == "finished":
                    result = item.get("result") or {}
                    break
                yield event(str(item.get("type") or "status"), {
                    key: value for key, value in item.items() if key not in ("type",)
                })
            assistant = result.get("assistant_message") or {}
            content = str(assistant.get("content") or "")
            if result.get("stopped"):
                yield event("status", {"text": "已停止生成"})
            elif not result.get("streamed"):
                for index in range(0, len(content), 16):
                    yield event("delta", {"text": content[index:index + 16]})
                    time.sleep(0.012)
            yield event("done", {"assistant": assistant, "stopped": bool(result.get("stopped"))})
            provider = assistant.get("provider") or "local"
            record_usage(
                user=request.user,
                app=conversation.app,
                action="agent_chat",
                provider=provider,
                model=assistant.get("model") or "local-agent",
                prompt=text,
                response=content,
            )
        except Exception as exc:  # noqa: BLE001
            yield event("error", {"message": f"{type(exc).__name__}: {exc}"})
        finally:
            close_old_connections()

    response = StreamingHttpResponse(stream(), content_type="text/event-stream; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_stop(request, pk: int):
    """POST /api/ai/agent/conversations/{id}/stop/ — 请求停止当前流式回答。"""
    conversation = _conversation_or_404(request, pk)
    require_app_role(request.user, conversation.app, "editor")
    if conversation.user_id not in (None, request.user.id) and not is_platform_admin_full(request.user):
        raise ValidationError({"detail": "只能停止自己的会话"})
    cache.set(f"agent_stop:{conversation.id}", 1, 120)
    return Response({"ok": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_undo(request, pk: int):
    """POST /api/ai/agent/conversations/{id}/undo/ {message_id} — 撤销上次应用。"""
    from django.shortcuts import get_object_or_404
    from ai.agent import undo_proposal
    from ai.models import AiMessage

    conversation = _conversation_or_404(request, pk)
    require_app_role(request.user, conversation.app, "editor")
    message_id = request.data.get("message_id")
    message = get_object_or_404(AiMessage, conversation=conversation, id=message_id)
    result = undo_proposal(conversation, message, request.user)
    return Response({**result, "conversation": conversation_payload(conversation)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_apply(request, pk: int):
    """POST /api/ai/agent/conversations/{id}/apply/ {message_id}"""
    from django.shortcuts import get_object_or_404

    conversation = _conversation_or_404(request, pk)
    require_app_role(request.user, conversation.app, "editor")
    message_id = request.data.get("message_id")
    message = get_object_or_404(AiMessage, conversation=conversation, id=message_id)
    result = apply_proposal(conversation, message, request.user)
    return Response({
        **result,
        "conversation": conversation_payload(conversation),
    })


# ---------------------------------------------------------------- AI 全自动建站

def _build_options(raw) -> dict:
    options = dict(DEFAULT_OPTIONS)
    if isinstance(raw, dict):
        for key in DEFAULT_OPTIONS:
            if key not in raw:
                continue
            if key == "source":
                options[key] = raw[key] if isinstance(raw[key], dict) else None
            elif key == "sources":
                options[key] = raw[key] if isinstance(raw[key], list) else None
            elif key == "pages_override":
                options[key] = raw[key] if isinstance(raw[key], list) else None
            else:
                options[key] = bool(raw[key])
    return options


def _source_preview_pages(options: dict, blueprint: dict) -> list[dict]:
    """数据源模式的前置页面计划：不连库，仅根据表名/字段名生成计划。"""
    import re

    raw = options.get("sources")
    if not isinstance(raw, list) or not raw:
        raw = [options.get("source")] if isinstance(options.get("source"), dict) else []
    tables = []
    for item in raw[:6]:
        if not isinstance(item, dict) or not str(item.get("table") or "").strip():
            continue
        table = str(item["table"]).strip()
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", table.lower()).strip("-")[:40] or "data"
        tables.append({
            "table": table,
            "label": str(item.get("label") or table),
            "slug": slug,
        })
    if not tables:
        return [dict(page, enabled=True) for page in blueprint.get("pages") or []]
    pages = [{"kind": "home", "name": "首页", "path": "home", "title": blueprint["site"]["name"], "enabled": True}]
    for table in tables:
        pages.append({"kind": "list", "name": table["label"], "path": f"data/{table['slug']}",
                      "title": table["label"], "enabled": True, "bound": True})
        pages.append({"kind": "detail", "name": f"{table['label']}详情", "path": f"data/{table['slug']}/:id",
                      "title": f"{table['label']}详情", "enabled": True, "bound": True})
    if len(tables) > 1:
        pages.append({"kind": "overview", "name": "数据总览", "path": "overview",
                      "title": "数据总览", "enabled": True})
    pages.append({"kind": "live", "name": "实时数据", "path": "live", "title": "实时数据", "enabled": True})
    pages.append({"kind": "search", "name": "站内搜索", "path": "search", "title": "站内搜索", "enabled": True})
    pages.append({"kind": "about", "name": "关于我们", "path": "about", "title": "关于我们", "enabled": True})
    for spec in blueprint.get("pages") or []:
        if spec.get("kind") in ("dashboard", "form", "custom", "landing", "contact", "pricing", "docs"):
            pages.append({**spec, "enabled": True})
    return pages


def _infer_page_kind(page, schema: dict) -> str:
    meta = (schema or {}).get("meta") or {}
    if meta.get("aiKind"):
        return str(meta["aiKind"])
    path = str(page.path or "")
    types = {node.get("type") for node in ((schema or {}).get("nodes") or {}).values() if isinstance(node, dict)}
    if path == "home":
        return "home"
    if "auto-form" in types:
        return "form"
    if "report-table" in types or "wp-statcard" in types:
        return "dashboard"
    if ":" in path:
        return "detail"
    if path in ("about", "contact", "pricing", "docs", "search"):
        return path
    if "content-list" in types or "article-detail" in types:
        return "list"
    return "custom"


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def page_regenerate(request, pk: int):
    """POST /api/ai/pages/{id}/regenerate/ — 用 AI 重新生成单个页面。"""
    from ai.autobuild import (
        THEMES, build_about_schema, build_contact_schema, build_detail_schema,
        build_docs_schema, build_home_schema, build_list_schema, build_pricing_schema,
        build_search_schema, local_blueprint,
    )
    from ai.pagelayout import generate_layout
    from datamodels.models import DataModel
    from django.shortcuts import get_object_or_404
    from pages.models import Page
    from pages.services import publish_page, save_draft, snapshot_page
    from releases.services import schedule_release_for_app

    page = get_object_or_404(Page, pk=pk)
    require_app_role(request.user, page.app, "editor")
    app = page.app
    blueprint = None
    job = AiBuildJob.objects.filter(app=app, status="success").order_by("-id").first()
    if job and isinstance(job.blueprint, dict):
        blueprint = job.blueprint
    else:
        blueprint = local_blueprint(app.description or app.name)
    site = blueprint.get("site") or {"name": app.name, "tagline": app.name, "description": app.description or "",
                                     "theme": "light", "highlights": []}
    about = blueprint.get("about") or {"title": f"关于{app.name}", "sections": []}
    content = blueprint.get("content") or {"label": "内容"}
    models = list(DataModel.objects.filter(app=app).order_by("id"))
    if not models:
        raise ValidationError({"detail": "应用还没有数据模型，无法重新生成页面"})
    model = models[0]
    kind = str(request.data.get("kind") or "").strip() or _infer_page_kind(page, page.schema or {})
    if kind == "live":
        raise ValidationError({"detail": "实时数据页依赖数据源绑定，请用 AI 助手重新绑定"})
    if kind not in ("home", "list", "detail", "about", "contact", "pricing", "docs", "search",
                    "dashboard", "form", "custom", "landing"):
        kind = "custom"

    other_pages = list(Page.objects.filter(app=app).order_by("id"))
    nav_links = [
        {"label": item.name, "path": item.path}
        for item in other_pages
        if ":" not in item.path and item.path != page.path
    ][:10]
    nav_links.insert(0, {"label": "首页", "path": "home"})
    details = [item for item in other_pages if ":" in item.path]
    first_detail = details[0].path if details else "article/:id"
    lists = [item for item in other_pages if ":" not in item.path and item.path not in ("home", "about", "contact", "search")]
    back_path = lists[0].path if lists else "news"
    ctx = {
        "theme": site.get("theme") or "light",
        "site_name": site.get("name") or app.name,
        "tagline": site.get("tagline") or app.name,
        "description": site.get("description") or app.description or "",
        "label": content.get("label") or "内容",
        "model_id": model.id,
        "highlights": site.get("highlights") or [],
        "about_title": about.get("title") or f"关于{app.name}",
        "about_sections": about.get("sections") or [],
        "about_intro": ((about.get("sections") or [{}])[0].get("body") or "")[:180],
        "nav_links": nav_links,
        "contact": blueprint.get("contact") or {},
        "pricing": blueprint.get("pricing") or {},
        "docs": blueprint.get("docs") or {},
        "site_prompt": job.prompt if job else (app.description or app.name),
        "use_llm": True,
    }
    page_spec = {
        "kind": kind, "name": page.name, "path": page.path,
        "title": (page.schema or {}).get("meta", {}).get("title") or page.name,
        "description": (page.schema or {}).get("meta", {}).get("description") or app.description or "",
        "brief": str(request.data.get("prompt") or "")[:300],
    }
    provider = "template"
    try:
        if kind in ("dashboard", "form", "custom", "landing"):
            palette = {**THEMES[ctx["theme"]], "dark": ctx["theme"] == "dark"}
            schema, provider = generate_layout(ctx, page_spec, kind, models, palette, nav_links)
        elif kind == "home":
            schema = build_home_schema(ctx)
        elif kind == "list":
            ctx["list_href"] = first_detail.replace(":id", "{id}")
            schema = build_list_schema(ctx)
            schema["nodes"]["headerTitle"]["props"]["content"] = page_spec["title"]
            schema["nodes"]["list"]["props"]["hrefPattern"] = ctx["list_href"]
        elif kind == "detail":
            schema = build_detail_schema(ctx)
            schema["nodes"]["article"]["props"].update({
                "articlePath": page.path.replace(":id", "{id}"), "backPath": back_path,
            })
        elif kind == "about":
            schema = build_about_schema(ctx)
        elif kind == "contact":
            schema = build_contact_schema(ctx)
        elif kind == "pricing":
            schema = build_pricing_schema(ctx)
        elif kind == "docs":
            schema = build_docs_schema(ctx)
        elif kind == "search":
            schema = build_search_schema(ctx)
        else:
            schema = build_home_schema(ctx)
        nav = (schema.get("nodes") or {}).get("nav")
        if nav:
            nav.setdefault("props", {})["links"] = nav_links
        nav_links_all = [{"label": item.name, "path": item.path} for item in other_pages if ":" not in item.path][:10]
        if not any(link["path"] == "search" for link in nav_links_all):
            nav_links_all.append({"label": "搜索", "path": "search"})
        if nav:
            nav["props"]["links"] = nav_links_all
        if kind not in ("dashboard", "form", "custom", "landing"):
            schema.setdefault("meta", {})["title"] = page_spec["title"]
            schema["meta"]["description"] = page_spec["description"]
        snapshot_page(page, request.user, "AI 重新生成前快照")
        page, errors, warnings = save_draft(page, schema, request.user)
        page.schema.setdefault("meta", {})["aiKind"] = kind
        page.save(update_fields=["schema", "updated_at"])
        version = None
        if bool(request.data.get("publish")):
            version, pub_errors, pub_warnings = publish_page(page, request.user, "AI 单页重新生成")
            if version is None:
                raise ValidationError({"detail": f"发布失败：{pub_errors or pub_warnings}"})
            schedule_release_for_app(app, changelog=f"AI 重新生成 {page.path}", trigger="ai_regenerate", user=request.user)
        else:
            page.status = "draft"
            page.save(update_fields=["status", "updated_at"])
        return Response({
            "ok": True, "page_id": page.id, "path": page.path, "kind": kind,
            "provider": provider, "version": version.version if version else None,
            "warnings": list(errors) + list(warnings),
        })
    except ValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": f"重新生成失败：{type(exc).__name__}: {exc}"}) from exc


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def datasource_inspect(request):
    """POST /api/ai/datasources/inspect/ — 建站前测试连接并读取表/字段，不落库。"""
    from datasources.executor import list_external_schema

    ds_type = str(request.data.get("type") or "postgres").strip().lower()
    if ds_type not in ("postgres", "mysql", "sqlserver"):
        raise ValidationError({"detail": "仅支持 PostgreSQL/MySQL/SQL Server"})
    database = str(request.data.get("database") or "").strip()
    if not database:
        raise ValidationError({"detail": "database 必填"})
    _ai_rate_limit(request.user, "datasource_inspect", limit=30, ttl=3600)
    cfg = {
        "host": str(request.data.get("host") or "127.0.0.1").strip(),
        "port": int(request.data.get("port") or 5432),
        "database": database,
        "username": str(request.data.get("username") or "").strip(),
        "password": str(request.data.get("password") or ""),
        "schema": str(request.data.get("schema") or "public").strip() or "public",
        "ssl": str(request.data.get("ssl") or "prefer"),
        "timeout": 15,
        "max_rows": 5,
    }
    try:
        tables = list_external_schema(ds_type, cfg)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": f"连接失败：{type(exc).__name__}: {exc}"}) from exc
    return Response({
        "type": ds_type,
        "database": database,
        "count": len(tables),
        "tables": [
            {
                "schema": table.get("schema") or cfg["schema"],
                "name": table.get("name"),
                "columns": [
                    {"name": col.get("name"), "type": col.get("type"), "nullable": col.get("nullable")}
                    for col in (table.get("columns") or [])[:40]
                ],
            }
            for table in tables[:80]
        ],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def page_diff(request, pk: int):
    """GET /api/ai/pages/{id}/diff/ — 当前草稿与最近快照的节点级差异。"""
    from django.shortcuts import get_object_or_404
    from pages.models import Page, PageVersion

    page = get_object_or_404(Page, pk=pk)
    require_app_role(request.user, page.app, "viewer")
    version = None
    if request.query_params.get("version"):
        version = PageVersion.objects.filter(page=page, version=int(request.query_params["version"])).first()
    if version is None:
        version = PageVersion.objects.filter(page=page).order_by("-version").first()
    old_schema = (version.schema if version else {}) or {}
    new_schema = page.schema or {}
    old_nodes = old_schema.get("nodes") or {}
    new_nodes = new_schema.get("nodes") or {}

    def brief(value):
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = str(value)
        return text[:160]

    changes = []
    added = removed = changed_count = 0
    for node_id in sorted(set(old_nodes) | set(new_nodes)):
        before = old_nodes.get(node_id)
        after = new_nodes.get(node_id)
        if before is None:
            added += 1
            changes.append({"id": node_id, "type": (after or {}).get("type"), "status": "added", "changes": []})
            continue
        if after is None:
            removed += 1
            changes.append({"id": node_id, "type": (before or {}).get("type"), "status": "removed", "changes": []})
            continue
        if not isinstance(before, dict) or not isinstance(after, dict):
            continue
        fields = []
        for key in ("type", "componentVersion"):
            if before.get(key) != after.get(key):
                fields.append({"field": key, "before": brief(before.get(key)), "after": brief(after.get(key))})
        before_props = before.get("props") or {}
        after_props = after.get("props") or {}
        for key in sorted(set(before_props) | set(after_props)):
            if before_props.get(key) != after_props.get(key):
                fields.append({"field": f"props.{key}", "before": brief(before_props.get(key)),
                               "after": brief(after_props.get(key))})
        before_style = before.get("style") or {}
        after_style = after.get("style") or {}
        for key in sorted(set(before_style) | set(after_style)):
            if before_style.get(key) != after_style.get(key):
                fields.append({"field": f"style.{key}", "before": brief(before_style.get(key)),
                               "after": brief(after_style.get(key))})
        if (before.get("children") or []) != (after.get("children") or []):
            fields.append({"field": "children", "before": brief(before.get("children")),
                           "after": brief(after.get("children"))})
        if fields:
            changed_count += 1
            changes.append({"id": node_id, "type": after.get("type"), "status": "changed", "changes": fields[:20]})

    before_meta = old_schema.get("meta") or {}
    after_meta = new_schema.get("meta") or {}
    meta_changes = []
    for key in sorted(set(before_meta) | set(after_meta)):
        if before_meta.get(key) != after_meta.get(key):
            meta_changes.append({"field": key, "before": brief(before_meta.get(key)),
                                 "after": brief(after_meta.get(key))})
    return Response({
        "page_id": page.id,
        "version": version.version if version else None,
        "same": not changes and not meta_changes,
        "summary": {"added": added, "removed": removed, "changed": changed_count,
                    "meta": len(meta_changes), "total": added + removed + changed_count + len(meta_changes)},
        "nodes": changes[:80],
        "meta": meta_changes[:20],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def datasources_existing(request):
    """GET /api/ai/datasources/existing/ — 当前用户可访问的已有数据源（不返回密码）。"""
    from core.permissions import get_app_role
    from datasources.executor import decode_secrets
    from datasources.models import Datasource

    rows = []
    for ds in Datasource.objects.select_related("app").order_by("-updated_at")[:200]:
        if not is_platform_admin_full(request.user) and get_app_role(request.user, ds.app) is None:
            continue
        cfg = decode_secrets(ds.config or {})
        rows.append({
            "id": ds.id, "name": ds.name, "type": ds.type,
            "app_id": ds.app_id, "app_name": ds.app.name,
            "host": cfg.get("host") or "", "port": cfg.get("port") or 5432,
            "database": cfg.get("database") or "", "username": cfg.get("username") or "",
            "schema": cfg.get("schema") or "public",
        })
    return Response({"count": len(rows), "results": rows[:80]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def datasource_inspect_existing(request):
    """POST /api/ai/datasources/inspect-existing/ — 用已保存的数据源读取表/字段。"""
    from core.permissions import get_app_role
    from datasources.executor import decode_secrets, list_external_schema
    from datasources.models import Datasource

    ds = Datasource.objects.filter(id=request.data.get("datasource_id")).first()
    if ds is None:
        raise ValidationError({"detail": "数据源不存在"})
    if not is_platform_admin_full(request.user) and get_app_role(request.user, ds.app) is None:
        raise ValidationError({"detail": "没有该数据源的访问权限"})
    _ai_rate_limit(request.user, "datasource_inspect", limit=30, ttl=3600)
    cfg = decode_secrets(ds.config or {})
    try:
        tables = list_external_schema(ds.type, cfg)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError({"detail": f"连接失败：{type(exc).__name__}: {exc}"}) from exc
    return Response({
        "type": ds.type, "database": cfg.get("database") or "", "count": len(tables),
        "tables": [
            {
                "schema": table.get("schema") or cfg.get("schema") or "public",
                "name": table.get("name"),
                "columns": [
                    {"name": col.get("name"), "type": col.get("type"), "nullable": col.get("nullable")}
                    for col in (table.get("columns") or [])[:40]
                ],
            }
            for table in tables[:80]
        ],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def autobuild_plan(request):
    """POST /api/ai/autobuild/plan/ — 建站前预览页面计划，不创建应用/任务。"""
    prompt = str(request.data.get("prompt") or "").strip()
    if not prompt:
        raise ValidationError({"detail": "请描述你想建的站点"})
    if len(prompt) > 2000:
        raise ValidationError({"detail": "描述过长（最多 2000 字）"})
    _ai_rate_limit(request.user, "autobuild_plan", limit=20, ttl=3600)
    options = _build_options(request.data.get("options"))
    blueprint = provider = model = None
    warnings = []
    if options.get("use_dsh", True):
        try:
            from ai.dsh import build_blueprint as dsh_build_blueprint, configured as dsh_configured

            if dsh_configured():
                result = dsh_build_blueprint(prompt, options)
                blueprint, provider, model, warnings = (
                    result["blueprint"], result["provider"], result["model"], result["warnings"]
                )
        except Exception as exc:  # noqa: BLE001
            warnings = [f"DSH 不可用，已回退内置蓝图：{type(exc).__name__}: {exc}"]
    if blueprint is None:
        blueprint, provider, model, warnings = generate_blueprint(
            prompt, use_llm=bool(options.get("use_llm", True)),
        )
    source_mode = bool(options.get("source") or options.get("sources"))
    pages = _source_preview_pages(options, blueprint) if source_mode else [
        {**page, "enabled": True} for page in (blueprint.get("pages") or [])
    ]
    return Response({
        "pages": pages,
        "source_mode": source_mode,
        "site": blueprint.get("site") or {},
        "provider": provider,
        "model": model,
        "warnings": warnings,
    })


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def autobuild_jobs(request):
    """GET /api/ai/autobuild/ 列表；POST 启动全自动建站。"""
    if request.method == "GET":
        qs = AiBuildJob.objects.filter(user=request.user).order_by("-created_at")
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(status=status_f)
        return Response({
            "count": qs.count(),
            "results": [job_payload(job) for job in qs[:20]],
        })

    prompt = str(request.data.get("prompt") or "").strip()
    options = _build_options(request.data.get("options"))
    source = options.get("source")
    sources = options.get("sources")
    if isinstance(source, dict) and source:
        if not str(source.get("table") or "").strip() or (
            not source.get("datasource_id") and not str(source.get("database") or "").strip()
        ):
            raise ValidationError({"detail": "PostgreSQL 数据源需要 database 与 table"})
        source["password"] = encrypt_secret(str(source.get("password") or ""))
        source["table"] = str(source.get("table")).strip()
        source["schema"] = str(source.get("schema") or "public").strip() or "public"
        try:
            source["limit"] = min(500, max(1, int(source.get("limit") or 200)))
        except (TypeError, ValueError):
            source["limit"] = 200
        if not prompt:
            prompt = f"根据 PostgreSQL 表 {source['table']} 自动生成数据展示站"
    if isinstance(sources, list) and sources:
        cleaned = []
        for item in sources[:6]:
            if not isinstance(item, dict):
                continue
            if not str(item.get("table") or "").strip() or (
                not item.get("datasource_id") and not str(item.get("database") or "").strip()
            ):
                raise ValidationError({"detail": "每个 PostgreSQL 数据源都需要 database 与 table"})
            item = dict(item)
            item["password"] = encrypt_secret(str(item.get("password") or ""))
            item["table"] = str(item.get("table")).strip()
            item["schema"] = str(item.get("schema") or "public").strip() or "public"
            try:
                item["limit"] = min(500, max(1, int(item.get("limit") or 200)))
            except (TypeError, ValueError):
                item["limit"] = 200
            cleaned.append(item)
        options["sources"] = cleaned
        if cleaned and not prompt:
            prompt = f"根据 PostgreSQL 表 {cleaned[0]['table']} 自动生成多模型数据站"
    if not prompt:
        raise ValidationError({"detail": "请描述你想建的站点"})
    if len(prompt) > 2000:
        raise ValidationError({"detail": "描述过长（最多 2000 字）"})
    if AiBuildJob.objects.filter(user=request.user, status__in=("pending", "running")).exists():
        raise ValidationError({"detail": "已有建站任务在执行，请等待完成或取消后再试"})
    _ai_rate_limit(request.user, "autobuild", limit=5, ttl=3600)
    sync = bool(request.data.get("sync")) and is_platform_admin_full(request.user)
    job = AiBuildJob.objects.create(
        user=request.user, prompt=prompt, options=options, status="pending",
        steps=[{"key": key, "label": label, "status": "pending", "message": ""} for key, label in _autobuild_steps()],
    )
    start_job(job, sync=sync)
    job.refresh_from_db()
    return Response(job_payload(job), status=200 if sync else 202)


def _autobuild_steps():
    from ai.autobuild import STEPS

    return STEPS


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def autobuild_detail(request, pk: int):
    from django.shortcuts import get_object_or_404

    job = get_object_or_404(AiBuildJob.objects.select_related("app"), pk=pk)
    if job.user_id != request.user.id and not is_platform_admin_full(request.user):
        raise ValidationError({"detail": "只能查看自己的建站任务"})
    return Response(job_payload(job))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def autobuild_cancel(request, pk: int):
    from django.shortcuts import get_object_or_404

    job = get_object_or_404(AiBuildJob, pk=pk)
    if job.user_id != request.user.id and not is_platform_admin_full(request.user):
        raise ValidationError({"detail": "只能取消自己的建站任务"})
    if job.status in ("success", "failed", "cancelled"):
        return Response(job_payload(job))
    AiBuildJob.objects.filter(id=job.id).update(cancel_requested=True)
    if job.status == "pending":
        AiBuildJob.objects.filter(id=job.id).update(status="cancelled", finished_at=timezone.now())
    job.refresh_from_db()
    return Response(job_payload(job))
