/** MiWebProcess 前端共享类型（与 docs/API.md 及 shared/component-registry.json 对应）。 */

// ================= 组件注册表 =================
export type ComponentType =
  | "basic"
  | "layout"
  | "form"
  | "data"
  | "feedback"
  | "nav"
  | "media"
  | "chart"
  | "advanced"
  | "business";

/** 组件实现来源：Element Plus / 原生标签 / 图表 / 富文本 / 旧版内置 / 自定义。 */
export type ComponentSource = "element-plus" | "native" | "chart" | "rich" | "advanced" | "legacy" | "custom";

export interface ComponentCategory {
  key: string;
  label: string;
  icon?: string;
}

export interface ComponentPropSchema {
  type: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  multipleOf?: number;
  items?: ComponentPropSchema;
  properties?: Record<string, ComponentPropSchema>;
  /** 属性面板控件：select / radio / switch / number / slider / color / date / code / expression / json / tableColumnsEditor / echartsOption ... */
  "x-ui"?: string;
  /** 属性分组标题（属性面板按组折叠）。 */
  "x-group"?: string;
  /** 是否允许切换为表达式/数据绑定；默认 true。 */
  "x-bindable"?: boolean;
  /** 控件额外配置（如 options 快捷编辑、图标集合）。 */
  "x-options"?: Record<string, any>;
}

export interface ComponentStyleSchema {
  preset?: "common" | "none" | string;
  groups?: string[];
  responsive?: boolean;
}

export interface ComponentMeta {
  id?: number;
  name: string; // 组件类型键，如 "ElButton"
  label: string;
  type: ComponentType;
  category: string; // basic | layout | form | data | feedback | nav | media | chart | advanced | custom
  version: string;
  icon?: string;
  /** 实现来源；旧版 wp-* 组件为 legacy。 */
  source?: ComponentSource;
  /** 实际渲染的 Element Plus 导出名或原生标签名。 */
  element?: string;
  is_container?: boolean;
  is_form_field?: boolean;
  default_children?: string[];
  actions_supported?: string[];
  props_schema: {
    type: string;
    title?: string;
    properties: Record<string, ComponentPropSchema>;
  };
  style_schema?: ComponentStyleSchema;
  default_props: Record<string, any>;
  events: string[]; // 支持的事件名：click / change / submit / load / confirm ...
  /** 声明会写入的页面状态 / 事件，格式 state:key / event:name */
  provides?: string[];
  /** 声明依赖的页面状态 / 事件 */
  consumes?: string[];
  payload_schema?: Record<string, any>;
  slots: string[]; // 命名插槽（空 = 仅默认插槽）
  accept_children: string[]; // ["*"] = 接受任意子组件
  accepts?: string[];
  is_custom?: boolean;
  is_enabled?: boolean;
  source_url?: string;
}

export interface RegistryFile {
  version?: string;
  schemaVersion: number;
  categories?: ComponentCategory[];
  /** 所有组件共享的样式 Schema；组件可用 style_schema.preset 引用。 */
  style_schema?: ComponentStyleSchema;
  components: ComponentMeta[];
}

// ================= 动作流 =================
export type ActionKind =
  | "setVariable"
  | "callDatasource"
  | "navigate"
  | "openModal"
  | "closeModal"
  | "openDrawer"
  | "closeDrawer"
  | "message"
  | "notification"
  | "confirm"
  | "record"
  | "condition"
  | "loop"
  | "parallel"
  | "tryCatch"
  | "delay"
  | "setStyle"
  | "emit"
  | "submitForm"
  | "resetForm"
  | "download"
  | "copy"
  | "print"
  | "http"
  | "js";

export interface ActionStep {
  id?: string;
  kind: ActionKind;
  params: Record<string, any>;
  /** condition / loop / tryCatch / parallel 的主分支；conditional 的 then。 */
  then?: ActionStep[];
  /** condition 的 else；tryCatch 的 catch。 */
  else?: ActionStep[];
  /** tryCatch 的捕获分支（与 else 等价，保留可读别名）。 */
  catch?: ActionStep[];
}

// ================= 页面 Schema =================
/**
 * 数据绑定（与 docs/API.md §10 及后端 core/schemas.py 的 __binding__ 结构一一对应）。
 * - source=variable:    ref = 变量 key
 * - source=datasource:  ref = "ds_<datasourceId>"（或纯数字 id）
 * - source=model:       ref = "model_<modelId>"（或纯数字 id）
 * - source=form:        ref = "form_<formNodeId>"（或纯数字 id）
 * - field: 结果内取数路径（a.b.c，可含 [*] 取全部元素）
 * - loopVar: 列表绑定时子树作用域变量名
 * - defaultValue: 取数失败时的默认值
 * - transform: 对取数结果再求值的表达式（上下文含 value 与作用域）
 */
