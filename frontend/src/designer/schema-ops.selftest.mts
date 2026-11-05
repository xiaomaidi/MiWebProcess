/**
 * schema-ops-core.ts 的最小自测（无测试框架，Node 原生类型剥离即可运行）。
 *
 * 运行（仓库根目录）：
 *   node frontend/src/designer/schema-ops.selftest.mts
 *
 * 说明：本文件是 .mts，不在 frontend/tsconfig.json 的 include（src/**\/*.ts）
 * 内，不参与 vue-tsc / vite 构建；仅作为纯函数回归用例。
 */
import assert from "node:assert/strict";
import {
  LamportClock,
  applyOp,
  compareClocks,
  diffSchemas,
  getOplogSeq,
  mergeRemoteOps,
  readOplogState,
  rebase,
  recordOps,
  setOplogSeq,
  syncClockFromSchema,
  type LamportClockValue,
  type SchemaOp,
} from "./schema-ops-core.ts";
import type { PageSchema } from "../types.ts";

function schema(text = "hello"): PageSchema {
  return {
    schemaVersion: 2,
    rootId: "root",
    nodes: {
      root: {
        id: "root",
        type: "wp-canvas",
        componentVersion: "2.0.0",
        props: {},
        children: ["text"],
      },
      text: {
        id: "text",
        type: "text",
        componentVersion: "1.0.0",
        props: { text },
        children: [],
      },
    },
    variables: {},
    meta: { title: "T", lang: "zh-CN" },
    layout: { mode: "flow", width: 1200, height: 800 },
  };
}

function clock(counter: number, clientId = "a"): LamportClockValue {
  return { counter, clientId };
}

function upsert(text: string, c: LamportClockValue, nodeId = "text"): SchemaOp {
  return {
    kind: "node.upsert",
    nodeId,
    node: {
      id: nodeId,
      type: "text",
      componentVersion: "1.0.0",
      props: { text },
      children: [],
    },
    clock: c,
  };
}

function del(c: LamportClockValue, nodeId = "text"): SchemaOp {
  return { kind: "node.delete", nodeId, clock: c };
}

function meta(title: string, c: LamportClockValue): SchemaOp {
  return { kind: "schema.meta", meta: { title, lang: "zh-CN" }, clock: c };
}

const visual = (s: PageSchema) => ({
  rootId: s.rootId,
  nodes: s.nodes,
  meta: s.meta,
});

/* 1. clock 比较：counter 优先，相等时 clientId 字典序大者胜 */
assert.ok(compareClocks(clock(2, "a"), clock(1, "z")) > 0);
assert.ok(compareClocks(clock(1, "a"), clock(2, "a")) < 0);
assert.ok(compareClocks(clock(1, "b"), clock(1, "a")) > 0);
assert.ok(compareClocks(clock(1, "a"), clock(1, "b")) < 0);
assert.equal(compareClocks(clock(1, "a"), clock(1, "a")), 0);

/* 2. applyOp 纯函数 + node LWW */
{
  const original = schema("base");
  const applied = applyOp(original, upsert("next", clock(5)));
  assert.equal(applied.applied, true);
  assert.equal(applied.schema.nodes.text.props.text, "next");
  assert.equal(original.nodes.text.props.text, "base", "applyOp 不能修改入参");
  assert.notEqual(applied.schema, original);

  const stale = applyOp(applied.schema, upsert("stale", clock(4, "z")));
  assert.equal(stale.applied, false);
  assert.equal(stale.reason, "stale");
  assert.equal(stale.schema.nodes.text.props.text, "next");

  const tieLow = applyOp(applied.schema, upsert("low-tie", clock(5, "a")));
  assert.equal(tieLow.applied, false);
  assert.equal(tieLow.schema.nodes.text.props.text, "next");

  const tieHigh = applyOp(applied.schema, upsert("high-tie", clock(5, "z")));
  assert.equal(tieHigh.applied, true);
  assert.equal(tieHigh.schema.nodes.text.props.text, "high-tie");
}

