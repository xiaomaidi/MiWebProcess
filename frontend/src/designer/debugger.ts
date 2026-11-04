/**
 * 设计器运行时调试台：轻量事件总线 + 录制器。
 *
 * 设计目标：
 * - 不修改任何既有文件：通过 window CustomEvent（wp:*）、window error /
 *   unhandledrejection、以及 Pinia store 的 $subscribe 旁路采集；
 * - 录制内容只保留可序列化的快照，最多 500 条，避免持有页面 schema / DOM / 组件实例；
 * - SSR 安全（所有 window 访问均有守卫），组件卸载时自动释放监听与订阅。
 *
 * 接入方式（不修改本题允许范围外的文件）：
 *   import { useDesignerDebugger } from "@/designer/debugger";
 *   const debuggerApi = useDesignerDebugger(); // 在 setup 中调用，自动绑定 schema store
 *   或直接 <DebuggerPanel />（面板内部已完成挂载 / 卸载生命周期）。
 */
import { getCurrentScope, onScopeDispose, ref, shallowRef } from "vue";
import type { PageSchema, SchemaNode } from "@/types";
import { useSchemaStore } from "@/store/schema";

export type DebugEventKind = "action" | "binding" | "event" | "error" | "navigation" | "data";

export interface DebugEvent {
  id: string;
  at: number;
  kind: DebugEventKind;
  label: string;
  detail?: unknown;
  nodeId?: string;
  durationMs?: number;
}

export interface DebugEventInput {
  kind: DebugEventKind;
  label: string;
  detail?: unknown;
  nodeId?: string;
  durationMs?: number;
  /** 仅用于外部回放 / 测试；默认取当前时间。 */
  at?: number;
  /** 仅用于外部回放 / 测试；默认自动生成。 */
  id?: string;
}

/** 事件上限，超出后丢弃最旧记录。 */
export const DEBUG_EVENT_LIMIT = 500;

export const DEBUG_EVENT_KINDS: readonly DebugEventKind[] = [
  "action",
  "binding",
  "event",
  "error",
  "navigation",
  "data",
];

export const DEBUG_KIND_LABELS: Record<DebugEventKind, string> = {
  action: "动作",
  binding: "绑定",
  event: "事件",
  error: "错误",
  navigation: "导航",
  data: "数据",
};

/** 响应式事件列表（新事件追加在末尾）。 */
export const debugEvents = shallowRef<DebugEvent[]>([]);

/** 是否暂停录制；暂停期间 recordDebugEvent 也会直接丢弃。 */
export const debugPaused = ref(false);

let idSeq = 0;

function nextEventId(): string {
  idSeq += 1;
  return `dbg-${Date.now().toString(36)}-${idSeq.toString(36)}`;
}

