/**
 * 可视化数据绑定的纯函数工具：
 * - 绑定 → 人话摘要 / 表达式（保持 `{{...}}` 与字段路径语法不变）
 * - 设计时值 / 形状预览、类型兼容提示
 * - 数据源静态数据 / 响应映射字段推导
 * - 条件表达式摘要
 */
import { refToId } from "@/engine/binding";
import { getPathValue } from "@/utils";
import type { ComponentPropSchema, DataBinding, DataModelInfo, DataSourceDef } from "@/types";

export type BindingSource = DataBinding["source"];
export type ValueKind = "array" | "object" | "string" | "number" | "boolean" | "null" | "unknown";

export interface BindingContext {
  datasources?: DataSourceDef[];
  models?: DataModelInfo[];
  variables?: Record<string, { value: any; scope?: string }>;
}

export interface BindingPickPayload {
  binding: DataBinding;
  expression: string;
  mode: "binding" | "expression";
}

export interface BindingRefOption {
  value: string;
  label: string;
  sub?: string;
  preview?: string;
  type?: ValueKind;
}

export interface BindingPreview {
  available: boolean;
  value?: any;
  text: string;
  hint?: string;
}

export const SOURCE_LABELS: Record<BindingSource, string> = {
  variable: "页面变量",
  datasource: "数据源",
  model: "数据模型",
  form: "表单",
};

/** 绑定引用的展示名（未找到时给出明确提示，而不是空白）。 */
export function refDisplayName(binding: Pick<DataBinding, "source" | "ref">, ctx: BindingContext = {}): string {
  const ref = String(binding.ref ?? "").trim();
  if (!ref) return `${SOURCE_LABELS[binding.source]}（未选择）`;
  if (binding.source === "variable") {
    const exists = !!ctx.variables && Object.prototype.hasOwnProperty.call(ctx.variables, ref);
    return `变量 ${ref}${exists ? "" : "（未定义）"}`;
  }
  if (binding.source === "datasource") {
    const ds = (ctx.datasources ?? []).find((d) => Number(d.id) === refToId(ref));
    return ds ? `数据源 ${ds.name}（#${ds.id}）` : `数据源 #${refToId(ref)}（未找到）`;
  }
  if (binding.source === "model") {
    const model = (ctx.models ?? []).find((m) => Number(m.id) === refToId(ref));
    return model ? `数据模型 ${model.name}（#${model.id}）` : `数据模型 #${refToId(ref)}（未找到）`;
  }
  const formId = ref.startsWith("form_") ? ref.slice(5) : ref;
  return `表单 ${formId || "（未选择）"}`;
}

/** 绑定求值的基础变量名（与 buildScope 中的作用域名一致）。 */
export function bindingBase(binding: Pick<DataBinding, "source" | "ref">): string {
  const ref = String(binding.ref ?? "").trim();
  if (binding.source === "variable") return ref;
  if (binding.source === "datasource") return `ds_${refToId(ref)}`;
  if (binding.source === "model") return `model_${refToId(ref)}`;
  return ref.startsWith("form_") ? ref : `form_${ref}`;
}

/** 拼接基础名与字段路径（字段以 [ 开头时不加分隔点）。 */
export function joinFieldPath(base: string, field?: string | null): string {
  const f = String(field ?? "").trim();
  if (!f) return base;
  return f.startsWith("[") ? `${base}${f}` : `${base}.${f}`;
}

/** 结构化绑定 → 表达式路径（如 model_1.results[*].name）。 */
export function bindingExpression(binding: Pick<DataBinding, "source" | "ref" | "field">): string {
  return joinFieldPath(bindingBase(binding), binding.field);
}

/** 结构化绑定 → 模板表达式 {{...}}，可直接写入普通 prop（向后兼容）。 */
export function bindingTemplate(binding: Pick<DataBinding, "source" | "ref" | "field">): string {
  return `{{${bindingExpression(binding)}}}`;
}

/** 绑定的人话摘要。 */
export function bindingSummary(binding: DataBinding | null | undefined, ctx: BindingContext = {}): string {
  if (!binding) return "未绑定";
  const parts = [refDisplayName(binding, ctx)];
  if (binding.field) parts.push(`字段 ${binding.field}`);
  if (binding.loopVar) parts.push(`循环变量 ${binding.loopVar}`);
  return parts.join(" · ");
}

