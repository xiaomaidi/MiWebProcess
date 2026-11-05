/**
 * 设计器 schema 实时同步（独立于 {@link ./collab.ts} 的应用房间 / 锁通道）。
 *
 * 通道：``ws(s)://host/ws/designer-sync/{pageId}/?token=<JWT>``
 *
 * 设计要点：
 * - 只广播「未保存」的 schema 草稿，真正落库仍走 ``PUT /api/pages/{id}/schema/``。
 * - 服务端快照（snapshot）来自数据库；重连后未保存的远端修改会丢失（MVP 限制）。
 * - 本模块只负责连接 / 收发 / 去重 / 脏数据判定，不直接改 Pinia store；由
 *   DesignerView 等集成方在 onRemote 回调里决定应用还是提示冲突。
 * - 回声避免：忽略 ``client_id`` 等于自己的消息；应用远端 schema 时可用
 *   {@link withRemoteApply} 包裹，且 {@link sendSchema} 会跳过与最近远端一致的
 *   schema。
 *
 * 集成方式（详见交付报告）：
 * ```ts
 * import {
 *   connect, dispose, onRemote, sendSchema, revision, persistedRevision,
 *   classifyRemoteSchema, withRemoteApply, markPersisted,
 * } from "@/designer/schema-sync";
 * ```
 */
import { ref } from "vue";
import { getToken } from "@/api";
import type { PageSchema } from "@/types";

export interface SchemaSyncRemote {
  kind: "snapshot" | "broadcast";
  schema: PageSchema;
  /** 服务端 revision：snapshot 为 DB schema_revision；广播为临时递增 revision。 */
  revision: number;
  /** 服务端计算的 schema SHA-256（DB 快照/广播时提供）。 */
  hash: string;
  /** 发送方稳定 clientId；snapshot 为空字符串。 */
  clientId: string;
  /** 发送方用户名；snapshot 为 "server"。 */
  from: string;
  receivedAt: number;
}

export type SchemaSyncListener = (remote: SchemaSyncRemote) => void;

export type RemoteSchemaDecision = "same" | "apply" | "conflict";

export interface ClassifyRemoteOptions {
  localSchema: PageSchema | null;
  remoteSchema: PageSchema;
  /** 本地是否有未保存修改（store.schema.dirty）。 */
  dirty: boolean;
}

const CLIENT_ID_KEY = "wp_designer_sync_client_id";
const MIN_SEND_INTERVAL_MS = 120;
const MAX_BACKOFF_MS = 15000;
const HEARTBEAT_MS = 25000;

/** 当前连接状态（响应式）。 */
export const connected = ref(false);
/** 最近一次收到的服务端 revision（snapshot 或广播，响应式）。 */
export const revision = ref(0);
/**
 * 最近一次「已落库」的 revision（响应式）。
 * 保存 API 的 `base_revision` 应使用本值，而不是临时广播 revision。
 */
export const persistedRevision = ref(0);
/** 正在把远端 schema 应用到本地 store 时为 true（防止 watcher 回声）。 */
export const applyingRemote = ref(false);

