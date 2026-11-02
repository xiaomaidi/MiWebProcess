"""模板中心：从模板或导出的应用 JSON 创建应用。"""
from __future__ import annotations

import re
from copy import deepcopy

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from appcore.models import (
    App, AppAuthConfig, AppMember, AppModule, AppTemplate, AppTemplateAccess, AppTemplateVersion,
    NotificationTemplate, ScheduledJob, WebhookEndpoint,
)
from appcore.modules import default_modules
from datamodels.models import DataModel, DataRecord
from datamodels.services import validate_fields_spec
from pages.models import Page
from workflow.models import WorkflowDefinition
from wp_utils import get_app, require_app_role

CODE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{1,63}$")


def _create_app(user, name: str, code: str, description: str, design_tokens: dict | None = None):
    name = str(name or "").strip()
    code = str(code or "").strip()
    if not name:
        raise ValidationError({"detail": "应用名称必填"})
    if not CODE_RE.match(code):
        raise ValidationError({"detail": "应用标识只能以字母开头，包含字母、数字、_、-"})
    if App.objects.filter(code=code).exists():
        raise ValidationError({"detail": f"应用标识 {code} 已存在"})
    app = App.objects.create(
        name=name,
        code=code,
        description=str(description or ""),
        owner=user,
        design_tokens=design_tokens or {},
    )
    AppMember.objects.create(app=app, user=user, role="owner")
    return app


def _create_page(app, page_data: dict):
    path = str(page_data.get("path") or "home").strip().strip("/")
    if not path:
        raise ValidationError({"detail": "页面 path 不能为空"})
    page = Page.objects.create(
        app=app,
        name=str(page_data.get("name") or path),
        path=path,
        type=str(page_data.get("type") or "page"),
        schema=page_data.get("schema") or {},
        schema_version=int(page_data.get("schemaVersion") or 2),
    )
    return page


def _create_model(app, model_data: dict):
    name = str(model_data.get("name") or "").strip()
    if not name:
        return None, []
    if DataModel.objects.filter(app=app, name=name).exists():
        raise ValidationError({"detail": f"数据模型 {name} 已存在"})
    fields = validate_fields_spec(model_data.get("fields") or [], app=app)
    model = DataModel.objects.create(
        app=app,
        name=name,
        fields=fields,
        indexes=model_data.get("indexes") or [],
        is_public=bool(model_data.get("is_public", False)),
        row_owner_field=str(model_data.get("row_owner_field") or "")[:80],
        data_scope=str(model_data.get("data_scope") or "all"),
        dept_field=str(model_data.get("dept_field") or "dept")[:80],
        action_roles=model_data.get("action_roles") or {},
        review_required=bool(model_data.get("review_required", False)),
        review_roles=model_data.get("review_roles") or [],
    )
    records = []
    for row in model_data.get("records") or []:
        if isinstance(row, dict):
            records.append(DataRecord.objects.create(model=model, data=row))
    return model, records


def _create_workflow(app, workflow_data: dict):
    if not isinstance(workflow_data, dict):
        return None
    name = str(workflow_data.get("name") or "").strip()
    code = str(workflow_data.get("code") or "").strip()
    nodes = workflow_data.get("nodes") or []
    if not name or not code or not isinstance(nodes, list):
        return None
    if WorkflowDefinition.objects.filter(app=app, code=code).exists():
        raise ValidationError({"detail": f"流程编码 {code} 已存在"})
    return WorkflowDefinition.objects.create(
        app=app,
        name=name,
        code=code,
        description=str(workflow_data.get("description") or "")[:500],
        nodes=nodes,
        status="published" if workflow_data.get("publish", True) else "draft",
    )


def _bind_schema_model(schema: dict, model_ids: dict[str, int]) -> dict:
    """把模板里的模型占位符替换成实际模型 id；支持 dataModelKey。"""
    if not isinstance(schema, dict):
        return schema
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict) or not isinstance(node.get("props"), dict):
            continue
        props = node["props"]
        key = str(props.get("dataModelKey") or "")
        value = props.get("dataModelId")
        if key and key in model_ids:
            props["dataModelId"] = model_ids[key]
        elif value == "__TEMPLATE_MODEL__" or (isinstance(value, str) and value.startswith("__TEMPLATE_MODEL__:")):
            requested = value.split(":", 1)[1] if ":" in str(value) else ""
            target = model_ids.get(requested) or (next(iter(model_ids.values())) if model_ids else 0)
            props["dataModelId"] = target
    return schema


