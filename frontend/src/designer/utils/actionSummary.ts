/** 动作链（ActionStep）的人话摘要、必填目标校验与默认动作工厂。 */
import { checkExpression } from "@/engine/expr";
import type { ActionKind, ActionStep, DataModelInfo, DataSourceDef } from "@/types";
import { findDatasource, findModel } from "./bindingSources";

export interface ActionContext {
  datasources: DataSourceDef[];
  models: DataModelInfo[];
  /** schema 中存在的节点 id，用于校验弹窗/样式类动作的目标。 */
  nodeIds?: Set<string>;
  /** 节点 id → 可读名称（可选）。 */
  nodeLabel?: (id: string) => string;
}

export interface ActionIssue {
  level: "error" | "warning";
  message: string;
  /** 嵌套分支中的完整路径，如「步骤 1 → then 步骤 2」。 */
  path: string;
  /** 顶层步骤下标，用于滚动定位。 */
  anchor: number;
}

export interface QuickAction {
  kind: ActionKind;
  label: string;
  group: string;
}

export const ACTION_LABELS: Record<ActionKind, string> = {
  setVariable: "设置变量",
  callDatasource: "调用数据源",
  navigate: "页面跳转",
  openModal: "打开弹窗",
  closeModal: "关闭弹窗",
  openDrawer: "打开抽屉",
  closeDrawer: "关闭抽屉",
  message: "轻提示",
  notification: "通知",
  confirm: "确认对话框",
  record: "数据操作",
  condition: "条件分支",
  loop: "循环",
  parallel: "并行",
  tryCatch: "异常捕获",
  delay: "延时",
  setStyle: "修改样式",
  emit: "触发事件",
  submitForm: "提交表单",
  resetForm: "重置表单",
  download: "下载文件",
  copy: "复制文本",
  print: "打印页面",
  http: "HTTP 请求",
  js: "受限表达式",
};

export const QUICK_ACTIONS: QuickAction[] = [
  { kind: "message", label: "轻提示 message", group: "常用" },
  { kind: "setVariable", label: "设置变量 setVariable", group: "常用" },
  { kind: "callDatasource", label: "调用数据源 callDatasource", group: "常用" },
  { kind: "navigate", label: "页面跳转 navigate", group: "常用" },
  { kind: "openModal", label: "打开弹窗 openModal", group: "常用" },
  { kind: "condition", label: "条件分支 condition", group: "流程" },
  { kind: "loop", label: "循环 loop", group: "流程" },
  { kind: "delay", label: "延时 delay", group: "流程" },
  { kind: "confirm", label: "确认对话框 confirm", group: "流程" },
  { kind: "tryCatch", label: "异常捕获 tryCatch", group: "流程" },
  { kind: "record", label: "数据操作 record", group: "数据" },
  { kind: "submitForm", label: "提交表单 submitForm", group: "数据" },
  { kind: "http", label: "HTTP 请求 http", group: "数据" },
];

export function actionLabel(kind: ActionKind | string): string {
  return ACTION_LABELS[kind as ActionKind] || String(kind);
}

function stepParams(step: ActionStep): Record<string, any> {
  return step.params && typeof step.params === "object" ? step.params : {};
}

function recordCount(steps?: ActionStep[]): number {
  return Array.isArray(steps) ? steps.length : 0;
}

function branchText(step: ActionStep): string {
  const parts: string[] = [];
  if (recordCount(step.then)) parts.push(`then ${recordCount(step.then)}`);
  if (recordCount(step.else)) parts.push(`else ${recordCount(step.else)}`);
  if (recordCount(step.catch)) parts.push(`catch ${recordCount(step.catch)}`);
  return parts.length ? `（${parts.join(" / ")}）` : "";
}

function targetLabel(id: string, ctx: ActionContext): string {
  if (!id) return "（未选择）";
  const label = ctx.nodeLabel?.(id);
  return label ? `${label}（${id}）` : id;
}