/** 选中字段的简短文案（列表行用）。 */
export function fieldLabelOf(binding: DataBinding | null | undefined): string {
  if (!binding) return "";
  return binding.field ? binding.field : "整个结果";
}

/** 安全预览任意值（字符串带引号，超长截断）。 */
export function formatValue(value: unknown, max = 72): string {
  if (value === undefined) return "未定义";
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value.length > max ? `${value.slice(0, max)}…` : value);
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  let text = "";
  try {
    text = JSON.stringify(value);
  } catch {
    text = String(value);
  }
  if (text === undefined) text = String(value);
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

export function valueKind(value: unknown): ValueKind {
  if (Array.isArray(value)) return "array";
  if (value === null) return "null";
  switch (typeof value) {
    case "object":
      return "object";
    case "string":
      return "string";
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    default:
      return "unknown";
  }
}

export function valueKindLabel(kind: ValueKind): string {
  const map: Record<ValueKind, string> = {
    array: "数组",
    object: "对象",
    string: "文本",
    number: "数字",
    boolean: "布尔",
    null: "空值",
    unknown: "未知",
  };
  return map[kind];
}

/** 值的“形状”标签，例如 数组(3) / 对象{5}。 */
export function shapeLabel(value: unknown): string {
  const kind = valueKind(value);
  if (kind === "array") return `数组(${(value as any[]).length})`;
  if (kind === "object") return `对象{${Object.keys(value as object).length}}`;
  return valueKindLabel(kind);
}

/** JSON Schema 属性类型 → 值类别。 */
export function kindOfSchemaType(type?: string): ValueKind | "any" {
  switch (String(type ?? "").toLowerCase()) {
    case "array":
      return "array";
    case "object":
      return "object";
    case "integer":
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "string":
      return "string";
    case "null":
      return "null";
    default:
      return "any";
  }
}

/** 数据模型字段类型 → 值类别（用于绑定类型提示）。 */
export function kindOfModelField(type?: string): ValueKind {
  const t = String(type ?? "").toLowerCase();
  if (["multiselect", "tags", "attachments", "references", "array"].includes(t)) return "array";
  if (["json", "geolocation", "object"].includes(t)) return "object";
  if (["number", "integer", "decimal", "money", "percent", "rating", "duration"].includes(t)) return "number";
  if (["boolean"].includes(t)) return "boolean";
  if (["reference", "user", "department"].includes(t)) return "unknown";
  return "string";
}

/** 属性期望类型与绑定字段类型的兼容提示；空字符串表示没有明显问题。 */
export function compatibilityWarning(expectedType: string | undefined, actualKind: ValueKind | "any"): string {
  const expected = kindOfSchemaType(expectedType);
  if (
    expected === "any" ||
    actualKind === "unknown" ||
    actualKind === "any" ||
    actualKind === "null" ||
    expected === actualKind
  ) {
    return "";
  }
  if (expected === "array") return "属性期望数组，当前字段不是数组；循环/列表场景可能无法渲染";
  if (expected === "object") return "属性期望对象，当前字段不是对象";
  if (expected === "number") return "属性期望数字，当前字段不是数字；建议配合 transform 转换";
  if (expected === "boolean") return "属性期望布尔值，当前字段不是布尔值；建议配合 transform 转换";
  if (expected === "string" && (actualKind === "object" || actualKind === "array")) {
    return "属性期望文本，当前字段是对象/数组；建议配合 transform 取标量";
  }
  return `属性期望${valueKindLabel(expected as ValueKind)}，当前字段为${valueKindLabel(actualKind as ValueKind)}`;
}

export function findDatasource(datasources: DataSourceDef[] | undefined, ref: string | number): DataSourceDef | undefined {
  const id = typeof ref === "number" ? ref : refToId(ref);
  return (datasources ?? []).find((d) => Number(d.id) === id);
}

export function findModel(models: DataModelInfo[] | undefined, ref: string | number): DataModelInfo | undefined {
  const id = typeof ref === "number" ? ref : refToId(ref);
  return (models ?? []).find((m) => Number(m.id) === id);
}

/** 静态数据源的 config.data（设计器内可直接预览真实结构）。 */
export function staticDatasourceData(ds: DataSourceDef | null | undefined): unknown {
  if (!ds) return undefined;
  const cfg = (ds.config ?? {}) as Record<string, any>;
  if (Object.prototype.hasOwnProperty.call(cfg, "data")) return cfg.data;
  if (typeof cfg.sample === "string") {
    try {
      return JSON.parse(cfg.sample);
    } catch {
      return undefined;
    }
  }
  return undefined;
}

