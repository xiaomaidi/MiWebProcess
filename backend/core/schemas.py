"""PageSchema 校验器（草稿保存=宽松，发布=严格）。

registry: {component_name: meta_dict}，未知组件在严格模式下报错。
返回 (errors, warnings)：errors 阻塞发布，warnings 仅提示。

wp-canvas 是画布根（设计器内置），不参与组件注册表校验。
"""
from __future__ import annotations

from typing import Any, Iterable

# 内置特殊组件（不走注册表校验）
SPECIAL_COMPONENTS = {"wp-canvas"}

from .expr import validate_expression
from .sanitize import check_html

SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = {1, 2}

_ACTION_KINDS = {
    "setVariable",
    "callDatasource",
    "navigate",
    "openModal",
    "closeModal",
    "openDrawer",
    "closeDrawer",
    "message",
    "notification",
    "confirm",
    "record",
    "condition",
    "loop",
    "parallel",
    "tryCatch",
    "delay",
    "setStyle",
    "emit",
    "submitForm",
    "resetForm",
    "download",
    "copy",
    "print",
    "http",
    "js",
}

def _check_js_action(code: str) -> list[str]:
    """受限 JS：只允许表达式，禁止语句/动态执行/DOM 访问。"""
    import re

    text = str(code or "").strip()
    if not text:
        return ["js 动作代码为空"]
    forbidden = re.compile(
        r"(?:\beval\b|\bFunction\b|\bwindow\b|\bdocument\b|\bfetch\b|XMLHttpRequest|localStorage|"
        r"sessionStorage|import\s*\(|=>|;|\bnew\b|\bwhile\b|\bfor\b|\breturn\b)",
        re.IGNORECASE,
    )
    if forbidden.search(text):
        return ["js 动作仅允许表达式，禁止语句/动态执行/DOM 访问"]
    # 括号必须成对（不追求完整 JS 语法，发布前的完整校验由前端 expr-eval 负责）。
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack: list[str] = []
    for ch in text:
        if ch in pairs:
            stack.append(ch)
        elif ch in pairs.values():
            if not stack or pairs[stack.pop()] != ch:
                return ["js 动作括号不匹配"]
    if stack:
        return ["js 动作括号不匹配"]
    return []


