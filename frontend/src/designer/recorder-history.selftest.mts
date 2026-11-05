/**
 * recorder-history.ts 的最小自测（无测试框架，Node 原生类型剥离即可运行）。
 *
 * 运行（Windows，仓库根目录）：
 *   "C:\Users\27606\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" \
 *     frontend/src/designer/recorder-history.selftest.mts
 *
 * 说明：本文件是 .mts，不在 frontend/tsconfig.json 的 include（src/**\/*.ts）里，
 * 不参与 vue-tsc / vite 构建；仅作为纯函数回归用例。
 */
import assert from "node:assert/strict";
import {
  DEFAULT_REPLAY_HISTORY_MODE,
  buildReplayHistoryLabel,
  captureReplayHistory,
  commitReplayHistory,
  markReplayApplied,
  normalizeReplayHistoryMode,
  type RecorderHistoryStoreLike,
} from "./recorder-history.ts";
import type { PageSchema } from "../types.ts";

function page(title: string): PageSchema {
  return {
    schemaVersion: 2,
    rootId: "root",
    nodes: {
      root: { id: "root", type: "wp-canvas", componentVersion: "2.0.0", props: { title }, children: [] },
    },
    variables: {},
    meta: { title, lang: "zh-CN", globalStyle: { cssVars: {} } },
    layout: { mode: "flow", width: 1200, height: 800 },
  } as PageSchema;
}

interface PushRecord {
  label: string;
  before: PageSchema;
  after: PageSchema;
}

function fakeHistoryStore(options: { stack?: number; future?: number; withPush?: boolean } = {}) {
  const store: RecorderHistoryStoreLike & { pushes: PushRecord[]; max: number } = {
    stack: [] as RecorderHistoryStoreLike["stack"],
    future: [] as RecorderHistoryStoreLike["future"],
    max: 100,
    pushes: [],
  };
  for (let i = 0; i < (options.stack ?? 0); i += 1) {
    store.stack!.push({ label: `初始 ${i}`, before: page(`s${i}-before`), after: page(`s${i}-after`) });
  }
  for (let i = 0; i < (options.future ?? 0); i += 1) {
    store.future!.push({ label: `未来 ${i}`, before: page(`f${i}-before`), after: page(`f${i}-after`) });
  }
  if (options.withPush !== false) {
    store.push = (label: string, before: unknown, after: unknown) => {
      store.pushes.push({ label, before: before as PageSchema, after: after as PageSchema });
      store.stack!.push({ label, before, after });
      if (store.stack!.length > store.max) store.stack!.shift();
      store.future = [];
    };
  }
  return store;
}
// 1. 模式归一化：默认 single，未知值回退 single，none 保留
assert.equal(DEFAULT_REPLAY_HISTORY_MODE, "single");
assert.equal(normalizeReplayHistoryMode(undefined), "single");
assert.equal(normalizeReplayHistoryMode(""), "single");
assert.equal(normalizeReplayHistoryMode("bogus"), "single");
assert.equal(normalizeReplayHistoryMode("none"), "none");
assert.equal(normalizeReplayHistoryMode("single"), "single");

// 2. 开始回放：抓取 schema + 历史栈状态；快照是深拷贝
{
  const store = fakeHistoryStore({ stack: 2, future: 1 });
  const current = page("before-replay");
  const capture = captureReplayHistory({ schema: current, historyStore: store, now: 1000 });
  assert.equal(capture.mode, "single");
  assert.equal(capture.startedAt, 1000);
  assert.deepEqual(capture.beforeSchema, current);
  assert.notEqual(capture.beforeSchema, current, "beforeSchema 必须是深拷贝");
  assert.equal(capture.historyBefore.stackLength, 2);
  assert.equal(capture.historyBefore.futureLength, 1);
  assert.equal(capture.historyBefore.canUndo, true);
  assert.equal(capture.historyBefore.canRedo, true);
  assert.equal(capture.historyBefore.max, 100);
  assert.equal(capture.historyBefore.stackTop, store.stack![1]);
  assert.equal(capture.historyBefore.futureTop, store.future![0]);
  current.meta!.title = "mutated-after-capture";
  assert.equal(capture.beforeSchema!.meta!.title, "before-replay");
}

