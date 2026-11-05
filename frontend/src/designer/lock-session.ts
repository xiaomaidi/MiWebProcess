/**
 * 服务端权威的设计器节点锁客户端。
 *
 * 与旧的 ``collab.ts``（客户端协商锁，`locks: Record<nodeId, username>`）不同：
 * - 锁的归属完全由服务端 WebSocket 消费者决定；
 * - 本模块只发送 acquire/release/heartbeat/selection/cursor；
 * - ``tryAcquire(nodeId)`` / ``acquire(nodeId)`` 返回 Promise<boolean>，以服务端回执为准；
 * - sessionId 按页面持久化在 sessionStorage，断线重连后可恢复自己此前持有的节点。
 *
 * 协议：``ws(s)://host/ws/designer-lock/{pageId}/?token=<JWT>&session=<uuid>``
 * 详见后端 ``collab/lock_consumer.py``。
 */
import { computed, reactive } from "vue";
import { getToken } from "@/api";

export interface LockInfo {
  nodeId: string;
  userId: number;
  username: string;
  sessionId: string;
  /** ISO 8601；服务端 TTL 90s，客户端只做展示/兜底清理。 */
  expiresAt: string;
}

/** 兼容旧命名。 */
export type ServerLock = LockInfo;

export interface LockPeer {
  sessionId: string;
  userId: number;
  username: string;
  lastSeen: number;
  selection: string[];
  cursor?: { x: number; y: number };
}

export interface LockSessionState {
  pageId: number;
  connected: boolean;
  /** 重连后正在把此前持有的节点重新申请回来的窗口期。 */
  recovering: boolean;
  /** 本轮恢复成功拿回的节点（每次 snapshot 重置）。 */
  recovered: string[];
  locks: Record<string, LockInfo>;
  peers: Record<string, LockPeer>;
  sessionId: string;
  /** 兼容旧字段：当前登录用户 ID（由 snapshot.self 提供）。 */
  selfUserId: number;
  isEditor: boolean;
  lastError: string;
}

interface PendingAcquire {
  nodeId: string;
  resolve: (granted: boolean) => void;
  timer: number;
}

const SESSION_KEY_PREFIX = "wp:designer:lock:session:";
const HELD_KEY_PREFIX = "wp:designer:lock:held:";
const HEARTBEAT_MS = 30_000;
const RECONNECT_MAX_MS = 15_000;
const ACQUIRE_TIMEOUT_MS = 5_000;
const RECOVERY_SETTLE_MS = 3_000;
const PEER_TIMEOUT_MS = 120_000;
const CURSOR_THROTTLE_MS = 50;
const MAX_NODE_ID = 120;
const MAX_SELECTION = 200;

const state = reactive<LockSessionState>({
  pageId: 0,
  connected: false,
  recovering: false,
  recovered: [],
  locks: {},
  peers: {},
  sessionId: "",
  selfUserId: 0,
  isEditor: false,
  lastError: "",
});

let socket: WebSocket | null = null;
let token = "";
let pageId = 0;
let disposed = false;
let retry = 0;
let reconnectTimer: number | undefined;
let heartbeatTimer: number | undefined;
let pruneTimer: number | undefined;
let lastCursorAt = 0;
let requestSeq = 0;
let thisUserId = 0;
let thisUsername = "";
let listenersBound = false;
let recoveryTimer: number | undefined;
let recoveryGeneration = 0;

const pending = new Map<string, PendingAcquire>();
/** 本会话希望持有的节点；跨重连（以及整页刷新）用于恢复。 */
const desired = new Set<string>();