function generateClientId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return `tab-${crypto.randomUUID()}`;
    }
  } catch {
    /* 忽略：隐私模式 / 非安全上下文 */
  }
  return `tab-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** 稳定 clientId：同一标签页 sessionStorage 内保持不变，刷新后仍可复用。 */
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

let socket: WebSocket | null = null;
let currentPageId = 0;
let tokenOverride = "";
let disposed = false;
let retry = 0;
let reconnectTimer: number | undefined;
let heartbeatTimer: number | undefined;
let flushTimer: number | undefined;
let lastSentAt = 0;
let lastSentFingerprint = "";
let lastSentRevision = -1;
let lastRemoteFingerprint = "";
let pending: { schema: PageSchema; baseRevision: number } | null = null;

const listeners = new Set<SchemaSyncListener>();

/* ------------------------------------------------------------------ 规范化 / 指纹 */

/**
 * 稳定序列化：递归排序对象 key，忽略 undefined 属性。
 * 后端 JSONB 会重排 key，只有排序后的表示才能做稳定比较。
 */
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
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
}

/** 本地快速指纹（FNV-1a 32bit）。仅用于本地相等比较，不同于服务端 SHA-256。 */
export function schemaFingerprint(value: unknown): string {
  const text = stableStringify(value);
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** 本地 schema 与远端 schema 是否存在差异。 */
export function hasSchemaChanges(local: PageSchema | null, remote: PageSchema): boolean {
  return schemaFingerprint(local) !== schemaFingerprint(remote);
}

/**
 * 判定收到远端 schema 后应如何处理：
 * - ``same``：内容一致，直接忽略；
 * - ``apply``：本地无未保存修改，可安全应用；
 * - ``conflict``：本地有修改，需提示用户（保留本地 / 手动重新加载）。
 */
export function classifyRemoteSchema(options: ClassifyRemoteOptions): RemoteSchemaDecision {
  if (!hasSchemaChanges(options.localSchema, options.remoteSchema)) return "same";
  if (!options.dirty) return "apply";
  return "conflict";
}

/**
 * 应用远端 schema 到本地 store 时包裹调用，避免 watcher 立刻把远端内容再广播回去。
 * 仅支持同步回调（Pinia action / setSchema 均为同步）。
 */
export function withRemoteApply<T>(apply: () => T): T {
  applyingRemote.value = true;
  try {
    return apply();
  } finally {
    applyingRemote.value = false;
  }
}

/* ------------------------------------------------------------------ 连接 */

function websocketUrl(pageId: number, token: string): string {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const auth = token || getToken();
  return `${proto}://${location.host}/ws/designer-sync/${encodeURIComponent(String(pageId))}/?token=${encodeURIComponent(auth)}`;
}

/**
 * 连接指定页面的实时同步通道。重复调用（同一页且连接中/已连接）是幂等的。
 * 切换 pageId 会关闭旧连接并重置 revision 状态。
 *
 * @param pageId 页面 id
 * @param token 可选 JWT；缺省读取 localStorage（api.getToken）
 */
export function connect(pageId: number | string, token = ""): void {
  if (typeof window === "undefined") return;
  const numeric = Number(pageId);
  if (!Number.isFinite(numeric) || numeric <= 0) return;
  if (token) tokenOverride = token;

  const pageChanged = currentPageId !== 0 && currentPageId !== numeric;
  if (pageChanged) {
    closeSocket();
    revision.value = 0;
    persistedRevision.value = 0;
    lastRemoteFingerprint = "";
    lastSentFingerprint = "";
    lastSentRevision = -1;
  }
  currentPageId = numeric;
  disposed = false;
  retry = 0;
  if (!socket) openSocket();
}

function openSocket(): void {
  if (disposed || typeof window === "undefined" || !currentPageId) return;
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
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
    // 重连后服务端会推送 snapshot；连接前排队但尚未发出的草稿在此尝试补发。
    flush();
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
    // 断线期间不保留未发送草稿，避免重连后把过期内容广播给已前进的会话。
    pending = null;
    stopHeartbeat();
    if (!disposed) scheduleReconnect();
  };
}

function closeSocket(): void {
  if (reconnectTimer !== undefined) {
    window.clearTimeout(reconnectTimer);
    reconnectTimer = undefined;
  }
  if (flushTimer !== undefined) {
    window.clearTimeout(flushTimer);
    flushTimer = undefined;
  }
  stopHeartbeat();
  const ws = socket;
  socket = null;
  connected.value = false;
  pending = null;
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
  const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** Math.min(retry - 1, 5)) + Math.floor(Math.random() * 250);
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
        /* 连接已坏，等待 onclose 重连 */
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
      console.warn("[schema-sync]", data.code || "error", data.message || "");
    }
    return;
  }
  if (data.type !== "snapshot" && data.type !== "schema") return;

  const schema = data.schema;
  if (!schema || typeof schema !== "object" || Array.isArray(schema)) return;
  const remoteRevision = Number(data.revision);
  if (!Number.isFinite(remoteRevision)) return;
  const remoteClientId = typeof data.client_id === "string" ? data.client_id : "";

  // 回声避免：服务端已排除发送方连接，这里再按 clientId 兜底多标签页/重放。
  if (remoteClientId && remoteClientId === clientId) return;

  if (data.type === "snapshot") {
    persistedRevision.value = Math.max(0, Math.trunc(remoteRevision));
    revision.value = Math.max(revision.value, persistedRevision.value);
  } else if (remoteRevision > revision.value) {
    revision.value = Math.trunc(remoteRevision);
  }

  const remote: SchemaSyncRemote = {
    kind: data.type,
    schema: schema as PageSchema,
    revision: Math.trunc(remoteRevision),
    hash: typeof data.hash === "string" ? data.hash : "",
    clientId: remoteClientId,
    from: typeof data.from === "string" ? data.from : "",
    receivedAt: Date.now(),
  };
  lastRemoteFingerprint = schemaFingerprint(schema);
  for (const listener of [...listeners]) {
    try {
      listener(remote);
    } catch (error) {
      if (typeof console !== "undefined") console.error("[schema-sync] listener failed", error);
    }
  }
}