function clipText(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

const MAX_DETAIL_TEXT = 8000;
const MAX_DETAIL_DEPTH = 5;
const MAX_DETAIL_ARRAY = 40;
const MAX_DETAIL_KEYS = 50;
const MAX_DETAIL_STRING = 2000;

function isPlainObject(value: object): boolean {
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/**
 * 把任意 detail 转成 JSON 安全、体积可控的快照。
 * 不保留原始对象引用（因此不会把 DOM / 组件实例 / 循环结构留在录制列表里）。
 */
function sanitizeDetail(value: unknown, depth = 0, seen = new WeakSet<object>()): unknown {
  if (value === null || value === undefined) return value;
  const valueType = typeof value;
  if (valueType === "string") {
    return (value as string).length > MAX_DETAIL_STRING
      ? `${(value as string).slice(0, MAX_DETAIL_STRING)}…`
      : value;
  }
  if (valueType === "number") {
    return Number.isFinite(value as number) ? value : String(value);
  }
  if (valueType === "boolean") return value;
  if (valueType === "bigint") return `${String(value)}n`;
  if (valueType === "symbol") return String(value);
  if (valueType === "function") {
    return `[Function ${(value as { name?: string }).name || "anonymous"}]`;
  }

  const objectValue = value as object;
  if (seen.has(objectValue)) return "[Circular]";
  if (depth >= MAX_DETAIL_DEPTH) return "[MaxDepth]";
  seen.add(objectValue);

  try {
    if (objectValue instanceof Date) {
      return Number.isNaN(objectValue.getTime()) ? "Invalid Date" : objectValue.toISOString();
    }
    if (objectValue instanceof Error) {
      return {
        name: objectValue.name,
        message: objectValue.message,
        stack: objectValue.stack ? clipText(objectValue.stack, MAX_DETAIL_STRING) : undefined,
      };
    }
    if (typeof Node !== "undefined" && objectValue instanceof Node) {
      const node = objectValue as Node;
      return `[${node.nodeName || "Node"}]`;
    }
    if (typeof Window !== "undefined" && objectValue instanceof Window) return "[Window]";
    if (Array.isArray(objectValue)) {
      const items = objectValue
        .slice(0, MAX_DETAIL_ARRAY)
        .map((item) => sanitizeDetail(item, depth + 1, seen));
      if (objectValue.length > MAX_DETAIL_ARRAY) {
        items.push(`…共 ${objectValue.length} 项`);
      }
      return items;
    }
    if (objectValue instanceof Map) {
      const entries = [...objectValue.entries()].slice(0, MAX_DETAIL_ARRAY);
      return entries.map(([key, item]) => [
        sanitizeDetail(key, depth + 1, seen),
        sanitizeDetail(item, depth + 1, seen),
      ]);
    }
    if (objectValue instanceof Set) {
      return [...objectValue.values()]
        .slice(0, MAX_DETAIL_ARRAY)
        .map((item) => sanitizeDetail(item, depth + 1, seen));
    }
    if (!isPlainObject(objectValue)) {
      const tag = Object.prototype.toString.call(objectValue);
      return `[${tag.slice(8, -1)}]`;
    }

    const source = objectValue as Record<string, unknown>;
    const result: Record<string, unknown> = {};
    const keys = Object.keys(source);
    for (const key of keys.slice(0, MAX_DETAIL_KEYS)) {
      try {
        result[key] = sanitizeDetail(source[key], depth + 1, seen);
      } catch {
        result[key] = "[Unreadable]";
      }
    }
    if (keys.length > MAX_DETAIL_KEYS) {
      result.__truncated__ = `…共 ${keys.length} 个字段`;
    }
    return result;
  } catch {
    return "[Unserializable]";
  } finally {
    seen.delete(objectValue);
  }
}

function normalizeNodeId(value: unknown): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? clipText(trimmed, 120) : undefined;
  }
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return undefined;
}

/** 记录一条调试事件；暂停时返回 null。 */
export function recordDebugEvent(input: DebugEventInput): DebugEvent | null {
  if (!input || typeof input !== "object") return null;
  if (debugPaused.value) return null;

  const kind = DEBUG_EVENT_KINDS.includes(input.kind) ? input.kind : "event";
  const label = clipText(String(input.label ?? "").replace(/\s+/g, " ").trim() || DEBUG_KIND_LABELS[kind], 180);
  const at =
    typeof input.at === "number" && Number.isFinite(input.at) ? input.at : Date.now();
  const event: DebugEvent = {
    id: typeof input.id === "string" && input.id ? input.id : nextEventId(),
    at,
    kind,
    label,
  };
  if (input.detail !== undefined) event.detail = sanitizeDetail(input.detail);
  const nodeId = normalizeNodeId(input.nodeId);
  if (nodeId) event.nodeId = nodeId;
  if (typeof input.durationMs === "number" && Number.isFinite(input.durationMs)) {
    event.durationMs = Math.max(0, Math.round(input.durationMs));
  }

  const current = debugEvents.value;
  debugEvents.value =
    current.length >= DEBUG_EVENT_LIMIT
      ? [...current.slice(current.length - DEBUG_EVENT_LIMIT + 1), event]
      : [...current, event];
  return event;
}