/* 3. 删除：摘除父引用；tombstone 阻止旧 upsert；更高 clock 可恢复；root 不可删 */
{
  const deleted = applyOp(schema(), del(clock(6)));
  assert.equal(deleted.applied, true);
  assert.equal(deleted.schema.nodes.text, undefined);
  assert.deepEqual(deleted.schema.nodes.root.children, []);

  const resurrectOld = applyOp(deleted.schema, upsert("old", clock(5)));
  assert.equal(resurrectOld.applied, false);
  assert.equal(resurrectOld.schema.nodes.text, undefined);

  const resurrectNew = applyOp(deleted.schema, upsert("new", clock(7)));
  assert.equal(resurrectNew.applied, true);
  assert.equal(resurrectNew.schema.nodes.text.props.text, "new");

  const rootDelete = applyOp(schema(), del(clock(99), "root"));
  assert.equal(rootDelete.applied, false);
  assert.equal(rootDelete.reason, "root");
  assert.ok(rootDelete.schema.nodes.root);

  // 删除与 upsert 的 equal-clock tiebreak
  const tieBase = applyOp(schema(), upsert("x", clock(5, "a"))).schema;
  const sameClockDelete = applyOp(tieBase, del(clock(5, "a")));
  assert.equal(sameClockDelete.applied, false);
  assert.equal(sameClockDelete.reason, "equal");
  const lowerClientDelete = applyOp(tieBase, del(clock(5, "0")));
  assert.equal(lowerClientDelete.applied, false);
  assert.equal(lowerClientDelete.reason, "stale");
  const higherClientDelete = applyOp(tieBase, del(clock(5, "z")));
  assert.equal(higherClientDelete.applied, true);
  assert.equal(higherClientDelete.schema.nodes.text, undefined);
}

/* 4. meta LWW（完整替换） */
{
  const first = applyOp(schema(), meta("M2", clock(3)));
  assert.equal(first.applied, true);
  assert.equal(first.schema.meta?.title, "M2");
  const stale = applyOp(first.schema, meta("M1", clock(2)));
  assert.equal(stale.applied, false);
  assert.equal(stale.schema.meta?.title, "M2");
  const tie = applyOp(first.schema, meta("M3", clock(3, "z")));
  assert.equal(tie.applied, true);
  assert.equal(tie.schema.meta?.title, "M3");
}

/* 5. mergeRemoteOps：按 clock 排序，高 clock 最终生效 */
{
  const local = schema("local");
  const high = upsert("high", clock(9, "b"));
  const low = upsert("low", clock(2, "z"));
  const merged = mergeRemoteOps(local, [high, low]);
  assert.equal(merged.applied.length, 1);
  assert.equal(merged.ignored.length, 1);
  assert.equal(merged.schema.nodes.text.props.text, "high");
  assert.equal(local.nodes.text.props.text, "local", "merge 不能修改入参");

  // 删除与 upsert 混合：更高 clock 的 upsert 覆盖删除
  const deleted = applyOp(local, del(clock(3))).schema;
  const restored = mergeRemoteOps(deleted, [
    upsert("restored", clock(8)),
    del(clock(4)),
  ]);
  assert.equal(restored.schema.nodes.text.props.text, "restored");
  assert.equal(restored.applied.length, 1);
  assert.equal(restored.ignored.length, 1);
}

/* 6. mergeRemoteOps 接受 {op, seq} 形式并观察 clock */
{
  const localClock = new LamportClock("local", 0);
  const merged = mergeRemoteOps(schema(), [{ op: upsert("x", clock(12, "remote")), seq: 7 }], localClock);
  assert.equal(merged.applied.length, 1);
  assert.equal(localClock.counter, 12);
  assert.equal(localClock.tick().counter, 13);
}

