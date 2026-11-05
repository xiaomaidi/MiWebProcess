/**
 * 设计器「操作录制 / 回放」引擎。
 *
 * 设计目标（不修改任何既有文件）：
 * - 通过 Pinia schema / history store 的 $subscribe 旁路采集，不侵入设计器逻辑；
 * - 每次动作保留「前 / 后」schema 的有界、可 JSON 序列化深拷贝（字符串 / 深度 / 节点数均有上限）；
 * - 最多 100 条动作，另有单快照 / 总内存 / 会话体积三级保护；
 * - 回放优先交给接入方回调（onApply），未提供时回退为 schema store 安全赋值，
 *   不使用 setSchema（避免重置 pageId / appId / 选中 / dirty）；可选 setSchema 模式；
 * - 回放与撤销历史集成：回放开始记录 schema / 历史栈状态，整次回放合并为一条历史命令
 *   （`replayHistoryMode: "single"`，默认），`"none"` 保持旧行为；中途停止按「部分结果」提交，
 *   一步未应用则保持不变。详见 recorder-history.ts；
 * - 所有 window / sessionStorage 访问都有守卫，SSR 下安全。
 *
 * 接入方式（推荐）：
 *   // DesignerView.vue（本文件未修改，需人工接入）
 *   <el-drawer v-model="recorderOpen" title="操作录制" size="460px">
 *     <RecorderPanel />
 *   </el-drawer>
 *
 * 或在设计器根组件提前调用，保证面板打开前的动作也被记录：
 *   const recorder = useActionRecorder({ autoStart: true });
 *   recorder.start(); // 自动开始
 */

import { getCurrentScope, onScopeDispose, ref, shallowRef, watch } from "vue";
import type { PageSchema } from "@/types";
import { useHistoryStore } from "@/store/history";
import { useSchemaStore } from "@/store/schema";
import { deepClone } from "@/utils";
import {
  DEFAULT_REPLAY_HISTORY_MODE,
  captureReplayHistory,
  commitReplayHistory,
  markReplayApplied,
  normalizeReplayHistoryMode,
  type ReplayHistoryCapture,
  type ReplayHistoryCommitResult,
  type ReplayHistoryMode,
  type RecorderHistoryCommandLike,
  type RecorderHistoryStoreLike,
} from "./recorder-history";

export {
  DEFAULT_REPLAY_HISTORY_MODE,
  REPLAY_HISTORY_MODES,
  buildReplayHistoryLabel,
  normalizeReplayHistoryMode,
} from "./recorder-history";
export type {
  ReplayHistoryCapture,
  ReplayHistoryCommitResult,
  ReplayHistoryMode,
  ReplayHistorySkipReason,
  ReplayHistoryStateSnapshot,
  RecorderHistoryCommandLike,
  RecorderHistoryStoreLike,
} from "./recorder-history";

// ---------------------------------------------------------------------------
// 常量与类型
// ---------------------------------------------------------------------------

/** 动作条数上限（题目要求 100）。 */
export const RECORDER_MAX_ACTIONS = 100;
/** 单份快照（JSON 字符数）上限，超出则该动作不保留结构快照。 */
export const RECORDER_MAX_SNAPSHOT_BYTES = 1_500_000;
/** 所有快照的总内存估算上限（JSON 字符数）。 */
export const RECORDER_MAX_TOTAL_BYTES = 8_000_000;
/** sessionStorage 单次写入体积上限（字符数，sessionStorage 通常约 5MB）。 */
export const RECORDER_MAX_SESSION_BYTES = 2_000_000;
/** 回放速度范围（毫秒 / 步）。 */
export const RECORDER_SPEED_MIN = 300;
export const RECORDER_SPEED_MAX = 2000;
export const RECORDER_SPEED_DEFAULT = 800;
export const RECORDER_SESSION_KEY = "wp.designer.recorder.v1";

export type RecorderStatus = "idle" | "recording" | "paused" | "replaying";
export type RecorderSource = "baseline" | "history" | "snapshot" | "undo" | "redo" | "import" | "manual";

export const RECORDER_SOURCE_LABELS: Record<RecorderSource, string> = {
  baseline: "基线",
  history: "编辑",
  snapshot: "变更",
  undo: "撤销",
  redo: "重做",
  import: "导入",
  manual: "快照",
};

export interface RecorderSelection {
  selectedId: string | null;
  selectedIds: string[];
}

/** 一条录制动作：before/after 均为有界深拷贝（可能因超限为 null）。 */
export interface RecordedAction {
  id: string;
  /** 会话内单调递增序号（导入后重排）。 */
  seq: number;
  label: string;
  /** 记录时刻（epoch ms）。 */
  at: number;
  /** 相对本次录制开始的毫秒数。 */
  elapsedMs: number;
  /** 动作耗时（由 schema 首次变更到历史命令落栈的近似值，0 表示未知）。 */
  durationMs: number;
  before: PageSchema | null;
  after: PageSchema | null;
  beforeBytes: number;
  afterBytes: number;
  selectionBefore: RecorderSelection;
  selection: RecorderSelection;
  source: RecorderSource;
  /** 快照被裁剪（长字符串 / 深层结构 / 超量节点）。 */
  truncated: boolean;
  /** after 快照因超过单份上限被省略，回放时跳过该条。 */
  snapshotOmitted: boolean;
}

export interface RecorderExport {
  format: "wp-designer-recorder";
  version: 1;
  exportedAt: number;
  pageId: number;
  appId: number;
  actions: RecordedAction[];
}

export interface RecorderSessionInfo {
  count: number;
  savedAt: number;
  pageId: number;
}

export interface ImportResult {
  ok: boolean;
  count: number;
  dropped: number;
  error?: string;
}

export interface ReplayOptions {
  /** 每步间隔（300-2000ms）。 */
  speedMs?: number;
  /** 起始动作下标（默认 0）。 */
  fromIndex?: number;
  /** 优先于引擎回调：由接入方把快照写入自己的 store / 编辑器。 */
  onApply?: (schema: PageSchema, action: RecordedAction) => void | Promise<void>;
  /** 默认 assign（保留历史栈）；setSchema 会重置选中 / pageId / dirty。 */
  applyMode?: "assign" | "setSchema";
  /** 本次回放的历史写入模式；缺省读引擎配置（默认 "single"）。 */
  replayHistoryMode?: ReplayHistoryMode;
}

/** 只依赖 schema store 的稳定子集（便于测试 / SSR 注入）。 */
export interface RecorderSchemaStoreLike {
  $subscribe?: (
    callback: (mutation: { type?: string }, state: unknown) => void,
    options?: { detached?: boolean; deep?: boolean }
  ) => () => void;
  schema?: PageSchema | null;
  selectedId?: string | null;
  selectedIds?: string[];
  pageId?: number;
  appId?: number;
  dirty?: boolean;
  setSchema?: (schema: PageSchema | null, pageId?: number, appId?: number) => void;
  select?: (id: string | null, additive?: boolean) => void;
  selectMany?: (ids: string[]) => void;
}