/** 清空录制（不会写入“已清空”事件）。 */
export function clearDebugEvents(): void {
  debugEvents.value = [];
}

export function setDebugPaused(paused: boolean): void {
  debugPaused.value = !!paused;
}

export function toggleDebugPaused(): void {
  debugPaused.value = !debugPaused.value;
}

export type DebugEventSummary = Record<DebugEventKind, number>;

export function debugEventSummary(events: readonly DebugEvent[] = debugEvents.value): DebugEventSummary {
  const summary: DebugEventSummary = {
    action: 0,
    binding: 0,
    event: 0,
    error: 0,
    navigation: 0,
    data: 0,
  };
  for (const event of events) summary[event.kind] += 1;
  return summary;
}

// ---------------------------------------------------------------------------
// window CustomEvent（wp:*）捕获
// ---------------------------------------------------------------------------

const STATIC_WP_EVENTS: readonly string[] = [
  "wp:event",
  "wp:data-changed",
  "wp:navigate",
  "wp:action",
  "wp:binding",
  "wp:message",
  "wp:notification",
  "wp:runtime-ready",
  "wp:page-ready",
];

const STATIC_EVENT_SET = new Set(STATIC_WP_EVENTS);
const trackedEventRefs = new Map<string, number>();
const eventListeners = new Map<string, EventListener>();
let captureUsers = 0;
let captureActive = false;

const MAX_SCHEMA_EVENT_NAMES = 100;

function hasWindow(): boolean {
  return typeof window !== "undefined";
}

function normalizeEventName(name: string): string | null {
  const raw = String(name ?? "").trim();
  if (!raw) return null;
  const full = raw.startsWith("wp:") ? raw : `wp:${raw}`;
  if (!/^wp:[^\s]{1,80}$/.test(full)) return null;
  return full;
}

function attachWpListener(name: string): void {
  if (!hasWindow() || eventListeners.has(name)) return;
  const listener: EventListener = (event) => {
    if (!captureActive || debugPaused.value) return;
    captureWpEvent(name, (event as CustomEvent).detail);
  };
  window.addEventListener(name, listener);
  eventListeners.set(name, listener);
}

function detachWpListener(name: string): void {
  if (!hasWindow()) return;
  const listener = eventListeners.get(name);
  if (!listener) return;
  window.removeEventListener(name, listener);
  eventListeners.delete(name);
}

/**
 * 动态订阅一个 wp:* 事件（设计器里页面事件名可能来自 schema，无法静态枚举）。
 * 返回取消订阅函数；重复调用按引用计数管理。
 */
export function trackDebugEventName(name: string): () => void {
  const full = normalizeEventName(name);
  if (!full) return () => {};
  trackedEventRefs.set(full, (trackedEventRefs.get(full) || 0) + 1);
  if (captureActive) attachWpListener(full);

  let released = false;
  return () => {
    if (released) return;
    released = true;
    const remaining = (trackedEventRefs.get(full) || 0) - 1;
    if (remaining > 0) {
      trackedEventRefs.set(full, remaining);
      return;
    }
    trackedEventRefs.delete(full);
    if (!STATIC_EVENT_SET.has(full)) detachWpListener(full);
  };
}

function pickNodeId(value: unknown, depth = 0): string | undefined {
  if (!value || typeof value !== "object" || depth > 2) return undefined;
  const record = value as Record<string, unknown>;
  const direct = normalizeNodeId(record.nodeId ?? record.node_id);
  if (direct) return direct;
  for (const key of ["detail", "payload", "data"]) {
    const nested = record[key];
    if (nested && typeof nested === "object" && nested !== value) {
      const found = pickNodeId(nested, depth + 1);
      if (found) return found;
    }
  }
  return undefined;
}

function pickDuration(value: unknown): number | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  const duration = record.durationMs ?? record.duration_ms ?? record.duration;
  return typeof duration === "number" && Number.isFinite(duration) ? duration : undefined;
}