/* 7. diffSchemas：删除先于 upsert，按 id 排序，meta 最后；可回放 */
{
  const previous = schema("old");
  previous.nodes.extra = {
    id: "extra",
    type: "text",
    componentVersion: "1.0.0",
    props: { text: "remove-me" },
    children: [],
  };
  previous.nodes.root.children = ["text", "extra"];
  const next = schema("changed");
  next.nodes.root.children = ["text", "added"];
  next.nodes.added = {
    id: "added",
    type: "text",
    componentVersion: "1.0.0",
    props: { text: "new" },
    children: [],
  };
  next.meta = { title: "Next", lang: "zh-CN" };

  const localClock = new LamportClock("tab-test", 0);
  const ops = diffSchemas(previous, next, localClock);
  assert.deepEqual(
    ops.map((op) => (op.kind === "schema.meta" ? "meta" : `${op.kind}:${op.nodeId}`)),
    ["node.delete:extra", "node.upsert:added", "node.upsert:root", "node.upsert:text", "meta"]
  );
  assert.deepEqual(
    ops.map((op) => op.clock.counter),
    [1, 2, 3, 4, 5]
  );

  const replayed = mergeRemoteOps(previous, ops);
  assert.equal(replayed.ignored.length, 0);
  assert.deepEqual(visual(replayed.schema), visual(next));

  // 只有 __oplog__ 变化不算内容变化
  const same = JSON.parse(JSON.stringify(next)) as PageSchema;
  (same as any).__oplog__ = { v: 1, nodes: {}, meta: null, seq: 3 };
  assert.equal(diffSchemas(same, next, new LamportClock("x", 0)).length, 0);
}

/* 8. recordOps：只记录 clock，不改内容；旧 clock 不回退 */
{
  const local = schema("local");
  const op = upsert("new", clock(10, "local"));
  const changed = recordOps(local, [op]);
  assert.equal(changed, 1);
  assert.equal(local.nodes.text.props.text, "local", "recordOps 只记录 clock");
  assert.equal(readOplogState(local).nodes.text.counter, 10);
  assert.equal(recordOps(local, [upsert("older", clock(9, "local"))]), 0);
  assert.equal(readOplogState(local).nodes.text.counter, 10);
}

/* 9. rebase：远端先合并，本地 pending 用新 clock 重盖后保留 */
{
  const localClock = new LamportClock("local", 2);
  const localSchema = schema("local-edit");
  recordOps(localSchema, [upsert("local-edit", clock(2, "local"))]);
  const localPending = [upsert("local-edit", clock(2, "local"))];
  const remote = upsert("remote", clock(5, "remote"));

  const result = rebase(localSchema, [remote], localPending, localClock);
  assert.equal(result.appliedRemote.length, 1);
  assert.equal(result.appliedLocal.length, 1);
  assert.equal(result.droppedLocal.length, 0);
  assert.equal(result.schema.nodes.text.props.text, "local-edit");
  assert.equal(result.pending.length, 1);
  assert.ok(result.pending[0].clock.counter > 5);
  assert.deepEqual(result.conflicts, ["node:text"]);

  // 未传 clock 且远端更高：本地旧内容无法重放 → dropped
  const noClock = rebase(schema("local"), [remote], [upsert("local", clock(2, "local"))]);
  assert.equal(noClock.appliedLocal.length, 0);
  assert.equal(noClock.droppedLocal.length, 1);
  assert.equal(noClock.schema.nodes.text.props.text, "remote");
}

/* 10. oplog seq + clock 同步 */
{
  const local = schema();
  assert.equal(getOplogSeq(local), 0);
  setOplogSeq(local, 9);
  assert.equal(getOplogSeq(local), 9);
  setOplogSeq(local, 4);
  assert.equal(getOplogSeq(local), 9, "seq 不能回退");

  recordOps(local, [upsert("x", clock(17))]);
  const localClock = new LamportClock("tab", 0);
  syncClockFromSchema(localClock, local);
  assert.equal(localClock.counter, 17);
  assert.equal(localClock.tick().counter, 18);
}

/* 11. 非法操作是 no-op */
{
  const local = schema();
  const invalid = applyOp(local, { kind: "nope" } as unknown as SchemaOp);
  assert.equal(invalid.applied, false);
  assert.equal(invalid.reason, "invalid");
  assert.equal(invalid.schema, local);
  assert.equal(mergeRemoteOps(local, [null as unknown as SchemaOp]).applied.length, 0);
}

console.log("schema-ops selftest: all assertions passed");