/** REST 数据源 response_map 的可选字段（映射后的顶层 key）。 */
export function responseMapFields(ds: DataSourceDef | null | undefined): string[] {
  if (!ds) return [];
  const map = (ds.config ?? {}) as Record<string, any>;
  const raw = map.response_map;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return [];
  return Object.keys(raw).slice(0, 30);
}

/** 数据源配置的一句话摘要。 */
export function datasourceHint(ds: DataSourceDef | null | undefined): string {
  if (!ds) return "未选择数据源";
  const cfg = (ds.config ?? {}) as Record<string, any>;
  const type = String(ds.type ?? "").toUpperCase();
  if (type === "STATIC") {
    const data = staticDatasourceData(ds);
    return `静态数据 · ${shapeLabel(data)}`;
  }
  if (type === "WEBSOCKET") return `WebSocket · ${cfg.url || "未配置地址"}`;
  if (type === "REST") {
    const method = String(cfg.method || "GET").toUpperCase();
    return `REST · ${method} ${cfg.url || "未配置地址"}`;
  }
  if (["SQL", "MYSQL", "POSTGRES", "SQLSERVER"].includes(type)) {
    return `${type} · ${cfg.database || "未配置数据库"}${cfg.query ? " · 自定义查询" : ""}`;
  }
  return `${type || "数据源"}${cfg.url ? ` · ${cfg.url}` : ""}`;
}

/** 绑定在设计器内的可预览值（数据源仅静态数据；模型/表单运行时才有值）。 */
export function bindingPreview(binding: DataBinding | null | undefined, ctx: BindingContext = {}): BindingPreview {
  if (!binding) return { available: false, text: "未绑定" };
  if (binding.source === "variable") {
    if (!binding.ref) return { available: false, text: "未选择变量", hint: "请选择页面变量" };
    if (!ctx.variables || !Object.prototype.hasOwnProperty.call(ctx.variables, binding.ref)) {
      return { available: false, text: "变量未定义", hint: "可在左侧变量面板创建该变量" };
    }
    const base = ctx.variables[binding.ref]?.value;
    if (!binding.field) return { available: true, value: base, text: formatValue(base) };
    const res = getPathValue(base, binding.field);
    if (!res.found) return { available: false, text: "字段未命中", hint: `当前变量中没有 ${binding.field}` };
    return { available: true, value: res.value, text: formatValue(res.value) };
  }
  if (binding.source === "datasource") {
    const ds = findDatasource(ctx.datasources, binding.ref);
    if (!ds) return { available: false, text: "数据源未找到" };
    const data = staticDatasourceData(ds);
    if (data === undefined) return { available: false, text: "运行时取数", hint: "数据源结果需在预览或运行时获取" };
    if (!binding.field) return { available: true, value: data, text: formatValue(data) };
    const res = getPathValue(data, binding.field);
    return res.found
      ? { available: true, value: res.value, text: formatValue(res.value) }
      : { available: false, text: "字段未命中", hint: `静态数据中没有 ${binding.field}` };
  }
  if (binding.source === "model") {
    const model = findModel(ctx.models, binding.ref);
    if (!model) return { available: false, text: "数据模型未找到" };
    return {
      available: false,
      text: "运行时取数",
      hint: `模型字段：${(model.fields ?? []).map((f) => f.name).slice(0, 6).join("、") || "暂无字段"}`,
    };
  }
  return { available: false, text: "运行时取表单值" };
}

/** 条件表达式摘要：把常见比较/逻辑表达式翻译成中文。 */
export function describeCondition(expr: string | null | undefined): string {
  const raw = stripOuterBraces(String(expr ?? "").trim());
  if (!raw) return "未设置表达式";
  if (raw === "true") return "始终显示";
  if (raw === "false") return "始终隐藏";
  return summarizeConditionExpr(raw, 0);
}

function stripOuterBraces(expr: string): string {
  const s = expr.trim();
  if (s.startsWith("{{") && s.endsWith("}}") && s.indexOf("{{", 2) === -1) return s.slice(2, -2).trim();
  return s;
}

function stripOuterParens(expr: string): string {
  let s = expr.trim();
  while (s.startsWith("(") && s.endsWith(")") && balanced(s.slice(1, -1))) s = s.slice(1, -1).trim();
  return s;
}