export interface ActionRecorderOptions {
  schemaStore?: RecorderSchemaStoreLike | null;
  historyStore?: RecorderHistoryStoreLike | null;
  maxActions?: number;
  maxSnapshotBytes?: number;
  maxTotalBytes?: number;
  maxSessionBytes?: number;
  /** schema 变更合并窗口（毫秒）。 */
  debounceMs?: number;
  /** 是否把记录写入 sessionStorage（默认关闭）。 */
  persistSession?: boolean;
  /** useActionRecorder 调用时自动开始录制（默认关闭）。 */
  autoStart?: boolean;
  /** sessionStorage 键；默认按 pageId 分键。 */
  sessionKey?: string;
  /** 回放默认写入方式。 */
  applyMode?: "assign" | "setSchema";
  /** 优先回调：接入方自行应用快照（需同时恢复 action.selection）。 */
  onApply?: (schema: PageSchema, action: RecordedAction) => void | Promise<void>;
  /** 每记录一条动作回调（可用于自动保存 / 埋点）。 */
  onRecord?: (action: RecordedAction) => void;
  /**
   * 回放结果写入撤销历史的模式：
   * - "single"（默认）整次回放合并为一条命令；
   * - "none" 不写历史（兼容接入前的旧行为）。
   */
  replayHistoryMode?: ReplayHistoryMode;
  /**
   * 历史 store 不支持 `push(label, before, after)` 时的兜底回调。
   * 返回 false 表示放弃写入；不提供则跳过写历史（回放本身不受影响）。
   */
  onPushHistory?: (label: string, before: PageSchema, after: PageSchema) => boolean | void;
}

// ---------------------------------------------------------------------------
// 有界深拷贝 / 指纹 / 内存
// ---------------------------------------------------------------------------

const MAX_DEPTH = 16;
const MAX_STRING = 4000;
const MAX_ARRAY = 3000;
const MAX_KEYS = 5000;
const MAX_SELECTION_IDS = 500;

interface Snapshot {
  schema: PageSchema | null;
  bytes: number;
  truncated: boolean;
  omitted: boolean;
  fingerprint: string;
}

function hashText(text: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return `${(hash >>> 0).toString(36)}:${text.length.toString(36)}`;
}

interface SanitizeState {
  truncated: boolean;
}

function sanitizeValue(value: unknown, depth: number, seen: WeakSet<object>, state: SanitizeState): unknown {
  if (value === null) return null;
  const valueType = typeof value;
  if (valueType === "undefined") return undefined;
  if (valueType === "string") {
    if ((value as string).length > MAX_STRING) {
      state.truncated = true;
      return `${(value as string).slice(0, MAX_STRING)}…[截断]`;
    }
    return value;
  }
  if (valueType === "number") {
    return Number.isFinite(value as number) ? value : String(value);
  }
  if (valueType === "boolean") return value;
  if (valueType === "bigint") return `${String(value)}n`;
  if (valueType === "function") {
    state.truncated = true;
    return undefined;
  }
  if (valueType === "symbol") return String(value);

  const objectValue = value as object;
  if (seen.has(objectValue)) {
    state.truncated = true;
    return "[Circular]";
  }
  if (depth >= MAX_DEPTH) {
    state.truncated = true;
    return null;
  }
  seen.add(objectValue);

  try {
    if (objectValue instanceof Date) return objectValue.toISOString();
    if (Array.isArray(objectValue)) {
      const length = Math.min(objectValue.length, MAX_ARRAY);
      if (objectValue.length > MAX_ARRAY) state.truncated = true;
      const out: unknown[] = [];
      for (let i = 0; i < length; i += 1) {
        const item = sanitizeValue(objectValue[i], depth + 1, seen, state);
        if (item !== undefined) out.push(item);
      }
      return out;
    }
    const keys = Object.keys(objectValue);
    if (keys.length > MAX_KEYS) state.truncated = true;
    const out: Record<string, unknown> = {};
    for (const key of keys.slice(0, MAX_KEYS)) {
      let raw: unknown;
      try {
        raw = (objectValue as Record<string, unknown>)[key];
      } catch {
        state.truncated = true;
        continue;
      }
      const item = sanitizeValue(raw, depth + 1, seen, state);
      if (item !== undefined) out[key] = item;
    }
    return out;
  } catch {
    state.truncated = true;
    return "[无法序列化]";
  }
}

export function looksLikePageSchema(value: unknown): value is PageSchema {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<PageSchema>;
  return (
    typeof candidate.rootId === "string" &&
    !!candidate.nodes &&
    typeof candidate.nodes === "object" &&
    !Array.isArray(candidate.nodes)
  );
}

function emptySnapshot(): Snapshot {
  return { schema: null, bytes: 0, truncated: false, omitted: false, fingerprint: "none" };
}

function buildSnapshot(value: unknown, maxBytes: number): Snapshot {
  if (!value || typeof value !== "object") return emptySnapshot();
  const state: SanitizeState = { truncated: false };
  let json = "";
  try {
    const clean = sanitizeValue(value, 0, new WeakSet<object>(), state);
    if (!clean || typeof clean !== "object") return emptySnapshot();
    json = JSON.stringify(clean);
  } catch {
    return { schema: null, bytes: 0, truncated: true, omitted: true, fingerprint: `invalid:${Date.now().toString(36)}` };
  }
  const bytes = json.length;
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return { schema: null, bytes, truncated: true, omitted: true, fingerprint: `invalid:${hashText(json)}` };
  }
  if (!looksLikePageSchema(parsed)) {
    return { schema: null, bytes, truncated: true, omitted: true, fingerprint: `invalid:${hashText(json)}` };
  }
  if (bytes > maxBytes) {
    return { schema: null, bytes, truncated: true, omitted: true, fingerprint: `omitted:${hashText(json)}` };
  }
  return {
    schema: parsed,
    bytes,
    truncated: state.truncated,
    omitted: false,
    fingerprint: hashText(json),
  };
}

/** 对已经是纯 JSON 的 schema 计算与 buildSnapshot 一致的指纹。 */
function fingerprintSchema(schema: PageSchema | null): string {
  if (!schema) return "none";
  try {
    return hashText(JSON.stringify(schema));
  } catch {
    return `invalid:${Date.now().toString(36)}`;
  }
}

function sanitizeSelection(value: unknown): RecorderSelection {
  if (!value || typeof value !== "object") return { selectedId: null, selectedIds: [] };
  const raw = value as { selectedId?: unknown; selectedIds?: unknown };
  const ids = Array.isArray(raw.selectedIds)
    ? raw.selectedIds.filter((item): item is string => typeof item === "string").slice(0, MAX_SELECTION_IDS)
    : [];
  const selectedId = typeof raw.selectedId === "string" ? raw.selectedId : null;
  return { selectedId, selectedIds: ids };
}

function selectionKey(selection: RecorderSelection): string {
  return `${selection.selectedId || ""}|${selection.selectedIds.join(",")}`;
}

function clipLabel(value: unknown, fallback = "画布变更"): string {
  const text = typeof value === "string" ? value : "";
  const clean = text.replace(/\s+/g, " ").trim();
  if (!clean) return fallback;
  return clean.length > 120 ? `${clean.slice(0, 120)}…` : clean;
}

function estimateMemoryBytes(actions: RecordedAction[]): number {
  const seen = new Set<PageSchema>();
  let total = 0;
  for (const action of actions) {
    if (action.before && !seen.has(action.before)) {
      seen.add(action.before);
      total += action.beforeBytes;
    }
    if (action.after && !seen.has(action.after)) {
      seen.add(action.after);
      total += action.afterBytes;
    }
  }
  return total;
}

function clampNumber(value: unknown, min: number, max: number, fallback: number): number {
  const num = typeof value === "number" && Number.isFinite(value) ? value : fallback;
  return Math.min(max, Math.max(min, Math.round(num)));
}

export function clampReplaySpeed(value: unknown): number {
  return clampNumber(value, RECORDER_SPEED_MIN, RECORDER_SPEED_MAX, RECORDER_SPEED_DEFAULT);
}

// ---------------------------------------------------------------------------
// 共享响应式状态（单例；面板与接入方读取同一份）
// ---------------------------------------------------------------------------

