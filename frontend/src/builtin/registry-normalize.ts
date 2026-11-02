/**
 * 组件注册表 v2 归一化。
 *
 * shared/component-registry.json 使用紧凑的“作者格式”：
 *   "text": ["string", "文字", "按钮"]
 *   "type": ["string", "类型", "primary", {"enum": [...], "ui": "select"}]
 * 归一化后得到运行时统一的 ComponentMeta（props_schema / style_schema / ...）。
 * 后端 components/registry.py 使用同一套规则，确保前后端看到完全一致的元数据。
 */
import type {
  ComponentCategory,
  ComponentMeta,
  ComponentPropSchema,
  ComponentSource,
  ComponentStyleSchema,
  ComponentType,
  RegistryFile,
} from "@/types";

export interface RawPropObject {
  /** 短类型别名，等价于 type */
  t?: string;
  type?: string;
  title?: string;
  description?: string;
  /** 短默认值别名，等价于 default */
  d?: unknown;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  multipleOf?: number;
  items?: ComponentPropSchema;
  properties?: Record<string, ComponentPropSchema>;
  ui?: string;
  "x-ui"?: string;
  g?: string;
  "x-group"?: string;
  b?: boolean;
  "x-bindable"?: boolean;
  options?: Record<string, any>;
  "x-options"?: Record<string, any>;
}

/** 紧凑属性：字符串字面量 / [type, title, default?, extra?] / 完整对象。 */
export type RawProp = string | unknown[] | RawPropObject;

export interface RawComponent {
  name: string;
  label: string;
  category: string;
  type?: ComponentType;
  version?: string;
  icon?: string;
  source?: ComponentSource;
  element?: string;
  container?: boolean;
  form?: boolean;
  slots?: string[];
  accepts?: string[];
  accept_children?: string[];
  events?: string[];
  actions?: string[];
  default_props?: Record<string, any>;
  default_children?: string[];
  props?: Record<string, RawProp>;
  props_schema?: ComponentMeta["props_schema"];
  style?: ComponentStyleSchema;
  [key: string]: any;
}

export interface RawRegistry {
  version?: string;
  schemaVersion?: number;
  categories?: ComponentCategory[];
  style_schema?: ComponentStyleSchema;
  components: RawComponent[];
}

const STANDARD_ACTIONS = [
  "setVariable",
  "callDatasource",
  "navigate",
  "openModal",
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
];

const NATIVE_TAGS = new Set([
  "div",
  "section",
  "article",
  "header",
  "footer",
  "main",
  "nav",
  "aside",
  "span",
  "p",
  "a",
  "img",
  "video",
  "audio",
  "iframe",
  "canvas",
  "svg",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
  "form",
  "label",
  "strong",
  "em",
  "br",
  "hr",
]);

function inferSource(raw: RawComponent): ComponentSource {
  if (raw.source) return raw.source;
  if (raw.name.startsWith("wp-")) return "legacy";
  if (raw.name.startsWith("chart-")) return "chart";
  if (["rich-text", "markdown", "code-block"].includes(raw.name)) return "rich";
  if (["html", "component-slot", "repeater", "conditional", "portal"].includes(raw.name)) return "advanced";
  if (NATIVE_TAGS.has(raw.name)) return "native";
  return "element-plus";
}

function normalizeProp(key: string, spec: RawProp): ComponentPropSchema {
  if (typeof spec === "string") {
    return { type: "string", title: key, default: spec };
  }
  if (Array.isArray(spec)) {
    const [type, title, def, extra] = spec as [string?, string?, unknown?, RawPropObject?];
    const out: ComponentPropSchema = {
      type: typeof type === "string" && type ? type : "string",
      title: typeof title === "string" && title ? title : key,
    };
    if (def !== undefined) out.default = def;
    if (extra && typeof extra === "object") Object.assign(out, compactExtra(extra));
    return out;
  }
  if (spec && typeof spec === "object") {
    const o = spec as RawPropObject;
    const out: ComponentPropSchema = {
      type: o.type || o.t || "string",
      title: o.title || key,
    };
    const def = o.default !== undefined ? o.default : o.d;
    if (def !== undefined) out.default = def;
    if (o.description) out.description = o.description;
    if (o.enum) out.enum = o.enum;
    if (o.minimum !== undefined) out.minimum = o.minimum;
    if (o.maximum !== undefined) out.maximum = o.maximum;
    if (o.multipleOf !== undefined) out.multipleOf = o.multipleOf;
    if (o.items) out.items = o.items;
    if (o.properties) out.properties = o.properties;
    const ui = o["x-ui"] || o.ui;
    if (ui) out["x-ui"] = ui;
    const group = o["x-group"] || o.g;
    if (group) out["x-group"] = group;
    const bindable = o["x-bindable"] ?? o.b;
    if (bindable !== undefined) out["x-bindable"] = bindable;
    const options = o["x-options"] || o.options;
    if (options) out["x-options"] = options;
    if (!out["x-ui"]) {
      if (out.enum) out["x-ui"] = "select";
      else if (out.type === "boolean") out["x-ui"] = "switch";
      else if (out.type === "number" || out.type === "integer") out["x-ui"] = "number";
      else if (out.type === "array" || out.type === "object") out["x-ui"] = "json";
    }
    return out;
  }
  return { type: "string", title: key };
}

