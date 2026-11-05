/**
 * 设计器 schema 操作日志客户端（Vue / 浏览器侧）。
 *
 * 通道：``ws(s)://host/ws/designer-ops/{pageId}/?token=<JWT>&after=<seq>``
 *
 * 与 {@link ./schema-sync} 的分工：
 * - schema-sync 仍负责整页 schema 快照 / 保存冲突提示；
 * - 本模块只传输**节点级操作**。连接 snapshot 返回 ``{seq, ops, has_more}``，
 *   之后增量广播 ``{type:"ops", ops:[{seq, op, client_id, ...}]}``。
 * - 服务端先落库再广播；发送方收到 ``appended`` ack（含服务端 seq），不会收到
 *   自己的 ``ops`` 广播。
 *
 * 集成契约（DesignerView）：
 * ```ts
 * import {
 *   connect, dispose, onOps, sendOps, lastSeq as opsLastSeq,
 *   diffSchemas, recordOps, mergeRemoteOps, withRemoteApply, getClock,
 *   syncClockFromSchema, setOplogSeq, fetchOps,
 * } from "@/designer/schema-ops";
 *
 * // 1. 首次加载完整 schema 后
 * connect(pageId, "", schema.schema);
 * let lastOpsSchema = JSON.parse(JSON.stringify(schema.schema));
 *
 * // 2. 远端操作
 * stopOps = onOps((event) => {
 *   if (!schema.schema) return;
 *   if (!event.ops.length) {
 *     setOplogSeq(schema.schema, opsLastSeq.value); // 空 snapshot 也记录游标
 *     return;
 *   }
 *   for (const record of event.ops) getClock().observe(record.op.clock);
 *   const merged = mergeRemoteOps(schema.schema, event.ops, getClock());
 *   if (!merged.applied.length) return;
 *   withRemoteApply(() => { schema.schema = merged.schema; });
 *   if (!merged.schema.nodes[schema.selectedId || ""]) {
 *     schema.selectedId = merged.schema.rootId;
 *     schema.selectedIds = [merged.schema.rootId];
 *   }
 *   // 只推进到已实际应用的最后一条；snapshot 有 has_more 时勿跳到 event.seq。
 *   setOplogSeq(schema.schema, opsLastSeq.value);
 *   lastOpsSchema = JSON.parse(JSON.stringify(schema.schema));
 *   schema.dirty = true; // 远端操作尚未整页落库；自动保存会持久化
 * });
 *
 * // 3. 本地变更 → diff → 发送（替换 schema-sync 的 sendSchema watcher）
 * watch(() => schema.schema, (value) => {
 *   if (!value || applyingRemote.value) return;
 *   const ops = diffSchemas(lastOpsSchema, value, getClock());
 *   if (!ops.length) return;
 *   recordOps(value, ops);
 *   sendOps(ops);
 *   lastOpsSchema = JSON.parse(JSON.stringify(value));
 * }, { deep: true });
 * ```
 *
 * 注意：
 * - 首次 connect 会带 ``after=0`` 重放操作日志（受服务端单页上限约束）；
 *   若整页 schema 中已有 ``__oplog__.seq``，会从该 seq 继续，避免重复重放。
 * - 断线期间 ``sendOps`` 会排队，重连后按当前 ``lastSeq`` 补拉并 flush。
 * - ``hasMore`` 为 true 时需要调用 ``fetchOps`` 继续分页（服务端单次最多 500）。
 */
import { ref } from "vue";
import { api, getToken } from "@/api";
import type { PageSchema } from "@/types";
import { persistedRevision } from "./schema-sync";
import {
  LamportClock,
  getOplogSeq,
  isSchemaOp,
  syncClockFromSchema,
  type SchemaOp,
} from "./schema-ops-core";

export * from "./schema-ops-core";
export { applyingRemote, withRemoteApply } from "./schema-sync";