export const recorderActions = shallowRef<RecordedAction[]>([]);
export const recorderStatus = ref<RecorderStatus>("idle");
export const recorderReplayPaused = ref(false);
export const recorderReplayIndex = ref(-1);
export const recorderReplaySpeed = ref(RECORDER_SPEED_DEFAULT);
export const recorderMemoryBytes = ref(0);
export const recorderDropped = ref(0);
export const recorderLastError = ref("");
/** 当前回放历史写入模式（面板 / 接入方可读；也可用 handle.setReplayHistoryMode 修改）。 */
export const recorderReplayHistoryMode = ref<ReplayHistoryMode>(DEFAULT_REPLAY_HISTORY_MODE);
/** 最近一次回放（含 jumpTo）的历史提交结果；null 表示尚未发生。 */
export const recorderLastReplayHistory = shallowRef<ReplayHistoryCommitResult | null>(null);

// ---------------------------------------------------------------------------
// 引擎
// ---------------------------------------------------------------------------

interface NormalizedOptions {
  schemaStore: RecorderSchemaStoreLike | null | undefined;
  historyStore: RecorderHistoryStoreLike | null | undefined;
  maxActions: number;
  maxSnapshotBytes: number;
  maxTotalBytes: number;
  maxSessionBytes: number;
  debounceMs: number;
  persistSession: boolean;
  sessionKey: string;
  applyMode: "assign" | "setSchema";
  onApply?: (schema: PageSchema, action: RecordedAction) => void | Promise<void>;
  onRecord?: (action: RecordedAction) => void;
  replayHistoryMode: ReplayHistoryMode;
  onPushHistory?: (label: string, before: PageSchema, after: PageSchema) => boolean | void;
}

function normalizeOptions(options: ActionRecorderOptions): NormalizedOptions {
  return {
    schemaStore: options.schemaStore,
    historyStore: options.historyStore,
    maxActions: clampNumber(options.maxActions, 1, RECORDER_MAX_ACTIONS, RECORDER_MAX_ACTIONS),
    maxSnapshotBytes: clampNumber(
      options.maxSnapshotBytes,
      64_000,
      16_000_000,
      RECORDER_MAX_SNAPSHOT_BYTES
    ),
    maxTotalBytes: clampNumber(options.maxTotalBytes, 256_000, 64_000_000, RECORDER_MAX_TOTAL_BYTES),
    maxSessionBytes: clampNumber(
      options.maxSessionBytes,
      64_000,
      4_500_000,
      RECORDER_MAX_SESSION_BYTES
    ),
    debounceMs: clampNumber(options.debounceMs, 20, 2000, 120),
    persistSession: options.persistSession === true,
    sessionKey: options.sessionKey || RECORDER_SESSION_KEY,
    applyMode: options.applyMode === "setSchema" ? "setSchema" : "assign",
    onApply: options.onApply,
    onRecord: options.onRecord,
    replayHistoryMode: normalizeReplayHistoryMode(options.replayHistoryMode),
    onPushHistory: options.onPushHistory,
  };
}

function resolveSchemaStore(): RecorderSchemaStoreLike | null {
  try {
    // 无 active pinia（SSR / 单测）时 useSchemaStore 会抛错。
    return useSchemaStore() as unknown as RecorderSchemaStoreLike;
  } catch {
    return null;
  }
}

function resolveHistoryStore(): RecorderHistoryStoreLike | null {
  try {
    return useHistoryStore() as unknown as RecorderHistoryStoreLike;
  } catch {
    return null;
  }
}

class RecorderEngine {
  private options: NormalizedOptions;

  private consumers = 0;
  private recording = false;
  private paused = false;
  private replaying = false;

  private schemaStore: RecorderSchemaStoreLike | null = null;
  private historyStore: RecorderHistoryStoreLike | null = null;

  private unsubscribe: Array<() => void> = [];
  private genericTimer: ReturnType<typeof setTimeout> | null = null;
  private genericLabel = "";
  private genericSource: RecorderSource = "snapshot";
  private persistTimer: ReturnType<typeof setTimeout> | null = null;
  private delayTimer: ReturnType<typeof setTimeout> | null = null;

  private lastObservedSchemaRef: PageSchema | null = null;
  private lastAfterSchema: PageSchema | null = null;
  private lastAfterFingerprint = "none";
  private lastAfterBytes = 0;
  private lastSelection: RecorderSelection = { selectedId: null, selectedIds: [] };
  private pendingChangeAt = 0;

  private lastStack: RecorderHistoryCommandLike[] = [];
  private lastFuture: RecorderHistoryCommandLike[] = [];
  private lastStackTop: RecorderHistoryCommandLike | null = null;

  private sessionStartedAt = 0;
  private seq = 0;

  private replayToken = 0;
  private statusBeforeReplay: RecorderStatus = "idle";
  private pauseWaiters: Array<() => void> = [];
  /** 当前回放的「历史合并」会话；回放结束 / 中止时提交一次。 */
  private replayHistory: ReplayHistoryCapture | null = null;

  constructor(options: ActionRecorderOptions = {}) {
    this.options = normalizeOptions(options);
    recorderReplayHistoryMode.value = this.options.replayHistoryMode;
    this.refreshStores();
  }

  // ---- 生命周期 ----------------------------------------------------------

  acquire(): () => void {
    this.consumers += 1;
    let released = false;
    return () => {
      if (released) return;
      released = true;
      this.consumers = Math.max(0, this.consumers - 1);
      if (this.consumers === 0) {
        if (this.replaying) this.stopReplay();
        if (!this.recording && !this.paused) this.detachSubscriptions();
      }
    };
  }

  configure(options: ActionRecorderOptions): void {
    if (options.schemaStore !== undefined) this.options.schemaStore = options.schemaStore;
    if (options.historyStore !== undefined) this.options.historyStore = options.historyStore;
    if (options.maxActions !== undefined) {
      this.options.maxActions = clampNumber(options.maxActions, 1, RECORDER_MAX_ACTIONS, RECORDER_MAX_ACTIONS);
    }
    if (options.maxSnapshotBytes !== undefined) {
      this.options.maxSnapshotBytes = clampNumber(options.maxSnapshotBytes, 64_000, 16_000_000, RECORDER_MAX_SNAPSHOT_BYTES);
    }
    if (options.maxTotalBytes !== undefined) {
      this.options.maxTotalBytes = clampNumber(options.maxTotalBytes, 256_000, 64_000_000, RECORDER_MAX_TOTAL_BYTES);
    }
    if (options.maxSessionBytes !== undefined) {
      this.options.maxSessionBytes = clampNumber(options.maxSessionBytes, 64_000, 4_500_000, RECORDER_MAX_SESSION_BYTES);
    }
    if (options.debounceMs !== undefined) this.options.debounceMs = clampNumber(options.debounceMs, 20, 2000, 120);
    if (options.persistSession !== undefined) this.options.persistSession = options.persistSession === true;
    if (options.sessionKey) this.options.sessionKey = options.sessionKey;
    if (options.applyMode) this.options.applyMode = options.applyMode === "setSchema" ? "setSchema" : "assign";
    if (options.onApply !== undefined) this.options.onApply = options.onApply;
    if (options.onRecord !== undefined) this.options.onRecord = options.onRecord;
    if (options.replayHistoryMode !== undefined) {
      this.options.replayHistoryMode = normalizeReplayHistoryMode(options.replayHistoryMode);
      recorderReplayHistoryMode.value = this.options.replayHistoryMode;
    }
    if (options.onPushHistory !== undefined) this.options.onPushHistory = options.onPushHistory;
    this.refreshStores();
  }

