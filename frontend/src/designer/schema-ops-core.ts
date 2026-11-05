/**
 * 设计器 schema 操作日志：纯函数核心（可在 Node 中直接自测，无 DOM / Vue 依赖）。
 *
 * 操作协议（与服务端 ``pages.schema_ops`` 对应）::
 *
 *   {kind:"node.upsert", nodeId, node, clock}   // node 为完整节点快照
 *   {kind:"node.delete", nodeId, clock}
 *   {kind:"schema.meta", meta, clock}            // 完整 meta 快照
 *
 * Lamport clock: ``{counter, clientId}``。合并规则固定为：
 *
 * - ``counter`` 大者胜；
 * - ``counter`` 相等时 ``clientId`` 字典序大者胜；
 * - 完全相同视为重复操作，忽略。
 *
 * 每个节点 / 页面 meta 的最近一次 clock 保存在 schema 的保留键
 * ``__oplog__`` 中（会随整页 schema 一起保存），因此重新加载后仍能正确
 * 比较远端操作，删除则以 tombstone clock 记录，后续更高 clock 的 upsert
 * 可以恢复节点。
 *
 * 注意：这是**节点级 LWW**，不是字段级 CRDT。两个客户端同时修改同一节点的
 * 不同字段时，整节点快照按 clock 取其一；同一节点内的 children 顺序也随该
 * 节点快照一起 LWW。
 */
import type { PageMeta, PageSchema, SchemaNode } from "../types";

export const OPLOG_KEY = "__oplog__";
export const OPLOG_VERSION = 1;

export interface LamportClockValue {
  counter: number;
  clientId: string;
}

export type NodeUpsertOp = {
  kind: "node.upsert";
  nodeId: string;
  node: SchemaNode;
  clock: LamportClockValue;
};

export type NodeDeleteOp = {
  kind: "node.delete";
  nodeId: string;
  clock: LamportClockValue;
};

export type SchemaMetaOp = {
  kind: "schema.meta";
  meta: PageMeta;
  clock: LamportClockValue;
};

export type SchemaOp = NodeUpsertOp | NodeDeleteOp | SchemaMetaOp;

/** 服务端日志行 / 客户端队列项的宽松输入：可直接传 op 或 {op, seq}。 */
export interface SchemaOpLike {
  op: SchemaOp;
  seq?: number;
}

export type SchemaOpInput = SchemaOp | SchemaOpLike;

export interface SchemaOplogState {
  v: number;
  /** nodeId → 最近一次 node.upsert / node.delete 的 clock（删除后为 tombstone）。 */
  nodes: Record<string, LamportClockValue>;
  /** 页面 meta 最近一次 clock。 */
  meta: LamportClockValue | null;
  /** 已应用 / 已保存的日志游标（可选，用于重连时减少重放）。 */
  seq: number;
}

export interface ApplyOpResult {
  schema: PageSchema;
  applied: boolean;
  reason: "applied" | "invalid" | "stale" | "equal" | "root";
}

export interface MergeResult {
  schema: PageSchema;
  applied: SchemaOp[];
  ignored: SchemaOp[];
}

export interface RebaseResult {
  schema: PageSchema;
  appliedRemote: SchemaOp[];
  ignoredRemote: SchemaOp[];
  appliedLocal: SchemaOp[];
  droppedLocal: SchemaOp[];
  /** 需要重新发送给服务端的本地操作（已用新 clock 重盖）。 */
  pending: SchemaOp[];
  /** 本地操作与远端操作命中同一节点的 key（node:<id> / meta）。 */
  conflicts: string[];
}

/* ------------------------------------------------------------------ 基础工具 */

function cloneJson<T>(value: T): T {
  if (value === undefined) return value;
  return JSON.parse(JSON.stringify(value)) as T;
}