export interface SchemaOperationRecord {
  seq: number;
  op: SchemaOp;
  /** 服务端日志行的 client_id（通常等于 op.clock.clientId）。 */
  clientId: string;
  baseRevision: number;
  userId: number | null;
  username: string;
  createdAt: string;
}

export interface SchemaOpsRemote {
  kind: "snapshot" | "ops";
  pageId: number;
  ops: SchemaOperationRecord[];
  /** snapshot 时为服务端当前最新 seq；ops 时为本地已收到的最新 seq。 */
  seq: number;
  after: number | null;
  hasMore: boolean;
  from: string;
}

export interface FetchedOps {
  seq: number;
  after: number;
  ops: SchemaOperationRecord[];
  hasMore: boolean;
}

export type SchemaOpsListener = (remote: SchemaOpsRemote) => void;

const CLIENT_ID_KEY = "wp_designer_ops_client_id";
const MAX_BACKOFF_MS = 15000;
const HEARTBEAT_MS = 25000;
const SNAPSHOT_LIMIT = 200;
const MAX_PENDING_OPS = 500;
const MAX_SEEN_SEQS = 5000;

/** 当前连接状态（响应式）。 */
export const connected = ref(false);
/** 已收到 / 已确认的最新服务端 seq（响应式）。重连时作为 after 游标。 */
export const lastSeq = ref(0);
/** 最近一次 snapshot 是否还有更多历史操作（需调用 fetchOps 继续拉取）。 */
export const hasMore = ref(false);

function generateClientId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return `ops-${crypto.randomUUID()}`;
    }
  } catch {
    /* 隐私模式 / 非安全上下文 */
  }
  return `ops-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 稳定 clientId：同一标签页 sessionStorage 内保持不变。 */
export function getOrCreateClientId(): string {
  if (typeof sessionStorage !== "undefined") {
    try {
      const existing = sessionStorage.getItem(CLIENT_ID_KEY);
      if (existing) return existing;
      const created = generateClientId();
      sessionStorage.setItem(CLIENT_ID_KEY, created);
      return created;
    } catch {
      /* 隐私模式允许读写失败 */
    }
  }
  return generateClientId();
}

export const clientId = getOrCreateClientId();
/** 当前客户端 Lamport clock；每次本地 diff 调用 tick。 */
export const clock = new LamportClock(clientId, 0);

export function getClock(): LamportClock {
  return clock;
}

let socket: WebSocket | null = null;
let currentPageId = 0;
let tokenOverride = "";
let disposed = false;
let retry = 0;
let reconnectTimer: number | undefined;
let heartbeatTimer: number | undefined;
let pendingOps: SchemaOp[] = [];
const seenSeqs = new Set<number>();
const listeners = new Set<SchemaOpsListener>();

/* ------------------------------------------------------------------ 连接 */

function websocketUrl(pageId: number, token: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const auth = token || getToken();
  const after = Math.max(0, Math.trunc(lastSeq.value || 0));
  return (
    `${proto}://${location.host}/ws/designer-ops/${encodeURIComponent(String(pageId))}/` +
    `?token=${encodeURIComponent(auth)}&after=${after}&limit=${SNAPSHOT_LIMIT}`
  );
}

/**
 * 连接指定页面的操作通道。重复调用（同一页且连接中/已连接）幂等。
 * 切换 pageId 会重置 seq / clock / 待发队列。
 *
 * @param pageId 页面 id
 * @param token 可选 JWT；缺省读取 localStorage
 * @param initialSchema 可选：首次加载的整页 schema，用于同步 Lamport counter
 *                      并从 ``__oplog__.seq`` 继续重放。
 */