export interface DataBinding {
  source: "variable" | "datasource" | "model" | "form";
  ref: string;
  field?: string;
  loopVar?: string;
  defaultValue?: any;
  transform?: string;
}

/** prop 值：普通字面量，或 { __binding__: DataBinding } */
export type BoundValue = any;

export interface SchemaNode {
  id: string;
  type: string; // 组件类型键；"wp-canvas" 为画布根
  componentVersion: string;
  props: Record<string, any>; // 值可为 BoundValue
  style?: Record<string, any>;
  /** 断点覆盖样式：xs/sm/md/lg/xl → CSS 属性对象（运行态生成 @media） */
  responsive?: Record<string, Record<string, any>>;
  /** 在指定断点隐藏节点：xs/sm/md/lg/xl */
  hideOn?: string[];
  /** 入场动效：fade-in / fade-up / zoom-in */
  motion?: string;
  /** 可选自定义 CSS（运行态挂 .wp-node-<id>） */
  customCss?: string;
  events?: Record<string, ActionStep[]>;
  children?: string[];
  /** 插槽：插槽名 → 子节点 id 列表（插槽名须在该组件 meta.slots 内） */
  slots?: Record<string, string[]>;
  /** 条件渲染（运行态求值，false 则隐藏） */
  condition?: { expr: string } | null;
  /** 循环渲染：绑定一个数组，子节点按元素重复渲染（loopVar 注入作用域） */
  dataBinding?: DataBinding | null;
  /** 自由布局定位（仅 free 模式） */
  layout?: { x: number; y: number; width: number; height: number } | null;
  /** 设计器锁定：阻止画布拖动 / 缩放 / 删除；运行态无影响。 */
  locked?: boolean;
  /** 设计器隐藏：仅在设计画布中隐藏（大纲仍可见）；运行态照常渲染。 */
  hidden?: boolean;
  /** 组合容器标记：由「组合」创建，供「取消组合」识别。 */
  isGroup?: boolean;
}

import type { DesignTokens } from "./design/tokens";

export interface PageMeta {
  title?: string;
  favicon?: string;
  lang?: string;
  description?: string;
  keywords?: string;
  ogImage?: string;
  /** 公开表单提交后服务端转发的 REST 数据源 id；0 表示不转发。 */
  forwardDatasourceId?: number;
  head?: string;
  designTokens?: DesignTokens;
  useAppTokens?: boolean;
  background?: Record<string, any>;
  globalStyle?: {
    cssVars?: Record<string, string>;
    fontFamily?: string;
    [key: string]: any;
  };
  seo?: {
    description?: string;
    keywords?: string;
    ogImage?: string;
  };
}

export interface PageStateDef {
  type?: "string" | "number" | "boolean" | "object" | "array" | "any";
  default?: any;
  description?: string;
}

export interface PageEventDef {
  description?: string;
  payload?: Record<string, string>;
}

export interface PageLifecycle {
  onLoad?: ActionStep[];
  onReady?: ActionStep[];
  onUnload?: ActionStep[];
}

export interface PageSchema {
  schemaVersion: number;
  rootId: string;
  nodes: Record<string, SchemaNode>;
  assets?: Record<string, { url: string; name: string; type: string }>;
  variables?: Record<string, { value: any; scope?: "global" | "page" }>;
  /** 正式页面状态定义：key → 类型 / 默认值 / 说明。 */
  state?: Record<string, PageStateDef>;
  /** 页面级事件契约：name → 说明 / payload 类型。 */
  events?: Record<string, PageEventDef>;
  /** 页面生命周期动作。 */
  lifecycle?: PageLifecycle;
  layout?: { mode: "flow" | "free"; width: number; height: number; grid?: number };
  /** 页面级 meta：标题 / favicon / SEO / 全局样式 / 背景。 */
  meta?: PageMeta;
  /** 页面级自定义 CSS（发布时注入）。 */
  customCss?: string;
}

// ================= 后端对象 =================
export interface AppInfo {
  id: number;
  name: string;
  code: string;
  description?: string;
  design_tokens?: Record<string, any>;
  owner_id: number;
  owner_username?: string;
  status: "draft" | "published" | "archived";
  version?: number;
  created_at: string;
  updated_at: string;
}

export interface AppMember {
  user: number;
  username: string;
  role: "viewer" | "editor" | "owner";
}