function captureWpEvent(name: string, detail: unknown): void {
  const payload = detail as Record<string, any> | undefined;
  if (name === "wp:event") {
    const eventName = typeof payload?.name === "string" ? payload.name : "event";
    const inner = payload && "detail" in payload ? payload.detail : detail;
    recordDebugEvent({
      kind: "event",
      label: `事件 · ${eventName}`,
      detail: payload ?? detail,
      nodeId: pickNodeId(inner),
      durationMs: pickDuration(inner),
    });
    return;
  }
  if (name === "wp:data-changed") {
    const modelId = payload?.modelId ?? payload?.model_id;
    recordDebugEvent({
      kind: "data",
      label: modelId !== undefined && modelId !== null ? `数据变更 · 模型 ${modelId}` : "数据变更",
      detail,
      nodeId: pickNodeId(detail),
      durationMs: pickDuration(detail),
    });
    return;
  }
  if (name === "wp:navigate") {
    const path = payload?.path ?? payload?.url ?? payload?.to ?? "";
    recordDebugEvent({
      kind: "navigation",
      label: path ? `导航 · ${path}` : "页面导航",
      detail,
      nodeId: pickNodeId(detail),
    });
    return;
  }
  if (name === "wp:action") {
    const action = payload?.label ?? payload?.action ?? payload?.kind ?? "动作";
    recordDebugEvent({
      kind: "action",
      label: `动作 · ${String(action)}`,
      detail,
      nodeId: pickNodeId(detail),
      durationMs: pickDuration(detail),
    });
    return;
  }
  if (name === "wp:binding") {
    const binding = payload?.label ?? payload?.ref ?? payload?.name ?? "绑定";
    recordDebugEvent({
      kind: "binding",
      label: `绑定 · ${String(binding)}`,
      detail,
      nodeId: pickNodeId(detail),
      durationMs: pickDuration(detail),
    });
    return;
  }

  const shortName = name.replace(/^wp:/, "");
  recordDebugEvent({
    kind: "event",
    label: `事件 · ${shortName}`,
    detail,
    nodeId: pickNodeId(detail),
    durationMs: pickDuration(detail),
  });
}

function onWindowError(event: ErrorEvent): void {
  const error = event.error instanceof Error ? event.error : null;
  const message = error?.message || event.message || "脚本错误";
  recordDebugEvent({
    kind: "error",
    label: clipText(message, 160),
    detail: {
      message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      stack: error?.stack ? clipText(error.stack, MAX_DETAIL_STRING) : undefined,
    },
  });
}

function onUnhandledRejection(event: PromiseRejectionEvent): void {
  const reason = event.reason;
  let message = "未处理的 Promise 拒绝";
  if (reason instanceof Error) message = reason.message || message;
  else if (typeof reason === "string" && reason) message = reason;
  recordDebugEvent({
    kind: "error",
    label: clipText(`Promise 拒绝 · ${message}`, 160),
    detail: {
      reason:
        reason instanceof Error
          ? { name: reason.name, message: reason.message, stack: reason.stack }
          : reason,
    },
  });
}

function onPopState(): void {
  if (!hasWindow()) return;
  recordDebugEvent({
    kind: "navigation",
    label: "浏览器历史切换",
    detail: { url: window.location.pathname + window.location.search + window.location.hash },
  });
}

function onHashChange(): void {
  if (!hasWindow()) return;
  recordDebugEvent({
    kind: "navigation",
    label: "URL 锚点变化",
    detail: { hash: window.location.hash },
  });
}