function isPlainObject(value: unknown): value is Record<string, any> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** 稳定序列化：对象 key 排序，忽略 undefined；用于节点相等比较。 */
export function stableStringify(value: unknown): string {
  if (value === null) return "null";
  const type = typeof value;
  if (type !== "object") {
    const encoded = JSON.stringify(value);
    return encoded === undefined ? "null" : encoded;
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort();
  return `{${keys
    .map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`)
    .join(",")}}`;
}

/* ------------------------------------------------------------------ clock */

export function isLamportClock(value: unknown): value is LamportClockValue {
  if (!isPlainObject(value)) return false;
  const counter = value.counter;
  const clientId = value.clientId;
  return (
    Number.isSafeInteger(counter) &&
    (counter as number) >= 0 &&
    typeof clientId === "string" &&
    clientId.length > 0 &&
    clientId.length <= 128
  );
}

export function cloneClock(clock: LamportClockValue): LamportClockValue {
  return { counter: clock.counter, clientId: clock.clientId };
}

/** 返回 <0 / 0 / >0；相等 counter 时 clientId 字典序大者胜。 */
export function compareClocks(a: LamportClockValue, b: LamportClockValue): number {
  if (a.counter !== b.counter) return a.counter < b.counter ? -1 : 1;
  if (a.clientId === b.clientId) return 0;
  return a.clientId < b.clientId ? -1 : 1;
}

/** 客户端 Lamport clock：生成本地操作并观察远端 clock。 */
export class LamportClock {
  readonly clientId: string;
  counter: number;

  constructor(clientId: string, counter = 0) {
    if (!clientId) throw new Error("LamportClock 需要非空 clientId");
    this.clientId = clientId;
    this.counter = Number.isSafeInteger(counter) && counter > 0 ? counter : 0;
  }

  tick(): LamportClockValue {
    this.counter += 1;
    return { counter: this.counter, clientId: this.clientId };
  }

  observe(clock: LamportClockValue | null | undefined): void {
    if (!isLamportClock(clock)) return;
    if (clock.counter > this.counter) this.counter = clock.counter;
  }

  value(): LamportClockValue {
    return { counter: this.counter, clientId: this.clientId };
  }
}

/* ------------------------------------------------------------------ oplog 元数据 */

export function readOplogState(schema: PageSchema): SchemaOplogState {
  const raw = (schema as unknown as Record<string, unknown>)[OPLOG_KEY];
  const state: SchemaOplogState = {
    v: OPLOG_VERSION,
    nodes: {},
    meta: null,
    seq: 0,
  };
  if (!isPlainObject(raw)) return state;
  if (isPlainObject(raw.nodes)) {
    for (const [nodeId, clock] of Object.entries(raw.nodes)) {
      if (isLamportClock(clock)) state.nodes[nodeId] = cloneClock(clock);
    }
  }
  if (isLamportClock(raw.meta)) state.meta = cloneClock(raw.meta);
  if (Number.isSafeInteger(raw.seq) && (raw.seq as number) > 0) {
    state.seq = raw.seq as number;
  }
  return state;
}

export function writeOplogState(schema: PageSchema, state: SchemaOplogState): void {
  (schema as unknown as Record<string, unknown>)[OPLOG_KEY] = state;
}

export function getOplogSeq(schema: PageSchema | null | undefined): number {
  return schema ? readOplogState(schema).seq : 0;
}

export function setOplogSeq(schema: PageSchema, seq: number): void {
  if (!Number.isSafeInteger(seq) || seq < 0) return;
  const state = readOplogState(schema);
  if (seq <= state.seq) return;
  state.seq = seq;
  writeOplogState(schema, state);
}

export function maxClockCounter(schema: PageSchema | null | undefined): number {
  if (!schema) return 0;
  const state = readOplogState(schema);
  let max = state.meta?.counter ?? 0;
  for (const clock of Object.values(state.nodes)) {
    if (clock.counter > max) max = clock.counter;
  }
  return max;
}

/** 把本地 clock 抬到 schema 中已记录的最大 counter，避免重新加载后生成更旧的 clock。 */
export function syncClockFromSchema(
  clock: LamportClock,
  schema: PageSchema | null | undefined
): void {
  const max = maxClockCounter(schema);
  if (max > clock.counter) clock.counter = max;
}

/* ------------------------------------------------------------------ 操作校验 */

function isNodeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 200;
}

export function isSchemaOp(value: unknown): value is SchemaOp {
  if (!isPlainObject(value)) return false;
  if (!isLamportClock(value.clock)) return false;
  switch (value.kind) {
    case "node.upsert": {
      if (!isNodeId(value.nodeId) || !isPlainObject(value.node)) return false;
      const node = value.node as Record<string, unknown>;
      return node.id === undefined || node.id === value.nodeId;
    }
    case "node.delete":
      return isNodeId(value.nodeId);
    case "schema.meta":
      return isPlainObject(value.meta);
    default:
      return false;
  }
}

/* ------------------------------------------------------------------ 应用单个操作 */

function detachNodeReferences(schema: PageSchema, nodeId: string): void {
  for (const node of Object.values(schema.nodes)) {
    if (Array.isArray(node.children)) {
      node.children = node.children.filter((child: string) => child !== nodeId);
    }
    if (node.slots) {
      for (const key of Object.keys(node.slots)) {
        const list = node.slots[key];
        if (Array.isArray(list)) {
          node.slots[key] = list.filter((child: string) => child !== nodeId);
        }
      }
    }
  }
}

function applyOpInternal(schema: PageSchema, op: SchemaOp): ApplyOpResult["reason"] {
  if (!isSchemaOp(op)) return "invalid";
  const state = readOplogState(schema);

  if (op.kind === "node.upsert") {
    const current = state.nodes[op.nodeId];
    if (current) {
      const order = compareClocks(op.clock, current);
      if (order < 0) return "stale";
      if (order === 0) return "equal";
    }
    const node = cloneJson(op.node) as SchemaNode;
    node.id = op.nodeId;
    schema.nodes[op.nodeId] = node;
    state.nodes[op.nodeId] = cloneClock(op.clock);
    writeOplogState(schema, state);
    return "applied";
  }

  if (op.kind === "node.delete") {
    if (op.nodeId === schema.rootId) return "root";
    const current = state.nodes[op.nodeId];
    if (current) {
      const order = compareClocks(op.clock, current);
      if (order < 0) return "stale";
      if (order === 0) return "equal";
    }
    delete schema.nodes[op.nodeId];
    detachNodeReferences(schema, op.nodeId);
    state.nodes[op.nodeId] = cloneClock(op.clock);
    writeOplogState(schema, state);
    return "applied";
  }

  // schema.meta：完整替换
  if (state.meta) {
    const order = compareClocks(op.clock, state.meta);
    if (order < 0) return "stale";
    if (order === 0) return "equal";
  }
  schema.meta = cloneJson(op.meta);
  state.meta = cloneClock(op.clock);
  writeOplogState(schema, state);
  return "applied";
}

/**
 * 应用单个操作（纯函数）：输入 schema 不被修改，返回新 schema（未应用时返回原引用）。
 */
export function applyOp(schema: PageSchema, op: SchemaOp): ApplyOpResult {
  if (!isSchemaOp(op)) return { schema, applied: false, reason: "invalid" };
  const next = cloneJson(schema);
  const reason = applyOpInternal(next, op);
  if (reason !== "applied") return { schema, applied: false, reason };
  return { schema: next, applied: true, reason };
}

/**
 * 本地已经反映在 schema 中的操作：只把 clock 记录到 ``__oplog__``，
 * 不修改节点 / meta 内容。用于 diff 生成操作后先记本地 clock，再发送。
 *
 * 返回实际抬高的记录数。
 */
export function recordOps(schema: PageSchema, ops: SchemaOp[]): number {
  const state = readOplogState(schema);
  let changed = 0;
  for (const op of ops) {
    if (!isSchemaOp(op)) continue;
    if (op.kind === "node.upsert") {
      const current = state.nodes[op.nodeId];
      if (!current || compareClocks(op.clock, current) > 0) {
        state.nodes[op.nodeId] = cloneClock(op.clock);
        changed += 1;
      }
      continue;
    }
    if (op.kind === "node.delete") {
      if (op.nodeId === schema.rootId) continue;
      const current = state.nodes[op.nodeId];
      if (!current || compareClocks(op.clock, current) > 0) {
        state.nodes[op.nodeId] = cloneClock(op.clock);
        changed += 1;
      }
      continue;
    }
    if (!state.meta || compareClocks(op.clock, state.meta) > 0) {
      state.meta = cloneClock(op.clock);
      changed += 1;
    }
  }
  if (changed > 0) writeOplogState(schema, state);
  return changed;
}

/* ------------------------------------------------------------------ diff */

function opKey(op: SchemaOp): string {
  return op.kind === "schema.meta" ? "meta" : `node:${op.nodeId}`;
}

/**
 * 对比两个 schema，生成节点级操作。纯函数；每个操作从传入 clock 取新 counter。
 *
 * 生成顺序固定为：删除（按 nodeId 排序）→ 节点 upsert（按 nodeId 排序）→ meta。
 * 不比较 ``__oplog__`` 自身。页面级 rootId / layout / variables / customCss 等
 * 字段不在本协议内（整页保存仍会持久化它们）。
 */
export function diffSchemas(
  previous: PageSchema | null | undefined,
  next: PageSchema,
  clock: LamportClock
): SchemaOp[] {
  const ops: SchemaOp[] = [];
  if (!next || !isPlainObject(next.nodes)) return ops;
  const prevNodes = previous?.nodes ?? {};
  const nextNodes = next.nodes;

  const removed = Object.keys(prevNodes)
    .filter((nodeId) => !(nodeId in nextNodes))
    .sort();
  for (const nodeId of removed) {
    ops.push({ kind: "node.delete", nodeId, clock: clock.tick() });
  }

  const changed = Object.keys(nextNodes)
    .filter((nodeId) => {
      const before = prevNodes[nodeId];
      const after = nextNodes[nodeId];
      return !before || stableStringify(before) !== stableStringify(after);
    })
    .sort();
  for (const nodeId of changed) {
    ops.push({
      kind: "node.upsert",
      nodeId,
      node: cloneJson(nextNodes[nodeId]),
      clock: clock.tick(),
    });
  }

  const previousMeta = previous?.meta ?? null;
  if (stableStringify(previousMeta) !== stableStringify(next.meta ?? null)) {
    ops.push({
      kind: "schema.meta",
      meta: cloneJson((next.meta ?? {}) as PageMeta),
      clock: clock.tick(),
    });
  }
  return ops;
}

/* ------------------------------------------------------------------ merge / rebase */

function opEntries(inputs: SchemaOpInput[]): Array<{
  op: SchemaOp;
  seq: number;
  index: number;
}> {
  const entries: Array<{ op: SchemaOp; seq: number; index: number }> = [];
  inputs.forEach((input, index) => {
    if (isSchemaOp(input)) {
      entries.push({ op: input, seq: 0, index });
      return;
    }
    if (input && isSchemaOp((input as SchemaOpLike).op)) {
      const seq = Number((input as SchemaOpLike).seq);
      entries.push({
        op: (input as SchemaOpLike).op,
        seq: Number.isSafeInteger(seq) && seq > 0 ? seq : 0,
        index,
      });
    }
  });
  entries.sort(
    (a, b) =>
      compareClocks(a.op.clock, b.op.clock) ||
      a.seq - b.seq ||
      a.index - b.index
  );
  return entries;
}

/**
 * 应用远端操作（冲突感知，按 clock 升序 + 服务端 seq 稳定排序）。
 *
 * 同一节点 / meta 上收到多条操作时，只有 clock 最高的那条会真正应用，其余
 * 低 clock 操作计入 ``ignored``（完整节点快照不需要逐条回放历史）。若最高
 * clock 仍低于本地已记录 clock，则该节点所有远端操作都被忽略。传入 ``clock``
 * 时会把本地 Lamport counter 抬到观察到的远端值。
 */
export function mergeRemoteOps(
  local: PageSchema,
  ops: SchemaOpInput[],
  clock?: LamportClock
): MergeResult {
  const entries = opEntries(Array.isArray(ops) ? ops : []);

  // 先按 key 选 clock 最高的操作；同 clock 用 seq / 输入顺序稳定取后者。
  const winners = new Map<string, (typeof entries)[number]>();
  for (const entry of entries) {
    clock?.observe(entry.op.clock);
    const key = opKey(entry.op);
    const current = winners.get(key);
    if (!current) {
      winners.set(key, entry);
      continue;
    }
    const order = compareClocks(entry.op.clock, current.op.clock);
    if (order > 0 || (order === 0 && entry.seq >= current.seq)) {
      winners.set(key, entry);
    }
  }

  const working = cloneJson(local);
  const applied: SchemaOp[] = [];
  const ignored: SchemaOp[] = [];
  const winnerSet = new Set(winners.values());

  for (const entry of entries) {
    if (!winnerSet.has(entry)) {
      ignored.push(entry.op);
      continue;
    }
    if (applyOpInternal(working, entry.op) === "applied") {
      applied.push(entry.op);
    } else {
      ignored.push(entry.op);
    }
  }
  return {
    schema: applied.length ? working : local,
    applied,
    ignored,
  };
}

function restampOp(op: SchemaOp, clock: LamportClockValue): SchemaOp {
  if (op.kind === "schema.meta") {
    return { ...op, meta: cloneJson(op.meta), clock };
  }
  if (op.kind === "node.upsert") {
    return { ...op, node: cloneJson(op.node), clock };
  }
  return { ...op, clock };
}

function opMatchesSchema(schema: PageSchema, op: SchemaOp): boolean {
  if (op.kind === "node.upsert") {
    const node = schema.nodes[op.nodeId];
    if (!node) return false;
    const desired = { ...cloneJson(op.node), id: op.nodeId };
    return stableStringify(node) === stableStringify(desired);
  }
  if (op.kind === "node.delete") {
    return !schema.nodes[op.nodeId];
  }
  return stableStringify(schema.meta ?? null) === stableStringify(op.meta ?? null);
}

/**
 * 离线 / 断线重连后的 rebase：
 *
 * 1. 先把远端操作按 LWW 合并到本地；
 * 2. 再把本地尚未确认的 pending 操作用**新的 clock** 重盖后应用到合并结果上
 *    （用户本地未发送的编辑优先保留）；传入 clock 时必须；
 * 3. 返回需要重新发送的操作与冲突 key。
 *
 * 未传 clock 时按原 clock 重放：内容已存在的操作保留在 ``pending``，否则丢弃。
 */
export function rebase(
  local: PageSchema,
  remoteOps: SchemaOpInput[],
  pendingLocalOps: SchemaOpInput[] = [],
  clock?: LamportClock
): RebaseResult {
  const merged = mergeRemoteOps(local, remoteOps, clock);
  const working = cloneJson(merged.schema);
  const touched = new Set(
    opEntries(Array.isArray(remoteOps) ? remoteOps : []).map((entry) =>
      opKey(entry.op)
    )
  );
  const appliedLocal: SchemaOp[] = [];
  const droppedLocal: SchemaOp[] = [];
  const pending: SchemaOp[] = [];
  const conflicts = new Set<string>();

  for (const entry of opEntries(Array.isArray(pendingLocalOps) ? pendingLocalOps : [])) {
    const candidate = clock ? restampOp(entry.op, clock.tick()) : entry.op;
    if (applyOpInternal(working, candidate) === "applied") {
      appliedLocal.push(candidate);
      pending.push(candidate);
      if (touched.has(opKey(candidate))) conflicts.add(opKey(candidate));
      continue;
    }
    if (!clock && opMatchesSchema(working, entry.op)) {
      pending.push(entry.op);
      continue;
    }
    droppedLocal.push(entry.op);
  }

  return {
    schema: appliedLocal.length ? working : merged.schema,
    appliedRemote: merged.applied,
    ignoredRemote: merged.ignored,
    appliedLocal,
    droppedLocal,
    pending,
    conflicts: [...conflicts],
  };
}

export { opKey as operationKey };