export interface PageInfo {
  id: number;
  app_id: number;
  name: string;
  path: string;
  type: "page" | "layout" | "popup" | "fragment";
  status: string;
  version: number;
  schema_version: number;
  thumbnail_url?: string;
  created_at: string;
  updated_at: string;
}

export interface PageVersionInfo {
  id: number;
  page_id: number;
  version: number;
  schema_version: number;
  publisher_id: number;
  publisher?: string;
  published_at: string;
  changelog?: string;
}

export interface DataSourceDef {
  id: number;
  app_id: number;
  name: string;
  type: "REST" | "SQL" | "static" | "websocket" | string;
  config: Record<string, any>;
  public_config?: Record<string, any>;
  transform?: Record<string, any>;
  status?: string;
  description?: string;
}

export interface WorkflowNode {
  id: string;
  name?: string;
  type: "start" | "approval" | "condition" | "end";
  assignee_role?: string;
  assignee_user_id?: number | null;
  condition?: string | { field?: string; operator?: string; value?: any };
  assignee_type?: "role" | "user" | "initiator" | "dept_leader";
  mode?: "all" | "any";
  timeout_hours?: number;
  approvers?: {
    assignee_role?: string;
    assignee_user_id?: number | null;
    assignee_type?: "role" | "user" | "dept_leader";
    department_id?: number | null;
  }[];
  true_next?: string;
  false_next?: string;
  on_approve?: Record<string, any>;
  on_reject?: Record<string, any>;
}