  handle(): ActionRecorderHandle {
    const engine = this;
    return {
      actions: recorderActions,
      status: recorderStatus,
      replayPaused: recorderReplayPaused,
      replayIndex: recorderReplayIndex,
      replaySpeed: recorderReplaySpeed,
      replayHistoryMode: recorderReplayHistoryMode,
      lastReplayHistory: recorderLastReplayHistory,
      memoryBytes: recorderMemoryBytes,
      dropped: recorderDropped,
      lastError: recorderLastError,
      start: (reset = true) => engine.start(reset),
      pause: () => engine.pause(),
      resume: () => engine.resume(),
      stop: () => engine.stop(),
      clear: () => engine.clear(),
      capture: (label?: string) => engine.capture(label),
      jumpTo: (index: number, options?: ReplayOptions) => engine.jumpTo(index, options),
      play: (options?: ReplayOptions) => engine.startReplay(options),
      pauseReplay: () => engine.pauseReplay(),
      resumeReplay: () => engine.resumeReplay(),
      stopReplay: () => engine.stopReplay(),
      setReplaySpeed: (ms: number) => engine.setReplaySpeed(ms),
      setReplayHistoryMode: (mode: ReplayHistoryMode) => engine.setReplayHistoryMode(mode),
      exportJson: (pretty = true) => engine.exportJson(pretty),
      exportPayload: () => engine.exportPayload(),
      importJson: (input: string | unknown) => engine.importJson(input),
      hasSession: () => engine.hasSession(),
      sessionInfo: () => engine.sessionInfo(),
      saveSession: () => engine.persistSession(),
      restoreSession: () => engine.restoreSession(),
      clearSession: () => engine.clearSession(),
      setSessionPersistence: (enabled: boolean) => engine.setSessionPersistence(enabled),
      isSessionPersistenceEnabled: () => engine.options.persistSession,
      dispose: () => engine.dispose(),
    };
  }

  dispose(): void {
    this.cancelGeneric();
    this.stopReplay();
    this.recording = false;
    this.paused = false;
    recorderStatus.value = "idle";
    this.detachSubscriptions();
    this.consumers = 0;
  }

  // ---- store / 订阅 ------------------------------------------------------

  private refreshStores(): void {
    this.schemaStore = this.options.schemaStore === undefined ? resolveSchemaStore() : this.options.schemaStore;
    this.historyStore = this.options.historyStore === undefined ? resolveHistoryStore() : this.options.historyStore;
  }

  private ensureSubscribed(): void {
    if (!this.schemaStore) this.refreshStores();
    if (this.unsubscribe.length) return;

    const schemaStore = this.schemaStore;
    if (schemaStore?.$subscribe) {
      const unsubscribe = schemaStore.$subscribe(() => this.onSchemaMutation(), { detached: true, deep: true });
      this.unsubscribe.push(unsubscribe);
    }

    // history store 里存着整份 schema 快照，deep $subscribe 会遍历全部快照（最多 100×2 份），
    // 这里改为轻量 getter 监听：只读取 stack/future 长度与栈顶命令引用，不深入快照内容。
    // flush 采用默认的 pre（微任务），可把 undo/redo 的多步同步变更合并成一次判定。
    const historyStore = this.historyStore;
    if (historyStore) {
      const stopHistoryWatch = watch(
        () => {
          const stack = Array.isArray(historyStore.stack) ? historyStore.stack : [];
          const future = Array.isArray(historyStore.future) ? historyStore.future : [];
          const top = stack.length ? stack[stack.length - 1] : null;
          return [stack.length, future.length, top?.label ?? "", top?.before ?? null, top?.after ?? null] as const;
        },
        () => this.onHistoryMutation(),
        { flush: "pre" }
      );
      this.unsubscribe.push(stopHistoryWatch);
    }

    this.lastObservedSchemaRef = schemaStore?.schema ?? null;
    this.lastSelection = this.currentSelection();
    this.syncHistory();
  }

  private detachSubscriptions(): void {
    for (const release of this.unsubscribe.splice(0)) {
      try {
        release();
      } catch {
        /* ignore */
      }
    }
    this.cancelGeneric();
    this.cancelPersist();
    if (this.delayTimer) {
      clearTimeout(this.delayTimer);
      this.delayTimer = null;
    }
  }

  private syncHistory(): void {
    const history = this.historyStore;
    const stack = Array.isArray(history?.stack) ? history!.stack! : [];
    const future = Array.isArray(history?.future) ? history!.future! : [];
    this.lastStack = stack.slice();
    this.lastFuture = future.slice();
    this.lastStackTop = stack.length ? stack[stack.length - 1] : null;
  }

  private currentSelection(): RecorderSelection {
    const store = this.schemaStore;
    return sanitizeSelection({
      selectedId: store?.selectedId ?? null,
      selectedIds: Array.isArray(store?.selectedIds) ? store!.selectedIds : [],
    });
  }

  // ---- 录制 --------------------------------------------------------------

  private canCapture(): boolean {
    return this.recording && !this.paused && !this.replaying;
  }

  start(reset = true): void {
    if (recorderStatus.value === "recording") return;
    if (recorderStatus.value === "paused") {
      this.resume();
      return;
    }
    if (this.replaying) this.stopReplay();
    recorderLastError.value = "";
    this.ensureSubscribed();
    this.recording = true;
    this.paused = false;
    recorderReplayPaused.value = false;
    recorderStatus.value = "recording";
    this.pendingChangeAt = 0;
    this.lastObservedSchemaRef = this.schemaStore?.schema ?? null;
    this.lastSelection = this.currentSelection();
    this.syncHistory();

    if (reset || !recorderActions.value.length) {
      this.resetActionList();
      this.sessionStartedAt = Date.now();
    } else if (!this.sessionStartedAt) {
      this.sessionStartedAt = Date.now();
    }

    const baseline = this.buildSnapshot(this.schemaStore?.schema ?? null);
    const needsBaseline =
      reset ||
      !recorderActions.value.length ||
      baseline.fingerprint !== this.lastAfterFingerprint;
    if (needsBaseline) {
      const now = Date.now();
      this.pushAction({
        id: this.nextId(),
        label: reset || !recorderActions.value.length ? "开始录制" : "继续录制",
        at: now,
        elapsedMs: Math.max(0, now - this.sessionStartedAt),
        durationMs: 0,
        before: reset ? baseline.schema : this.lastAfterSchema,
        after: baseline.schema,
        beforeBytes: reset ? baseline.bytes : this.lastAfterBytes,
        afterBytes: baseline.bytes,
        selectionBefore: this.lastSelection,
        selection: this.currentSelection(),
        source: "baseline",
        truncated: baseline.truncated,
        snapshotOmitted: !baseline.schema,
      });
      this.lastAfterSchema = baseline.schema;
      this.lastAfterFingerprint = baseline.fingerprint;
      this.lastAfterBytes = baseline.bytes;
    }
    this.schedulePersist();
  }

  pause(): void {
    if (!this.recording || this.paused || this.replaying) return;
    this.flushPendingCapture();
    this.paused = true;
    recorderStatus.value = "paused";
    this.schedulePersist();
  }