function balanced(s: string): boolean {
  let depth = 0;
  let quote = "";
  for (const ch of s) {
    if (quote) {
      if (ch === quote) quote = "";
      continue;
    }
    if (ch === "'" || ch === '"') quote = ch;
    else if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (depth < 0) return false;
  }
  return depth === 0 && !quote;
}

/** 按顶层 && / || 拆分（忽略括号与引号内的运算符）。 */
function splitTopLevelLogic(expr: string): { op: "&&" | "||"; text: string }[] {
  const parts: { op: "&&" | "||"; text: string }[] = [];
  let depth = 0;
  let quote = "";
  let start = 0;
  let pendingOp: "&&" | "||" | "" = "";
  for (let i = 0; i < expr.length; i++) {
    const ch = expr[i];
    if (quote) {
      if (ch === quote) quote = "";
      continue;
    }
    if (ch === "'" || ch === '"') quote = ch;
    else if (ch === "(") depth++;
    else if (ch === ")") depth--;
    else if (depth === 0 && (ch === "&" || ch === "|") && expr[i + 1] === ch) {
      parts.push({ op: pendingOp || "&&", text: expr.slice(start, i) });
      pendingOp = ch === "&" ? "&&" : "||";
      i++;
      start = i + 1;
    }
  }
  if (parts.length) parts.push({ op: pendingOp || "&&", text: expr.slice(start) });
  return parts;
}

function humanizeOperand(raw: string): string {
  let s = raw.trim();
  while (s.startsWith("(") && s.endsWith(")") && balanced(s.slice(1, -1))) s = s.slice(1, -1).trim();
  s = s.replace(/^\$/, "").replace(/^scope\./, "").replace(/\?\./g, ".");
  if ((s.startsWith("'") && s.endsWith("'")) || (s.startsWith('"') && s.endsWith('"'))) {
    return `「${s.slice(1, -1)}」`;
  }
  return s;
}

function summarizeAtom(expr: string): string {
  let s = stripOuterParens(expr.trim());
  if (!s) return "空表达式";
  if (s === "true") return "恒为真";
  if (s === "false") return "恒为假";
  if (s.startsWith("!")) return `非（${summarizeAtom(s.slice(1))}）`;

  const lenMatch = s.match(/^len\(\s*([^)]+?)\s*\)\s*(===|==|!==|!=|>=|<=|>|<)\s*(-?\d+)$/);
  if (lenMatch) {
    const [, target, op, num] = lenMatch;
    if ((op === ">" || op === "!==" || op === "!=") && Number(num) === 0) return `${humanizeOperand(target)} 非空`;
    if ((op === "===" || op === "==" || op === "<=") && Number(num) === 0) return `${humanizeOperand(target)} 为空`;
    return `${humanizeOperand(target)} 的长度 ${op} ${num}`;
  }

  const opRe = /^(.+?)\s*(===|!==|==|!=|>=|<=|>|<)\s*(.+)$/;
  const m = s.match(opRe);
  if (m) {
    const [, left, op, right] = m;
    const words: Record<string, string> = {
      "===": "等于",
      "==": "等于",
      "!==": "不等于",
      "!=": "不等于",
      ">=": "大于等于",
      "<=": "小于等于",
      ">": "大于",
      "<": "小于",
    };
    return `${humanizeOperand(left)} ${words[op]} ${humanizeOperand(right)}`;
  }
  if (/^[A-Za-z_$][\w$.?\[\]]*$/.test(s)) return `${humanizeOperand(s)} 为真`;
  return `「${s}」成立`;
}

function summarizeConditionExpr(expr: string, depth: number): string {
  if (depth > 3) return `「${expr}」成立`;
  const parts = splitTopLevelLogic(expr);
  if (parts.length > 1) {
    return parts
      .map((p, i) => {
        const text = summarizeConditionExpr(p.text, depth + 1);
        if (i === 0) return text;
        return `${p.op === "&&" ? " 且 " : " 或 "}${text}`;
      })
      .join("");
  }
  return summarizeAtom(expr);
}

/** 属性 schema 的字面量回退值（清除绑定后恢复）。 */
export function literalForSchema(ps?: ComponentPropSchema | null): unknown {
  if (!ps) return "";
  if (ps.default !== undefined) return ps.default;
  switch (ps.type) {
    case "number":
    case "integer":
      return 0;
    case "boolean":
      return false;
    case "array":
      return [];
    case "object":
      return {};
    default:
      return "";
  }
}
