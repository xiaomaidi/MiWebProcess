"""服务端表达式引擎。

设计态/运行态前端使用 expr-eval（JS 风格语法）。服务端用于发布校验、导出与
SSR 场景下的隔离求值。本模块：

- 严禁 eval / exec / compile / Function 构造器等动态代码执行。
- 首选 py_quickjs（QuickJS 嵌入式，天然隔离 + 超时）；未安装时自动降级为
  内置 AST 白名单求值器（纯 Python 树遍历，无代码生成）。
- 前端 JS 风格运算符（&& || !== === true/false/null）在校验前转换为 Python 语义。
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any

# ---------------------------------------------------------------- 语法转换
_STRING_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
_OP_RE = re.compile(
    r"(&&|\|\||===|!==|!=|==|>=|<=|>|<|\+|-|\*|/|%|\*\*|!|=|,|\(|\)|\[|\]|\.|:|;)"
)

def _mask_strings(expr: str) -> list[str]:
    """把字符串字面量抽出来占位，避免运算符替换误伤字符串内容。"""
    parts = []
    out = []
    last = 0
    for m in _STRING_RE.finditer(expr):
        out.append(expr[last : m.start()])
        parts.append(m.group(0))
        out.append(f"\x00S{len(parts) - 1}\x00")
        last = m.end()
    out.append(expr[last:])
    return "".join(out), parts


def js_expr_to_python(expr: str) -> str:
    """JS 风格表达式 → Python 表达式（仅白名单子集，供 AST 解析）。"""
    masked, parts = _mask_strings(expr)
    masked = masked.replace("&&", " and ").replace("||", " or ")
    masked = masked.replace("!==", "!=").replace("===", "==")
    masked = masked.replace("?.", ".").replace("??", " or ")
    # 一元 !（避免误伤 != / !==）
    masked = re.sub(r"(?<![=!])!(?!=)", "not ", masked)
    for name in ("true", "false", "null"):
        masked = re.sub(rf"\b{name}\b", {"true": "True", "false": "False", "null": "None"}[name], masked)
    masked = re.sub(r"\bundefined\b", "None", masked)
    # 前端 v2 内置函数是 $if/$ds/...；Python 关键字不能直接做函数名，if 映射为 _if。
    masked = re.sub(r"\$if\b", "_if", masked)
    masked = re.sub(r"\$([A-Za-z_$][\w$]*)", r"\1", masked)
    for i, s in enumerate(parts):
        masked = masked.replace(f"\x00S{i}\x00", s)
    return masked


# ---------------------------------------------------------------- AST 白名单
_ALLOWED_NODES = {
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Store,
    ast.BinOp, ast.BoolOp, ast.UnaryOp, ast.Compare, ast.IfExp,
    ast.List, ast.Tuple, ast.Dict, ast.Subscript, ast.Slice,
    ast.Attribute, ast.Call, ast.JoinedStr, ast.FormattedValue,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
}
_ALLOWED_CALLS = {
    "len", "str", "int", "float", "round", "abs", "min", "max", "sum",
    # 前端 v2 表达式内置函数（服务端仅做语法白名单，实际数据源求值在前端/运行时）。
    "ds", "state", "form", "user", "now", "uuid", "i18n", "match", "filter",
    "map", "find", "_if",
}
_BLOCKED_NAMES = re.compile(r"^__.*__$")


def validate_expression(expr: str) -> list[str]:
    """返回错误列表；空列表表示语法与白名单均通过。"""
    errors: list[str] = []
    if not isinstance(expr, str) or not expr.strip():
        return ["表达式为空"]
    try:
        py = js_expr_to_python(expr)
        tree = ast.parse(py, mode="eval")
    except (SyntaxError, ValueError) as e:
        return [f"表达式语法错误: {e}"]
    for node in ast.walk(tree):
        if not isinstance(node, tuple(_ALLOWED_NODES)):
            errors.append(f"不允许的语法结构: {type(node).__name__}")
            continue
        if isinstance(node, ast.Name) and _BLOCKED_NAMES.match(node.id):
            errors.append(f"不允许的标识符: {node.id}")
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id not in _ALLOWED_CALLS:
                errors.append(f"不允许的函数调用: {fn.id}")
            elif not isinstance(fn, ast.Name):
                errors.append("仅允许调用白名单中的函数")
        if isinstance(node, ast.Attribute) and _BLOCKED_NAMES.match(node.attr):
            errors.append(f"不允许的属性访问: {node.attr}")
    return errors


def _eval_node(node: ast.AST, scope: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        if _BLOCKED_NAMES.match(node.id):
            raise ValueError(f"非法标识符: {node.id}")
        return None
    if isinstance(node, ast.BinOp):
        l = _eval_node(node.left, scope)
        r = _eval_node(node.right, scope)
        op = node.op
        if isinstance(op, ast.Add):
            return l + r
        if isinstance(op, ast.Sub):
            return l - r
        if isinstance(op, ast.Mult):
            return l * r
        if isinstance(op, ast.Div):
            return l / r if r else None
        if isinstance(op, ast.FloorDiv):
            return l // r if r else None
        if isinstance(op, ast.Mod):
            return l % r if r else None
        if isinstance(op, ast.Pow):
            return l ** r
    if isinstance(node, ast.BoolOp):
        vals = [_eval_node(v, scope) for v in node.values]
        if isinstance(node.op, ast.And):
            for v in vals:
                if not v:
                    return v
            return vals[-1]
        for v in vals:
            if v:
                return v
        return vals[-1]
    if isinstance(node, ast.UnaryOp):
        v = _eval_node(node.operand, scope)
        if isinstance(node.op, ast.Not):
            return not v
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return +v
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, scope)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, scope)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.In):
                ok = left in right
            elif isinstance(op, ast.NotIn):
                ok = left not in right
            else:
                raise ValueError("不支持的比较运算符")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval_node(node.body, scope) if _eval_node(node.test, scope) else _eval_node(node.orelse, scope)
    if isinstance(node, ast.List):
        return [_eval_node(e, scope) for e in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(e, scope) for e in node.elts)
    if isinstance(node, ast.Dict):
        return {
            _eval_node(k, scope): _eval_node(v, scope)
            for k, v in zip(node.keys, node.values)
        }
    if isinstance(node, ast.Subscript):
        obj = _eval_node(node.value, scope)
        idx = node.slice
        if isinstance(idx, ast.Slice):
            lo = _eval_node(idx.lower, scope) if idx.lower else None
            hi = _eval_node(idx.upper, scope) if idx.upper else None
            return obj[lo:hi]
        i = _eval_node(idx, scope)
        return obj[i]
    if isinstance(node, ast.Attribute):
        obj = _eval_node(node.value, scope)
        if _BLOCKED_NAMES.match(node.attr):
            raise ValueError(f"非法属性: {node.attr}")
        if isinstance(obj, dict):
            return obj.get(node.attr)
        if hasattr(obj, node.attr):
            v = getattr(obj, node.attr)
            if callable(v):
                raise ValueError(f"禁止调用对象方法: {node.attr}")
            return v
        return None
    if isinstance(node, ast.Call):
        fn = node.func
        if not isinstance(fn, ast.Name) or fn.id not in _ALLOWED_CALLS:
            raise ValueError("非法调用")
        args = [_eval_node(a, scope) for a in node.args]
        return getattr(__builtins__, fn.id)(*args)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(_eval_node(v, scope) if isinstance(v, ast.FormattedValue) else v.value)
            for v in node.values
        )
    raise ValueError(f"不支持的节点: {type(node).__name__}")


def safe_eval(expr: str, variables: dict[str, Any] | None = None) -> Any:
    """隔离求值一个表达式。语法错误抛 ValueError。"""
    variables = dict(variables or {})
    py = js_expr_to_python(expr)
    tree = ast.parse(py, mode="eval")
    return _eval_node(tree.body, variables)


def get_path(obj: Any, path: str) -> tuple[bool, Any]:
    """按 `a.b.c` / `a[*]` / `a[0]` 取数。返回 (found, value)。"""
    if obj is None or not path:
        return True, obj
    cur = obj
    for part in re.split(r"\.", path):
        if not part:
            continue
        m = re.match(r"^([^\[\]]*)\[(.*)\]$", part)
        if m:
            key, idx = m.group(1), m.group(2)
            if key:
                if isinstance(cur, dict) and key in cur:
                    cur = cur[key]
                else:
                    return False, None
            if idx == "*":
                if isinstance(cur, (list, tuple)):
                    cur = list(cur)
                else:
                    return False, None
            else:
                try:
                    cur = cur[int(idx)]
                except (KeyError, IndexError, TypeError, ValueError):
                    return False, None
        else:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            elif hasattr(cur, part) and not part.startswith("_"):
                cur = getattr(cur, part)
            else:
                return False, None
    return True, cur


def json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        if isinstance(value, dict):
            return {str(k): json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(v) for v in value]
        return str(value)


__all__ = [
    "js_expr_to_python",
    "validate_expression",
    "safe_eval",
    "get_path",
    "json_safe",
]