  resume(): void {
    if (!this.recording || !this.paused || this.replaying) return;
    this.paused = false;
    recorderStatus.value = "recording";
    this.pendingChangeAt = 0;
    this.lastObservedSchemaRef = this.schemaStore?.schema ?? null;
    this.lastSelection = this.currentSelection();
    this.syncHistory();

    // 暂停期间的结构变化补一条基线，保证后续动作的 before/回放连续。
    const snapshot = this.buildSnapshot(this.schemaStore?.schema ?? null);
    if (!recorderActions.value.length) {
      const now = Date.now();
      this.pushAction({
        id: this.nextId(),
        label: "继续录制",
        at: now,
        elapsedMs: Math.max(0, now - (this.sessionStartedAt || now)),
        durationMs: 0,
        before: null,
        after: snapshot.schema,
        beforeBytes: 0,
        afterBytes: snapshot.bytes,
        selectionBefore: this.lastSelection,
        selection: this.currentSelection(),
        source: "baseline",
        truncated: snapshot.truncated,
        snapshotOmitted: !snapshot.schema,
      });
      this.lastAfterSchema = snapshot.schema;
      this.lastAfterFingerprint = snapshot.fingerprint;
      this.lastAfterBytes = snapshot.bytes;
      return;
    }
    if (snapshot.fingerprint !== this.lastAfterFingerprint) {
      const now = Date.now();
      this.pushAction({
        id: this.nextId(),
        label: "继续录制",
        at: now,
        elapsedMs: Math.max(0, now - this.sessionStartedAt),
        durationMs: 0,
        before: this.lastAfterSchema,
        after: snapshot.schema,
        beforeBytes: this.lastAfterBytes,
        afterBytes: snapshot.bytes,
        selectionBefore: this.lastSelection,
        selection: this.currentSelection(),
        source: "baseline",
        truncated: snapshot.truncated,
        snapshotOmitted: !snapshot.schema,
      });
      this.lastAfterSchema = snapshot.schema;
      this.lastAfterFingerprint = snapshot.fingerprint;
      this.lastAfterBytes = snapshot.bytes;
    }
  }

  stop(): void {
    if (this.replaying) this.stopReplay();
    if (!this.recording && !this.paused) {
      recorderStatus.value = "idle";
      return;
    }
    if (this.canCapture()) this.flushPendingCapture();
    this.recording = false;
    this.paused = false;
    this.pendingChangeAt = 0;
    recorderStatus.value = "idle";
    this.detachSubscriptions();
    if (this.options.persistSession) this.persistSession();
  }

  clear(): void {
    this.cancelGeneric();
    if (this.replaying) this.stopReplay();
    this.resetActionList();
    this.lastObservedSchemaRef = this.schemaStore?.schema ?? null;
    this.lastSelection = this.currentSelection();
    this.pendingChangeAt = 0;
    recorderLastError.value = "";
    this.clearSession();
    this.schedulePersist();
  }

  capture(label?: string): boolean {
    if (!this.canCapture()) return false;
    this.captureGeneric(clipLabel(label, "手动快照"), "manual");
    return true;
  }

  private resetActionList(): void {
    recorderActions.value = [];
    recorderMemoryBytes.value = 0;
    recorderDropped.value = 0;
    recorderReplayIndex.value = -1;
    recorderReplayPaused.value = false;
    this.seq = 0;
    this.lastAfterSchema = null;
    this.lastAfterFingerprint = "none";
    this.lastAfterBytes = 0;
  }

  private nextId(): string {
    this.seq += 1;
    return `rec-${Date.now().toString(36)}-${this.seq.toString(36)}`;
  }

  private buildSnapshot(value: unknown): Snapshot {
    return buildSnapshot(value, this.options.maxSnapshotBytes);
  }

  private onSchemaMutation(): void {
    const schema = this.schemaStore?.schema ?? null;
    if (schema !== this.lastObservedSchemaRef) {
      this.lastObservedSchemaRef = schema;
      this.lastSelection = this.currentSelection();
      if (!this.canCapture()) return;
      // undo/redo 会先更新 history，再赋值 schema；不要用通用标签覆盖更精确的撤销/重做标签。
      if (this.hasPendingHistoryLabel()) return;
      this.pendingChangeAt ||= Date.now();
      this.scheduleGeneric("页面结构已载入", "snapshot");
      return;
    }
    if (!this.canCapture()) {
      this.lastSelection = this.currentSelection();
      return;
    }
    if (this.hasPendingHistoryLabel()) return;
    this.pendingChangeAt ||= Date.now();
    this.scheduleGeneric("画布变更", "snapshot");
  }

  private hasPendingHistoryLabel(): boolean {
    return !!this.genericTimer && (this.genericSource === "undo" || this.genericSource === "redo");
  }

  private onHistoryMutation(): void {
    const history = this.historyStore;
    if (!history) return;
    const stack = Array.isArray(history.stack) ? history.stack : [];
    const future = Array.isArray(history.future) ? history.future : [];
    const prevStackTop = this.lastStackTop;
    const prevFutureTop = this.lastFuture.length ? this.lastFuture[this.lastFuture.length - 1] : null;
    const stackShrank = stack.length < this.lastStack.length;
    const futureGrew = future.length > this.lastFuture.length;
    const futureShrank = future.length < this.lastFuture.length;
    const top = stack.length ? stack[stack.length - 1] : null;

    // 撤销：stack 减少、future 增加。schema 赋值可能晚于本次订阅，统一走防抖捕获。
    if (stackShrank && futureGrew && this.canCapture()) {
      this.scheduleGeneric(`撤销 · ${clipLabel(future[future.length - 1]?.label, "上一步")}`, "undo");
    } else if (top !== prevStackTop && this.canCapture()) {
      let added: RecorderHistoryCommandLike[] = [];
      if (prevStackTop) {
        const prevIndex = stack.lastIndexOf(prevStackTop);
        added = prevIndex >= 0 ? stack.slice(prevIndex + 1) : [];
      } else {
        added = stack.slice();
      }
      if (!added.length && stack.length) added = [stack[stack.length - 1]];
      const isRedo =
        added.length === 1 &&
        futureShrank &&
        prevFutureTop !== null &&
        (added[0] === prevFutureTop ||
          (added[0]?.label === prevFutureTop.label &&
            added[0]?.before === prevFutureTop.before &&
            added[0]?.after === prevFutureTop.after));
      if (isRedo) {
        this.scheduleGeneric(`重做 · ${clipLabel(added[0]?.label, "上一步")}`, "redo");
      } else {
        for (const command of added) this.recordCommand(command);
      }
    }

    this.lastStack = stack.slice();
    this.lastFuture = future.slice();
    this.lastStackTop = top;
  }

  private recordCommand(command: RecorderHistoryCommandLike): void {
    if (!this.canCapture()) return;
    this.cancelGeneric();
    const before = this.buildSnapshot(command.before);
    const after = this.buildSnapshot(command.after);
    const now = Date.now();
    const selection = this.currentSelection();
    const reuseBefore =
      before.fingerprint !== "none" &&
      before.fingerprint === this.lastAfterFingerprint &&
      !!this.lastAfterSchema;
    const beforeSchema = reuseBefore ? this.lastAfterSchema : before.schema;
    const beforeBytes = reuseBefore ? this.lastAfterBytes : before.bytes;
    const durationMs = this.pendingChangeAt ? clampNumber(now - this.pendingChangeAt, 0, 600_000, 0) : 0;
    this.pendingChangeAt = 0;

    this.pushAction({
      id: this.nextId(),
      label: clipLabel(command.label),
      at: now,
      elapsedMs: Math.max(0, now - (this.sessionStartedAt || now)),
      durationMs,
      before: beforeSchema,
      after: after.schema,
      beforeBytes,
      afterBytes: after.bytes,
      selectionBefore: this.lastSelection,
      selection,
      source: "history",
      truncated: before.truncated || after.truncated,
      snapshotOmitted: !after.schema,
    });

    this.lastAfterSchema = after.schema;
    this.lastAfterFingerprint = after.fingerprint;
    this.lastAfterBytes = after.bytes;
    this.lastSelection = selection;
  }

  private scheduleGeneric(label: string, source: RecorderSource): void {
    if (!this.canCapture()) return;
    this.genericLabel = label;
    this.genericSource = source;
    if (this.genericTimer) clearTimeout(this.genericTimer);
    this.genericTimer = setTimeout(() => {
      this.genericTimer = null;
      this.captureGeneric(this.genericLabel, this.genericSource);
    }, this.options.debounceMs);
  }