/** 订阅远端 snapshot / schema；返回取消订阅函数。 */
export function onRemote(listener: SchemaSyncListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/* ------------------------------------------------------------------ 发送 */

/**
 * 发送本地 schema（合并 120ms 内的连续修改，避免每次按键都发包）。
 * 与最近一次远端内容一致时自动跳过，避免应用远端后回声。
 *
 * @param schema 当前完整 schema
 * @param baseRevision 可选：最近一次已落库的 revision（默认 persistedRevision）
 * @returns 是否已排队/发送（false = 未连接或参数无效）
 */
export function sendSchema(schema: PageSchema, baseRevision?: number): boolean {
  if (typeof window === "undefined" || !schema || typeof schema !== "object") return false;
  if (!connected.value || !currentPageId) return false;
  const normalizedBase = Number(baseRevision);
  const base = Number.isFinite(normalizedBase) && normalizedBase > 0
    ? Math.trunc(normalizedBase)
    : persistedRevision.value || revision.value || 1;
  pending = { schema, baseRevision: base };
  const elapsed = Date.now() - lastSentAt;
  if (elapsed >= MIN_SEND_INTERVAL_MS) {
    flush();
    return true;
  }
  if (flushTimer === undefined) {
    flushTimer = window.setTimeout(() => {
      flushTimer = undefined;
      flush();
    }, MIN_SEND_INTERVAL_MS - elapsed);
  }
  return true;
}

/** {@link sendSchema} 的短别名。 */
export const send = sendSchema;

function flush(): void {
  if (!pending) return;
  const ws = socket;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    // 未连接时丢弃积压草稿（本地编辑仍在 store 中，由集成方决定是否重发）。
    pending = null;
    return;
  }
  const { schema, baseRevision } = pending;
  pending = null;

  const fingerprint = schemaFingerprint(schema);
  if (fingerprint === lastRemoteFingerprint) return; // 刚应用了远端内容
  if (fingerprint === lastSentFingerprint && baseRevision === lastSentRevision) return; // 无变化

  const payload = JSON.stringify({
    type: "schema",
    base_revision: baseRevision,
    client_id: clientId,
    schema,
  });
  try {
    ws.send(payload);
  } catch {
    return; // 连接已断，onclose 会重连；保留 pending 不值得重发旧内容
  }
  lastSentAt = Date.now();
  lastSentFingerprint = fingerprint;
  lastSentRevision = baseRevision;
}

/** 保存成功后同步「已落库 revision」，保证后续 sendSchema / 保存使用正确 base。 */
export function markPersisted(nextRevision: number): void {
  const normalized = Number(nextRevision);
  if (!Number.isFinite(normalized) || normalized <= 0) return;
  persistedRevision.value = Math.trunc(normalized);
  revision.value = Math.max(revision.value, persistedRevision.value);
}

/* ------------------------------------------------------------------ 释放 */

/** 关闭连接、清理定时器与订阅；组件卸载 / 路由离开时调用。 */
export function dispose(): void {
  disposed = true;
  pending = null;
  closeSocket();
  listeners.clear();
  currentPageId = 0;
  revision.value = 0;
  persistedRevision.value = 0;
  lastRemoteFingerprint = "";
  lastSentFingerprint = "";
  lastSentRevision = -1;
}

/** 便于以命名空间方式使用：`schemaSync.connect(...)`。 */
export const schemaSync = {
  connect,
  send: sendSchema,
  sendSchema,
  onRemote,
  dispose,
  markPersisted,
  classifyRemoteSchema,
  withRemoteApply,
  stableStringify,
  schemaFingerprint,
  connected,
  revision,
  persistedRevision,
  applyingRemote,
  clientId,
};
