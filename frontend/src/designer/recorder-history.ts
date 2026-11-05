/**
 * 操作录制「回放 → 撤销历史」适配层。
 *
 * 这是纯函数模块：不依赖 Vue / Pinia / DOM，可被 Node 直接执行（见 recorder-history.selftest.mts），
 * 由 recorder.ts 在真实 store 上调用。
 *
 * ## 语义
 *
 * - `replayHistoryMode = "single"`（默认）：整次回放合并为 **一条** 历史命令。
 *   回放开始时记录 `before`（当时 schema）与历史栈状态；回放过程中把快照直接写入画布，
 *   全程不调用 `history.push`；结束时只 push 一次 `(label, before, after)`。
 * - `replayHistoryMode = "none"`：不写历史（保持接入本功能前的旧行为）。
 *
 * ## 中止语义（"single" 模式下）
 *
 * 回放被中途停止 / 抛错时，**已应用的快照作为一条命令提交**：
 * - `before` = 回放开始前的 schema；
 * - `after`  = 中止瞬间画布上的 schema（部分结果）。
 * 这样撤销可以一次性回到回放前，重做回到部分结果；不会留下「画布变了但历史没变」的脏历史。
 * 若一步都没有应用，则不提交任何命令，画布与历史都保持原样。
 *
 * ## 历史 store 兼容
 *
 * 1. 优先调用 `historyStore.push(label, before, after)`（当前 `store/history.ts` 支持，且会清空 redo 分支）；
 * 2. 否则调用接入方提供的 `onPushHistory(label, before, after)` 回调（返回 `false` 表示放弃写入）；
 * 3. 两者都没有时跳过写历史，回放本身不受影响，跳过原因写入返回结果的 `note`。
 *
 * ## 并发编辑注意
 *
 * 回放期间应避免同时撤销 / 重做或手工编辑画布：本模块只记录「回放开始前」与「回放结束时」的 schema，
 * 中途的外部变更会被合并进同一条命令（after 取结束瞬间的权威状态）。`onPushHistory` 必须同步完成写入。
 */

import type { PageSchema } from "@/types";

export type ReplayHistoryMode = "none" | "single";

export const REPLAY_HISTORY_MODES: readonly ReplayHistoryMode[] = ["none", "single"];

export const DEFAULT_REPLAY_HISTORY_MODE: ReplayHistoryMode = "single";

export interface RecorderHistoryCommandLike {
  label?: string;
  before?: unknown;
  after?: unknown;
}

/**
 * 历史 store 的最小结构约定。
 *
 * `push` / `stack` / `future` 与当前 `frontend/src/store/history.ts` 保持一致；
 * `$subscribe` 仅用于兼容既有类型导出（recorder 通过轻量 watch 读取栈）。
 */
export interface RecorderHistoryStoreLike {
  $subscribe?: (
    callback: (mutation: { type?: string }, state: unknown) => void,
    options?: { detached?: boolean; deep?: boolean }
  ) => () => void;
  stack?: RecorderHistoryCommandLike[];
  future?: RecorderHistoryCommandLike[];
  max?: number;
  push?: (label: string, before: unknown, after: unknown) => unknown;
}

/** 回放开始时抓取的历史栈状态（用于诊断 / 报告，不回写）。 */
export interface ReplayHistoryStateSnapshot {
  stackLength: number;
  futureLength: number;
  canUndo: boolean;
  canRedo: boolean;
  max: number | null;
  stackTop: RecorderHistoryCommandLike | null;
  futureTop: RecorderHistoryCommandLike | null;
}

/** 一次回放（或一次 jumpTo）从开始到提交所需的状态。 */
export interface ReplayHistoryCapture {
  mode: ReplayHistoryMode;
  startedAt: number;
  /** 回放开始前的 schema 深拷贝；null 表示当时没有可读 schema。 */
  beforeSchema: PageSchema | null;
  /** 回放开始前的历史栈状态。 */
  historyBefore: ReplayHistoryStateSnapshot;
  /** 已成功应用的快照数（不含被省略 / 跳过的动作）。 */
  appliedCount: number;
  /** 最近一次成功应用后的 schema 深拷贝。 */
  lastAppliedSchema: PageSchema | null;
  /** 最近一次成功应用的动作标签（诊断用）。 */
  lastActionLabel: string;
}

export type ReplayHistorySkipReason =
  | "mode-none"
  | "no-applied"
  | "missing-before"
  | "missing-after"
  | "unchanged"
  | "no-history-store"
  | "rejected";

export interface ReplayHistoryCommitInput {
  capture: ReplayHistoryCapture;
  /** 回放结束 / 中止时的权威 schema（通常来自 schema store）；为空时回退到最后一个已应用快照。 */
  resultSchema?: PageSchema | null;
  historyStore?: RecorderHistoryStoreLike | null;
  /** 历史 store 没有 push 时的兜底；返回 false 表示拒绝写入。 */
  onPush?: (label: string, before: PageSchema, after: PageSchema) => boolean | void;
  aborted?: boolean;
  now?: number;
}