function compactExtra(extra: RawPropObject): Partial<ComponentPropSchema> {
  const out: Partial<ComponentPropSchema> = {};
  if (extra.description) out.description = extra.description;
  if (extra.enum) out.enum = extra.enum;
  if (extra.minimum !== undefined) out.minimum = extra.minimum;
  if (extra.maximum !== undefined) out.maximum = extra.maximum;
  if (extra.multipleOf !== undefined) out.multipleOf = extra.multipleOf;
  if (extra.items) out.items = extra.items;
  if (extra.properties) out.properties = extra.properties;
  const ui = extra["x-ui"] || extra.ui;
  if (ui) out["x-ui"] = ui;
  const group = extra["x-group"] || extra.g;
  if (group) out["x-group"] = group;
  const bindable = extra["x-bindable"] ?? extra.b;
  if (bindable !== undefined) out["x-bindable"] = bindable;
  const options = extra["x-options"] || extra.options;
  if (options) out["x-options"] = options;
  return out;
}

function buildPropsSchema(raw: RawComponent): ComponentMeta["props_schema"] {
  if (raw.props_schema?.properties) return raw.props_schema;
  const properties: Record<string, ComponentPropSchema> = {};
  for (const [key, spec] of Object.entries(raw.props || {})) {
    properties[key] = normalizeProp(key, spec);
  }
  return { type: "object", properties };
}

function normalizeComponent(raw: RawComponent, commonStyle: ComponentStyleSchema): ComponentMeta {
  const category = raw.category || "custom";
  const source = inferSource(raw);
  const accepts = raw.accepts ?? raw.accept_children ?? [];
  const isContainer = raw.container ?? accepts.length > 0;
  const slots = raw.slots ?? (isContainer ? ["default"] : []);
  return {
    name: raw.name,
    label: raw.label || raw.name,
    type: raw.type || (category as ComponentType),
    category,
    version: raw.version || "2.0.0",
    icon: raw.icon || "",
    source,
    element: raw.element || raw.name,
    is_container: isContainer,
    is_form_field: raw.form ?? false,
    default_children: raw.default_children || [],
    actions_supported: raw.actions || STANDARD_ACTIONS,
    props_schema: buildPropsSchema(raw),
    style_schema: { ...commonStyle, ...(raw.style || {}) },
    default_props: raw.default_props || {},
    events: raw.events || ["click"],
    slots,
    accept_children: accepts,
    accepts,
  };
}

export function normalizeRegistry(raw: RawRegistry): RegistryFile {
  const commonStyle: ComponentStyleSchema = raw.style_schema || {
    preset: "common",
    groups: ["layout", "size", "spacing", "typography", "background", "border", "effect"],
    responsive: true,
  };
  return {
    version: raw.version || "2.0.0",
    schemaVersion: raw.schemaVersion || 2,
    categories: raw.categories || [],
    style_schema: commonStyle,
    components: (raw.components || []).map((c) => normalizeComponent(c, commonStyle)),
  };
}

/** 分类排序 + 中文名 + 图标；未声明的分类自动追加。 */
export function categoriesOf(reg: RegistryFile): ComponentCategory[] {
  const declared = reg.categories || [];
  const seen = new Set(declared.map((c) => c.key));
  const extra: ComponentCategory[] = [];
  for (const c of reg.components) {
    if (!seen.has(c.category)) {
      seen.add(c.category);
      extra.push({ key: c.category, label: c.category, icon: "Grid" });
    }
  }
  return [...declared, ...extra];
}