  private cancelGeneric(): void {
    if (this.genericTimer) {
      clearTimeout(this.genericTimer);
      this.genericTimer = null;
    }
  }

  private flushPendingCapture(): void {
    if (!this.genericTimer) return;
    this.cancelGeneric();
    this.captureGeneric(this.genericLabel || "画布变更", this.genericSource || "snapshot");
  }

  private captureGeneric(label: string, source: RecorderSource): void {
    if (!this.canCapture()) return;
    const snapshot = this.buildSnapshot(this.schemaStore?.schema ?? null);
    const selection = this.currentSelection();

    // 选中 / dirty 变化也会触发 deep 订阅；schema 指纹未变时不产生动作。
    if (snapshot.fingerprint === this.lastAfterFingerprint) {
      this.lastSelection = selection;
      this.pendingChangeAt = 0;
      return;
    }

    const now = Date.now();
    const durationMs = this.pendingChangeAt ? clampNumber(now - this.pendingChangeAt, 0, 600_000, 0) : 0;
    this.pendingChangeAt = 0;

    this.pushAction({
      id: this.nextId(),
      label: clipLabel(label),
      at: now,
      elapsedMs: Math.max(0, now - (this.sessionStartedAt || now)),
      durationMs,
      before: this.lastAfterSchema,
      after: snapshot.schema,
      beforeBytes: this.lastAfterBytes,
      afterBytes: snapshot.bytes,
      selectionBefore: this.lastSelection,
      selection,
      source,
      truncated: snapshot.truncated,
      snapshotOmitted: !snapshot.schema,
    });

    this.lastAfterSchema = snapshot.schema;
    this.lastAfterFingerprint = snapshot.fingerprint;
    this.lastAfterBytes = snapshot.bytes;
    this.lastSelection = selection;
  }

  private pushAction(action: Omit<RecordedAction, "seq">): void {
    const seq = (recorderActions.value[recorderActions.value.length - 1]?.seq || 0) + 1;
    const full: RecordedAction = { ...action, seq };
    const list = [...recorderActions.value, full];
    while (list.length > this.options.maxActions) {
      list.shift();
      recorderDropped.value += 1;
    }
    while (list.length > 1 && estimateMemoryBytes(list) > this.options.maxTotalBytes) {
      list.shift();
      recorderDropped.value += 1;
    }
    recorderActions.value = list;
    recorderMemoryBytes.value = estimateMemoryBytes(list);
    this.schedulePersist();
    try {
      this.options.onRecord?.(full);
    } catch {
      /* 接入方回调异常不应影响录制 */
    }
  }

  // ---- 回放 --------------------------------------------------------------

  setReplaySpeed(ms: number): number {
    const speed = clampReplaySpeed(ms);
    recorderReplaySpeed.value = speed;
    return speed;
  }

  /** 修改默认回放历史模式（"single" 合并为一条命令 / "none" 不写历史）。 */
  setReplayHistoryMode(mode: ReplayHistoryMode): ReplayHistoryMode {
    const normalized = normalizeReplayHistoryMode(mode);
    this.options.replayHistoryMode = normalized;
    recorderReplayHistoryMode.value = normalized;
    return normalized;
  }

  async jumpTo(index: number, options: ReplayOptions = {}): Promise<boolean> {
    const action = recorderActions.value[index];
    if (!action) {
      recorderLastError.value = "快照不存在";
      return false;
    }
    if (!action.after) {
      recorderLastError.value = "该动作没有可用快照（体积过大已省略）";
      return false;
    }
    if (this.replaying) this.stopReplay();
    // 单次跳转 = 一条历史命令（仍不改变 startReplay 的「整次回放一条」语义）。
    const capture = this.captureReplayHistoryFor(options.replayHistoryMode);
    try {
      await this.applySnapshot(action.after, action, options);
      markReplayApplied(capture, action.after, action.label);
      this.commitReplayHistoryCapture(capture, false);
      recorderReplayIndex.value = index;
      recorderLastError.value = "";
      this.resetBaselineFromCurrent();
      return true;
    } catch (error) {
      recorderLastError.value = error instanceof Error ? error.message : String(error);
      return false;
    }
  }

  async startReplay(options: ReplayOptions = {}): Promise<void> {
    const actions = recorderActions.value;
    if (!actions.length) {
      recorderLastError.value = "没有可回放的记录";
      return;
    }
    if (this.replaying) this.stopReplay();
    this.setReplaySpeed(options.speedMs ?? recorderReplaySpeed.value);
    const fromIndex = clampNumber(options.fromIndex, 0, Math.max(0, actions.length - 1), 0);
    this.statusBeforeReplay =
      recorderStatus.value === "replaying"
        ? "idle"
        : recorderStatus.value === "paused"
          ? "paused"
          : recorderStatus.value === "recording"
            ? "recording"
            : "idle";
    // 在应用任何快照之前抓取 schema / 历史栈状态，作为唯一一条历史命令的 before。
    this.replayHistory = this.captureReplayHistoryFor(options.replayHistoryMode);
    this.replaying = true;
    recorderReplayPaused.value = false;
    recorderStatus.value = "replaying";
    recorderReplayIndex.value = -1;
    recorderLastError.value = "";
    const token = ++this.replayToken;

    try {
      for (let i = fromIndex; i < actions.length; i += 1) {
        if (token !== this.replayToken) return;
        await this.waitWhilePaused(token);
        if (token !== this.replayToken) return;
        const action = actions[i];
        if (action.after) {
          await this.applySnapshot(action.after, action, options);
          // 只累计成功应用的快照；不在这里写历史（整次回放最后只 push 一次）。
          markReplayApplied(this.replayHistory, action.after, action.label);
        }
        recorderReplayIndex.value = i;
        if (i < actions.length - 1) {
          // 实时读取速度，允许回放过程中拖动速度滑块。
          await this.waitDelay(recorderReplaySpeed.value, token);
        }
      }
      if (token !== this.replayToken) return;
      this.finishReplay();
    } catch (error) {
      if (token !== this.replayToken) return;
      recorderLastError.value = error instanceof Error ? error.message : String(error);
      // 中止：已应用的快照合并为一条命令（部分结果），未应用则保持原状。
      this.stopReplay();
    }
  }

  pauseReplay(): void {
    if (!this.replaying || recorderReplayPaused.value) return;
    recorderReplayPaused.value = true;
  }

  resumeReplay(): void {
    if (!this.replaying || !recorderReplayPaused.value) return;
    recorderReplayPaused.value = false;
    for (const resolve of this.pauseWaiters.splice(0)) resolve();
  }

  stopReplay(): void {
    if (!this.replaying) {
      recorderReplayPaused.value = false;
      this.replayHistory = null;
      return;
    }
    this.replayToken += 1;
    // 中止也提交一次：before=回放前，after=中止瞬间（部分结果）；0 步时不提交。
    this.commitActiveReplayHistory(true);
    this.replaying = false;
    recorderReplayPaused.value = false;
    for (const resolve of this.pauseWaiters.splice(0)) resolve();
    recorderStatus.value = this.statusBeforeReplay;
    this.resetBaselineFromCurrent();
  }

  private finishReplay(): void {
    // 正常结束：整次回放合并为一条历史命令。
    this.commitActiveReplayHistory(false);
    this.replaying = false;
    recorderReplayPaused.value = false;
    for (const resolve of this.pauseWaiters.splice(0)) resolve();
    recorderStatus.value = this.statusBeforeReplay;
    this.resetBaselineFromCurrent();
  }