def _check_prop_schema(node_id: str, key: str, value: Any, ps: dict, errors: list[str]) -> None:
    """轻量 JSON Schema 校验（type/enum/min/max）；绑定值跳过。"""
    if not isinstance(ps, dict):
        return
    if isinstance(value, dict) and "__binding__" in value:
        return
    typ = ps.get("type")
    checks = {
        "string": lambda v: isinstance(v, str),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "array": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }
    if typ in checks and not checks[typ](value):
        errors.append(f"[{node_id}] props.{key} 类型应为 {typ}")
        return
    if "enum" in ps and value not in ps["enum"]:
        errors.append(f"[{node_id}] props.{key} 不在枚举范围: {value}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in ps and value < ps["minimum"]:
            errors.append(f"[{node_id}] props.{key} 小于最小值 {ps['minimum']}")
        if "maximum" in ps and value > ps["maximum"]:
            errors.append(f"[{node_id}] props.{key} 大于最大值 {ps['maximum']}")

_LOOP_VAR_RE = None


def _iter_nodes(schema: dict) -> Iterable[dict]:
    for node in (schema.get("nodes") or {}).values():
        if isinstance(node, dict):
            yield node


def _check_binding(binding: Any, warnings: list[str], node_id: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(binding, dict):
        return ["dataBinding 必须是对象"]
    source = binding.get("source")
    if source not in ("variable", "datasource", "model", "form"):
        errors.append(f"[{node_id}] dataBinding.source 非法: {source}")
    if not isinstance(binding.get("ref"), str) or not binding.get("ref"):
        errors.append(f"[{node_id}] dataBinding.ref 缺失")
    if binding.get("field") is not None and not isinstance(binding["field"], str):
        errors.append(f"[{node_id}] dataBinding.field 必须是字符串")
    if binding.get("loopVar") is not None and not isinstance(binding["loopVar"], str):
        errors.append(f"[{node_id}] dataBinding.loopVar 必须是字符串")
    if binding.get("transform"):
        errors.extend(f"[{node_id}] " + e for e in validate_expression(binding["transform"]))
    return errors


def _check_action_steps(steps: Any, errors: list[str], node_id: str, path: str = "") -> None:
    if steps is None:
        return
    if not isinstance(steps, list):
        errors.append(f"[{node_id}] events 动作链必须是数组")
        return
    for i, step in enumerate(steps):
        p = f"{path}[{i}]"
        if not isinstance(step, dict):
            errors.append(f"[{node_id}] {p} 动作必须是对象")
            continue
        kind = step.get("kind")
        if kind not in _ACTION_KINDS:
            errors.append(f"[{node_id}] {p} 非法动作类型: {kind}")
            continue
        if not isinstance(step.get("params", {}), dict):
            errors.append(f"[{node_id}] {p} params 必须是对象")
        if kind == "condition":
            expr = (step.get("params") or {}).get("expr", "")
            errors.extend(f"[{node_id}] {p} " + e for e in validate_expression(expr))
            _check_action_steps(step.get("then"), errors, node_id, p + ".then")
            _check_action_steps(step.get("else"), errors, node_id, p + ".else")
        elif kind in ("confirm", "loop", "parallel", "tryCatch"):
            if kind == "loop":
                list_expr = (step.get("params") or {}).get("list", "")
                if isinstance(list_expr, str) and list_expr.strip():
                    errors.extend(f"[{node_id}] {p} " + e for e in validate_expression(list_expr))
            _check_action_steps(step.get("then"), errors, node_id, p + ".then")
            _check_action_steps(step.get("else"), errors, node_id, p + ".else")
            _check_action_steps(step.get("catch"), errors, node_id, p + ".catch")
        elif kind == "js":
            code = (step.get("params") or {}).get("code", "")
            errors.extend(f"[{node_id}] {p} " + e for e in _check_js_action(code))


def _collect_known_names(schema: dict) -> set[str]:
    names = {"page", "app", "null", "true", "false"}
    for v in (schema.get("variables") or {}).values():
        if isinstance(v, dict) and v.get("name"):
            names.add(v["name"])
        elif isinstance(v, dict):
            pass
    for key in (schema.get("variables") or {}).keys():
        names.add(key)
    for node in _iter_nodes(schema):
        b = node.get("dataBinding")
        if isinstance(b, dict) and b.get("loopVar"):
            names.add(b["loopVar"])
        name = node.get("_form_var")  # 由 validate_page_schema 注入
        if name:
            names.add(name)
    names.update(f"ds_{i}" for i in range(200))
    names.update(f"form_{i}" for i in range(200))
    return names


def _check_unknown_variables(schema: dict, warnings: list[str]) -> None:
    known = _collect_known_names(schema)
    import re

    for node in _iter_nodes(schema):
        exprs = []
        if node.get("condition"):
            exprs.append(node["condition"].get("expr", ""))
        for chain in (node.get("events") or {}).values():
            for step in chain if isinstance(chain, list) else []:
                if isinstance(step, dict) and (step.get("params") or {}).get("expr"):
                    exprs.append(step["params"]["expr"])
        if isinstance(node.get("dataBinding"), dict) and node["dataBinding"].get("transform"):
            exprs.append(node["dataBinding"]["transform"])
        for expr in exprs:
            for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", expr or ""):
                if m.group(1) not in known and m.group(1) not in (
                    "len", "str", "int", "float", "round", "abs", "min", "max", "sum", "not", "and", "or",
                    "item", "index", "error", "value", "state", "form", "user", "app", "page", "now",
                    "ds", "map", "filter", "find", "if", "match", "uuid", "i18n", "true", "false", "null",
                ):
                    warnings.append(f"[{node.get('id')}] 表达式引用了未知变量: {m.group(1)}")
                    break


def validate_page_schema(
    schema: Any,
    registry: dict[str, dict] | None = None,
    strict: bool = True,
) -> tuple[list[str], list[str]]:
    """校验 PageSchema。strict=True 用于发布（未知组件/孤儿节点报错）。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(schema, dict):
        return ["schema 必须是 JSON 对象"], warnings

    sv = schema.get("schemaVersion")
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(f"schemaVersion 必须为 {SCHEMA_VERSION} 或兼容的 1")
    elif sv == 1:
        warnings.append("schemaVersion=1 为旧格式，建议保存为新版 v2")
    nodes = schema.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return errors + ["nodes 缺失或为空"], warnings
    root_id = schema.get("rootId")
    if not isinstance(root_id, str) or root_id not in nodes:
        errors.append("rootId 缺失或不在 nodes 中")
        return errors, warnings
    if not isinstance(schema.get("layout"), dict):
        warnings.append("layout 缺失，使用默认流式布局")

    # 资产 / 变量
    for key, asset in (schema.get("assets") or {}).items():
        if not isinstance(asset, dict) or not asset.get("url"):
            errors.append(f"assets[{key}] 非法")
    variables = schema.get("variables") or {}
    if not isinstance(variables, dict):
        errors.append("variables 必须是对象")
        variables = {}
    for key, var in variables.items():
        if not isinstance(var, dict) or "value" not in var:
            errors.append(f"variables[{key}] 非法（需 {{value, scope}}）")

    # 页面级 meta / 全局样式 / SEO
    meta = schema.get("meta")
    if meta is not None:
        if not isinstance(meta, dict):
            errors.append("meta 必须是对象")
        else:
            for key in ("title", "favicon", "lang", "description", "keywords", "ogImage", "head"):
                if meta.get(key) is not None and not isinstance(meta[key], str):
                    errors.append(f"meta.{key} 必须是字符串")
            if meta.get("head"):
                _, head_issues = check_html(meta["head"])
                errors.extend(f"meta.head: {e}" for e in head_issues)
            style = meta.get("globalStyle")
            if style is not None:
                if not isinstance(style, dict):
                    errors.append("meta.globalStyle 必须是对象")
                elif isinstance(style.get("cssVars"), dict):
                    for k in style["cssVars"]:
                        if not isinstance(k, str) or not k.startswith("--"):
                            errors.append(f"meta.globalStyle.cssVars 键必须以 -- 开头: {k}")
    if schema.get("customCss") is not None and not isinstance(schema.get("customCss"), str):
        errors.append("customCss 必须是字符串")

    # 节点基础字段
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            errors.append(f"nodes[{nid}] 必须是对象")
            continue
        if node.get("id") != nid:
            errors.append(f"nodes[{nid}].id 与键不一致")
        if not isinstance(node.get("type"), str) or not node.get("type"):
            errors.append(f"[{nid}] type 缺失")
        if not isinstance(node.get("componentVersion"), str):
            warnings.append(f"[{nid}] componentVersion 缺失")
        if not isinstance(node.get("props"), dict):
            errors.append(f"[{nid}] props 必须是对象")
            continue
        for pname, pval in node["props"].items():
            if (
                isinstance(pval, dict)
                and "__binding__" in pval
                and not (set(pval.keys()) == {"__binding__"} or isinstance(pval.get("__binding__"), dict))
            ):
                errors.append(f"[{nid}] props.{pname} 绑定对象非法")
            if isinstance(pval, dict) and "__binding__" in pval:
                errors.extend(_check_binding(pval["__binding__"], warnings, nid))
        if node.get("style") is not None and not isinstance(node.get("style"), dict):
            errors.append(f"[{nid}] style 必须是对象")
        if node.get("customCss") is not None and not isinstance(node.get("customCss"), str):
            errors.append(f"[{nid}] customCss 必须是字符串")
        if node.get("children") is not None and not isinstance(node.get("children"), list):
            errors.append(f"[{nid}] children 必须是数组")
        if node.get("slots") is not None:
            slots = node["slots"]
            if not isinstance(slots, dict):
                errors.append(f"[{nid}] slots 必须是对象")
            else:
                for sname, ids in slots.items():
                    if not isinstance(ids, list):
                        errors.append(f"[{nid}] slots.{sname} 必须是数组")
        b = node.get("dataBinding")
        if b is not None:
            errors.extend(_check_binding(b, warnings, nid))
        cond = node.get("condition")
        if cond is not None:
            if not isinstance(cond, dict) or not isinstance(cond.get("expr"), str):
                errors.append(f"[{nid}] condition 必须是 {{expr}}")
            else:
                errors.extend(f"[{nid}] " + e for e in validate_expression(cond["expr"]))
        for ename, chain in (node.get("events") or {}).items():
            if not isinstance(ename, str) or not ename:
                errors.append(f"[{nid}] 事件名非法")
            _check_action_steps(chain, errors, nid, f"events.{ename}")

    # 引用完整性：children / slots 指向的 id 必须存在
    for nid, node in nodes.items():
        if not isinstance(node, dict):
            continue
        for child in node.get("children") or []:
            if child not in nodes:
                errors.append(f"[{nid}] children 引用了不存在的节点: {child}")
        for sname, ids in (node.get("slots") or {}).items():
            for child in ids if isinstance(ids, list) else []:
                if child not in nodes:
                    errors.append(f"[{nid}] slots.{sname} 引用了不存在的节点: {child}")

    # 环检测（children + slots 边）
    def children_of(nid: str) -> list[str]:
        node = nodes.get(nid) or {}
        out = list(node.get("children") or [])
        for ids in (node.get("slots") or {}).values():
            if isinstance(ids, list):
                out.extend(ids)
        return [c for c in out if isinstance(c, str) and c in nodes]

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in nodes}

    def dfs(nid: str) -> bool:
        color[nid] = GRAY
        for c in children_of(nid):
            if color[c] == GRAY:
                return True
            if color[c] == WHITE and dfs(c):
                return True
        color[nid] = BLACK
        return False

    if dfs(root_id):
        errors.append("节点树存在循环引用")

    # 孤儿节点（从 root 不可达）
    reached: set[str] = set()
    stack = [root_id]
    while stack:
        nid = stack.pop()
        if nid in reached:
            continue
        reached.add(nid)
        stack.extend(children_of(nid))
    for nid in nodes:
        if nid not in reached:
            (errors if strict else warnings).append(f"孤儿节点（从 root 不可达）: {nid}")

    # 组件注册表 + accept_children 白名单
    if registry:
        for nid, node in nodes.items():
            if not isinstance(node, dict):
                continue
            if node.get("type") in SPECIAL_COMPONENTS:
                continue
            meta = registry.get(node.get("type"))
            if meta is None:
                (errors if strict else warnings).append(f"[{nid}] 未知组件类型: {node.get('type')}")
                continue

            # 组件版本兼容：主版本不同给 warning（运行时仍按注册表渲染），缺失给 warning。
            expected = str(meta.get("version") or "")
            actual = str(node.get("componentVersion") or "")
            if not actual:
                warnings.append(f"[{nid}] componentVersion 缺失")
            elif expected and actual.split(".")[0] != expected.split(".")[0]:
                warnings.append(f"[{nid}] 组件版本 {actual} 与注册表 {expected} 主版本不一致")

            # props_schema 轻量校验
            declared_props = ((meta.get("props_schema") or {}).get("properties") or {})
            for pname, pval in (node.get("props") or {}).items():
                ps = declared_props.get(pname)
                if ps:
                    _check_prop_schema(nid, pname, pval, ps, errors)

            # HTML / SVG 白名单
            if node.get("type") == "html":
                raw = str((node.get("props") or {}).get("html") or "")
                cleaned, issues = check_html(raw)
                errors.extend(f"[{nid}] {e}" for e in issues)
                if not issues and cleaned != raw.strip():
                    warnings.append(f"[{nid}] HTML 已按白名单清洗")
            elif node.get("type") == "svg":
                raw = str((node.get("props") or {}).get("code") or "")
                _, issues = check_html(raw, allow_svg=True)
                errors.extend(f"[{nid}] {e}" for e in issues)

            allow = meta.get("accept_children") or meta.get("accepts")
            if allow and "*" not in allow:
                for child in children_of(nid):
                    ctype = nodes[child].get("type")
                    if ctype not in allow:
                        errors.append(f"[{nid}] 组件 {meta.get('name')} 不接受子组件 {ctype}")
            declared_slots = meta.get("slots") or []
            for sname in (node.get("slots") or {}):
                if declared_slots and sname not in declared_slots:
                    errors.append(f"[{nid}] 组件 {meta.get('name')} 未声明插槽 {sname}")

    _check_unknown_variables(schema, warnings)
    return errors, warnings


__all__ = ["validate_page_schema", "SCHEMA_VERSION"]