export function connect(
  pageId: number | string,
  token = "",
  initialSchema?: PageSchema | null
): void {
  if (typeof window === "undefined") return;
  const numeric = Number(pageId);
  if (!Number.isFinite(numeric) || numeric <= 0) return;
  if (token) tokenOverride = token;

  const pageChanged = currentPageId !== 0 && currentPageId !== numeric;
  if (pageChanged) {
    closeSocket();
    lastSeq.value = 0;
    hasMore.value = false;
    seenSeqs.clear();
    pendingOps = [];
    clock.counter = 0;
  }
  currentPageId = numeric;
  disposed = false;
  retry = 0;

  if (initialSchema) {
    syncClockFromSchema(clock, initialSchema);
    const savedSeq = getOplogSeq(initialSchema);
    if (savedSeq > lastSeq.value) lastSeq.value = savedSeq;
  }

  if (!socket) openSocket();
}

function openSocket(): void {
  if (disposed || typeof window === "undefined" || !currentPageId) return;
  if (
    socket &&
    (socket.readyState === WebSocket.OPEN ||
      socket.readyState === WebSocket.CONNECTING)
  ) {
    return;
  }
  let ws: WebSocket;
  try {
    ws = new WebSocket(websocketUrl(currentPageId, tokenOverride));
  } catch {
    scheduleReconnect();
    return;
  }
  socket = ws;
  ws.onopen = () => {
    if (socket !== ws) return;
    connected.value = true;
    retry = 0;
    startHeartbeat();
    flushPending();
  };
  ws.onmessage = (event: MessageEvent) => {
    if (socket !== ws) return;
    handleMessage(event.data);
  };
  ws.onerror = () => {
    try {
      ws.close();
    } catch {
      /* ignore */
    }
  };
  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    connected.value = false;
    stopHeartbeat();
    if (!disposed) scheduleReconnect();
  };
}

function closeSocket(): void {
  if (reconnectTimer !== undefined) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  stopHeartbeat();
  const ws = socket;
  socket = null;
  connected.value = false;
  if (ws) {
    ws.onopen = null;
    ws.onmessage = null;
    ws.onerror = null;
    ws.onclose = null;
    try {
      ws.close(1000, "disposed");
    } catch {
      /* ignore */
    }
  }
}

function scheduleReconnect(): void {
  if (disposed || reconnectTimer !== undefined) return;
  retry += 1;
  const delay =
    Math.min(MAX_BACKOFF_MS, 500 * 2 ** Math.min(retry - 1, 5)) +
    Math.floor(Math.random() * 250);
  reconnectTimer = window.setTimeout(() => {
    reconnectTimer = undefined;
    openSocket();
  }, delay);
}

function startHeartbeat(): void {
  stopHeartbeat();
  heartbeatTimer = window.setInterval(() => {
    if (socket?.readyState === WebSocket.OPEN) {
      try {
        socket.send(JSON.stringify({ type: "ping" }));
      } catch {
        /* 等待 onclose 重连 */
      }
    }
  }, HEARTBEAT_MS);
}

function stopHeartbeat(): void {
  if (heartbeatTimer !== undefined) {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = undefined;
  }
}

/* ------------------------------------------------------------------ 接收 */

function toPositiveInt(value: unknown, fallback = 0): number {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 0) return fallback;
  return number;
}

function normalizeRecord(raw: unknown): SchemaOperationRecord | null {
  if (!raw || typeof raw !== "object") return null;
  const record = raw as Record<string, any>;
  const op = record.op;
  if (!isSchemaOp(op)) return null;
  const seq = toPositiveInt(record.seq, 0);
  const clientIdValue =
    typeof record.client_id === "string"
      ? record.client_id
      : typeof record.clientId === "string"
        ? record.clientId
        : op.clock.clientId;
  return {
    seq,
    op,
    clientId: clientIdValue,
    baseRevision: toPositiveInt(
      record.base_revision ?? record.baseRevision,
      0
    ),
    userId:
      record.user_id === null || record.user_id === undefined
        ? null
        : toPositiveInt(record.user_id, 0) || null,
    username:
      typeof record.username === "string" ? record.username : "",
    createdAt:
      typeof record.created_at === "string"
        ? record.created_at
        : typeof record.createdAt === "string"
          ? record.createdAt
          : "",
  };
}