export interface ReplayHistoryCommitResult {
  mode: ReplayHistoryMode;
  pushed: boolean;
  reason: ReplayHistorySkipReason | null;
  label: string;
  /** 未写入历史时的人类可读说明；写入成功为空字符串。 */
  note: string;
  before: PageSchema | null;
  after: PageSchema | null;
  appliedCount: number;
  aborted: boolean;
  durationMs: number;
  historyBefore: ReplayHistoryStateSnapshot;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** 宽松归一化：未知值回退到默认值 "single"（保证新增选项向后兼容）。 */
export function normalizeReplayHistoryMode(value: unknown): ReplayHistoryMode {
  return value === "none" ? "none" : DEFAULT_REPLAY_HISTORY_MODE;
}

function cloneSchema(schema: PageSchema | null): PageSchema | null {
  if (!schema) return null;
  try {
    if (typeof structuredClone === "function") return structuredClone(schema) as PageSchema;
  } catch {
    /* 响应式代理 / 不可结构化克隆时回退 JSON */
  }
  try {
    return JSON.parse(JSON.stringify(schema)) as PageSchema;
  } catch {
    return null;
  }
}

function schemaSignature(schema: PageSchema | null): string {
  if (!schema) return "none";
  try {
    return JSON.stringify(schema);
  } catch {
    return "";
  }
}

function readHistoryState(historyStore: RecorderHistoryStoreLike | null | undefined): ReplayHistoryStateSnapshot {
  const stack = Array.isArray(historyStore?.stack) ? historyStore!.stack! : [];
  const future = Array.isArray(historyStore?.future) ? historyStore!.future! : [];
  const max = typeof historyStore?.max === "number" && Number.isFinite(historyStore.max) ? historyStore.max : null;
  return {
    stackLength: stack.length,
    futureLength: future.length,
    canUndo: stack.length > 0,
    canRedo: future.length > 0,
    max,
    stackTop: stack.length ? stack[stack.length - 1] : null,
    futureTop: future.length ? future[future.length - 1] : null,
  };
}

/** 回放开始时调用：抓取当前 schema 与历史栈状态。 */
export function captureReplayHistory(args: {
  mode?: unknown;
  schema: PageSchema | null;
  historyStore?: RecorderHistoryStoreLike | null;
  now?: number;
}): ReplayHistoryCapture {
  return {
    mode: normalizeReplayHistoryMode(args.mode),
    startedAt: typeof args.now === "number" ? args.now : Date.now(),
    beforeSchema: cloneSchema(args.schema),
    historyBefore: readHistoryState(args.historyStore),
    appliedCount: 0,
    lastAppliedSchema: null,
    lastActionLabel: "",
  };
}

/** 每成功应用一个快照后调用；只更新本地状态，不触碰历史栈。 */
export function markReplayApplied(
  capture: ReplayHistoryCapture | null,
  schema: PageSchema | null,
  actionLabel = ""
): void {
  if (!capture) return;
  capture.appliedCount += 1;
  capture.lastAppliedSchema = cloneSchema(schema);
  capture.lastActionLabel = actionLabel;
}

/** 生成历史命令标签，例如「回放 · 4 步」「回放（中途停止）· 2 步」。 */
export function buildReplayHistoryLabel(args: { appliedCount: number; aborted?: boolean }): string {
  const applied = Math.max(0, Math.floor(args.appliedCount || 0));
  return args.aborted ? `回放（中途停止）· ${applied} 步` : `回放 · ${applied} 步`;
}

/**
 * 回放结束 / 中止时调用：把整次回放合并为一条历史命令。
 * 该函数只会在通过所有前置检查后调用一次 `push`（或 `onPush`）。
 */
export function commitReplayHistory(input: ReplayHistoryCommitInput): ReplayHistoryCommitResult {
  const { capture, resultSchema, historyStore, onPush, aborted = false } = input;
  const label = buildReplayHistoryLabel({ appliedCount: capture.appliedCount, aborted });
  const now = typeof input.now === "number" ? input.now : Date.now();
  const base: ReplayHistoryCommitResult = {
    mode: capture.mode,
    pushed: false,
    reason: null,
    label,
    note: "",
    before: capture.beforeSchema,
    after: capture.lastAppliedSchema,
    appliedCount: capture.appliedCount,
    aborted,
    durationMs: Math.max(0, now - capture.startedAt),
    historyBefore: capture.historyBefore,
  };

  if (capture.mode === "none") {
    return { ...base, reason: "mode-none", note: "replayHistoryMode=none：回放结果不写入撤销历史。" };
  }
  if (capture.appliedCount <= 0) {
    return { ...base, reason: "no-applied", note: "没有应用任何快照，画布与历史保持不变。" };
  }

  const before = cloneSchema(capture.beforeSchema);
  if (!before) {
    return { ...base, reason: "missing-before", note: "缺少回放前 schema，未写入历史。" };
  }
  const after = cloneSchema(resultSchema ?? capture.lastAppliedSchema);
  if (!after) {
    return { ...base, reason: "missing-after", note: "缺少回放结果 schema，未写入历史。" };
  }
  if (schemaSignature(before) === schemaSignature(after)) {
    return { ...base, before, after, reason: "unchanged", note: "回放前后 schema 相同，未写入空命令。" };
  }

  if (typeof historyStore?.push === "function") {
    try {
      historyStore.push(label, before, after);
      return { ...base, before, after, pushed: true };
    } catch (error) {
      return { ...base, before, after, reason: "rejected", note: `history.push 抛错：${errorMessage(error)}` };
    }
  }

  if (typeof onPush === "function") {
    try {
      const accepted = onPush(label, before, after);
      if (accepted === false) {
        return { ...base, before, after, reason: "rejected", note: "onPushHistory 返回 false，未写入历史。" };
      }
      return { ...base, before, after, pushed: true };
    } catch (error) {
      return { ...base, before, after, reason: "rejected", note: `onPushHistory 抛错：${errorMessage(error)}` };
    }
  }

  return {
    ...base,
    before,
    after,
    reason: "no-history-store",
    note: "历史 store 不支持 push(label, before, after)，且未提供 onPushHistory 回调；回放结果未写入撤销历史。",
  };
}
