"""数据模型字段校验 / 记录校验 / 动态过滤。"""
from __future__ import annotations

import ast
import operator
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from rest_framework.exceptions import ValidationError

from .aggregates import aggregate_functions
from .models import FIELD_TYPES, DataModel, DataRecord

NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}:\d{2})?$")
TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[+\d][\d\s-]{5,24}$")
# 多文件附件：URL 数组，最多 20 个、单个 URL 最长 500 字符。
ATTACHMENTS_MAX_COUNT = 20
ATTACHMENTS_MAX_URL_LENGTH = 500


def _is_attachment_url(value: Any) -> bool:
    """附件 URL：支持 http(s) 绝对地址、协议相对地址和站内 /media 相对地址。"""
    if not isinstance(value, str) or not value or len(value) > ATTACHMENTS_MAX_URL_LENGTH:
        return False
    if any(ch.isspace() for ch in value):
        return False
    if value.startswith("/"):
        return True
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def attachment_problem(value: Any) -> str:
    """返回 attachments 值的校验错误（空串表示通过）；[] 与 null 均合法。"""
    if not isinstance(value, list):
        return "必须是附件 URL 数组"
    if len(value) > ATTACHMENTS_MAX_COUNT:
        return f"最多允许 {ATTACHMENTS_MAX_COUNT} 个附件"
    for item in value:
        if not isinstance(item, str) or not item:
            return "每个附件必须是非空 URL 字符串"
        if len(item) > ATTACHMENTS_MAX_URL_LENGTH:
            return f"附件 URL 不能超过 {ATTACHMENTS_MAX_URL_LENGTH} 字符"
        if not _is_attachment_url(item):
            return f"附件 URL 格式不正确: {item[:80]!r}"
    return ""


def validate_fields_spec(fields: list, app=None) -> list:
    """校验 fields 定义，返回规范化列表。"""
    if not isinstance(fields, list):
        raise ValidationError({"detail": "fields 必须是数组"})
    seen = set()
    out = []
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            raise ValidationError({"detail": f"fields[{i}] 必须是对象"})
        name = str(f.get("name") or "").strip()
        if not name or not NAME_RE.match(name):
            raise ValidationError({"detail": f"fields[{i}].name 非法标识符: {name!r}"})
        if name in seen:
            raise ValidationError({"detail": f"字段名重复: {name}"})
        seen.add(name)
        ftype = f.get("type", "string")
        if ftype not in FIELD_TYPES:
            raise ValidationError({"detail": f"字段 {name} 类型非法: {ftype}（允许 {FIELD_TYPES}）"})
        ref_model = f.get("ref_model")
        if ftype in ("reference", "references"):
            if not ref_model:
                raise ValidationError({"detail": f"字段 {name} 为 {ftype} 类型需要 ref_model"})
            if app and not DataModel.objects.filter(app=app, name=ref_model).exists():
                raise ValidationError({"detail": f"字段 {name} 的 ref_model {ref_model} 不存在"})
        if ftype in ("select", "multiselect", "tags"):
            options = f.get("options")
            if not isinstance(options, list) or not options:
                raise ValidationError({"detail": f"字段 {name} 为 {ftype} 类型需要 options"})
        if ftype == "formula" and not str(f.get("formula") or "").strip():
            raise ValidationError({"detail": f"字段 {name} 为 formula 类型需要 formula 表达式"})
        item = {
            "name": name,
            "type": ftype,
            "required": bool(f.get("required", False)),
            "default": f.get("default"),
            "unique": bool(f.get("unique", False)),
        }
        if f.get("label"):
            item["label"] = str(f["label"])[:80]
        if f.get("description"):
            item["description"] = str(f["description"])[:255]
        if isinstance(f.get("rules"), list):
            item["rules"] = [r for r in f["rules"] if isinstance(r, dict)]
        if isinstance(f.get("options"), list):
            normalized_options = []
            for option in f["options"]:
                if isinstance(option, dict):
                    normalized_options.append(option)
                elif isinstance(option, (str, int, float)):
                    normalized_options.append({"label": str(option), "value": option})
            item["options"] = normalized_options
        for key in ("min", "max", "precision", "currency", "max_length", "accept", "multiple", "ref_display", "placeholder", "format", "unit", "formula"):
            if f.get(key) is not None:
                item[key] = f[key]
        if isinstance(f.get("read_roles"), list):
            item["read_roles"] = [r for r in f["read_roles"] if r in ("viewer", "editor", "owner")]
        if isinstance(f.get("write_roles"), list):
            item["write_roles"] = [r for r in f["write_roles"] if r in ("viewer", "editor", "owner")]
        if isinstance(f.get("mask_roles"), list):
            item["mask_roles"] = [r for r in f["mask_roles"] if r in ("viewer", "editor", "owner")]
        if f.get("ui") in ("text", "textarea", "richtext", "select", "multi-select", "date", "datetime", "time", "number", "switch", "image", "file", "attachments", "color", "rating"):
            item["ui"] = f["ui"]
        if ftype in ("reference", "references"):
            item["ref_model"] = str(ref_model)
        out.append(item)
    return out


