/** 数据绑定解析（与 API.md / 后端 core/schemas.py 的 __binding__ 结构对应）。 */
import type { DataBinding, RuntimeScope } from "@/types";
import { evaluateExpression, resolveTemplates } from "./expr";
import { getPathValue } from "@/utils";

/** prop 值是否为绑定对象。 */
export function isBindingValue(v: any): v is { __binding__: DataBinding } {
  return !!v && typeof v === "object" && !Array.isArray(v) && v.__binding__ && typeof v.__binding__ === "object";
}

/** "ds_1" / "1" → 数字 id。 */
export function refToId(ref: string): number {
  const m = String(ref ?? "").replace(/^(ds|model|form)_/, "");
  return Number(m) || 0;
}

/**
 * 组装表达式求值作用域：
 * variables + ds_<id> + model_<id> + form_<ref> + 循环变量 + 页面/用户/表单别名。
 */
export function buildScope(scope: RuntimeScope, extra?: Record<string, any>): Record<string, any> {
  const s: Record<string, any> = { ...scope.variables };
  const dsByName: Record<string, any> = {};
  for (const [id, v] of Object.entries(scope.datasourceResults)) {
    s[`ds_${id}`] = v;
    dsByName[`ds_${id}`] = v;
  }
  for (const [id, v] of Object.entries(scope.modelResults)) s[`model_${id}`] = v;
  for (const [ref, v] of Object.entries(scope.formValues)) s[`form_${ref}`] = v;
  for (const [name, v] of Object.entries(scope.loopVars)) s[name] = v;
  // 便捷别名（$state / $form / $user / $app / $page）。
  const allFormValues = Object.assign({}, ...Object.values(scope.formValues).map((v) => ({ ...(v || {}) })));
  s.state = s.state ?? scope.variables;
  s.form = scope.variables.form ?? allFormValues;
  s.user = scope.variables.user ?? scope.variables.currentUser ?? null;
  s.app = scope.variables.app ?? null;
  s.page = scope.variables.page ?? null;
  s.route = scope.routeParams ?? {};
  s.params = scope.routeParams ?? {};
  s.datasourceResults = scope.datasourceResults;
  s.modelResults = scope.modelResults;
  s.formValues = scope.formValues;
  s.i18n = scope.variables.i18n ?? {};
  s.dsByName = dsByName;
  if (extra) Object.assign(s, extra);
  return s;
}

/** 取绑定基础对象。 */
function baseFor(binding: DataBinding, scope: RuntimeScope): any {
  switch (binding.source) {
    case "variable":
      return scope.variables[binding.ref];
    case "datasource":
      return scope.datasourceResults[refToId(binding.ref)];
    case "model":
      return scope.modelResults[refToId(binding.ref)];
    case "form":
      return scope.formValues[binding.ref.startsWith("form_") ? binding.ref.slice(5) : binding.ref];
    default:
      return undefined;
  }
}

/** 解析一个绑定：基础对象 → 字段路径（支持 [*]）→ transform 表达式；失败回退 defaultValue。 */
export function resolveBinding(binding: DataBinding, scope: RuntimeScope, extra?: Record<string, any>): any {
  const base = baseFor(binding, scope);
  let found = !binding.field;
  let value: any = binding.field ? getPathValue(base, binding.field).value : base;
  if (binding.field) found = getPathValue(base, binding.field).found;
  if (!found) value = binding.defaultValue;
  if (binding.transform) {
    value = evaluateExpression(binding.transform, buildScope(scope, { ...extra, value }));
  }
  if (value === undefined && binding.defaultValue !== undefined) value = binding.defaultValue;
  return value;
}

/** 解析组件全部 props 中的绑定与 {{...}} 模板。 */
export function resolveProps(props: Record<string, any>, scope: RuntimeScope, extra?: Record<string, any>): Record<string, any> {
  const ctx = buildScope(scope, extra);
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(props)) {
    out[k] = isBindingValue(v) ? resolveBinding(v.__binding__, scope, extra) : resolveTemplates(v, ctx);
  }
  return out;
}

/** 循环渲染：取 node.dataBinding 指向的数组（兼容 Paged {results}）。 */
export function resolveLoopItems(nodeDataBinding: DataBinding | null | undefined, scope: RuntimeScope, extra?: Record<string, any>): any[] {
  if (!nodeDataBinding) return [];
  const v = resolveBinding(nodeDataBinding, scope, extra);
  if (Array.isArray(v)) return v;
  if (v && typeof v === "object") {
    for (const key of ["results", "rows", "items", "data", "records"]) {
      if (Array.isArray((v as any)[key])) return (v as any)[key];
    }
    if (v !== undefined) return [v];
  }
  return [];
}