def _mark_schema_model(schema: dict) -> dict:
    """克隆时把原模型 id 改为占位符，交给新应用重新绑定。"""
    if not isinstance(schema, dict):
        return schema
    for node in (schema.get("nodes") or {}).values():
        if isinstance(node, dict) and isinstance(node.get("props"), dict):
            value = node["props"].get("dataModelId")
            if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
                node["props"]["dataModelId"] = "__TEMPLATE_MODEL__"
    return schema


def _mark_schema_workflow(schema: dict, workflow_map: dict[int, str]) -> dict:
    if not isinstance(schema, dict):
        return schema
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict) or node.get("type") != "approval-panel":
            continue
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        try:
            definition_id = int(props.get("definitionId") or 0)
        except (TypeError, ValueError):
            definition_id = 0
        if definition_id and definition_id in workflow_map:
            props["workflowCode"] = workflow_map[definition_id]
            props["definitionId"] = "__TEMPLATE_WORKFLOW__"


def _bind_schema_workflow(schema: dict, workflows: dict[str, int]) -> dict:
    if not isinstance(schema, dict):
        return schema
    for node in (schema.get("nodes") or {}).values():
        if not isinstance(node, dict) or node.get("type") != "approval-panel":
            continue
        props = node.get("props")
        if not isinstance(props, dict):
            continue
        code = str(props.get("workflowCode") or "")
        if code and code in workflows:
            props["definitionId"] = workflows[code]
    return schema