def _check_type(value: Any, ftype: str, field_name: str) -> bool:
    if value is None:
        return True
    if ftype in ("string", "longtext", "richtext", "email", "phone", "url", "password", "image", "file", "signature", "barcode", "color", "auto_number"):
        return isinstance(value, str)
    if ftype == "select":
        return isinstance(value, (str, int, float)) and not isinstance(value, bool)
    if ftype in ("number", "decimal", "money", "percent", "rating"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if ftype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "boolean":
        return isinstance(value, bool)
    if ftype in ("date", "datetime"):
        return isinstance(value, str) and bool(DATE_RE.match(value))
    if ftype == "time":
        return isinstance(value, str) and bool(TIME_RE.match(value))
    if ftype == "duration":
        return isinstance(value, (str, int, float)) and not isinstance(value, bool)
    if ftype == "json":
        return isinstance(value, (dict, list))
    if ftype == "attachments":
        # 元素级 URL/数量/长度在 validate_data 中给出更精确的错误。
        return isinstance(value, list)
    if ftype == "reference":
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if ftype == "references":
        return isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in value)
    if ftype in ("multiselect", "tags"):
        return isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value)
    if ftype in ("user", "department"):
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if ftype == "geolocation":
        return isinstance(value, dict) and "lat" in value and "lng" in value
    if ftype in ("formula", "created_at", "updated_at"):
        return True
    return True


_FORMULA_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}
_FORMULA_CMPOPS = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Gt: operator.gt,
    ast.GtE: operator.ge, ast.Lt: operator.lt, ast.LtE: operator.le,
}
_FORMULA_FUNCS = {
    "abs": abs, "round": round, "min": min, "max": max, "len": len,
    "sum": sum, "int": int, "float": float, "str": str,
}