  /** 回放开始时抓取当前 schema 与历史栈状态（mode 缺省取引擎配置）。 */
  private captureReplayHistoryFor(modeInput?: ReplayHistoryMode): ReplayHistoryCapture {
    const capture = captureReplayHistory({
      mode: normalizeReplayHistoryMode(modeInput ?? this.options.replayHistoryMode),
      schema: this.schemaSnapshotForHistory(),
      historyStore: this.historyStore,
    });
    recorderLastReplayHistory.value = null;
    return capture;
  }

  private schemaSnapshotForHistory(): PageSchema | null {
    const schema = this.schemaStore?.schema;
    if (!schema) return null;
    try {
      return deepClone(schema);
    } catch {
      return null;
    }
  }

  private commitReplayHistoryCapture(capture: ReplayHistoryCapture, aborted: boolean): void {
    const result = commitReplayHistory({
      capture,
      resultSchema: this.schemaSnapshotForHistory(),
      historyStore: this.historyStore,
      onPush: this.options.onPushHistory,
      aborted,
    });
    recorderLastReplayHistory.value = result;
    if (result.pushed) {
      // 立即把 lastStack/lastFuture 同步到 push 后的状态，避免 recorder 把自己的
      // 回放命令当成一条新动作再录一遍（history watch 是异步 flush 的）。
      this.syncHistory();
    }
  }

  private commitActiveReplayHistory(aborted: boolean): void {
    const capture = this.replayHistory;
    this.replayHistory = null;
    if (!capture) return;
    this.commitReplayHistoryCapture(capture, aborted);
  }

  private async waitWhilePaused(token: number): Promise<void> {
    while (this.replaying && recorderReplayPaused.value && token === this.replayToken) {
      await new Promise<void>((resolve) => this.pauseWaiters.push(resolve));
    }
  }

  private async waitDelay(ms: number, token: number): Promise<void> {
    let remaining = Math.max(0, ms);
    while (remaining > 0) {
      if (token !== this.replayToken) return;
      await this.waitWhilePaused(token);
      if (token !== this.replayToken) return;
      const step = Math.min(50, remaining);
      await new Promise<void>((resolve) => {
        this.delayTimer = setTimeout(resolve, step);
      });
      this.delayTimer = null;
      remaining -= step;
    }
  }

  private async applySnapshot(
    schema: PageSchema,
    action: RecordedAction,
    options: ReplayOptions
  ): Promise<void> {
    const clone = deepClone(schema);
    const callback = options.onApply || this.options.onApply;
    if (callback) {
      await callback(clone, action);
      return;
    }
    const store = this.schemaStore;
    if (!store) throw new Error("缺少 schema store，无法回放；请通过 onApply 回调应用快照");
    const mode = options.applyMode || this.options.applyMode;
    if (mode === "setSchema" && typeof store.setSchema === "function") {
      store.setSchema(clone, store.pageId ?? 0, store.appId ?? 0);
      // setSchema 会把 dirty 置回 false；回放属于未保存变更，保持 dirty 以免误判。
      if (typeof store.dirty === "boolean") store.dirty = true;
    } else {
      store.schema = clone;
      if (typeof store.dirty === "boolean") store.dirty = true;
    }
    this.restoreSelection(action.selection, clone);
  }

  private restoreSelection(selection: RecorderSelection, schema: PageSchema): void {
    const store = this.schemaStore;
    if (!store) return;
    const nodes = schema.nodes || {};
    const ids = selection.selectedIds.filter((id) => !!nodes[id]);
    const selectedId = selection.selectedId && nodes[selection.selectedId] ? selection.selectedId : null;
    if (selectedId && !ids.includes(selectedId)) ids.push(selectedId);
    if (!ids.length && schema.rootId && nodes[schema.rootId]) ids.push(schema.rootId);
    try {
      if (typeof store.selectMany === "function") {
        store.selectMany(ids);
      } else {
        store.selectedIds = ids;
        store.selectedId = ids[ids.length - 1] || schema.rootId;
      }
    } catch {
      /* 选中恢复失败不影响快照应用 */
    }
  }

  private resetBaselineFromCurrent(): void {
    const snapshot = this.buildSnapshot(this.schemaStore?.schema ?? null);
    this.lastAfterSchema = snapshot.schema;
    this.lastAfterFingerprint = snapshot.fingerprint;
    this.lastAfterBytes = snapshot.bytes;
    this.lastObservedSchemaRef = this.schemaStore?.schema ?? null;
    this.lastSelection = this.currentSelection();
    this.pendingChangeAt = 0;
  }

  // ---- 导入 / 导出 / 会话 ------------------------------------------------

  exportPayload(): RecorderExport {
    const store = this.schemaStore;
    return {
      format: "wp-designer-recorder",
      version: 1,
      exportedAt: Date.now(),
      pageId: store?.pageId ?? 0,
      appId: store?.appId ?? 0,
      actions: recorderActions.value.map((action) => ({
        ...action,
        selectionBefore: { ...action.selectionBefore, selectedIds: [...action.selectionBefore.selectedIds] },
        selection: { ...action.selection, selectedIds: [...action.selection.selectedIds] },
      })),
    };
  }

  exportJson(pretty = true): string {
    return JSON.stringify(this.exportPayload(), null, pretty ? 2 : 0);
  }

  importJson(input: string | unknown): ImportResult {
    let data: unknown = input;
    if (typeof input === "string") {
      try {
        data = JSON.parse(input);
      } catch {
        return { ok: false, count: 0, dropped: 0, error: "JSON 解析失败" };
      }
    }
    const rawActions = Array.isArray(data)
      ? data
      : data && typeof data === "object" && Array.isArray((data as { actions?: unknown }).actions)
        ? ((data as { actions: unknown[] }).actions as unknown[])
        : null;
    if (!rawActions) return { ok: false, count: 0, dropped: 0, error: "不是有效的录制文件（缺少 actions）" };
    const normalized = this.normalizeImportedActions(rawActions);
    if (!normalized.length) return { ok: false, count: 0, dropped: 0, error: "录制文件里没有可用动作" };
    const dropped = rawActions.length - normalized.length;
    this.replaceActions(normalized);
    return { ok: true, count: normalized.length, dropped };
  }

  private normalizeImportedActions(rawActions: unknown[]): RecordedAction[] {
    const out: RecordedAction[] = [];
    for (const raw of rawActions) {
      if (!raw || typeof raw !== "object") continue;
      const item = raw as Record<string, unknown>;
      const before = this.buildSnapshot(item.before);
      const after = this.buildSnapshot(item.after);
      if (!before.schema && !after.schema && !this.hasRawSnapshot(item.before) && !this.hasRawSnapshot(item.after)) {
        continue;
      }
      const at = typeof item.at === "number" && Number.isFinite(item.at) ? item.at : Date.now();
      const source = this.normalizeSource(item.source);
      out.push({
        id: this.nextId(),
        seq: out.length + 1,
        label: clipLabel(item.label, "导入动作"),
        at,
        elapsedMs: clampNumber(item.elapsedMs, 0, 86_400_000, 0),
        durationMs: clampNumber(item.durationMs, 0, 600_000, 0),
        before: before.schema,
        after: after.schema,
        beforeBytes: before.bytes,
        afterBytes: after.bytes,
        selectionBefore: sanitizeSelection(item.selectionBefore),
        selection: sanitizeSelection(item.selection ?? item.selectionAfter),
        source,
        truncated:
          item.truncated === true || before.truncated || after.truncated,
        snapshotOmitted: !after.schema,
      });
    }
    if (out.length > this.options.maxActions) out.splice(0, out.length - this.options.maxActions);
    while (out.length > 1 && estimateMemoryBytes(out) > this.options.maxTotalBytes) out.shift();
    return out.map((action, index) => ({ ...action, seq: index + 1 }));
  }