/** 单个动作的人话摘要；未知动作退回原始 kind。 */
export function summarizeAction(step: ActionStep, ctx: ActionContext): string {
  const p = stepParams(step);
  const branch = branchText(step);
  switch (step.kind) {
    case "setVariable":
      return `设置变量 ${p.name || "（未命名）"} = ${String(p.value ?? "").trim() || "（空）"}`;
    case "callDatasource": {
      const ds = findDatasource(ctx.datasources, p.ref ?? "");
      return `调用数据源 ${ds ? ds.name : p.ref || "（未选择）"}${p.params && Object.keys(p.params).length ? "（带参数）" : ""}`;
    }
    case "navigate": {
      const target = p.target === "_blank" ? "新窗口" : "当前页";
      return `跳转到 ${p.path || "（未填写路径）"}（${target}）`;
    }
    case "openModal":
      return `打开弹窗 ${targetLabel(String(p.nodeId ?? ""), ctx)}`;
    case "closeModal":
      return `关闭弹窗 ${targetLabel(String(p.nodeId ?? ""), ctx)}`;
    case "openDrawer":
      return `打开抽屉 ${targetLabel(String(p.nodeId ?? ""), ctx)}`;
    case "closeDrawer":
      return `关闭抽屉 ${targetLabel(String(p.nodeId ?? ""), ctx)}`;
    case "message":
      return `提示「${p.text || "（空文本）"}」${p.type ? `（${p.type}）` : ""}`;
    case "notification":
      return `通知「${p.title || "通知"}」：${p.text || "（空文本）"}`;
    case "confirm":
      return `确认「${p.text || "（空文本）"}」${branch}`;
    case "record": {
      const model = findModel(ctx.models, p.modelId ?? "");
      const opMap: Record<string, string> = { list: "查询", create: "新增", update: "更新", remove: "删除" };
      return `数据${opMap[p.op] || p.op || "操作"}：${model ? model.name : p.modelId ? `#${p.modelId}` : "（未选择模型）"}${
        p.varName ? ` → 变量 ${p.varName}` : ""
      }`;
    }
    case "condition":
      return `条件「${p.expr || "（空表达式）"}」${branch}`;
    case "loop":
      return `循环 ${p.list || "（未填写数组）"}，元素变量 ${p.itemVar || "item"}${branch}`;
    case "parallel":
      return `并行执行 ${recordCount(step.then)} 个动作`;
    case "tryCatch":
      return `尝试执行 ${recordCount(step.then)} 个动作${recordCount(step.catch) ? `，异常时执行 ${recordCount(step.catch)} 个` : ""}`;
    case "delay":
      return `等待 ${Number(p.ms ?? 0)} ms`;
    case "setStyle":
      return `修改节点 ${targetLabel(String(p.nodeId ?? ""), ctx)} 的样式`;
    case "emit":
      return `触发事件 ${p.event || "（未命名）"}${p.payload ? "（带 payload）" : ""}`;
    case "submitForm":
      return `提交表单${p.formId ? ` ${p.formId}` : ""}（${p.op === "update" ? "更新" : "新增"}）${
        p.successText ? `，成功提示「${p.successText}」` : ""
      }`;
    case "resetForm":
      return `重置表单${p.formId ? ` ${p.formId}` : "（全部）"}`;
    case "download":
      return `下载文件 ${p.filename || "（未命名）"}`;
    case "copy":
      return `复制文本「${String(p.text || "").slice(0, 24) || "（空）"}」`;
    case "print":
      return "打印当前页面";
    case "http":
      return `HTTP ${String(p.method || "GET").toUpperCase()} ${p.path || "（未填写路径）"}${
        p.varName ? ` → 变量 ${p.varName}` : ""
      }`;
    case "js":
      return `执行受限表达式${p.code ? `：${String(p.code).slice(0, 28)}` : "（空）"}${p.varName ? ` → ${p.varName}` : ""}`;
    default:
      return String((step as ActionStep).kind);
  }
}

/** 单步校验：必填目标 + 表达式语法；返回可直接展示的问题列表。 */
export function validateStep(step: ActionStep, ctx: ActionContext, path: string, anchor: number, out: ActionIssue[]): void {
  const p = stepParams(step);
  const error = (message: string) => out.push({ level: "error", message, path, anchor });
  const warn = (message: string) => out.push({ level: "warning", message, path, anchor });

  const need = (value: unknown, label: string) => {
    if (value === undefined || value === null || String(value).trim() === "") {
      error(`「${actionLabel(step.kind)}」缺少${label}`);
      return false;
    }
    return true;
  };

  switch (step.kind) {
    case "setVariable":
      if (need(p.name, "变量名") && !/^[A-Za-z_$][\w$]*$/.test(String(p.name).trim())) {
        error(`变量名「${p.name}」不是合法标识符`);
      }
      break;
    case "callDatasource":
      if (need(p.ref, "数据源")) {
        if (!findDatasource(ctx.datasources, p.ref)) warn(`引用的数据源 ${p.ref} 不存在或未加载`);
      }
      break;
    case "navigate":
      if (need(p.path, "跳转路径") && !String(p.path).trim().startsWith("/")) {
        warn("跳转路径建议以 / 开头（站内路径）");
      }
      break;
    case "openModal":
    case "openDrawer":
    case "closeModal":
    case "closeDrawer":
    case "setStyle":
      if (need(p.nodeId, "目标节点 id")) {
        if (ctx.nodeIds && !ctx.nodeIds.has(String(p.nodeId))) {
          const msg = `目标节点 ${p.nodeId} 不在当前页面中`;
          step.kind === "setStyle" ? warn(msg) : error(msg);
        }
      }
      break;
    case "message":
    case "notification":
      need(p.text, "提示文本");
      break;
    case "confirm":
      if (!String(p.text ?? "").trim()) warn("确认对话框没有文案，将使用默认提示");
      break;
    case "record":
      if (need(p.modelId, "数据模型")) {
        if (!findModel(ctx.models, p.modelId)) warn(`引用的数据模型 ${p.modelId} 不存在或未加载`);
      }
      if ((p.op === "update" || p.op === "remove") && !String(p.id ?? "").trim()) {
        warn(`「${p.op === "remove" ? "删除" : "更新"}」操作建议填写记录 id`);
      }
      break;
    case "condition": {
      if (need(p.expr, "条件表达式")) {
        const result = checkExpression(String(p.expr));
        if (!result.ok) error(`条件表达式无法解析：${result.error || "语法错误"}`);
      }
      break;
    }
    case "loop": {
      if (need(p.list, "数组表达式")) {
        const result = checkExpression(String(p.list));
        if (!result.ok) error(`数组表达式无法解析：${result.error || "语法错误"}`);
      }
      if (!recordCount(step.then)) warn("循环没有子动作，运行时不会做任何事");
      break;
    }
    case "parallel":
      if (!recordCount(step.then)) warn("并行动作没有子步骤");
      break;
    case "tryCatch":
      if (!recordCount(step.then)) warn("try 分支为空");
      break;
    case "emit":
      need(p.event, "事件名");
      break;
    case "submitForm":
      if (p.op === "update" && !String(p.recordId ?? "").trim()) warn("更新模式下建议填写记录 ID");
      break;
    case "http":
      if (need(p.path, "请求路径") && !String(p.path).startsWith("/")) {
        warn("HTTP 路径一般以 / 开头（/api 前缀由运行时拼接）");
      }
      break;
    case "js":
      if (need(p.code, "表达式")) {
        const result = checkExpression(String(p.code));
        if (!result.ok) error(`表达式无法解析：${result.error || "语法错误"}`);
      }
      break;
    case "copy":
      need(p.text, "复制内容");
      break;
    case "delay":
      if (Number(p.ms) < 0) error("延时不能为负数");
      break;
    default:
      break;
  }

  const branch = (steps: ActionStep[] | undefined, label: string) => {
    (steps ?? []).forEach((child, index) => {
      validateStep(child, ctx, `${path} → ${label} ${index + 1}`, anchor, out);
    });
  };
  if (step.kind === "condition" || step.kind === "confirm") {
    branch(step.then, "then");
    branch(step.else, "else");
  } else if (step.kind === "loop" || step.kind === "parallel") {
    branch(step.then, "then");
  } else if (step.kind === "tryCatch") {
    branch(step.then, "try");
    branch(step.catch?.length ? step.catch : step.else, "catch");
  }
}

/** 校验整个事件的动作链。 */
export function validateActionSteps(steps: ActionStep[], ctx: ActionContext): ActionIssue[] {
  const out: ActionIssue[] = [];
  steps.forEach((step, index) => {
    validateStep(step, ctx, `步骤 ${index + 1}`, index, out);
  });
  return out;
}

function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return `step-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 新建动作的默认参数（尽量填入首个数据源/模型，减少空目标）。 */
export function makeDefaultStep(kind: ActionKind, ctx?: Partial<ActionContext>): ActionStep {
  const firstDs = ctx?.datasources?.[0];
  const firstModel = ctx?.models?.[0];
  const step: ActionStep = { id: newId(), kind, params: {} };
  switch (kind) {
    case "setVariable":
      step.params = { name: "", value: "" };
      break;
    case "callDatasource":
      step.params = { ref: firstDs ? `ds_${firstDs.id}` : "" };
      break;
    case "navigate":
      step.params = { path: "/", target: "_self" };
      break;
    case "openModal":
    case "openDrawer":
      step.params = { nodeId: "" };
      break;
    case "closeModal":
    case "closeDrawer":
      step.params = { nodeId: "" };
      break;
    case "message":
      step.params = { text: "", type: "info" };
      break;
    case "notification":
      step.params = { text: "", title: "", type: "info" };
      break;
    case "confirm":
      step.params = { text: "", title: "" };
      step.then = [];
      step.else = [];
      break;
    case "record":
      step.params = { modelId: firstModel?.id, op: "list", varName: "" };
      break;
    case "condition":
      step.params = { expr: "true" };
      step.then = [];
      step.else = [];
      break;
    case "loop":
      step.params = { list: "", itemVar: "item", indexVar: "index" };
      step.then = [];
      break;
    case "parallel":
      step.params = {};
      step.then = [];
      break;
    case "tryCatch":
      step.params = {};
      step.then = [];
      step.catch = [];
      break;
    case "delay":
      step.params = { ms: 300 };
      break;
    case "setStyle":
      step.params = { nodeId: "", style: {} };
      break;
    case "emit":
      step.params = { event: "custom" };
      break;
    case "submitForm":
      step.params = { formId: "", modelId: firstModel?.id, op: "create", successText: "提交成功" };
      break;
    case "resetForm":
      step.params = { formId: "" };
      break;
    case "download":
      step.params = { filename: "download.txt", mime: "text/plain;charset=utf-8", content: "" };
      break;
    case "copy":
      step.params = { text: "" };
      break;
    case "print":
      step.params = {};
      break;
    case "http":
      step.params = { method: "GET", path: "" };
      break;
    case "js":
      step.params = { code: "", varName: "" };
      break;
    default:
      break;
  }
  return step;
}