def evaluate_formula(expression: str, values: dict, extra_funcs: dict | None = None) -> Any:
    """Small, side-effect-free formula evaluator for computed fields."""
    tree = ast.parse(expression, mode="eval")
    funcs = {**_FORMULA_FUNCS, **(extra_funcs or {})}

    def run(node):
        if isinstance(node, ast.Expression):
            return run(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in values:
                return values[node.id]
            raise ValueError(f"未知字段 {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _FORMULA_BINOPS:
            return _FORMULA_BINOPS[type(node.op)](run(node.left), run(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            value = run(node.operand)
            return +value if isinstance(node.op, ast.UAdd) else -value if isinstance(node.op, ast.USub) else not value
        if isinstance(node, ast.BoolOp):
            vals = [run(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.Compare):
            left = run(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                if type(op) not in _FORMULA_CMPOPS:
                    raise ValueError("不支持的比较运算")
                right = run(comparator)
                if not _FORMULA_CMPOPS[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return run(node.body) if run(node.test) else run(node.orelse)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
            return funcs[node.func.id](*[run(a) for a in node.args])
        if isinstance(node, (ast.List, ast.Tuple)):
            return [run(e) for e in node.elts]
        raise ValueError("不支持的公式语法")

    return run(tree)


def visible_data(model: DataModel, data: dict, role: str | None, *, admin: bool = False) -> dict:
    """按字段 read_roles 裁剪读取结果；admin 不受限制。"""
    if admin:
        return dict(data or {})
    specs = model.field_map()
    out = {}
    for key, value in (data or {}).items():
        spec = specs.get(key) or {}
        roles = spec.get("read_roles")
        if isinstance(roles, list) and roles and role not in roles:
            continue
        mask_roles = spec.get("mask_roles")
        if isinstance(mask_roles, list) and mask_roles and role in mask_roles:
            out[key] = "***"
            continue
        out[key] = value
    return out


def check_write_fields(model: DataModel, data: dict, role: str | None, *, admin: bool = False) -> None:
    """字段 write_roles 基础校验；admin 不受限制。"""
    if admin:
        return
    specs = model.field_map()
    for key in (data or {}).keys():
        spec = specs.get(key) or {}
        roles = spec.get("write_roles")
        if isinstance(roles, list) and roles and role not in roles:
            raise ValidationError({"detail": f"字段 {key} 无写入权限"})


ACTIONS = ("view", "create", "update", "delete", "export")


def allowed_action(model, role: str | None, action: str, *, admin: bool = False) -> bool:
    if admin or role == "owner":
        return True
    config = model.action_roles or {}
    allowed = config.get(action)
    if not isinstance(allowed, list) or not allowed:
        return True
    return role in allowed


def require_action(model, role: str | None, action: str, *, admin: bool = False) -> None:
    if not allowed_action(model, role, action, admin=admin):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied(f"当前角色无权执行 {action} 操作")


def publish_due_records(model) -> int:
    """把已到发布时间的 scheduled 记录切为 published（无 worker 时的惰性发布）。"""
    fields = {f.get("name") for f in (model.fields or []) if isinstance(f, dict)}
    if "status" not in fields or "published_at" not in fields:
        return 0
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    from datamodels.models import DataRecord

    now = timezone.now()
    changed = 0
    for record in DataRecord.objects.filter(model=model):
        data = record.data or {}
        if data.get("status") != "scheduled" or not data.get("published_at"):
            continue
        due = parse_datetime(str(data["published_at"]))
        if due is None or due > now:
            continue
        data = dict(data)
        data["status"] = "published"
        record.data = data
        record.save(update_fields=["data", "updated_at"])
        changed += 1
    return changed


def apply_row_scope(model: DataModel, rows: list[dict], user, *, admin: bool = False, dept_scope=None) -> list[dict]:
    """行级权限。

    - ``owner``：row_owner_field 等于用户 id 或用户名；
    - ``dept`` / ``dept_and_children``：dept_field 落在用户可见部门内
      （负责人可见整棵子树，普通成员仅本部门）。
    """
    if admin:
        return rows
    scope = model.data_scope or "all"
    field = (model.row_owner_field or "").strip()
    if scope == "owner" and field:
        allowed = {str(getattr(user, "id", "")), str(getattr(user, "username", ""))}
        return [
            row for row in rows
            if str((row.get("data") or {}).get(field, "")) in allowed
        ]
    if scope in ("dept", "dept_and_children"):
        if dept_scope is None:
            from org.services import department_scope

            dept_scope = department_scope(user)
        dept_field = (model.dept_field or "dept").strip() or "dept"
        return [
            row for row in rows
            if dept_scope.matches((row.get("data") or {}).get(dept_field))
        ]
    return rows


def can_access_record(model: DataModel, data: dict, user, *, admin: bool = False, dept_scope=None) -> bool:
    """单条记录是否落在当前用户的数据范围内。"""
    if admin:
        return True
    scope = model.data_scope or "all"
    if scope == "owner":
        field = (model.row_owner_field or "").strip()
        if not field:
            return True
        allowed = {str(getattr(user, "id", "")), str(getattr(user, "username", ""))}
        return str((data or {}).get(field, "")) in allowed
    if scope in ("dept", "dept_and_children"):
        if dept_scope is None:
            from org.services import department_scope

            dept_scope = department_scope(user)
        dept_field = (model.dept_field or "dept").strip() or "dept"
        return dept_scope.matches((data or {}).get(dept_field))
    return True


def default_department_value(user, model: DataModel | None = None):
    """新建记录时默认归属部门（按字段类型返回 id 字符串/数字，无部门返回空串）。"""
    try:
        from org.services import primary_department

        dept = primary_department(user)
        if dept is None:
            return ""
        field = (model.dept_field or "dept").strip() if model is not None else "dept"
        spec = (model.field_map().get(field) if model is not None else {}) or {}
        if spec.get("type") in ("number", "reference"):
            return dept.id
        return str(dept.id)
    except Exception:
        return ""


def guard_department_assignment(model: DataModel, data: dict, user, *, admin: bool = False) -> None:
    """部门数据范围：非管理员不能把记录写到不可见部门。"""
    if admin or (model.data_scope or "all") not in ("dept", "dept_and_children"):
        return
    dept_field = (model.dept_field or "dept").strip() or "dept"
    value = (data or {}).get(dept_field)
    if value in (None, ""):
        return
    from org.services import department_scope

    scope = department_scope(user)
    if not scope.matches(value):
        from rest_framework.exceptions import PermissionDenied

        raise PermissionDenied("不能写入其他部门的数据")


def validate_data(
    model: DataModel, data: dict, *, partial: bool = False, exclude_pk: int | None = None,
    user=None, role: str | None = None, admin: bool = False,
) -> dict:
    """校验记录 data：必填 / 类型 / 唯一 / 引用 / 字段写权限。返回清洗后的 data。"""
    if not isinstance(data, dict):
        raise ValidationError({"detail": "data 必须是对象"})
    if user is not None:
        check_write_fields(model, data, role, admin=admin)
    specs = model.field_map()
    cleaned = dict(data)
    errors = []

    for name, spec in specs.items():
        value = data.get(name)
        if value is None and spec.get("type") == "auto_number":
            value = f"{model.name[:6].upper()}-{model.records.count() + 1:04d}"
            cleaned[name] = value
        if value is None and spec.get("type") in ("created_at", "updated_at"):
            value = datetime.now().astimezone().isoformat()
            cleaned[name] = value
        if value is None:
            if spec.get("default") is not None:
                cleaned[name] = spec["default"]
            elif spec.get("required") and not partial and spec["type"] not in ("formula", "auto_number", "created_at", "updated_at"):
                errors.append(f"缺少必填字段 {name}")
            elif spec.get("required") and partial:
                pass
            continue
        if not _check_type(value, spec["type"], name):
            errors.append(f"字段 {name} 类型应为 {spec['type']}")
            continue
        if spec["type"] == "attachments":
            problem = attachment_problem(value)
            if problem:
                errors.append(f"字段 {name} {problem}")
            continue
        if spec["type"] in ("reference", "references"):
            target_name = spec.get("ref_model")
            target = DataModel.objects.filter(name=target_name, app=model.app).first()
            if target is None:
                errors.append(f"字段 {name} 的引用模型 {target_name} 不存在")
            elif spec["type"] == "reference" and not DataRecord.objects.filter(model=target, id=value).exists():
                errors.append(f"字段 {name} 引用的记录 {value} 不存在")
            elif spec["type"] == "references":
                missing = [v for v in value if not DataRecord.objects.filter(model=target, id=v).exists()]
                if missing:
                    errors.append(f"字段 {name} 引用的记录不存在: {missing}")
        if spec.get("max_length") and isinstance(value, str) and len(value) > int(spec["max_length"]):
            errors.append(f"字段 {name} 超过最大长度 {spec['max_length']}")
        if spec.get("min") is not None and isinstance(value, (int, float)) and value < spec["min"]:
            errors.append(f"字段 {name} 小于最小值 {spec['min']}")
        if spec.get("max") is not None and isinstance(value, (int, float)) and value > spec["max"]:
            errors.append(f"字段 {name} 大于最大值 {spec['max']}")
        if spec["type"] == "email" and not EMAIL_RE.match(str(value)):
            errors.append(f"字段 {name} 邮箱格式不正确")
        if spec["type"] == "phone" and not PHONE_RE.match(str(value)):
            errors.append(f"字段 {name} 手机号格式不正确")
        if spec["type"] in ("select", "multiselect", "tags"):
            allowed = [str(o.get("value")) for o in (spec.get("options") or []) if isinstance(o, dict)]
            vals = value if isinstance(value, list) else [value]
            if allowed and any(str(v) not in allowed for v in vals):
                errors.append(f"字段 {name} 的值不在可选项内")
        if spec.get("unique") and value is not None:
            qs = DataRecord.objects.filter(model=model)
            if exclude_pk is not None:
                qs = qs.exclude(id=exclude_pk)
            # JSON 精确匹配
            if qs.filter(**{f"data__{name}": value}).exists():
                errors.append(f"字段 {name} 值 {value!r} 已存在（唯一约束）")
    formula_fields = [(name, spec) for name, spec in specs.items() if spec.get("type") == "formula" and spec.get("formula")]
    if formula_fields:
        aggregates = aggregate_functions(model)
        for _ in range(len(formula_fields) + 1):
            changed = False
            for name, spec in formula_fields:
                try:
                    value = evaluate_formula(str(spec["formula"]), cleaned, aggregates)
                except (ValueError, TypeError, ZeroDivisionError, SyntaxError):
                    continue
                if cleaned.get(name) != value:
                    cleaned[name] = value
                    changed = True
            if not changed:
                break
        for name, _spec in formula_fields:
            if cleaned.get(name) is None:
                errors.append(f"字段 {name} 公式无法计算")
    if errors:
        raise ValidationError({"detail": "; ".join(errors)})
    return cleaned


def dynamic_query(model: DataModel, params: dict) -> list[dict]:
    """动态过滤：?field=value, ?field__gt/gte/lt/lte/contains；排序 sort/-field。

    为保证 SQLite/Postgres 行为一致，比较类过滤在内存中进行（应用内记录量有限）。
    """
    exact: dict[str, Any] = {}
    comparators: list[tuple[str, str, Any]] = []
    field_types = {f.get("name"): f.get("type") for f in (model.fields or []) if isinstance(f, dict)}

    def coerce_exact(key: str, raw: Any) -> Any:
        ftype = field_types.get(key)
        if raw is None:
            return raw
        try:
            if ftype in ("number", "integer", "decimal", "money", "percent", "rating", "reference", "user", "department"):
                text = str(raw).strip()
                number = float(text)
                return int(number) if number.is_integer() else number
            if ftype == "boolean":
                text = str(raw).strip().lower()
                if text in ("1", "true", "yes", "on"):
                    return True
                if text in ("0", "false", "no", "off"):
                    return False
        except (TypeError, ValueError):
            pass
        return raw

    for key, raw in params.items():
        if key in ("page", "size", "page_size", "sort", "search"):
            continue
        if key.endswith("__contains"):
            field = key[: -len("__contains")]
            comparators.append((field, "contains", raw))
        elif key.endswith("__gte"):
            comparators.append((key[: -len("__gte")], "gte", raw))
        elif key.endswith("__gt"):
            comparators.append((key[: -len("__gt")], "gt", raw))
        elif key.endswith("__lte"):
            comparators.append((key[: -len("__lte")], "lte", raw))
        elif key.endswith("__lt"):
            comparators.append((key[: -len("__lt")], "lt", raw))
        else:
            exact[key] = coerce_exact(key, raw)

    if exact:
        rows = list(model.records.filter(**{f"data__{k}": v for k, v in exact.items()}).values("id", "data", "created_at", "updated_at"))
    else:
        rows = list(model.records.values("id", "data", "created_at", "updated_at"))

    def _as_number(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def match(row: dict) -> bool:
        data = row.get("data") or {}
        for field, op, raw in comparators:
            v = data.get(field)
            if v is None:
                return False
            if op == "contains":
                if not isinstance(v, str):
                    return False
                if str(raw).lower() not in v.lower():
                    return False
                continue
            a, b = _as_number(v), _as_number(raw)
            if a is None or b is None:
                # 非数值比较按字符串
                sv, sr = str(v), str(raw)
                ok = sv > sr if op == "gt" else sv >= sr if op == "gte" else sv < sr if op == "lt" else sv <= sr
            else:
                ok = a > b if op == "gt" else a >= b if op == "gte" else a < b if op == "lt" else a <= b
            if not ok:
                return False
        return True

    rows = [r for r in rows if match(r)]

    search = str(params.get("search") or "").strip().lower()
    if search:
        rows = [
            r for r in rows
            if any(search in str(v).lower() for v in (r.get("data") or {}).values() if v is not None)
        ]

    sort = params.get("sort")
    if sort:
        field = str(sort)
        reverse = field.startswith("-")
        if reverse:
            field = field[1:]
        def keyfn(r: dict):
            v = (r.get("data") or {}).get(field)
            if v is None:
                return (0, "")
            n = _as_number(v)
            if n is not None:
                return (2, n)
            return (1, str(v))

        rows.sort(key=keyfn, reverse=reverse)
    else:
        rows.sort(key=lambda r: r["id"], reverse=True)
    return rows


def paginate_rows(rows: list[dict], request) -> dict:
    """docs/API.md 分页形状：{count, results, page, size}。"""
    try:
        page = max(1, int(request.query_params.get("page", 1)))
        page_size = int(request.query_params.get("size") or request.query_params.get("page_size") or 20)
        page_size = min(100, max(1, page_size))
    except (TypeError, ValueError):
        page, page_size = 1, 20
    total = len(rows)
    start = (page - 1) * page_size
    return {"count": total, "results": rows[start : start + page_size], "page": page, "size": page_size}
