/**
 * 组件状态 / 变体的纯函数工具（无副作用，便于 Node 自测）。
 *
 * 渲染规则：
 * - 基础 props/style ← 激活变体 props/style（后者覆盖前者）
 * - 交互状态（hover/active/focus/disabled）的 style 在运行态由注入的
 *   `[data-wp-node="id"]:hover` 等 CSS 规则生效；props 在该状态激活时覆盖。
 * - 设计态通过 state-preview 模块强制预览某个状态（不写入 schema）。
 */
import type {
  ComponentStateName,
  ComponentStateOverride,
  ComponentStates,
  ComponentVariant,
  DataBinding,
  RuntimeScope,
  SchemaNode,
} from "@/types";

/**
 * 与 engine/binding.ts 的 isBindingValue 保持一致的本地形状判断。
 * 这里不直接 import binding，避免纯函数模块（及其 Node 自测）被运行时依赖拖入。
 */
function isBindingValueShape(value: unknown): value is { __binding__: DataBinding } {
  return (
    !!value &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    !!(value as { __binding__?: unknown }).__binding__ &&
    typeof (value as { __binding__?: unknown }).__binding__ === "object"
  );
}

export interface StateMeta {
  key: ComponentStateName;
  label: string;
  hint: string;
}

/** 状态顺序：与属性面板折叠顺序一致。 */
export const COMPONENT_STATES: StateMeta[] = [
  { key: "hover", label: "悬停 hover", hint: "鼠标移入" },
  { key: "active", label: "按下 active", hint: "鼠标按下 / 触摸" },
  { key: "focus", label: "聚焦 focus", hint: "键盘或输入聚焦" },
  { key: "disabled", label: "禁用 disabled", hint: "disabled / is-disabled" },
];

export interface InteractionFlags {
  disabled?: boolean;
  hovered?: boolean;
  pressed?: boolean;
  focused?: boolean;
}

/** 当前激活变体（不存在 / id 无效时返回 null）。 */
export function findActiveVariant(node: SchemaNode | null | undefined): ComponentVariant | null {
  if (!node || !node.activeVariant || !Array.isArray(node.variants)) return null;
  return node.variants.find((v) => !!v && v.id === node.activeVariant) || null;
}

/** 基础 props 叠加激活变体 props（返回新对象，不修改节点）。 */
export function mergeVariantProps(node: SchemaNode | null | undefined): Record<string, any> {
  const base = node?.props || {};
  const variant = findActiveVariant(node);
  if (!variant?.props || !Object.keys(variant.props).length) return { ...base };
  return { ...base, ...variant.props };
}

/** 激活变体 style（返回新对象，不修改节点）。 */
export function mergeVariantStyle(node: SchemaNode | null | undefined): Record<string, any> {
  const variant = findActiveVariant(node);
  return variant?.style && Object.keys(variant.style).length ? { ...variant.style } : {};
}

/**
 * 是否「像数据绑定」：结构化 `{__binding__}` 或含 `{{...}}` 的模板字符串。
 * 变体 style 暂不支持解析这两种值，用于设计器提示与运行时忽略。
 */
export function isBindingLikeValue(value: unknown): boolean {
  if (isBindingValueShape(value)) return true;
  return typeof value === "string" && /\{\{[\s\S]*?\}\}/.test(value);
}

export interface VariantBindingEntry {
  key: string;
  kind: "binding" | "expression";
  /** kind=binding 时为结构化绑定；expression 时为 null。 */
  binding: DataBinding | null;
  /** 原始 prop 值（绑定对象或表达式字符串）。 */
  value: unknown;
}

/**
 * 变体 props 中的绑定 / 表达式条目（用于 UI chip 与摘要）。
 * 普通字面量不会返回；不修改入参。
 */
