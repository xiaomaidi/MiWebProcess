/**
 * 页面协同静态分析。
 *
 * 表达式使用 expr-eval 的 tokenizer 解析（IVAR / IMEMBER），
 * 比纯字符串搜索更准确；绑定值仍按 __binding__.ref 精确读取。
 */
import { Parser } from "expr-eval";
import type { ActionStep, ComponentMeta, PageSchema } from "@/types";

const parser = new Parser({ allowMemberAccess: true });

export interface StateUsage {
  key: string;
  setters: string[];
  readers: string[];
  providers: string[];
}

export interface EventUsage {
  event: string;
  defined: boolean;
  senders: string[];
  receivers: string[];
}

export interface DependencyUsage {
  label: string;
  type: string;
  provides: string[];
  consumes: string[];
}

export interface CoordinationAnalysis {
  states: StateUsage[];
  events: EventUsage[];
  dependencies: DependencyUsage[];
  expressionCount: number;
}

function walkSteps(steps: any, cb: (step: ActionStep) => void) {
  if (!Array.isArray(steps)) return;
  for (const step of steps) {
    if (!step || typeof step !== "object") continue;
    cb(step);
    walkSteps(step.then, cb);
    walkSteps(step.else, cb);
    walkSteps(step.catch, cb);
  }
}

function scanBindings(value: any, cb: (name: string) => void) {
  if (Array.isArray(value)) {
    for (const item of value) scanBindings(item, cb);
    return;
  }
  if (!value || typeof value !== "object") return;
  if (value.__binding__) {
    if (value.__binding__.source === "variable" && value.__binding__.ref) {
      cb(String(value.__binding__.ref));
    }
    return;
  }
  for (const item of Object.values(value)) scanBindings(item, cb);
}

/** 从一段表达式中提取成员路径，例如 stock.selectedId → ["stock.selectedId"]。 */
function expressionPaths(expr: string): string[] {
  const source = expr.trim();
  if (!source) return [];
  try {
    const parsed: any = parser.parse(source);
    const tokens = parsed?.tokens || [];
    const paths: string[] = [];
    let current = "";
    for (const token of tokens) {
      if (token.type === "IVAR") {
        if (current) paths.push(current);
        current = String(token.value || "");
      } else if (token.type === "IMEMBER" && current) {
        current += `.${token.value}`;
      } else {
        if (current) paths.push(current);
        current = "";
      }
    }
    if (current) paths.push(current);
    return paths;
  } catch {
    // 解析失败时退回标识符扫描，避免整段表达式被忽略。
    return Array.from(source.matchAll(/[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*/g)).map(
      (match) => match[0]
    );
  }
}

function extractExpressions(text: string): string[] {
  const out: string[] = [];
  for (const match of text.matchAll(/\{\{([\s\S]*?)\}\}/g)) out.push(match[1]);
  return out;
}

export function analyzeCoordination(
  schema: PageSchema | null,
  metaOf: (type: string) => ComponentMeta | undefined
): CoordinationAnalysis {
  if (!schema) return { states: [], events: [], dependencies: [], expressionCount: 0 };
  const stateMap: Record<string, { setters: Set<string>; readers: Set<string>; providers: Set<string> }> = {};
  const eventMap: Record<string, { defined: boolean; senders: Set<string>; receivers: Set<string> }> = {};
  const dependencies: DependencyUsage[] = [];
  let expressionCount = 0;

  const ensureState = (key: string) =>
    (stateMap[key] ||= { setters: new Set(), readers: new Set(), providers: new Set() });
  const ensureEvent = (name: string) =>
    (eventMap[name] ||= { defined: !!schema.events?.[name], senders: new Set(), receivers: new Set() });

  for (const key of Object.keys(schema.state || {})) ensureState(key);
  for (const key of Object.keys(schema.events || {})) ensureEvent(key);

  const aliases = new Map<string, string>();
  for (const key of Object.keys(schema.state || {})) {
    aliases.set(key, key);
    aliases.set(key.replace(/:/g, "."), key);
  }

  const readExpression = (text: string, owner: string) => {
    const expressions = extractExpressions(text);
    if (!expressions.length) {
      // 纯表达式字段（condition / action param）也进入解析。
      if (/[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+/.test(text)) expressions.push(text);
    }
    for (const expr of expressions) {
      expressionCount += 1;
      for (const path of expressionPaths(expr)) {
        for (const [alias, key] of aliases) {
          if (path === alias || path.startsWith(`${alias}.`)) {
            ensureState(key).readers.add(owner);
            break;
          }
        }
      }
    }
  };

  const scanValue = (value: any, owner: string) => {
    if (typeof value === "string") {
      readExpression(value, owner);
      return;
    }
    if (Array.isArray(value)) {
      for (const item of value) scanValue(item, owner);
      return;
    }
    if (value && typeof value === "object") {
      for (const item of Object.values(value)) scanValue(item, owner);
    }
  };

  for (const node of Object.values(schema.nodes || {})) {
    const label = node.props?.label || node.props?.title || node.type;
    const meta = metaOf(node.type);
    if (meta) {
      const dependency: DependencyUsage = {
        label,
        type: node.type,
        provides: [...(meta.provides || [])],
        consumes: [...(meta.consumes || [])],
      };
      if (dependency.provides.length || dependency.consumes.length) dependencies.push(dependency);
      for (const item of meta.provides || []) {
        if (String(item).startsWith("state:")) ensureState(String(item).slice(6)).providers.add(label);
      }
      for (const item of meta.consumes || []) {
        if (String(item).startsWith("event:")) ensureEvent(String(item).slice(6)).receivers.add(label);
      }
    }
    scanBindings(node.props, (name) => ensureState(name).readers.add(label));
    scanValue(node.props, label);
    if (node.condition?.expr) readExpression(node.condition.expr, label);
    for (const steps of Object.values(node.events || {})) {
      walkSteps(steps, (step) => {
        if (step.kind === "setVariable" && step.params?.name) ensureState(String(step.params.name)).setters.add(label);
        if (step.params?.varName) ensureState(String(step.params.varName)).setters.add(label);
        if (step.kind === "emit") ensureEvent(String(step.params?.event || "custom")).senders.add(label);
        scanValue(step.params || {}, label);
      });
    }
  }

  for (const [phase, steps] of Object.entries(schema.lifecycle || {})) {
    walkSteps(steps, (step) => {
      if (step.kind === "setVariable" && step.params?.name) ensureState(String(step.params.name)).setters.add(`lifecycle.${phase}`);
      if (step.params?.varName) ensureState(String(step.params.varName)).setters.add(`lifecycle.${phase}`);
      if (step.kind === "emit") ensureEvent(String(step.params?.event || "custom")).senders.add(`lifecycle.${phase}`);
      scanValue(step.params || {}, `lifecycle.${phase}`);
    });
  }

  return {
    states: Object.entries(stateMap)
      .map(([key, value]) => ({
        key,
        setters: [...value.setters],
        readers: [...value.readers],
        providers: [...value.providers],
      }))
      .sort((a, b) => a.key.localeCompare(b.key)),
    events: Object.entries(eventMap)
      .map(([event, value]) => ({
        event,
        defined: value.defined,
        senders: [...value.senders],
        receivers: [...value.receivers],
      }))
      .sort((a, b) => a.event.localeCompare(b.event)),
    dependencies,
    expressionCount,
  };
}