function installWindowCapture(): () => void {
  if (!hasWindow()) return () => {};
  captureUsers += 1;
  if (!captureActive) {
    captureActive = true;
    for (const name of STATIC_WP_EVENTS) attachWpListener(name);
    for (const name of trackedEventRefs.keys()) attachWpListener(name);
    window.addEventListener("error", onWindowError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);
    window.addEventListener("popstate", onPopState);
    window.addEventListener("hashchange", onHashChange);
  }

  let released = false;
  return () => {
    if (released) return;
    released = true;
    captureUsers = Math.max(0, captureUsers - 1);
    if (captureUsers > 0 || !hasWindow()) return;
    captureActive = false;
    for (const [name, listener] of eventListeners) {
      window.removeEventListener(name, listener);
    }
    eventListeners.clear();
    window.removeEventListener("error", onWindowError);
    window.removeEventListener("unhandledrejection", onUnhandledRejection);
    window.removeEventListener("popstate", onPopState);
    window.removeEventListener("hashchange", onHashChange);
  };
}

// ---------------------------------------------------------------------------
// Pinia schema store 旁路观察
// ---------------------------------------------------------------------------

export interface DebugSchemaStoreLike {
  $subscribe?: (
    callback: (mutation: { type?: string }, state: unknown) => void,
    options?: { detached?: boolean; deep?: boolean }
  ) => () => void;
  schema?: PageSchema | null;
  selectedId?: string | null;
  selectedIds?: string[];
  dirty?: boolean;
  pageId?: number;
  appId?: number;
}

interface SchemaSubscription {
  refs: number;
  release: () => void;
}

const schemaSubscriptions = new WeakMap<object, SchemaSubscription>();

function resolveSchemaStore(): DebugSchemaStoreLike | null {
  try {
    // 无 active pinia（SSR / 单测）时 useSchemaStore 会抛错，安全返回 null。
    return useSchemaStore() as unknown as DebugSchemaStoreLike;
  } catch {
    return null;
  }
}

function selectionKey(id: string | null | undefined, ids: string[] | undefined): string {
  return `${id ?? ""}|${(ids || []).join(",")}`;
}

function nodeLabel(node: SchemaNode): string {
  const props = node.props || {};
  const text = props.label ?? props.title ?? props.content ?? props.text ?? props.name ?? "";
  const clean = String(text).replace(/\s+/g, " ").trim();
  return clean ? `${clipText(clean, 32)} (${node.type})` : node.type;
}

function schemaEventNames(schema: PageSchema | null): string[] {
  if (!schema) return [];
  const names = new Set<string>();
  try {
    for (const name of Object.keys(schema.events || {})) {
      names.add(name);
      if (names.size >= MAX_SCHEMA_EVENT_NAMES) break;
    }
    for (const node of Object.values(schema.nodes || {})) {
      for (const name of Object.keys(node.events || {})) {
        names.add(name);
        if (names.size >= MAX_SCHEMA_EVENT_NAMES) break;
      }
      if (names.size >= MAX_SCHEMA_EVENT_NAMES) break;
    }
  } catch {
    /* 损坏的 schema 不阻断调试台 */
  }
  return [...names];
}

function syncSchemaEventNames(schema: PageSchema | null): Array<() => void> {
  const releases: Array<() => void> = [];
  for (const name of schemaEventNames(schema)) {
    try {
      releases.push(trackDebugEventName(name));
    } catch {
      /* ignore */
    }
  }
  return releases;
}