export function variantBindingEntries(variant: ComponentVariant | null | undefined): VariantBindingEntry[] {
  const props = variant?.props;
  if (!props) return [];
  const out: VariantBindingEntry[] = [];
  for (const [key, value] of Object.entries(props)) {
    if (isBindingValueShape(value)) {
      out.push({ key, kind: "binding", binding: value.__binding__, value });
    } else if (typeof value === "string" && /\{\{[\s\S]*?\}\}/.test(value)) {
      out.push({ key, kind: "expression", binding: null, value });
    }
  }
  return out;
}

/** 变体 style 中「像绑定」的键（这些值运行时不会解析）。 */
export function variantStyleBindingKeys(style: Record<string, any> | null | undefined): string[] {
  if (!style) return [];
  return Object.entries(style)
    .filter(([, value]) => isBindingLikeValue(value))
    .map(([key]) => key);
}

/**
 * 拆分变体 style：可用静态样式 + 不支持绑定的键。
 * 供 NodeRenderer 过滤掉 `[object Object]` 之类的无效 CSS 值。
 */
export function splitVariantStyleBindings(style: Record<string, any> | null | undefined): {
  style: Record<string, any>;
  bindingKeys: string[];
} {
  const out: Record<string, any> = {};
  const bindingKeys: string[] = [];
  for (const [key, value] of Object.entries(style || {})) {
    if (isBindingLikeValue(value)) bindingKeys.push(key);
    else out[key] = value;
  }
  return { style: out, bindingKeys };
}

export interface DesignPropsResult {
  props: Record<string, any>;
  /** 使用占位值的键（预览数据缺失或绑定未命中）。 */
  unresolved: string[];
  /** 使用设计时预览数据解析出真实值的键。 */
  resolved: string[];
}

/** 设计时预览解析器（NodeRenderer 传入 engine/binding 的 resolveProps）。 */
export type PreviewPropResolver = (props: Record<string, any>, scope: RuntimeScope) => Record<string, any>;

/**
 * 设计态 props 解析（纯函数，不修改入参）：
 * - 有预览作用域：绑定 / {{...}} 表达式交给与运行态相同的 resolveProps 解析；
 * - 无预览数据 / 绑定未命中：绑定回退 binding.defaultValue，再回退占位值；
 * - 普通字面量原样保留。
 *
 * 设计器目前用页面变量当前值构造预览作用域；没有可预览变量时只输出安全占位值。
 */
export function resolveDesignProps(
  props: Record<string, any>,
  previewScope: RuntimeScope | null,
  placeholderFor: (key: string, value: unknown) => any,
  resolvePreview?: PreviewPropResolver
): DesignPropsResult {
  const out: Record<string, any> = {};
  const unresolved: string[] = [];
  const resolved: string[] = [];
  let previewed: Record<string, any> | null = null;
  if (previewScope && resolvePreview) {
    try {
      previewed = resolvePreview(props, previewScope);
    } catch {
      previewed = null;
    }
  }
  for (const [key, value] of Object.entries(props)) {
    const binding = isBindingValueShape(value) ? value.__binding__ : null;
    if (binding) {
      const next = previewed ? previewed[key] : undefined;
      if (next !== undefined) {
        out[key] = next;
        resolved.push(key);
      } else if (binding.defaultValue !== undefined) {
        out[key] = binding.defaultValue;
        resolved.push(key);
      } else {
        out[key] = placeholderFor(key, value);
        unresolved.push(key);
      }
      continue;
    }
    if (previewed) {
      const next = previewed[key];
      if (next !== undefined) {
        out[key] = next;
        if (typeof value === "string" && value.includes("{{")) resolved.push(key);
      } else if (typeof value === "string" && value.includes("{{")) {
        out[key] = placeholderFor(key, value);
        unresolved.push(key);
      } else {
        out[key] = value;
      }
      continue;
    }
    out[key] = value;
  }
  return { props: out, unresolved, resolved };
}

function nonEmptyObject(value: unknown): value is Record<string, any> {
  return !!value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0;
}

/** 某个状态的覆盖对象。 */
export function stateOverride(
  node: SchemaNode | null | undefined,
  state: ComponentStateName
): ComponentStateOverride | null {
  const entry = node?.states?.[state];
  return entry && typeof entry === "object" ? entry : null;
}