function storageGet(key: string): string {
  try {
    return sessionStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function storageSet(key: string, value: string): void {
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch {
    /* 隐私模式/配额不足时忽略 */
  }
}

function uuid(): string {
  const cryptoObj = globalThis.crypto;
  if (cryptoObj && typeof cryptoObj.randomUUID === "function") return cryptoObj.randomUUID();
  const bytes = new Uint8Array(16);
  if (cryptoObj && typeof cryptoObj.getRandomValues === "function") cryptoObj.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function sessionKey(id: number): string {
  return `${SESSION_KEY_PREFIX}${id}`;
}

function heldKey(id: number): string {
  return `${HELD_KEY_PREFIX}${id}`;
}

function loadSessionId(id: number): string {
  const stored = storageGet(sessionKey(id)).trim();
  if (stored) return stored;
  const created = uuid();
  storageSet(sessionKey(id), created);
  return created;
}

function loadHeld(id: number): string[] {
  const raw = storageGet(heldKey(id));
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map((item) => String(item)).filter((item) => item && item.length <= MAX_NODE_ID);
  } catch {
    return [];
  }
}

function saveHeld(): void {
  if (!pageId) return;
  storageSet(heldKey(pageId), JSON.stringify([...desired]));
}

function wsBase(): string {
  const injected = String((globalThis as any).__WP_WS_BASE__ || "").replace(/\/$/, "");
  if (injected) return injected;
  const proto = globalThis.location?.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${globalThis.location?.host || "localhost"}`;
}

function buildUrl(): string {
  const qs = new URLSearchParams({ token, session: state.sessionId });
  return `${wsBase()}/ws/designer-lock/${pageId}/?${qs.toString()}`;
}

function send(payload: Record<string, unknown>): boolean {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  try {
    socket.send(JSON.stringify(payload));
    return true;
  } catch {
    return false;
  }
}

function isOwn(lock: LockInfo | undefined | null): boolean {
  if (!lock) return false;
  if (lock.sessionId !== state.sessionId) return false;
  return thisUserId === 0 || lock.userId === thisUserId;
}

function normalizeNodeId(raw: unknown): string {
  const text = typeof raw === "string" ? raw.trim() : "";
  return text && text.length <= MAX_NODE_ID ? text : "";
}

function normalizeLock(raw: any): LockInfo | null {
  if (!raw || typeof raw !== "object") return null;
  const nodeId = normalizeNodeId(raw.nodeId);
  if (!nodeId) return null;
  return {
    nodeId,
    userId: Number(raw.userId) || 0,
    username: String(raw.username || ""),
    sessionId: String(raw.sessionId || ""),
    expiresAt: String(raw.expiresAt || ""),
  };
}

function touchPeer(sessionId: string, patch: Partial<LockPeer> = {}): void {
  if (!sessionId || sessionId === state.sessionId) return;
  const existing = state.peers[sessionId];
  state.peers[sessionId] = {
    sessionId,
    userId: patch.userId ?? existing?.userId ?? 0,
    username: patch.username ?? existing?.username ?? "",
    selection: patch.selection ?? existing?.selection ?? [],
    cursor: patch.cursor ?? existing?.cursor,
    lastSeen: Date.now(),
  };
}

function prunePeers(): void {
  const cutoff = Date.now() - PEER_TIMEOUT_MS;
  for (const [id, peer] of Object.entries(state.peers)) {
    if (peer.lastSeen < cutoff) delete state.peers[id];
  }
}

function pruneExpiredLocks(): void {
  const now = Date.now();
  for (const [nodeId, lock] of Object.entries(state.locks)) {
    const expiresAt = Date.parse(lock.expiresAt);
    if (!Number.isFinite(expiresAt) || expiresAt <= now) {
      delete state.locks[nodeId];
      if (isOwn(lock)) desired.delete(nodeId);
    }
  }
}

function settlePending(requestId: string | undefined, granted: boolean): boolean {
  if (!requestId) return false;
  const item = pending.get(requestId);
  if (!item) return false;
  window.clearTimeout(item.timer);
  pending.delete(requestId);
  item.resolve(granted);
  return true;
}

function settleNode(nodeId: string, granted: boolean): void {
  for (const [requestId, item] of pending) {
    if (item.nodeId === nodeId) settlePending(requestId, granted);
  }
}

function rejectAllPending(): void {
  for (const [requestId, item] of pending) {
    window.clearTimeout(item.timer);
    pending.delete(requestId);
    item.resolve(false);
  }
}

function markRecovered(nodeId: string): void {
  if (!state.recovered.includes(nodeId)) state.recovered.push(nodeId);
}

// ------------------------------------------------------------------ 恢复
function beginRecovery(): void {
  const generation = ++recoveryGeneration;
  if (recoveryTimer) window.clearTimeout(recoveryTimer);
  state.recovering = false;

  // 被他人持有的节点不要抢；自己的锁已经是 owned，只需把空闲的候选节点拿回来。
  const blocked = new Set<string>();
  for (const lock of Object.values(state.locks)) {
    if (isOwn(lock)) desired.add(lock.nodeId);
    else blocked.add(lock.nodeId);
  }
  saveHeld();

  const candidates = [...desired].filter(
    (nodeId) => !blocked.has(nodeId) && !isOwn(state.locks[nodeId])
  );
  if (!candidates.length || !state.connected) return;

  state.recovering = true;
  recoveryTimer = window.setTimeout(() => {
    if (generation === recoveryGeneration) state.recovering = false;
  }, RECOVERY_SETTLE_MS);

  void Promise.allSettled(
    candidates.map(async (nodeId) => {
      const granted = await acquire(nodeId);
      if (generation !== recoveryGeneration) return false;
      if (granted) markRecovered(nodeId);
      return granted;
    })
  ).finally(() => {
    if (generation !== recoveryGeneration) return;
    if (recoveryTimer) window.clearTimeout(recoveryTimer);
    recoveryTimer = undefined;
    state.recovering = false;
  });
}

// ------------------------------------------------------------------ 消息处理
function handleSnapshot(message: any): void {
  const self = message && typeof message.self === "object" && message.self ? message.self : {};
  thisUserId = Number(self.userId) || 0;
  state.selfUserId = thisUserId;
  thisUsername = String(self.username || "");
  state.isEditor = Boolean(self.isEditor);
  const serverSession = String(self.sessionId || "").trim();
  if (serverSession) {
    state.sessionId = serverSession;
    if (pageId && serverSession !== storageGet(sessionKey(pageId))) {
      storageSet(sessionKey(pageId), serverSession);
    }
  }

  state.locks = {};
  state.peers = {};
  state.recovered = [];
  recoveryGeneration += 1;

  const rawLocks = Array.isArray(message?.locks) ? message.locks : [];
  for (const raw of rawLocks) {
    const lock = normalizeLock(raw);
    if (!lock) continue;
    state.locks[lock.nodeId] = lock;
    if (isOwn(lock)) {
      desired.add(lock.nodeId);
    } else {
      touchPeer(lock.sessionId, { userId: lock.userId, username: lock.username });
    }
  }
  saveHeld();
  // 先发一次心跳，避免快照里自己的锁在 30s 心跳前过期。
  send({ type: "heartbeat" });
  beginRecovery();
}

function handleLockGranted(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  state.locks[nodeId] = {
    nodeId,
    userId: thisUserId,
    username: thisUsername,
    sessionId: state.sessionId,
    expiresAt: String(message?.expiresAt || ""),
  };
  desired.add(nodeId);
  saveHeld();
  if (!settlePending(String(message?.requestId || ""), true)) settleNode(nodeId, true);
  if (state.recovering) markRecovered(nodeId);
}

function handleLockDenied(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const owner = normalizeLock(message?.owner);
  if (owner) {
    state.locks[nodeId] = owner;
    touchPeer(owner.sessionId, { userId: owner.userId, username: owner.username });
  } else if (!isOwn(state.locks[nodeId])) {
    delete state.locks[nodeId];
  }
  desired.delete(nodeId);
  saveHeld();
  if (!settlePending(String(message?.requestId || ""), false)) settleNode(nodeId, false);
}

function handleLockEvent(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const action = String(message?.action || "acquire");
  if (action === "release") {
    delete state.locks[nodeId];
    if (String(message?.sessionId || "") === state.sessionId) {
      desired.delete(nodeId);
      saveHeld();
    }
    return;
  }
  const lock = normalizeLock(message);
  if (!lock) return;
  state.locks[nodeId] = lock;
  if (isOwn(lock)) {
    desired.add(lock.nodeId);
    saveHeld();
  } else {
    desired.delete(nodeId);
    touchPeer(lock.sessionId, { userId: lock.userId, username: lock.username });
  }
}

function handleHeartbeatAck(message: any): void {
  const expiresAt = String(message?.expiresAt || "");
  if (!expiresAt) return;
  for (const [nodeId, lock] of Object.entries(state.locks)) {
    if (isOwn(lock)) state.locks[nodeId] = { ...lock, expiresAt };
  }
}

function handleMessage(raw: string): void {
  let message: any;
  try {
    message = JSON.parse(raw);
  } catch {
    return;
  }
  if (!message || typeof message !== "object") return;
  switch (String(message.type || "")) {
    case "snapshot":
      handleSnapshot(message);
      break;
    case "lock-granted":
      handleLockGranted(message);
      break;
    case "lock-denied":
      handleLockDenied(message);
      break;
    case "lock":
      handleLockEvent(message);
      break;
    case "heartbeat-ack":
      handleHeartbeatAck(message);
      break;
    case "selection": {
      const peerSession = String(message.sessionId || "");
      const ids = Array.isArray(message.ids) ? message.ids.map((id: unknown) => String(id)) : [];
      touchPeer(peerSession, {
        userId: Number(message.userId) || undefined,
        username: String(message.username || ""),
        selection: ids.slice(0, MAX_SELECTION),
      });
      break;
    }
    case "cursor": {
      const x = Number(message.x);
      const y = Number(message.y);
      if (!Number.isFinite(x) || !Number.isFinite(y)) break;
      touchPeer(String(message.sessionId || ""), {
        userId: Number(message.userId) || undefined,
        username: String(message.username || ""),
        cursor: { x, y },
      });
      break;
    }
    case "error": {
      state.lastError = String(message.message || "");
      if (message.requestId) settlePending(String(message.requestId), false);
      else if (message.nodeId) settleNode(String(message.nodeId), false);
      break;
    }
    default:
      break;
  }
}

// ------------------------------------------------------------------ 连接生命周期
function stopTimers(): void {
  if (reconnectTimer) window.clearTimeout(reconnectTimer);
  if (heartbeatTimer) window.clearInterval(heartbeatTimer);
  if (pruneTimer) window.clearInterval(pruneTimer);
  if (recoveryTimer) window.clearTimeout(recoveryTimer);
  reconnectTimer = undefined;
  heartbeatTimer = undefined;
  pruneTimer = undefined;
  recoveryTimer = undefined;
}

function startTimers(): void {
  if (heartbeatTimer) window.clearInterval(heartbeatTimer);
  heartbeatTimer = window.setInterval(() => heartbeat(), HEARTBEAT_MS);
  if (pruneTimer) window.clearInterval(pruneTimer);
  pruneTimer = window.setInterval(() => {
    pruneExpiredLocks();
    prunePeers();
  }, 15_000);
}

function scheduleReconnect(): void {
  if (disposed || !pageId || !token) return;
  retry += 1;
  const base = Math.min(RECONNECT_MAX_MS, 500 * 2 ** Math.min(retry, 5));
  const jitter = Math.floor(Math.random() * 250);
  reconnectTimer = window.setTimeout(openSocket, base + jitter);
}

function teardownSocket(): void {
  if (!socket) return;
  const old = socket;
  socket = null;
  old.onopen = null;
  old.onmessage = null;
  old.onclose = null;
  old.onerror = null;
  try {
    old.close();
  } catch {
    /* ignore */
  }
}

function openSocket(): void {
  if (disposed || !pageId || !token) return;
  teardownSocket();
  try {
    socket = new WebSocket(buildUrl());
  } catch {
    socket = null;
    scheduleReconnect();
    return;
  }
  const current = socket;
  current.onopen = () => {
    if (current !== socket) return;
    state.connected = true;
    state.lastError = "";
    retry = 0;
    startTimers();
  };
  current.onmessage = (event: MessageEvent) => {
    if (current !== socket) return;
    handleMessage(String(event.data));
  };
  current.onclose = () => {
    if (current !== socket) return;
    socket = null;
    state.connected = false;
    state.recovering = false;
    rejectAllPending();
    // 服务端在断线时会释放本会话的锁；保留 desired 以便重连后恢复。
    state.locks = {};
    state.peers = {};
    stopTimers();
    scheduleReconnect();
  };
  current.onerror = () => {
    if (current !== socket) return;
    state.connected = false;
  };
}

function bindGlobalListeners(): void {
  if (listenersBound || typeof window === "undefined") return;
  listenersBound = true;
  window.addEventListener("online", () => {
    if (!state.connected && pageId && token) openSocket();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (state.connected) heartbeat();
    else if (pageId && token) openSocket();
  });
}

// ------------------------------------------------------------------ 公开 API
/**
 * 连接指定页面的锁通道。
 * - ``token`` 省略时从登录态读取（兼容旧调用 ``connect(pageId)``）；
 * - 重复调用同一页面/令牌时幂等。
 */
export function connect(nextPageId: number, nextToken?: string): void {
  if (typeof window === "undefined") return;
  const page = Number(nextPageId) || 0;
  if (!page) return;
  const supplied = String(nextToken || "").trim();
  const resolvedToken = supplied || getToken();
  if (!resolvedToken) {
    state.lastError = "缺少登录令牌";
    return;
  }
  if (pageId === page && socket && socket.readyState <= WebSocket.OPEN) {
    // 同页同令牌幂等；令牌变化（重新登录）则重建连接。
    if (resolvedToken === token) return;
  }
  stopTimers();
  teardownSocket();
  rejectAllPending();

  disposed = false;
  pageId = page;
  token = resolvedToken;
  state.pageId = page;
  state.sessionId = loadSessionId(page);
  state.connected = false;
  state.recovering = false;
  state.recovered = [];
  state.locks = {};
  state.peers = {};
  state.selfUserId = 0;
  state.isEditor = false;
  state.lastError = "";
  thisUserId = 0;
  thisUsername = "";
  desired.clear();
  for (const nodeId of loadHeld(page)) desired.add(nodeId);

  bindGlobalListeners();
  openSocket();
}

/** 断开但保留会话/已持有节点记录（可再次 connect 恢复）。 */
export function disconnect(): void {
  disposed = true;
  teardownSocket();
  stopTimers();
  rejectAllPending();
  state.connected = false;
  state.recovering = false;
  state.locks = {};
  state.peers = {};
}

/** 彻底释放：关闭连接、清理定时器与本地恢复状态。组件卸载时调用。 */
export function dispose(): void {
  disconnect();
  state.recovered = [];
  desired.clear();
  if (pageId) storageSet(heldKey(pageId), "");
  pageId = 0;
  token = "";
  state.pageId = 0;
  state.sessionId = "";
  state.selfUserId = 0;
  thisUserId = 0;
  thisUsername = "";
  disposed = true;
}

/**
 * 请求服务端授予节点锁；以服务端回执为准。
 * 已持有返回 true，被他人持有/无权限/断线/超时返回 false。
 */
export function tryAcquire(nodeId: string): Promise<boolean> {
  const id = normalizeNodeId(nodeId);
  if (!id || typeof window === "undefined") return Promise.resolve(false);
  const existing = state.locks[id];
  if (existing) return Promise.resolve(isOwn(existing));
  if (!state.connected || !socket || socket.readyState !== WebSocket.OPEN) return Promise.resolve(false);
  // snapshot 之前服务端身份未知，仍发请求让服务端裁决；已知非编辑者则直接拒绝。
  if (thisUserId && !state.isEditor) return Promise.resolve(false);

  return new Promise<boolean>((resolve) => {
    requestSeq += 1;
    const requestId = `lock-${Date.now().toString(36)}-${requestSeq}`;
    const timer = window.setTimeout(() => {
      pending.delete(requestId);
      resolve(false);
    }, ACQUIRE_TIMEOUT_MS);
    pending.set(requestId, { nodeId: id, resolve, timer });
    if (!send({ type: "acquire", nodeId: id, requestId })) {
      window.clearTimeout(timer);
      pending.delete(requestId);
      resolve(false);
    }
  });
}

/** 兼容旧 API 命名；等价于 tryAcquire。 */
export const acquire = tryAcquire;

/** 显式释放自己持有的锁（服务端只会删除本会话的锁）。 */
export function release(nodeId: string): void {
  const id = normalizeNodeId(nodeId);
  if (!id) return;
  desired.delete(id);
  saveHeld();
  if (isOwn(state.locks[id])) delete state.locks[id];
  send({ type: "release", nodeId: id });
}

/** 心跳：为当前会话在该页面的全部锁续期（服务端 TTL 90s）。 */
export function heartbeat(): void {
  send({ type: "heartbeat" });
}

/** 选区广播（不涉及锁归属）。 */
export function sendSelection(ids: string[]): void {
  const clean = (Array.isArray(ids) ? ids : [])
    .map((id) => normalizeNodeId(id))
    .filter(Boolean)
    .slice(0, MAX_SELECTION);
  send({ type: "selection", ids: clean });
}

/** 光标广播；客户端 50ms 限流，服务端同样限流。 */
export function sendCursor(x: number, y: number): void {
  const now = Date.now();
  if (now - lastCursorAt < CURSOR_THROTTLE_MS) return;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return;
  lastCursorAt = now;
  send({ type: "cursor", x, y });
}

export function isRemoteLocked(nodeId: string): boolean {
  const lock = state.locks[normalizeNodeId(nodeId)];
  return Boolean(lock && !isOwn(lock));
}

/** 兼容旧 API：返回快照视图。 */
export function consumeSnapshot() {
  return { locks: Object.values(state.locks), recovering: state.recovering };
}

/** Vue 组合式入口：只读响应式视图 + 操作函数。 */
export function useLockSession() {
  const owned = computed(() =>
    Object.values(state.locks)
      .filter((lock) => isOwn(lock))
      .map((lock) => lock.nodeId)
      .sort()
  );
  const remoteLocks = computed(() => {
    const result: Record<string, LockInfo> = {};
    for (const [nodeId, lock] of Object.entries(state.locks)) {
      if (!isOwn(lock)) result[nodeId] = lock;
    }
    return result;
  });
  return {
    state,
    sessionId: computed(() => state.sessionId),
    connected: computed(() => state.connected),
    recovering: computed(() => state.recovering),
    recovered: computed(() => [...state.recovered]),
    locks: computed(() => state.locks),
    owned,
    remoteLocks,
    peers: computed(() => Object.values(state.peers)),
    connect,
    disconnect,
    dispose,
    tryAcquire,
    acquire,
    release,
    heartbeat,
    sendSelection,
    sendCursor,
    isRemoteLocked,
  };
}

/**
 * 兼容旧 API 名称（已接入 DesignerView/CanvasArea/CollabPresence 的调用方）：
 * ``remoteLocks``/``locks`` 保持「数组」形态，其余与 useLockSession 一致。
 */
export function useDesignerLocks() {
  const base = useLockSession();
  return {
    ...base,
    locks: computed(() => Object.values(state.locks)),
    remoteLocks: computed(() => Object.values(state.locks).filter((lock) => !isOwn(lock))),
  };
}

export default useLockSession;