function installSchemaWatch(store: DebugSchemaStoreLike): () => void {
  if (typeof store.$subscribe !== "function") return () => {};

  let lastSchema = store.schema ?? null;
  let lastSelection = selectionKey(store.selectedId, store.selectedIds);
  let lastDirty = !!store.dirty;
  let eventNameReleases = syncSchemaEventNames(lastSchema);

  const unsubscribe = store.$subscribe(
    (_mutation, state) => {
      const current = (state || store) as DebugSchemaStoreLike;
      const schema = current.schema ?? null;

      if (schema !== lastSchema) {
        lastSchema = schema;
        lastSelection = selectionKey(current.selectedId, current.selectedIds);
        lastDirty = !!current.dirty;
        for (const release of eventNameReleases.splice(0)) release();
        eventNameReleases = syncSchemaEventNames(schema);
        recordDebugEvent({
          kind: "data",
          label: schema ? "页面结构已载入" : "页面结构已清空",
          detail: schema
            ? {
                pageId: current.pageId,
                appId: current.appId,
                rootId: schema.rootId,
                nodeCount: Object.keys(schema.nodes || {}).length,
              }
            : undefined,
          nodeId: schema?.rootId,
        });
        return;
      }

      const selection = selectionKey(current.selectedId, current.selectedIds);
      if (selection !== lastSelection) {
        lastSelection = selection;
        const selectedId = current.selectedId ?? null;
        const node = selectedId && schema ? schema.nodes[selectedId] : undefined;
        recordDebugEvent({
          kind: "action",
          label: selectedId
            ? node
              ? `选中节点 · ${nodeLabel(node)}`
              : `选中节点 · ${selectedId}`
            : "取消选中",
          detail: {
            selectedId,
            selectedIds: [...(current.selectedIds || [])],
            type: node?.type,
          },
          nodeId: selectedId ?? undefined,
        });
      }

      const dirty = !!current.dirty;
      if (dirty !== lastDirty) {
        lastDirty = dirty;
        recordDebugEvent({
          kind: "action",
          label: dirty ? "画布已修改" : "改动已保存",
          detail: { dirty },
          nodeId: current.selectedId ?? undefined,
        });
      }
    },
    // deep 才能捕获直接赋值（如 store.selectedId = ...）；detached 避免绑定组件 scope。
    { detached: true, deep: true }
  );

  return () => {
    for (const release of eventNameReleases.splice(0)) release();
    try {
      unsubscribe();
    } catch {
      /* ignore */
    }
  };
}

function acquireSchemaSubscription(store: DebugSchemaStoreLike): () => void {
  const key = store as unknown as object;
  let entry = schemaSubscriptions.get(key);
  if (!entry) {
    entry = { refs: 0, release: installSchemaWatch(store) };
    schemaSubscriptions.set(key, entry);
  }
  entry.refs += 1;
  const current = entry;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    current.refs -= 1;
    if (current.refs > 0) return;
    current.release();
    schemaSubscriptions.delete(key);
  };
}

// ---------------------------------------------------------------------------
// 组合式入口
// ---------------------------------------------------------------------------

export interface DesignerDebuggerOptions {
  /**
   * 显式传入 schema store（便于测试 / 非 setup 环境）。
   * 不传时自动尝试 useSchemaStore()；失败则只采集 window 事件。
   */
  schemaStore?: DebugSchemaStoreLike | null;
}

export interface DesignerDebuggerHandle {
  events: typeof debugEvents;
  paused: typeof debugPaused;
  record: typeof recordDebugEvent;
  clear: typeof clearDebugEvents;
  pause: () => void;
  resume: () => void;
  toggle: () => void;
  /** 释放 window 监听与 store 订阅；重复调用安全。 */
  stop: () => void;
}

/**
 * 在组件 setup 中调用：自动开始采集，并在组件卸载（scope dispose）时释放。
 * 也可在非组件环境调用，此时需自行调用返回的 stop()。
 */
export function useDesignerDebugger(options: DesignerDebuggerOptions = {}): DesignerDebuggerHandle {
  const releaseWindow = installWindowCapture();
  const schemaStore =
    options.schemaStore === undefined ? resolveSchemaStore() : options.schemaStore;
  const releaseSchema = schemaStore ? acquireSchemaSubscription(schemaStore) : () => {};

  let stopped = false;
  const stop = () => {
    if (stopped) return;
    stopped = true;
    releaseSchema();
    releaseWindow();
  };

  if (getCurrentScope()) onScopeDispose(stop);

  return {
    events: debugEvents,
    paused: debugPaused,
    record: recordDebugEvent,
    clear: clearDebugEvents,
    pause: () => setDebugPaused(true),
    resume: () => setDebugPaused(false),
    toggle: toggleDebugPaused,
    stop,
  };
}