export interface WorkflowDefinition {
  id: number;
  app_id: number;
  name: string;
  code: string;
  description: string;
  nodes: WorkflowNode[];
  status: "draft" | "published" | "archived";
  version: number;
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowTask {
  id: number;
  instance_id: number;
  instance_title?: string;
  definition_name?: string;
  app_id?: number;
  business_model_id?: number | null;
  business_record_id?: number | null;
  node_id: string;
  node_name: string;
  assignee?: number | null;
  assignee_name?: string;
  assignee_role?: string;
  status: "pending" | "approved" | "rejected" | "transferred" | "cancelled";
  comment?: string;
  action_by?: number | null;
  action_by_name?: string;
  due_at?: string | null;
  is_overdue?: boolean;
  remind_count?: number;
  last_reminded_at?: string | null;
  definition_nodes?: WorkflowNode[];
  created_at?: string;
  updated_at?: string;
}

export interface WorkflowInstance {
  id: number;
  definition: number;
  definition_name: string;
  definition_code: string;
  app: number;
  business_model_id?: number | null;
  business_record_id?: number | null;
  title: string;
  data: Record<string, any>;
  status: "running" | "approved" | "rejected" | "cancelled";
  current_node_id?: string;
  current_index: number;
  initiator_name?: string;
  tasks: WorkflowTask[];
  created_at?: string;
  updated_at?: string;
}

/** 数据模型字段类型（与后端 datamodels/models.py 的 FIELD_TYPES 对齐）。 */
export type DataModelFieldType =
  | "string"
  | "longtext"
  | "richtext"
  | "email"
  | "phone"
  | "url"
  | "password"
  | "select"
  | "multiselect"
  | "tags"
  | "number"
  | "integer"
  | "decimal"
  | "money"
  | "percent"
  | "boolean"
  | "date"
  | "datetime"
  | "time"
  | "duration"
  | "json"
  | "reference"
  | "references"
  | "image"
  | "file"
  /** 多文件附件：URL 数组（最多 20 个，单项 <= 500 字符）。 */
  | "attachments"
  | "user"
  | "department"
  | "auto_number"
  | "formula"
  | "created_at"
  | "updated_at"
  | "geolocation"
  | "signature"
  | "barcode"
  | "rating"
  | "color";

export interface DataModelField {
  name: string;
  label?: string;
  type: DataModelFieldType | string;
  required?: boolean;
  default?: any;
  unique?: boolean;
  description?: string;
  ref_model?: string;
  min?: number;
  max?: number;
  precision?: number;
  currency?: string;
  max_length?: number;
  accept?: string;
  multiple?: boolean;
  ref_display?: string;
  placeholder?: string;
  format?: string;
  unit?: string;
  formula?: string;
  /** 可选：数据模型字段上的额外校验规则（Element Plus FormItem rules 结构）。 */
  rules?: Record<string, any>[];
  /** reference 字段的可选选项。 */
  options?: { label: string; value: any }[];
  /** 编辑控件：text / textarea / richtext / select / date */
  ui?: string;
  /** 命中这些角色时返回 ***，用于手机号/金额等脱敏。 */
  mask_roles?: string[];
}

export interface DataModelInfo {
  id: number;
  app_id: number;
  name: string;
  code?: string;
  is_public?: boolean;
  row_owner_field?: string;
  workflow_definition_id?: number | null;
  data_scope?: "all" | "owner";
  action_roles?: Record<string, string[]>;
  fields: DataModelField[];
  relations?: any[];
  indexes?: any[];
}

export interface ReleaseInfo {
  id: number;
  app: number;
  app_code?: string;
  version: number;
  status: "pending" | "releasing" | "active" | "rollback" | "failed";
  traffic_ratio: number;
  previous_release: number | null;
  bundle_url?: string;
  error?: string;
  changelog?: string;
  task?: { id: number; status: string; log: string; created_at: string; updated_at: string } | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface AuditLogInfo {
  id: number;
  user_id: number;
  username: string;
  app_id: number | null;
  object_type: string;
  object_id: string | number | null;
  action: string;
  before?: any;
  after?: any;
  ip?: string;
  created_at: string;
}

export interface UserInfo {
  id: number;
  username: string;
  first_name?: string;
  last_name?: string;
  email?: string;
  is_superuser: boolean;
  is_platform_admin?: boolean;
  is_staff?: boolean;
  is_active: boolean;
  last_login?: string;
}

// ================= 运行时 =================
export interface FormSubmitResult {
  valid: boolean;
  values: Record<string, any>;
}

export interface RuntimeScope {
  variables: Record<string, any>;
  /** 当前动态路由参数（article/:id、news/:category）。 */
  routeParams: Record<string, string>;
  routePath: string;
  setPageMeta?(meta: { title?: string; description?: string; image?: string; type?: string }): void;
  setVariable(name: string, value: any): void;
  /** 数据源结果缓存（reactive）：datasourceId → 响应体 */
  datasourceResults: Record<number, any>;
  /** 数据模型查询结果缓存：modelId → Paged 对象 */
  modelResults: Record<number, any>;
  /** 表单值：ref（"form_<nodeId>"）→ 字段值 */
  formValues: Record<string, Record<string, any>>;
  /** 表单校验器：form node id → validate()；由 NodeRenderer 注册。 */
  formValidators?: Record<string, () => Promise<boolean>>;
  /** 循环渲染：当前循环变量（loopVar 名 → 值），由 NodeRenderer 注入 */
  loopVars: Record<string, any>;
  callDatasource(id: number, params?: Record<string, any>): Promise<any>;
  navigate(path: string, target?: string): void;
  openModal(nodeId: string): void;
  closeModal(nodeId: string): void;
  modalNodeIds: Set<string>;
  /** 抽屉（v2）：与弹窗分开管理，便于 openDrawer/closeDrawer 动作。 */
  drawerNodeIds?: Set<string>;
  openDrawer?(nodeId: string): void;
  closeDrawer?(nodeId: string): void;
  message(text: string, type?: "success" | "info" | "warning" | "error"): void;
  notification?(text: string, type?: "success" | "info" | "warning" | "error", title?: string): void;
  confirm?(text: string, title?: string): Promise<boolean>;
  submitForm?(formId?: string): Promise<FormSubmitResult>;
  resetForm?(formId?: string): void;
  /** 运行态动态改节点样式（setStyle 动作）。 */
  setNodeStyle?(nodeId: string, style: Record<string, any>): void;
  record: {
    list(modelId: number, params?: Record<string, any>): Promise<any>;
    get(modelId: number, id: number): Promise<any>;
    create(modelId: number, data: Record<string, any>): Promise<any>;
    update(modelId: number, id: number, data: Record<string, any>): Promise<any>;
    remove(modelId: number, id: number): Promise<void>;
  };
  onNodeError?(nodeId: string, error: unknown): void;
  emit?(event: string, payload?: unknown): void;
  /** 运行时数据源配置（含 REST/WebSocket public_config）。 */
  datasources?: any[];
  /** 应用模块开关 */
  modules?: Record<string, boolean>;
  /** 订阅 WebSocket 数据源；返回取消订阅函数。 */
  subscribeDatasource?(id: number, params: Record<string, any>, handler: (data: any, raw?: any) => void): () => void;
  /** 页面状态契约：用于 setVariable 运行时校验。 */
  stateDefs?: Record<string, PageStateDef>;
  /** 页面事件契约：用于 emit payload 校验。 */
  eventSchemas?: Record<string, PageEventDef>;
  /** 运行时协同错误（状态类型 / 事件 payload）。 */
  coordinationErrors?: string[];
}

export interface Paged<T> {
  count: number;
  results: T[];
  page: number;
  size: number;
}