def _apply_bundle(user, name: str, code: str, bundle: dict):
    with transaction.atomic():
        app = _create_app(user, name, code, bundle.get("description") or "", bundle.get("design_tokens"))
        models = []
        for model_data in bundle.get("models") or []:
            model, records = _create_model(app, model_data)
            if model:
                models.append({"model": model, "records": records, "workflow_code": model_data.get("workflow_code")})
        model_ids = {item["model"].name: item["model"].id for item in models}
        pages = []
        for page_data in bundle.get("pages") or []:
            page_data = dict(page_data)
            if model_ids:
                page_data["schema"] = _bind_schema_model(page_data.get("schema") or {}, model_ids)
            pages.append(_create_page(app, page_data))
        created_workflows = []
        workflow_payloads = bundle.get("workflows")
        if not isinstance(workflow_payloads, list) or not workflow_payloads:
            workflow_payloads = [bundle.get("workflow") or {}]
        for wf_data in workflow_payloads:
            wf = _create_workflow(app, wf_data)
            if wf:
                created_workflows.append(wf)
        wf_by_code = {wf.code: wf for wf in created_workflows}
        workflow_ids = {wf.code: wf.id for wf in created_workflows}
        for page in pages:
            updated = _bind_schema_workflow(page.schema or {}, workflow_ids)
            if updated != page.schema:
                page.schema = updated
                page.save(update_fields=["schema", "updated_at"])
        for item in models:
            code = item.get("workflow_code")
            if code and code in wf_by_code:
                item["model"].workflow_definition_id = wf_by_code[code].id
                item["model"].save(update_fields=["workflow_definition_id"])
        auth = bundle.get("auth_config") or {}
        if isinstance(auth, dict):
            auth_fields = {
                "enabled": bool(auth.get("enabled", True)),
                "require_login": bool(auth.get("require_login", False)),
                "allow_register": bool(auth.get("allow_register", False)),
                "auto_join": bool(auth.get("auto_join", True)),
                "default_role": str(auth.get("default_role") or "viewer"),
                "invite_required": bool(auth.get("invite_required", False)),
                "invite_code": str(auth.get("invite_code") or "")[:80],
                "login_title": str(auth.get("login_title") or app.name)[:160],
                "login_subtitle": str(auth.get("login_subtitle") or "")[:240],
                "logo_url": str(auth.get("logo_url") or "")[:500],
                "theme_color": str(auth.get("theme_color") or "#2563eb")[:20],
                "redirect_path": str(auth.get("redirect_path") or "")[:200],
                "allowed_domains": auth.get("allowed_domains") or [],
            }
            AppAuthConfig.objects.create(app=app, **auth_fields)
        module_payloads = bundle.get("modules") or default_modules()
        for item in module_payloads:
            if not isinstance(item, dict) or not item.get("key"):
                continue
            AppModule.objects.update_or_create(
                app=app, key=str(item["key"]),
                defaults={"enabled": bool(item.get("enabled", True)), "config": item.get("config") or {}},
            )
        for tpl in bundle.get("notification_templates") or []:
            if not isinstance(tpl, dict) or not tpl.get("key"):
                continue
            NotificationTemplate.objects.update_or_create(
                app=app, key=str(tpl["key"]),
                defaults={"name": str(tpl.get("name") or tpl["key"])[:160], "channel": str(tpl.get("channel") or "inapp"),
                          "subject": str(tpl.get("subject") or ""), "content": str(tpl.get("content") or ""),
                          "enabled": bool(tpl.get("enabled", True)), "variables": tpl.get("variables") or []},
            )
        for hook in bundle.get("webhooks") or []:
            if not isinstance(hook, dict) or not hook.get("url"):
                continue
            WebhookEndpoint.objects.create(
                app=app, name=str(hook.get("name") or "Webhook")[:160], url=str(hook["url"])[:500],
                secret=str(hook.get("secret") or "")[:120], events=hook.get("events") or [],
                enabled=bool(hook.get("enabled", True)),
            )
        for job in bundle.get("jobs") or []:
            if not isinstance(job, dict) or not job.get("code"):
                continue
            ScheduledJob.objects.update_or_create(
                app=app, code=str(job["code"]),
                defaults={"name": str(job.get("name") or job["code"])[:160], "handler": str(job.get("handler") or "noop"),
                          "cron": str(job.get("cron") or "0 2 * * *"), "payload": job.get("payload") or {},
                          "enabled": bool(job.get("enabled", True))},
            )
        member_errors = []
        for member in bundle.get("members") or []:
            user_id = member.get("user_id") or member.get("id")
            role = str(member.get("role") or "viewer")
            if role not in ("viewer", "editor"):
                member_errors.append({"user_id": user_id, "reason": "角色只能是 viewer/editor"})
                continue
            if not user_id or int(user_id) == user.id:
                continue
            from accounts.models import User

            target = User.objects.filter(id=int(user_id), is_active=True).first()
            if target is None:
                member_errors.append({"user_id": user_id, "reason": "用户不存在或已禁用"})
                continue
            AppMember.objects.get_or_create(app=app, user=target, defaults={"role": role})
    return Response(
        {
            "app": {"id": app.id, "name": app.name, "code": app.code},
            "pages": [{"id": p.id, "name": p.name, "path": p.path} for p in pages],
            "models": [
                {"id": item["model"].id, "name": item["model"].name, "records": len(item["records"])}
                for item in models
            ],
            "workflow": {"id": created_workflows[0].id, "name": created_workflows[0].name, "status": created_workflows[0].status} if created_workflows else None,
            "member_errors": member_errors,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_template(request):
    """POST /api/templates/apply/ — 原子创建应用、页面、数据模型、示例数据、权限、流程。"""
    return _apply_bundle(
        request.user,
        request.data.get("name"),
        request.data.get("code"),
        request.data,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def import_template(request):
    """POST /api/templates/import/ {name, code, template} — 导入导出的模板 JSON。"""
    bundle = request.data.get("template") or request.data
    if not isinstance(bundle, dict):
        raise ValidationError({"detail": "template 必须是对象"})
    bundle = deepcopy(bundle)
    for page in bundle.get("pages") or []:
        if isinstance(page, dict):
            page["schema"] = _mark_schema_model(page.get("schema") or {})
    return _apply_bundle(
        request.user,
        request.data.get("name") or bundle.get("name"),
        request.data.get("code"),
        bundle,
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def export_app_template(request, app_id: int):
    """GET /api/templates/export/{app_id}/ — 导出可克隆的应用模板 JSON。"""
    app = get_app(app_id)
    require_app_role(request.user, app, "viewer")
    pages = []
    for page in app.pages.all().order_by("id"):
        pages.append({
            "name": page.name,
            "path": page.path,
            "type": page.type,
            "schema": page.schema,
            "schemaVersion": page.schema_version,
        })
    models = []
    for model in app.datamodels.all().order_by("id"):
        models.append({
            "name": model.name,
            "fields": model.fields,
            "indexes": model.indexes,
            "is_public": model.is_public,
            "row_owner_field": model.row_owner_field,
            "data_scope": model.data_scope,
            "dept_field": model.dept_field,
            "action_roles": model.action_roles,
            "review_required": model.review_required,
            "review_roles": model.review_roles,
            "workflow_code": next((wf.code for wf in app.workflows.all() if wf.id == model.workflow_definition_id), ""),
            "records": [row.data for row in model.records.all().order_by("id")],
        })
    workflows = [
        {
            "name": wf.name,
            "code": wf.code,
            "description": wf.description,
            "nodes": wf.nodes,
            "publish": wf.status == "published",
        }
        for wf in app.workflows.all().order_by("id")
    ]
    return Response({
        "name": app.name,
        "description": app.description,
        "design_tokens": app.design_tokens or {},
        "pages": pages,
        "models": models,
        "workflow": workflows[0] if workflows else {},
        "workflows": workflows,
        "auth_config": _export_auth_config(app),
        "modules": _export_modules(app),
        "notification_templates": [
            {"key": t.key, "name": t.name, "channel": t.channel, "subject": t.subject,
             "content": t.content, "enabled": t.enabled, "variables": t.variables or []}
            for t in app.notification_templates.all()
        ],
        "webhooks": [
            {"name": w.name, "url": w.url, "events": w.events or [], "enabled": w.enabled}
            for w in app.webhooks.all()
        ],
        "jobs": [
            {"name": j.name, "code": j.code, "handler": j.handler, "cron": j.cron,
             "payload": j.payload or {}, "enabled": j.enabled}
            for j in app.scheduled_jobs.all()
        ],
        "members": [
            {"user_id": m.user_id, "username": m.user.username, "role": m.role}
            for m in app.members.select_related("user").all()
        ],
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def clone_app(request):
    """POST /api/templates/clone/ {source_app_id,name,code} — 克隆应用结构。"""
    source = get_app(request.data.get("source_app_id"))
    require_app_role(request.user, source, "viewer")
    bundle = _export_bundle(source)
    return _apply_bundle(request.user, request.data.get("name") or f"{source.name} 副本", request.data.get("code"), bundle)


def _export_bundle(app) -> dict:
    workflow_map = {wf.id: wf.code for wf in app.workflows.all()}
    pages = [
        {"name": p.name, "path": p.path, "type": p.type, "schema": _mark_schema_workflow(_mark_schema_model(deepcopy(p.schema)), workflow_map), "schemaVersion": p.schema_version}
        for p in app.pages.all().order_by("id")
    ]
    models = [
        {
            "name": m.name, "fields": m.fields, "indexes": m.indexes,
            "is_public": m.is_public, "row_owner_field": m.row_owner_field,
            "data_scope": m.data_scope, "dept_field": m.dept_field,
            "action_roles": m.action_roles, "review_required": m.review_required,
            "review_roles": m.review_roles,
            "workflow_code": workflow_map.get(m.workflow_definition_id, ""),
            "records": [row.data for row in m.records.all().order_by("id")],
        }
        for m in app.datamodels.all().order_by("id")
    ]
    workflows = [
        {
            "name": wf.name, "code": wf.code, "description": wf.description,
            "nodes": wf.nodes, "publish": wf.status == "published",
        }
        for wf in app.workflows.all().order_by("id")
    ]
    return {
        "name": app.name,
        "description": app.description,
        "design_tokens": app.design_tokens or {},
        "pages": pages,
        "models": models,
        "workflow": workflows[0] if workflows else {},
        "workflows": workflows,
        "auth_config": _export_auth_config(app),
        "modules": _export_modules(app),
        "notification_templates": [
            {"key": t.key, "name": t.name, "channel": t.channel, "subject": t.subject,
             "content": t.content, "enabled": t.enabled, "variables": t.variables or []}
            for t in app.notification_templates.all()
        ],
        "webhooks": [
            {"name": w.name, "url": w.url, "events": w.events or [], "enabled": w.enabled}
            for w in app.webhooks.all()
        ],
        "jobs": [
            {"name": j.name, "code": j.code, "handler": j.handler, "cron": j.cron,
             "payload": j.payload or {}, "enabled": j.enabled}
            for j in app.scheduled_jobs.all()
        ],
        "members": [
            {"user_id": m.user_id, "username": m.user.username, "role": m.role}
            for m in app.members.select_related("user").all()
        ],
    }


def _export_auth_config(app) -> dict:
    config = getattr(app, "auth_config", None)
    if config is None:
        return {}
    return {
        "enabled": config.enabled,
        "require_login": config.require_login,
        "allow_register": config.allow_register,
        "auto_join": config.auto_join,
        "default_role": config.default_role,
        "invite_required": config.invite_required,
        "invite_code": config.invite_code,
        "login_title": config.login_title,
        "login_subtitle": config.login_subtitle,
        "logo_url": config.logo_url,
        "theme_color": config.theme_color,
        "redirect_path": config.redirect_path,
        "allowed_domains": config.allowed_domains or [],
    }


def _export_modules(app) -> list[dict]:
    rows = {item.key: item for item in app.modules.all()}
    return [
        {**item, "enabled": rows[item["key"]].enabled if item["key"] in rows else item["enabled"]}
        for item in default_modules()
    ]


def _template_payload(template: AppTemplate, include_bundle: bool = False) -> dict:
    data = {
        "id": template.id,
        "key": template.key,
        "name": template.name,
        "description": template.description,
        "category": template.category,
        "icon": template.icon,
        "accent": template.accent,
        "tags": template.tags or [],
        "owner_id": template.owner_id,
        "owner_username": template.owner.username,
        "visibility": template.visibility,
        "status": template.status,
        "current_version": template.current_version,
        "downloads": template.downloads,
        "created_at": template.created_at,
        "updated_at": template.updated_at,
    }
    if include_bundle:
        data["bundle"] = template.bundle or {}
    return data


def _template_role(template: AppTemplate, user):
    if template.owner_id == user.id:
        return "owner"
    if getattr(user, "is_superuser", False):
        return "owner"
    access = AppTemplateAccess.objects.filter(template=template, user=user).first()
    if access:
        return access.role
    if template.status == "published" and template.visibility == "market":
        return "viewer"
    return None


def _require_template(template: AppTemplate, user, minimum: str = "viewer"):
    role = _template_role(template, user)
    order = {"viewer": 1, "editor": 2, "owner": 3}
    if role is None or order.get(role, 0) < order.get(minimum, 1):
        raise PermissionDenied("没有该模板的访问权限")
    return role


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def library_list_create(request):
    """GET/POST /api/templates/library/ — 服务端模板库。"""
    if request.method == "GET":
        if getattr(request.user, "is_superuser", False):
            qs = AppTemplate.objects.all()
        else:
            qs = AppTemplate.objects.filter(
                Q(owner=request.user)
                | Q(accesses__user=request.user)
                | Q(status="published", visibility="market")
            ).distinct()
        q = (request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(name__icontains=q)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        scope = request.query_params.get("scope")
        if scope == "mine":
            qs = qs.filter(owner=request.user)
        elif scope == "market":
            qs = qs.filter(status="published", visibility="market")
        return Response({
            "count": qs.count(),
            "results": [_template_payload(t) for t in qs.select_related("owner").order_by("-updated_at")],
        })
    name = str(request.data.get("name") or "").strip()
    bundle = request.data.get("bundle")
    if not name or not isinstance(bundle, dict):
        raise ValidationError({"detail": "name 和 bundle 必填"})
    if not isinstance(bundle.get("pages"), list) or not bundle["pages"]:
        raise ValidationError({"detail": "模板 bundle 至少需要一个页面"})
    template = AppTemplate.objects.create(
        name=name,
        description=str(request.data.get("description") or bundle.get("description") or ""),
        category=str(request.data.get("category") or ""),
        icon=str(request.data.get("icon") or "◇"),
        accent=str(request.data.get("accent") or "#409eff"),
        tags=request.data.get("tags") or [],
        bundle=bundle,
        owner=request.user,
        visibility="private",
        status="draft",
        current_version=1,
    )
    AppTemplateVersion.objects.create(
        template=template, version=1, bundle=bundle, changelog="创建模板", created_by=request.user
    )
    return Response(_template_payload(template, include_bundle=True), status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def library_detail(request, pk: int):
    template = AppTemplate.objects.filter(pk=pk).select_related("owner").first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        _require_template(template, request.user)
        return Response(_template_payload(template, include_bundle=True))
    if request.method == "DELETE":
        if template.owner_id != request.user.id and not getattr(request.user, "is_superuser", False):
            raise PermissionDenied("只有模板所有者可以删除")
        template.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    _require_template(template, request.user, "editor")
    if "name" in request.data:
        template.name = str(request.data.get("name") or template.name)
    if "description" in request.data:
        template.description = str(request.data.get("description") or "")
    if "category" in request.data:
        template.category = str(request.data.get("category") or "")
    if "visibility" in request.data and request.data["visibility"] in ("private", "shared", "market"):
        template.visibility = request.data["visibility"]
    if "status" in request.data and request.data["status"] in ("draft", "published"):
        template.status = request.data["status"]
    bundle = request.data.get("bundle")
    if isinstance(bundle, dict):
        if not isinstance(bundle.get("pages"), list) or not bundle["pages"]:
            raise ValidationError({"detail": "模板至少需要一个页面"})
        template.bundle = bundle
        template.current_version += 1
        AppTemplateVersion.objects.create(
            template=template,
            version=template.current_version,
            bundle=bundle,
            changelog=str(request.data.get("changelog") or "更新模板"),
            created_by=request.user,
        )
    template.save()
    return Response(_template_payload(template, include_bundle=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def library_publish(request, pk: int):
    template = AppTemplate.objects.filter(pk=pk).first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    _require_template(template, request.user, "owner")
    visibility = request.data.get("visibility") or "market"
    if visibility not in ("private", "shared", "market"):
        raise ValidationError({"detail": "visibility 不正确"})
    template.visibility = visibility
    template.status = "published"
    template.save(update_fields=["visibility", "status", "updated_at"])
    return Response(_template_payload(template))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def library_access(request, pk: int):
    template = AppTemplate.objects.filter(pk=pk).first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    _require_template(template, request.user, "owner")
    if request.method == "GET":
        rows = template.accesses.select_related("user").all()
        return Response([
            {"id": row.id, "user_id": row.user_id, "username": row.user.username, "role": row.role}
            for row in rows
        ])
    from accounts.models import User

    user = User.objects.filter(id=request.data.get("user_id"), is_active=True).first()
    if user is None:
        raise ValidationError({"detail": "用户不存在或已禁用"})
    role = request.data.get("role") or "viewer"
    if role not in ("viewer", "editor"):
        raise ValidationError({"detail": "role 只能是 viewer/editor"})
    access, _ = AppTemplateAccess.objects.update_or_create(
        template=template, user=user, defaults={"role": role}
    )
    return Response({"id": access.id, "user_id": user.id, "username": user.username, "role": access.role})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def library_access_detail(request, pk: int, user_id: int):
    template = AppTemplate.objects.filter(pk=pk).first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    _require_template(template, request.user, "owner")
    AppTemplateAccess.objects.filter(template=template, user_id=user_id).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def library_apply(request, pk: int):
    template = AppTemplate.objects.filter(pk=pk).first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    _require_template(template, request.user)
    import uuid

    code = str(request.data.get("code") or f"{template.key}-{uuid.uuid4().hex[:5]}")
    response = _apply_bundle(
        request.user,
        request.data.get("name") or template.name,
        code,
        {**template.bundle, "members": request.data.get("members") or []},
    )
    template.downloads += 1
    template.save(update_fields=["downloads", "updated_at"])
    return response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def library_versions(request, pk: int):
    template = AppTemplate.objects.filter(pk=pk).first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    _require_template(template, request.user)
    rows = template.versions.select_related("created_by").all()
    return Response([
        {
            "version": row.version,
            "changelog": row.changelog,
            "created_by": row.created_by.username if row.created_by else "",
            "created_at": row.created_at,
        }
        for row in rows
    ])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def library_rollback(request, pk: int, version: int):
    template = AppTemplate.objects.filter(pk=pk).first()
    if template is None:
        return Response(status=status.HTTP_404_NOT_FOUND)
    _require_template(template, request.user, "editor")
    target = template.versions.filter(version=version).first()
    if target is None:
        raise ValidationError({"detail": "模板版本不存在"})
    template.current_version += 1
    template.bundle = target.bundle
    template.save(update_fields=["current_version", "bundle", "updated_at"])
    AppTemplateVersion.objects.create(
        template=template,
        version=template.current_version,
        bundle=target.bundle,
        changelog=f"回滚到 v{version}",
        created_by=request.user,
    )
    return Response(_template_payload(template, include_bundle=True))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def library_from_app(request, app_id: int):
    app = get_app(app_id)
    require_app_role(request.user, app, "viewer")
    bundle = _export_bundle(app)
    template = AppTemplate.objects.create(
        name=str(request.data.get("name") or f"{app.name} 模板"),
        description=app.description,
        category=str(request.data.get("category") or ""),
        icon=str(request.data.get("icon") or "◇"),
        accent=str(request.data.get("accent") or "#409eff"),
        tags=request.data.get("tags") or [],
        bundle=bundle,
        owner=request.user,
        visibility="private",
        status="draft",
        current_version=1,
    )
    AppTemplateVersion.objects.create(
        template=template, version=1, bundle=bundle, changelog="从应用创建", created_by=request.user
    )
    return Response(_template_payload(template, include_bundle=True), status=status.HTTP_201_CREATED)