function normalizeRecords(raw: unknown): SchemaOperationRecord[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .map((item) => normalizeRecord(item))
    .filter((item): item is SchemaOperationRecord => item !== null);
}

function markSeen(seq: number): void {
  if (!Number.isSafeInteger(seq) || seq <= 0) return;
  seenSeqs.add(seq);
  if (seq > lastSeq.value) lastSeq.value = seq;
  if (seenSeqs.size > MAX_SEEN_SEQS) {
    // Set 保持插入顺序；清掉最早的一部分，避免长时间会话内存无界增长。
    let removed = 0;
    for (const value of seenSeqs) {
      seenSeqs.delete(value);
      removed += 1;
      if (removed >= 1000) break;
    }
  }
}

function isSeen(seq: number): boolean {
  return seq > 0 && seenSeqs.has(seq);
}

function observeRecord(record: SchemaOperationRecord): void {
  clock.observe(record.op.clock);
  markSeen(record.seq);
}

function handleMessage(raw: unknown): void {
  if (typeof raw !== "string") return;
  let data: any;
  try {
    data = JSON.parse(raw);
  } catch {
    return;
  }
  if (!data || typeof data !== "object") return;
  if (data.type === "pong") return;
  if (data.type === "error") {
    if (typeof console !== "undefined") {
      console.warn("[schema-ops]", data.code || "error", data.message || "");
    }
    return;
  }
  if (data.page_id && currentPageId && Number(data.page_id) !== currentPageId) {
    return;
  }

  if (data.type === "snapshot") {
    const records = normalizeRecords(data.ops);
    const serverSeq = toPositiveInt(data.seq, 0);
    const after =
      data.after === null || data.after === undefined
        ? null
        : toPositiveInt(data.after, 0);
    const fresh = records.filter((record) => !isSeen(record.seq));
    for (const record of fresh) observeRecord(record);

    const more = !!data.has_more;
    hasMore.value = more;
    if (!more) {
      // 没有更多时服务端 seq 就是完整游标；有更多时只推进到本批最后一条。
      if (serverSeq > lastSeq.value) lastSeq.value = serverSeq;
    } else if (fresh.length && fresh[fresh.length - 1].seq > lastSeq.value) {
      lastSeq.value = fresh[fresh.length - 1].seq;
    }

    const remote: SchemaOpsRemote = {
      kind: "snapshot",
      pageId: currentPageId,
      ops: fresh,
      seq: serverSeq,
      after,
      hasMore: more,
      from: typeof data.from === "string" ? data.from : "server",
    };
    for (const listener of [...listeners]) {
      try {
        listener(remote);
      } catch (error) {
        if (typeof console !== "undefined") {
          console.error("[schema-ops] listener failed", error);
        }
      }
    }
    return;
  }

  if (data.type === "ops") {
    const records = normalizeRecords(data.ops);
    const fresh = records.filter((record) => !isSeen(record.seq));
    if (!fresh.length) return;
    for (const record of fresh) observeRecord(record);
    const remote: SchemaOpsRemote = {
      kind: "ops",
      pageId: currentPageId,
      ops: fresh,
      seq: Math.max(toPositiveInt(data.last_seq, 0), lastSeq.value),
      after: null,
      hasMore: false,
      from: typeof data.from === "string" ? data.from : "",
    };
    for (const listener of [...listeners]) {
      try {
        listener(remote);
      } catch (error) {
        if (typeof console !== "undefined") {
          console.error("[schema-ops] listener failed", error);
        }
      }
    }
    return;
  }

  if (data.type === "appended") {
    // 自己的操作：本地已应用，仅记录服务端分配 seq，不重复回调 onOps。
    const records = normalizeRecords(data.ops);
    for (const record of records) observeRecord(record);
    const serverSeq = toPositiveInt(data.last_seq, 0);
    if (serverSeq > lastSeq.value) lastSeq.value = serverSeq;
  }
}