  private hasRawSnapshot(value: unknown): boolean {
    return !!value && typeof value === "object";
  }

  private normalizeSource(value: unknown): RecorderSource {
    return value === "baseline" ||
      value === "history" ||
      value === "snapshot" ||
      value === "undo" ||
      value === "redo" ||
      value === "import" ||
      value === "manual"
      ? value
      : "import";
  }

  private replaceActions(actions: RecordedAction[]): void {
    this.cancelGeneric();
    this.stopReplay();
    this.recording = false;
    this.paused = false;
    recorderStatus.value = "idle";
    recorderActions.value = actions;
    recorderMemoryBytes.value = estimateMemoryBytes(actions);
    recorderDropped.value = 0;
    recorderReplayIndex.value = -1;
    recorderReplayPaused.value = false;
    const last = actions.length ? actions[actions.length - 1] : null;
    this.lastAfterSchema = last?.after ?? null;
    this.lastAfterFingerprint = last?.after ? fingerprintSchema(last.after) : "none";
    this.lastAfterBytes = last?.afterBytes ?? 0;
    this.lastObservedSchemaRef = this.schemaStore?.schema ?? null;
    this.lastSelection = this.currentSelection();
    this.pendingChangeAt = 0;
    this.syncHistory();
    this.detachSubscriptions();
    if (this.options.persistSession) this.persistSession();
  }

  private storageKey(): string {
    const base = this.options.sessionKey;
    const pageId = this.schemaStore?.pageId ?? 0;
    return pageId ? `${base}:${pageId}` : base;
  }

  private readSessionRaw(): string | null {
    try {
      if (typeof sessionStorage === "undefined") return null;
      return sessionStorage.getItem(this.storageKey());
    } catch {
      return null;
    }
  }

  hasSession(): boolean {
    return !!this.readSessionRaw();
  }

  sessionInfo(): RecorderSessionInfo | null {
    const raw = this.readSessionRaw();
    if (!raw) return null;
    try {
      const data = JSON.parse(raw) as { savedAt?: unknown; pageId?: unknown; actions?: unknown };
      return {
        count: Array.isArray(data.actions) ? data.actions.length : 0,
        savedAt: typeof data.savedAt === "number" ? data.savedAt : 0,
        pageId: typeof data.pageId === "number" ? data.pageId : 0,
      };
    } catch {
      return null;
    }
  }

  setSessionPersistence(enabled: boolean): void {
    this.options.persistSession = enabled;
    if (enabled) this.persistSession();
  }

  persistSession(): boolean {
    try {
      if (typeof sessionStorage === "undefined") return false;
      if (!recorderActions.value.length) {
        sessionStorage.removeItem(this.storageKey());
        return true;
      }
      const store = this.schemaStore;
      let list = recorderActions.value;
      const build = () =>
        JSON.stringify({
          format: "wp-designer-recorder-session",
          version: 1,
          savedAt: Date.now(),
          pageId: store?.pageId ?? 0,
          appId: store?.appId ?? 0,
          actions: list,
        });
      let json = build();
      while (json.length > this.options.maxSessionBytes && list.length > 1) {
        const remove = Math.max(1, Math.ceil(list.length * 0.2));
        list = list.slice(remove);
        json = build();
      }
      if (json.length > this.options.maxSessionBytes) return false;
      sessionStorage.setItem(this.storageKey(), json);
      return true;
    } catch {
      return false;
    }
  }

  restoreSession(): ImportResult {
    const raw = this.readSessionRaw();
    if (!raw) return { ok: false, count: 0, dropped: 0, error: "没有可恢复的会话记录" };
    let data: unknown;
    try {
      data = JSON.parse(raw);
    } catch {
      return { ok: false, count: 0, dropped: 0, error: "会话记录已损坏" };
    }
    const rawActions = Array.isArray(data)
      ? data
      : data && typeof data === "object" && Array.isArray((data as { actions?: unknown }).actions)
        ? ((data as { actions: unknown[] }).actions as unknown[])
        : null;
    if (!rawActions) return { ok: false, count: 0, dropped: 0, error: "会话记录格式不正确" };
    const normalized = this.normalizeImportedActions(rawActions);
    if (!normalized.length) return { ok: false, count: 0, dropped: 0, error: "会话记录里没有可用动作" };
    this.replaceActions(normalized);
    return { ok: true, count: normalized.length, dropped: rawActions.length - normalized.length };
  }

  clearSession(): void {
    try {
      if (typeof sessionStorage !== "undefined") sessionStorage.removeItem(this.storageKey());
    } catch {
      /* ignore */
    }
  }

  private schedulePersist(): void {
    if (!this.options.persistSession) return;
    if (this.persistTimer) clearTimeout(this.persistTimer);
    this.persistTimer = setTimeout(() => {
      this.persistTimer = null;
      this.persistSession();
    }, 500);
  }

  private cancelPersist(): void {
    if (this.persistTimer) {
      clearTimeout(this.persistTimer);
      this.persistTimer = null;
    }
  }
}

// ---------------------------------------------------------------------------
// 组合式入口
// ---------------------------------------------------------------------------

export interface ActionRecorderHandle {
  actions: typeof recorderActions;
  status: typeof recorderStatus;
  replayPaused: typeof recorderReplayPaused;
  replayIndex: typeof recorderReplayIndex;
  replaySpeed: typeof recorderReplaySpeed;
  replayHistoryMode: typeof recorderReplayHistoryMode;
  lastReplayHistory: typeof recorderLastReplayHistory;
  memoryBytes: typeof recorderMemoryBytes;
  dropped: typeof recorderDropped;
  lastError: typeof recorderLastError;
  start: (reset?: boolean) => void;
  pause: () => void;
  resume: () => void;
  stop: () => void;
  clear: () => void;
  capture: (label?: string) => boolean;
  jumpTo: (index: number, options?: ReplayOptions) => Promise<boolean>;
  play: (options?: ReplayOptions) => Promise<void>;
  pauseReplay: () => void;
  resumeReplay: () => void;
  stopReplay: () => void;
  setReplaySpeed: (ms: number) => number;
  setReplayHistoryMode: (mode: ReplayHistoryMode) => ReplayHistoryMode;
  exportJson: (pretty?: boolean) => string;
  exportPayload: () => RecorderExport;
  importJson: (input: string | unknown) => ImportResult;
  hasSession: () => boolean;
  sessionInfo: () => RecorderSessionInfo | null;
  saveSession: () => boolean;
  restoreSession: () => ImportResult;
  clearSession: () => void;
  setSessionPersistence: (enabled: boolean) => void;
  isSessionPersistenceEnabled: () => boolean;
  /** 彻底释放订阅并结束录制（面板 scope 卸载时由 useActionRecorder 自动减引用）。 */
  dispose: () => void;
}

let engine: RecorderEngine | null = null;

function getEngine(options: ActionRecorderOptions = {}): RecorderEngine {
  if (!engine) engine = new RecorderEngine(options);
  else if (Object.keys(options).length) engine.configure(options);
  return engine;
}

/**
 * 在组件 setup 中调用：返回共享录制器句柄，并在 scope 释放时自动减少引用。
 * 面板关闭 / 组件卸载时若仍在录制，会保留后台订阅（可继续记录）；
 * 需要彻底释放请调用 handle.dispose()。
 */
export function useActionRecorder(options: ActionRecorderOptions = {}): ActionRecorderHandle {
  const instance = getEngine(options);
  const release = instance.acquire();
  if (getCurrentScope()) onScopeDispose(release);
  const handle = instance.handle();
  if (options.autoStart && recorderStatus.value === "idle") {
    instance.start(recorderActions.value.length === 0);
  }
  return handle;
}