/** 某个状态的 style（不存在时为空对象）。 */
export function stateStyleFor(node: SchemaNode | null | undefined, state: ComponentStateName | null): Record<string, any> {
  if (!state) return {};
  const entry = node?.states?.[state];
  return entry?.style && Object.keys(entry.style).length ? { ...entry.style } : {};
}

/** 某个状态的 props（不存在时为空对象）。 */
export function statePropsFor(
  node: SchemaNode | null | undefined,
  state: ComponentStateName | null
): Record<string, any> {
  if (!state) return {};
  const entry = node?.states?.[state];
  return entry?.props && Object.keys(entry.props).length ? { ...entry.props } : {};
}

/**
 * 运行态交互状态判定（优先级 disabled > active > hover > focus）。
 * 只返回节点确实声明过的状态，避免无意义重算。
 */
export function resolveInteractionState(
  node: SchemaNode | null | undefined,
  flags: InteractionFlags
): ComponentStateName | null {
  const states: ComponentStates | undefined = node?.states;
  if (!states) return null;
  const has = (state: ComponentStateName) => !!states[state];
  if (flags.disabled && has("disabled")) return "disabled";
  if (flags.pressed && has("active")) return "active";
  if (flags.hovered && has("hover")) return "hover";
  if (flags.focused && has("focus")) return "focus";
  return null;
}

/** 某个状态是否存在可用的 props / style 覆盖。 */
export function hasStateOverride(node: SchemaNode | null | undefined, state: ComponentStateName): boolean {
  const entry = node?.states?.[state];
  return nonEmptyObject(entry?.style) || nonEmptyObject(entry?.props);
}

/** 节点是否有任意状态覆盖。 */
export function hasAnyState(node: SchemaNode | null | undefined): boolean {
  return COMPONENT_STATES.some((s) => hasStateOverride(node, s.key));
}

function styleObjectToCss(style: Record<string, any> | undefined, important = false): string {
  if (!style) return "";
  return Object.entries(style)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())}: ${value}${important ? " !important" : ""};`)
    .join(" ");
}

/** 属性选择器中的节点 id 转义（id 由 uid 生成，正常只含字母数字）。 */
export function escapeAttrValue(value: string): string {
  return String(value ?? "").replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

const STATE_SELECTOR: Record<ComponentStateName, (sel: string) => string> = {
  hover: (sel) => `${sel}:hover`,
  active: (sel) => `${sel}:active`,
  focus: (sel) => `${sel}:focus`,
  disabled: (sel) => `${sel}:disabled, ${sel}[aria-disabled="true"], ${sel}.is-disabled`,
};

/**
 * 生成运行态状态样式 CSS（每个状态一条规则）。
 * 依赖 NodeRenderer 写在组件根元素的 data-wp-node 属性。
 */
export function buildStateCss(node: SchemaNode | null | undefined): string {
  if (!node?.states) return "";
  const base = `[data-wp-node="${escapeAttrValue(node.id)}"]`;
  const chunks: string[] = [];
  for (const { key } of COMPONENT_STATES) {
    const style = node.states[key]?.style;
    // 运行态节点基础样式以 inline style 输出，状态 CSS 需 !important 才能覆盖。
    const body = styleObjectToCss(style, true);
    if (body) chunks.push(`${STATE_SELECTOR[key](base)}{${body}}`);
  }
  return chunks.join("\n");
}

/** 变体 / 状态覆盖的展示摘要（属性面板用）。 */
export function overrideSummary(entry: ComponentStateOverride | ComponentVariant | null | undefined): string {
  if (!entry) return "未设置";
  const parts: string[] = [];
  if (nonEmptyObject(entry.style)) parts.push(`样式 ${Object.keys(entry.style).length}`);
  if (nonEmptyObject(entry.props)) parts.push(`props ${Object.keys(entry.props).length}`);
  return parts.length ? parts.join(" · ") : "未设置";
}