/** 订阅 snapshot / 远端 ops；返回取消订阅函数。 */
export function onOps(listener: SchemaOpsListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/* ------------------------------------------------------------------ 发送 */

function baseRevisionValue(baseRevision?: number): number {
  const explicit = Number(baseRevision);
  if (Number.isSafeInteger(explicit) && explicit >= 0) return explicit;
  return Math.max(0, Math.trunc(persistedRevision.value || 0));
}

function queueOps(ops: SchemaOp[]): void {
  if (!ops.length) return;
  pendingOps = pendingOps.concat(ops).slice(-MAX_PENDING_OPS);
}

function flushPending(): void {
  if (!pendingOps.length) return;
  const ws = socket;
  if (!ws || ws.readyState !== WebSocket.OPEN) return;
  const ops = pendingOps;
  pendingOps = [];
  try {
    ws.send(
      JSON.stringify({
        type: "ops",
        client_id: clientId,
        base_revision: baseRevisionValue(),
        ops,
      })
    );
  } catch {
    pendingOps = ops.concat(pendingOps);
    try {
      ws.close();
    } catch {
      /* onclose 会重连 */
    }
  }
}

/**
 * 发送一批本地操作。断线时排队（上限 500 条），连接恢复后自动 flush。
 *
 * @returns 是否已发送或已入队；无有效操作返回 false。
 */
export function sendOps(ops: SchemaOp[], baseRevision?: number): boolean {
  const valid = (Array.isArray(ops) ? ops : []).filter((op) =>
    isSchemaOp(op)
  );
  if (!valid.length) return false;
  if (!connected.value || !socket || socket.readyState !== WebSocket.OPEN) {
    queueOps(valid);
    return true;
  }
  try {
    socket.send(
      JSON.stringify({
        type: "ops",
        client_id: clientId,
        base_revision: baseRevisionValue(baseRevision),
        ops: valid,
      })
    );
    return true;
  } catch {
    queueOps(valid);
    try {
      socket.close();
    } catch {
      /* ignore */
    }
    return false;
  }
}

/**
 * 手动分页拉取历史操作（snapshot 的 ``has_more`` 为 true 时使用）。
 *
 * 本函数只返回数据，不修改 lastSeq / 不触发 onOps；调用方合并后可用
 * ``setOplogSeq(schema, fetched.seq)`` 推进持久化游标。
 */
export async function fetchOps(
  after: number = lastSeq.value,
  limit = 200
): Promise<FetchedOps> {
  const pageId = currentPageId;
  if (!pageId) return { seq: 0, after, ops: [], hasMore: false };
  const cursor = Math.max(0, toPositiveInt(after, 0));
  const size = Math.max(1, Math.min(500, toPositiveInt(limit, 200) || 200));
  const data = await api.get<any>(
    `/pages/${pageId}/schema/ops/?after=${cursor}&limit=${size}`,
    { silent: true }
  );
  return {
    seq: toPositiveInt(data?.seq, 0),
    after: toPositiveInt(data?.after, cursor),
    ops: normalizeRecords(data?.ops),
    hasMore: !!data?.has_more,
  };
}

/** 最近一次服务端 seq 的普通值（便于在非响应式代码中使用）。 */
export function getLastSeq(): number {
  return lastSeq.value;
}

/* ------------------------------------------------------------------ 释放 */

/** 关闭连接、清理定时器 / 队列 / 订阅；组件卸载时调用。 */
export function dispose(): void {
  disposed = true;
  pendingOps = [];
  closeSocket();
  listeners.clear();
  seenSeqs.clear();
  currentPageId = 0;
  lastSeq.value = 0;
  hasMore.value = false;
  clock.counter = 0;
}

/** 便于命名空间方式使用。 */
export const schemaOps = {
  connect,
  sendOps,
  onOps,
  dispose,
  fetchOps,
  getLastSeq,
  getClock,
  clientId,
  connected,
  lastSeq,
  hasMore,
};
