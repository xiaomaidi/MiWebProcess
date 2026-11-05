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
  SchemaNode,
} from "@/types";

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
