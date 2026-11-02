/**
 * 前端表达式引擎：expr-eval（纯解析、无副作用）。严禁 new Function / eval。
 *
 * 在基础算术/比较/逻辑之上补齐 v2 内置函数：
 *   $ds / $state / $form / $user / $now / $uuid / $i18n / $if / $match
 *   $filter / $map / $find / $sum / $len
 * 同时支持模板插值 "Hello {{user.name}}"；整串只有一个插值时保留原始类型。
 */
import * as exprEval from "expr-eval";

type Scope = Record<string, any>;

const TEMPLATE_RE = /\{\{([\s\S]+?)\}\}/g;

function normalizeExpr(expr: string): string {
  let s = String(expr ?? "").trim();
  if (s.startsWith("{{") && s.endsWith("}}") && s.indexOf("{{", 2) === -1) {
    s = s.slice(2, -2).trim();
  }
  // expr-eval 不支持可选链/空值合并；降级为普通访问 / 逻辑或。
  s = s.replace(/\?\.\[/g, "[").replace(/\?\./g, ".");
  s = s.replace(/\?\?/g, "||");
  // $if 不能作为 expr-eval 的函数名（关键字冲突），映射为 if_。
  s = s.replace(/\$if\b/g, "if_");
  // $foo(...) / $foo → foo(...) / foo；函数与变量在下面注册。
  s = s.replace(/\$([A-Za-z_$][\w$]*)/g, "$1");
  return s;
}

function pathGet(obj: any, path: string | undefined): any {
  if (!path) return obj;
  let cur = obj;
  for (const part of String(path).split(".")) {
    if (cur === null || cur === undefined) return undefined;
    if (part === "*") return Array.isArray(cur) ? cur : [];
    cur = cur[part];
  }
  return cur;
}

function toNumber(v: any): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function makeParser(scope: Scope): exprEval.Parser {
  const p = new exprEval.Parser({
    operators: {
      logical: true,
      comparison: true,
      in: true,
      assignment: false,
    },
  } as any);

  p.functions.len = (v: any) => {
    if (v === null || v === undefined) return 0;
    if (Array.isArray(v) || typeof v === "string") return v.length;
    if (typeof v === "object") return Object.keys(v).length;
    return 0;
  };
  p.functions.sum = (arr: any, field?: string) => {
    if (!Array.isArray(arr)) return 0;
    return arr.reduce((acc, item) => acc + toNumber(field ? pathGet(item, field) : item), 0);
  };
  p.functions.map = (arr: any, field: string) => (Array.isArray(arr) ? arr.map((item) => pathGet(item, field)) : []);
  p.functions.filter = (arr: any, field: string, value?: any) => {
    if (!Array.isArray(arr)) return [];
    if (value === undefined) return arr.filter((item) => !!pathGet(item, field));
    return arr.filter((item) => pathGet(item, field) === value);
  };
  p.functions.find = (arr: any, field: string, value: any) => {
    if (!Array.isArray(arr)) return undefined;
    return arr.find((item) => pathGet(item, field) === value);
  };
  p.functions.if_ = (cond: any, a: any, b: any) => (cond ? a : b);
  p.functions.match = (value: any, pattern: any) => {
    try {
      return new RegExp(String(pattern)).test(String(value ?? ""));
    } catch {
      return false;
    }
  };
  p.functions.now = () => Date.now();
  p.functions.uuid = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
    return `wp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  };
  p.functions.i18n = (key: any) => scope.i18n?.[String(key)] ?? String(key ?? "");
  p.functions.state = (path?: string) => pathGet(scope.state ?? scope, path);
  p.functions.form = (path?: string) => pathGet(scope.form ?? {}, path);
  p.functions.ds = (name: any) => {
    const key = String(name ?? "");
    return scope[`ds_${key}`] ?? scope.datasourceResults?.[Number(key)] ?? undefined;
  };
  p.functions.user = () => scope.user ?? scope.$user ?? null;
  return p;
}

/** 模板插值：整串只有一个 {{expr}} 时返回原始类型，否则转字符串拼接。 */
export function interpolate(template: string, scope: Scope): any {
  if (typeof template !== "string" || !template.includes("{{")) return template;
  const whole = template.trim().match(/^\{\{([\s\S]+)\}\}$/);
  if (whole && whole[1].indexOf("{{") === -1) {
    return evaluateExpression(whole[1], scope);
  }
  return template.replace(TEMPLATE_RE, (_m, expr: string) => {
    const v = evaluateExpression(expr, scope);
    if (v === null || v === undefined) return "";
    if (typeof v === "object") {
      try {
        return JSON.stringify(v);
      } catch {
        return String(v);
      }
    }
    return String(v);
  });
}

export function evaluateExpression(expr: string | undefined, scope: Scope): any {
  if (!expr) return undefined;
  try {
    const p = makeParser(scope || {});
    const parsed = p.parse(normalizeExpr(expr));
    return parsed.evaluate({
      ...scope,
      now: Date.now(),
      uuid:
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `wp-${Date.now().toString(36)}`,
      user: scope?.user ?? scope?.$user,
      state: scope?.state ?? scope,
      form: scope?.form ?? {},
      i18n: scope?.i18n ?? {},
    });
  } catch {
    return undefined;
  }
}

export function checkExpression(expr: string): { ok: boolean; error?: string } {
  if (!expr) return { ok: true };
  try {
    const p = makeParser({});
    p.parse(normalizeExpr(expr));
    return { ok: true };
  } catch (e: any) {
    return { ok: false, error: String(e?.message || e) };
  }
}

/** 将作用域变量 + 事件参数组成表达式上下文。 */
export function buildScope(base: Record<string, any>, extra?: Record<string, any>): Record<string, any> {
  return { ...base, ...(extra || {}) };
}

/** 字符串/数组/对象中的 {{...}} 递归解析；用于未声明为绑定的普通 prop。 */
export function resolveTemplates(value: any, scope: Scope, depth = 0): any {
  if (depth > 8) return value;
  if (typeof value === "string") return interpolate(value, scope);
  if (Array.isArray(value)) return value.map((v) => resolveTemplates(v, scope, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(value)) out[k] = resolveTemplates(v, scope, depth + 1);
    return out;
  }
  return value;
}