// 3. 整次回放只 push 一次；前后状态正确、redo 分支被清空
{
  const store = fakeHistoryStore({ stack: 1, future: 1 });
  const start = page("start");
  const capture = captureReplayHistory({ schema: start, historyStore: store, now: 1000 });
  const applied = [page("step-1"), page("step-2"), page("step-3")];
  for (let i = 0; i < applied.length; i += 1) {
    markReplayApplied(capture, applied[i], `动作 ${i + 1}`);
  }
  // 回放过程中不写历史
  assert.equal(store.pushes.length, 0);
  assert.equal(store.stack!.length, 1, "回放过程中 stack 不应增长");

  const result = commitReplayHistory({ capture, resultSchema: applied[2], historyStore: store, now: 1600 });
  assert.equal(result.pushed, true);
  assert.equal(result.reason, null);
  assert.equal(result.label, "回放 · 3 步");
  assert.equal(result.appliedCount, 3);
  assert.equal(result.durationMs, 600);
  assert.equal(store.pushes.length, 1, "整次回放必须只 push 一次");
  assert.equal(store.stack!.length, 2);
  assert.equal(store.future!.length, 0, "push 后 redo 分支应被清空");
  assert.deepEqual(store.pushes[0].before, start);
  assert.deepEqual(store.pushes[0].after, applied[2]);

  // 历史里保存的 before/after 与外部引用隔离
  assert.notEqual(store.pushes[0].before, capture.beforeSchema);
  applied[2].meta!.title = "mutated-after-commit";
  assert.equal(store.pushes[0].after.meta!.title, "step-3");
}

// 4. 中途停止：已应用的部分结果合并为一条命令
{
  const store = fakeHistoryStore({ stack: 2, future: 0 });
  const start = page("start");
  const capture = captureReplayHistory({ schema: start, historyStore: store });
  markReplayApplied(capture, page("partial-1"), "动作 1");
  markReplayApplied(capture, page("partial-2"), "动作 2");
  const partial = page("partial-2");
  const result = commitReplayHistory({ capture, resultSchema: partial, historyStore: store, aborted: true });
  assert.equal(result.pushed, true);
  assert.equal(result.aborted, true);
  assert.equal(result.label, "回放（中途停止）· 2 步");
  assert.equal(store.pushes.length, 1);
  assert.deepEqual(store.pushes[0].before, start);
  assert.deepEqual(store.pushes[0].after, partial);
}

// 5. 一步都没应用就中止：不 push，历史与 redo 分支保持原样
{
  const store = fakeHistoryStore({ stack: 1, future: 2 });
  const beforeStack = store.stack!.length;
  const beforeFuture = store.future!.length;
  const capture = captureReplayHistory({ schema: page("start"), historyStore: store });
  const result = commitReplayHistory({ capture, resultSchema: page("start"), historyStore: store, aborted: true });
  assert.equal(result.pushed, false);
  assert.equal(result.reason, "no-applied");
  assert.equal(store.pushes.length, 0);
  assert.equal(store.stack!.length, beforeStack);
  assert.equal(store.future!.length, beforeFuture);
}

// 6. replayHistoryMode = "none"：完全不写历史
{
  const store = fakeHistoryStore({ stack: 1, future: 0 });
  const capture = captureReplayHistory({ mode: "none", schema: page("start"), historyStore: store });
  markReplayApplied(capture, page("end"), "动作 1");
  const result = commitReplayHistory({ capture, resultSchema: page("end"), historyStore: store });
  assert.equal(result.pushed, false);
  assert.equal(result.reason, "mode-none");
  assert.equal(store.pushes.length, 0);
  assert.equal(store.future!.length, 0);
}

// 7. 回放前后 schema 相同：不写空命令
{
  const store = fakeHistoryStore({ stack: 1 });
  const same = page("same");
  const capture = captureReplayHistory({ schema: same, historyStore: store });
  markReplayApplied(capture, same, "动作 1");
  const result = commitReplayHistory({ capture, resultSchema: same, historyStore: store });
  assert.equal(result.pushed, false);
  assert.equal(result.reason, "unchanged");
  assert.equal(store.pushes.length, 0);
}

// 8. store 没有 push：使用 onPushHistory 回调（成功 / 拒绝 / 抛错）
{
  const store = fakeHistoryStore({ stack: 1, withPush: false });
  const capture = captureReplayHistory({ schema: page("start"), historyStore: store });
  markReplayApplied(capture, page("end"), "动作 1");
  let calls = 0;
  const result = commitReplayHistory({
    capture,
    resultSchema: page("end"),
    historyStore: store,
    onPush: (label, before, after) => {
      calls += 1;
      assert.equal(label, "回放 · 1 步");
      assert.deepEqual(before, page("start"));
      assert.deepEqual(after, page("end"));
    },
  });
  assert.equal(result.pushed, true);
  assert.equal(calls, 1);

  // store 有 push 时优先使用 push，回调不参与
  const withPush = fakeHistoryStore({ stack: 1 });
  const captureWithPush = captureReplayHistory({ schema: page("start"), historyStore: withPush });
  markReplayApplied(captureWithPush, page("end"), "动作 1");
  let callbackCalls = 0;
  const viaPush = commitReplayHistory({
    capture: captureWithPush,
    resultSchema: page("end"),
    historyStore: withPush,
    onPush: () => {
      callbackCalls += 1;
    },
  });
  assert.equal(viaPush.pushed, true);
  assert.equal(withPush.pushes.length, 1);
  assert.equal(callbackCalls, 0, "store 支持 push 时 onPushHistory 不应被调用");

  const rejected = commitReplayHistory({
    capture: (() => {
      const c = captureReplayHistory({ schema: page("start"), historyStore: store });
      markReplayApplied(c, page("end"), "动作 1");
      return c;
    })(),
    resultSchema: page("end"),
    historyStore: store,
    onPush: () => false,
  });
  assert.equal(rejected.pushed, false);
  assert.equal(rejected.reason, "rejected");
  assert.match(rejected.note, /onPushHistory/);

  const thrown = commitReplayHistory({
    capture: (() => {
      const c = captureReplayHistory({ schema: page("start"), historyStore: store });
      markReplayApplied(c, page("end"), "动作 1");
      return c;
    })(),
    resultSchema: page("end"),
    historyStore: store,
    onPush: () => {
      throw new Error("boom");
    },
  });
  assert.equal(thrown.pushed, false);
  assert.equal(thrown.reason, "rejected");
  assert.match(thrown.note, /boom/);
}

// 9. 既没有 push 也没有回调：跳过并给出说明，不影响回放
{
  const store = fakeHistoryStore({ stack: 1, withPush: false });
  const capture = captureReplayHistory({ schema: page("start"), historyStore: store });
  markReplayApplied(capture, page("end"), "动作 1");
  const result = commitReplayHistory({ capture, resultSchema: page("end"), historyStore: store });
  assert.equal(result.pushed, false);
  assert.equal(result.reason, "no-history-store");
  assert.match(result.note, /push/);
  assert.equal(store.pushes.length, 0);
}

// 10. 缺少 before / after：跳过而不是写入坏命令
{
  const store = fakeHistoryStore({ stack: 1 });
  const noBefore = captureReplayHistory({ schema: null, historyStore: store });
  markReplayApplied(noBefore, page("end"), "动作 1");
  const resultA = commitReplayHistory({ capture: noBefore, resultSchema: page("end"), historyStore: store });
  assert.equal(resultA.pushed, false);
  assert.equal(resultA.reason, "missing-before");

  const noAfter = captureReplayHistory({ schema: page("start"), historyStore: store });
  markReplayApplied(noAfter, null, "动作 1");
  const resultB = commitReplayHistory({ capture: noAfter, resultSchema: null, historyStore: store });
  assert.equal(resultB.pushed, false);
  assert.equal(resultB.reason, "missing-after");
  assert.equal(store.pushes.length, 0);
}

// 11. resultSchema 缺省时回退到最后一个已应用快照
{
  const store = fakeHistoryStore({ stack: 1 });
  const capture = captureReplayHistory({ schema: page("start"), historyStore: store });
  markReplayApplied(capture, page("last"), "动作 1");
  const result = commitReplayHistory({ capture, historyStore: store });
  assert.equal(result.pushed, true);
  assert.deepEqual(store.pushes[0].after, page("last"));
}

// 12. 标签
assert.equal(buildReplayHistoryLabel({ appliedCount: 0 }), "回放 · 0 步");
assert.equal(buildReplayHistoryLabel({ appliedCount: 4 }), "回放 · 4 步");
assert.equal(buildReplayHistoryLabel({ appliedCount: 4, aborted: true }), "回放（中途停止）· 4 步");

console.log("recorder-history selftest: 12 groups passed");
