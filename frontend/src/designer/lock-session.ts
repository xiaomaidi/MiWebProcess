/**
 * 服务端权威的设计器节点锁客户端。
 *
 * 与旧的 ``collab.ts``（客户端协商锁，`locks: Record<nodeId, username>`）不同：
 * - 锁的归属完全由服务端 WebSocket 消费者决定；
 * - 本模块发送 acquire/release/cancel/heartbeat/selection/cursor；
 * - ``tryAcquire`` / ``acquire`` 保持 Promise<boolean> 兼容旧调用；
 *   ``acquireDetailed`` / ``waitForLock`` 返回 {granted, queued, position, owner, timeout}；
 * - 服务端会把被拒的 acquire 放进节点 FIFO 等待队列（30s / 50 人），
 *   本模块通过 ``state.queues``、``onLockWait`` 与 ``cancelWait`` 暴露排队状态；
 * - sessionId 按页面持久化在 sessionStorage，断线重连后可恢复自己此前持有的节点；
 *   显式 ``waitForLock`` 的等待会在重连后按剩余时间重新入队。
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

/** 单个节点的服务端排队状态（``state.queues[nodeId]``）。 */
export type LockQueueStatus =
  | "waiting"
  | "reconnecting"
  | "granted"
  | "timeout"
  | "denied"
  | "cancelled";

export interface LockQueueState {
  nodeId: string;
  /** 1 基位置；0 表示未知/已不在队列。 */
  position: number;
  owner: LockInfo | null;
  /** ISO 8601 的服务端排队截止时间。 */
  timeoutAt: string;
  /** 本次允许等待的总毫秒数（用于展示，不代表剩余）。 */
  timeoutMs: number;
  enqueuedAt: number;
  status: LockQueueStatus;
  /** queue-full / queue-busy / timeout / cancelled / denied 等。 */
  reason: string;
  queueLength: number;
  updatedAt: number;
}

export interface LockWaitResult {
  granted: boolean;
  queued: boolean;
  position: number;
  owner: LockInfo | null;
  /** true 表示等待超时（区别于权限/队列满导致的 denied）。 */
  timeout: boolean;
  reason: string;
  lock: LockInfo | null;
  timeoutAt: string;
  cancelled?: boolean;
}

export interface AcquireOptions {
  /** 客户端最长等待时间；服务端上限默认 30s。缺省 35s（含网络余量）。 */
  timeoutMs?: number;
  /** 断线重连后自动恢复这次等待（waitForLock 默认 true，acquire 默认 false）。 */
  resumable?: boolean;
  /** 每次排队状态变化时的回调，便于 UI 局部更新。 */
  onUpdate?: (state: LockQueueState | null) => void;
}

export type LockWaitEventType =
  | "queued"
  | "queue"
  | "granted"
  | "timeout"
  | "denied"
  | "cancelled"
  | "reconnecting";

export interface LockWaitEvent {
  type: LockWaitEventType;
  nodeId: string;
  state: LockQueueState | null;
  result?: LockWaitResult;
  owner?: LockInfo | null;
  reason?: string;
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
  /** 当前会话在各节点上的等待队列（响应式，供 LockWaitToast 读取）。 */
  queues: Record<string, LockQueueState>;
  sessionId: string;
  /** 兼容旧字段：当前登录用户 ID（由 snapshot.self 提供）。 */
  selfUserId: number;
  isEditor: boolean;
  lastError: string;
}

interface PendingAcquire {
  nodeId: string;
  requestId: string;
  resolve: (result: LockWaitResult) => void;
  timer: number;
  /** 已收到服务端 lock-queued/queue，处于排队中。 */
  queued: boolean;
  resumable: boolean;
  /** 客户端最终截止时间（毫秒时间戳）。 */
  deadlineAt: number;
  /** 本次请求允许的最长等待毫秒数。 */
  timeoutMs: number;
  onUpdate?: (state: LockQueueState | null) => void;
}

const SESSION_KEY_PREFIX = "wp:designer:lock:session:";
const HELD_KEY_PREFIX = "wp:designer:lock:held:";
const HEARTBEAT_MS = 30_000;
const RECONNECT_MAX_MS = 15_000;
/** 发出 acquire 后等待首个回执（lock-granted / lock-queued / lock-denied）的时间。 */
const ACQUIRE_RESPONSE_TIMEOUT_MS = 6_000;
/** 未显式指定 timeoutMs 时的总等待预算：服务端队列上限 30s + 网络余量。 */
const DEFAULT_WAIT_TIMEOUT_MS = 35_000;
const MAX_WAIT_TIMEOUT_MS = 120_000;
/** 服务端 timeoutAt 之后的本地兜底宽限，避免消息延迟导致误判。 */
const WAIT_GRACE_MS = 1_500;
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
  queues: {},
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
let toastMountRequested = false;

const pending = new Map<string, PendingAcquire>();
/** 本会话希望持有的节点；跨重连（以及整页刷新）用于恢复。 */
const desired = new Set<string>();
const waitListeners = new Set<(event: LockWaitEvent) => void>();
/** 刚取消的节点：若服务端授权与取消消息竞态，收到 grant 后立刻还锁。 */
const cancelledWaitNodes = new Set<string>();

function markJustCancelled(nodeId: string): void {
  cancelledWaitNodes.add(nodeId);
  window.setTimeout(() => cancelledWaitNodes.delete(nodeId), 5_000);
}

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

function nextRequestId(): string {
  requestSeq += 1;
  return `lock-${Date.now().toString(36)}-${requestSeq}`;
}

function timeoutAtMs(raw: unknown): number {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  const parsed = Date.parse(String(raw || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function emptyResult(reason: string): LockWaitResult {
  return {
    granted: false,
    queued: false,
    position: 0,
    owner: null,
    timeout: false,
    reason,
    lock: null,
    timeoutAt: "",
  };
}

function setQueueState(
  nodeId: string,
  patch: Partial<LockQueueState> & { status?: LockQueueStatus }
): LockQueueState {
  const existing = state.queues[nodeId];
  const next: LockQueueState = {
    nodeId,
    position: patch.position ?? existing?.position ?? 0,
    owner: patch.owner !== undefined ? patch.owner : existing?.owner ?? null,
    timeoutAt: patch.timeoutAt ?? existing?.timeoutAt ?? "",
    timeoutMs: patch.timeoutMs ?? existing?.timeoutMs ?? 0,
    enqueuedAt: existing?.enqueuedAt ?? Date.now(),
    status: patch.status ?? existing?.status ?? "waiting",
    reason: patch.reason ?? existing?.reason ?? "",
    queueLength: patch.queueLength ?? existing?.queueLength ?? 0,
    updatedAt: Date.now(),
  };
  state.queues[nodeId] = next;
  return next;
}

function emitWait(event: LockWaitEvent): void {
  for (const listener of [...waitListeners]) {
    try {
      listener(event);
    } catch {
      /* 订阅方异常不影响锁主流程 */
    }
  }
}

/** 订阅排队/授权/超时/取消事件；返回取消订阅函数。 */
export function onLockWait(handler: (event: LockWaitEvent) => void): () => void {
  waitListeners.add(handler);
  return () => waitListeners.delete(handler);
}

export function offLockWait(handler: (event: LockWaitEvent) => void): void {
  waitListeners.delete(handler);
}

export function onLockWaitEvent(handler: (event: LockWaitEvent) => void): () => void {
  return onLockWait(handler);
}

function armPendingTimer(item: PendingAcquire, delayMs: number): void {
  if (item.timer) window.clearTimeout(item.timer);
  item.timer = window.setTimeout(() => expirePending(item), Math.max(0, delayMs));
}

function finishPending(item: PendingAcquire, result: LockWaitResult): void {
  if (item.timer) window.clearTimeout(item.timer);
  item.timer = 0;
  if (pending.get(item.requestId) === item) pending.delete(item.requestId);
  item.resolve(result);
}

/** 客户端兜底超时：撤销服务端排队，避免“客户端已放弃、服务端仍授权”。 */
function expirePending(item: PendingAcquire): void {
  if (pending.get(item.requestId) !== item) return;
  const queue = state.queues[item.nodeId];
  const result: LockWaitResult = {
    granted: false,
    queued: Boolean(item.queued || queue),
    position: queue?.position ?? 0,
    owner: queue?.owner ?? null,
    timeout: true,
    reason: "timeout",
    lock: null,
    timeoutAt: queue?.timeoutAt ?? "",
  };
  const otherPending = [...pending.values()].some(
    (entry) => entry !== item && entry.nodeId === item.nodeId
  );
  if (state.connected && !otherPending) send({ type: "cancel", nodeId: item.nodeId });
  finishPending(item, result);
  item.onUpdate?.(null);
  const stillPending = [...pending.values()].some((entry) => entry.nodeId === item.nodeId);
  if (stillPending) return;
  if (queue) {
    const timedOut = setQueueState(item.nodeId, { status: "timeout", reason: "timeout" });
    emitWait({ type: "timeout", nodeId: item.nodeId, state: { ...timedOut }, result });
    delete state.queues[item.nodeId];
  }
}

function settlePending(requestId: string | undefined, result: LockWaitResult): boolean {
  if (!requestId) return false;
  const item = pending.get(requestId);
  if (!item) return false;
  finishPending(item, result);
  return true;
}

function settleNode(nodeId: string, result: LockWaitResult): void {
  for (const [requestId, item] of [...pending]) {
    if (item.nodeId === nodeId) settlePending(requestId, result);
  }
}

function rejectAllPending(reason = "disconnected", preserveResumable = false): void {
  for (const [requestId, item] of [...pending]) {
    if (preserveResumable && item.resumable) continue;
    const queue = state.queues[item.nodeId];
    finishPending(item, {
      granted: false,
      queued: item.queued,
      position: queue?.position ?? 0,
      owner: queue?.owner ?? null,
      timeout: reason === "timeout",
      reason,
      lock: null,
      timeoutAt: queue?.timeoutAt ?? "",
    });
  }
}

/** 把某个节点最新队列状态同步给等待中的 Promise 与 UI 回调。 */
function syncPendingQueue(nodeId: string, queue: LockQueueState | null): void {
  for (const item of [...pending.values()]) {
    if (item.nodeId !== nodeId) continue;
    item.queued = Boolean(queue && (queue.status === "waiting" || queue.status === "reconnecting"));
    if (queue) {
      const deadline = timeoutAtMs(queue.timeoutAt);
      if (deadline > 0) item.deadlineAt = Math.min(item.deadlineAt, deadline);
    }
    item.onUpdate?.(queue ? { ...queue } : null);
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
      // 恢复只做一次性短尝试：失败立即撤销排队，避免后台恢复把用户拖进长等待。
      const result = await acquireDetailed(nodeId, {
        resumable: false,
        timeoutMs: ACQUIRE_RESPONSE_TIMEOUT_MS,
      });
      if (generation !== recoveryGeneration) return false;
      if (result.granted) markRecovered(nodeId);
      return result.granted;
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

  const previousQueues = state.queues;
  state.locks = {};
  state.peers = {};
  state.queues = {};
  state.recovered = [];
  recoveryGeneration += 1;

  // 重连后服务端队列已随旧连接销毁；保留可恢复等待的 UI 状态，snapshot 后重发 acquire。
  for (const item of pending.values()) {
    if (!item.resumable) continue;
    const previous = previousQueues[item.nodeId];
    if (previous) {
      setQueueState(item.nodeId, { ...previous, status: "reconnecting", reason: "reconnecting" });
    } else {
      setQueueState(item.nodeId, { status: "reconnecting", reason: "reconnecting" });
    }
    item.queued = false;
  }

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
  resumePendingWaits();
}

/** 重连后重新发起可恢复的等待（服务端会重新排队并分配新位置）。 */
function resumePendingWaits(): void {
  if (!state.connected) return;
  const resumable = [...pending.values()].filter((item) => item.resumable);
  for (const item of resumable) {
    if (Date.now() >= item.deadlineAt) {
      expirePending(item);
      continue;
    }
    const oldRequestId = item.requestId;
    if (oldRequestId) pending.delete(oldRequestId);
    item.requestId = nextRequestId();
    item.queued = false;
    pending.set(item.requestId, item);
    const remaining = Math.max(1_000, item.deadlineAt - Date.now());
    armPendingTimer(item, Math.min(ACQUIRE_RESPONSE_TIMEOUT_MS, remaining));
    const queue = setQueueState(item.nodeId, { status: "reconnecting", reason: "reconnecting" });
    emitWait({ type: "reconnecting", nodeId: item.nodeId, state: { ...queue } });
    if (
      !send({
        type: "acquire",
        nodeId: item.nodeId,
        requestId: item.requestId,
        timeoutMs: remaining,
      })
    ) {
      armPendingTimer(item, 0);
    }
  }
}

function handleLockQueued(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const owner = normalizeLock(message?.owner);
  const position = Math.max(0, Number(message?.position) || 0);
  const timeoutAt = String(message?.timeoutAt || "");
  const queueLength = Math.max(0, Number(message?.queueLength) || 0);
  const deadline = timeoutAtMs(timeoutAt);
  const queue = setQueueState(nodeId, {
    position,
    owner,
    timeoutAt,
    timeoutMs: deadline > 0 ? Math.max(0, deadline - Date.now()) : 0,
    status: "waiting",
    reason: "",
    queueLength,
  });
  if (owner) touchPeer(owner.sessionId, { userId: owner.userId, username: owner.username });
  syncPendingQueue(nodeId, queue);
  const requestId = String(message?.requestId || "");
  const item = requestId ? pending.get(requestId) : undefined;
  if (item) {
    item.queued = true;
    if (deadline > 0) item.deadlineAt = Math.min(item.deadlineAt, deadline);
    armPendingTimer(item, Math.max(0, item.deadlineAt - Date.now()) + WAIT_GRACE_MS);
  }
  emitWait({ type: "queued", nodeId, state: { ...queue }, owner });
}

function handleQueue(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const owner = normalizeLock(message?.owner);
  const waiters = Array.isArray(message?.waiters) ? message.waiters : [];
  const queueLength = Math.max(
    0,
    Number(message?.queueLength) || (Array.isArray(waiters) ? waiters.length : 0)
  );
  let position = Math.max(0, Number(message?.position) || 0);
  let timeoutAt = String(message?.timeoutAt || "");
  if (position <= 0 && waiters.length) {
    const mine = waiters.find((waiter: any) => String(waiter?.sessionId || "") === state.sessionId);
    if (mine) {
      position = Math.max(0, Number(mine.position) || 0);
      timeoutAt = String(mine.timeoutAt || "");
    }
  }
  const existing = state.queues[nodeId];
  if (position > 0) {
    const deadline = timeoutAtMs(timeoutAt);
    const queue = setQueueState(nodeId, {
      position,
      owner,
      timeoutAt,
      timeoutMs: deadline > 0 ? Math.max(0, deadline - Date.now()) : existing?.timeoutMs ?? 0,
      status: "waiting",
      queueLength,
      reason: "",
    });
    if (owner) touchPeer(owner.sessionId, { userId: owner.userId, username: owner.username });
    syncPendingQueue(nodeId, queue);
    for (const item of [...pending.values()]) {
      if (item.nodeId !== nodeId) continue;
      if (deadline > 0) item.deadlineAt = Math.min(item.deadlineAt, deadline);
      armPendingTimer(item, Math.max(0, item.deadlineAt - Date.now()) + WAIT_GRACE_MS);
    }
    emitWait({ type: "queue", nodeId, state: { ...queue }, owner });
    return;
  }
  if (existing) {
    if (owner) existing.owner = owner;
    existing.queueLength = queueLength;
    existing.updatedAt = Date.now();
    syncPendingQueue(nodeId, existing);
    emitWait({ type: "queue", nodeId, state: { ...existing }, owner });
  }
}

function handleLockGranted(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  // 取消与授权竞态：用户已放弃等待时，若服务端仍把锁转交过来就立即归还，
  // 避免留下一把没有 UI 使用的孤儿锁（要等 90s TTL 才释放）。
  if (
    cancelledWaitNodes.has(nodeId) &&
    ![...pending.values()].some((item) => item.nodeId === nodeId)
  ) {
    cancelledWaitNodes.delete(nodeId);
    delete state.queues[nodeId];
    if (state.connected) send({ type: "release", nodeId });
    return;
  }
  const wasQueued = Boolean(state.queues[nodeId]) || [...pending.values()].some(
    (item) => item.nodeId === nodeId && item.queued
  );
  const lock: LockInfo = {
    nodeId,
    userId: thisUserId,
    username: thisUsername,
    sessionId: state.sessionId,
    expiresAt: String(message?.expiresAt || ""),
  };
  state.locks[nodeId] = lock;
  desired.add(nodeId);
  saveHeld();
  delete state.queues[nodeId];
  const result: LockWaitResult = {
    granted: true,
    queued: wasQueued,
    position: 0,
    owner: lock,
    timeout: false,
    reason: "granted",
    lock,
    timeoutAt: "",
  };
  settlePending(String(message?.requestId || ""), result);
  settleNode(nodeId, result);
  if (state.recovering) markRecovered(nodeId);
  if (wasQueued) emitWait({ type: "granted", nodeId, state: null, result, owner: lock });
}

function handleLockDenied(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const owner = normalizeLock(message?.owner);
  const reason = String(message?.reason || "locked");
  const queue = state.queues[nodeId];
  if (owner) {
    state.locks[nodeId] = owner;
    touchPeer(owner.sessionId, { userId: owner.userId, username: owner.username });
  } else if (!isOwn(state.locks[nodeId])) {
    delete state.locks[nodeId];
  }
  desired.delete(nodeId);
  saveHeld();
  delete state.queues[nodeId];
  const result: LockWaitResult = {
    granted: false,
    queued: Boolean(queue),
    position: queue?.position ?? 0,
    owner,
    timeout: false,
    reason,
    lock: null,
    timeoutAt: queue?.timeoutAt ?? "",
  };
  settlePending(String(message?.requestId || ""), result);
  settleNode(nodeId, result);
  emitWait({
    type: "denied",
    nodeId,
    state: queue ? { ...queue, status: "denied", reason, updatedAt: Date.now() } : null,
    result,
    owner,
    reason,
  });
}

function handleLockTimeout(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const queue = state.queues[nodeId];
  const result: LockWaitResult = {
    granted: false,
    queued: Boolean(queue),
    position: queue?.position ?? 0,
    owner: queue?.owner ?? null,
    timeout: true,
    reason: "timeout",
    lock: null,
    timeoutAt: queue?.timeoutAt ?? "",
  };
  delete state.queues[nodeId];
  settlePending(String(message?.requestId || ""), result);
  settleNode(nodeId, result);
  emitWait({
    type: "timeout",
    nodeId,
    state: queue ? { ...queue, status: "timeout", reason: "timeout", updatedAt: Date.now() } : null,
    result,
  });
}

function handleLockEvent(message: any): void {
  const nodeId = normalizeNodeId(message?.nodeId);
  if (!nodeId) return;
  const action = String(message?.action || "acquire");
  if (action === "release") {
    delete state.locks[nodeId];
    const queue = state.queues[nodeId];
    if (queue && String(message?.sessionId || "") !== state.sessionId) {
      // 持锁者已释放；真正的授权/位置更新由服务端随后的 lock-granted/queue 推送。
      queue.owner = null;
      queue.updatedAt = Date.now();
    }
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
    const queue = state.queues[nodeId];
    if (queue) {
      queue.owner = lock;
      queue.updatedAt = Date.now();
    }
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
    case "lock-queued":
      handleLockQueued(message);
      break;
    case "queue":
      handleQueue(message);
      break;
    case "lock-timeout":
      handleLockTimeout(message);
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
      const reason = String(message.code || "error");
      const nodeId = normalizeNodeId(message.nodeId);
      if (nodeId) {
        const queue = state.queues[nodeId];
        delete state.queues[nodeId];
        const result: LockWaitResult = {
          ...emptyResult(reason),
          queued: Boolean(queue),
          position: queue?.position ?? 0,
          owner: queue?.owner ?? null,
          timeoutAt: queue?.timeoutAt ?? "",
        };
        settlePending(String(message.requestId || ""), result);
        settleNode(nodeId, result);
      } else if (message.requestId) {
        settlePending(String(message.requestId), emptyResult(reason));
      }
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
    const resumableNodes = new Set(
      [...pending.values()].filter((item) => item.resumable).map((item) => item.nodeId)
    );
    rejectAllPending("disconnected", true);
    // 可恢复的等待不要停在 6s 的首包超时上：按剩余总预算重新计时，
    // 否则重连退避期间会被误判为超时。
    for (const item of pending.values()) {
      if (!item.resumable) continue;
      armPendingTimer(item, Math.max(0, item.deadlineAt - Date.now()) + WAIT_GRACE_MS);
    }
    // 服务端在断线时会释放本会话的锁/排队；保留 desired 以便重连后恢复。
    state.locks = {};
    state.peers = {};
    for (const nodeId of Object.keys(state.queues)) {
      if (resumableNodes.has(nodeId)) {
        const queue = setQueueState(nodeId, { status: "reconnecting", reason: "disconnected" });
        for (const item of pending.values()) {
          if (item.nodeId === nodeId) item.onUpdate?.({ ...queue });
        }
      } else {
        delete state.queues[nodeId];
      }
    }
    stopTimers();
    scheduleReconnect();
  };
  current.onerror = () => {
    if (current !== socket) return;
    state.connected = false;
  };
}

/** 自动挂载排队提示（LockWaitToast）；宿主不可用/显式关闭时静默跳过。 */
function ensureLockWaitToast(): void {
  if (typeof document === "undefined" || toastMountRequested) return;
  if ((globalThis as any).__WP_LOCK_WAIT_TOAST__ === false) return;
  toastMountRequested = true;
  void import("./lock-wait-toast")
    .then((mod) => mod.mountLockWaitToast())
    .catch(() => {
      toastMountRequested = false;
    });
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
  state.queues = {};
  state.selfUserId = 0;
  state.isEditor = false;
  state.lastError = "";
  thisUserId = 0;
  thisUsername = "";
  desired.clear();
  for (const nodeId of loadHeld(page)) desired.add(nodeId);

  bindGlobalListeners();
  ensureLockWaitToast();
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
  state.queues = {};
}

/** 彻底释放：关闭连接、清理定时器与本地恢复状态。组件卸载时调用。 */
export function dispose(): void {
  disconnect();
  state.recovered = [];
  state.queues = {};
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
  if (toastMountRequested) {
    toastMountRequested = false;
    void import("./lock-wait-toast")
      .then((mod) => mod.unmountLockWaitToast())
      .catch(() => {
        /* 宿主已卸载时忽略 */
      });
  }
}

/**
 * 详细版获取锁：返回 ``{granted, queued, position, owner, timeout}``。
 * - 节点空闲：立即 granted；
 * - 被他人持有：进入服务端 FIFO 队列，直到授权/超时/取消；
 * - ``resumable`` 为 true 时，断线重连会自动重发申请（保留剩余等待时间）。
 */
export function acquireDetailed(nodeId: string, options: AcquireOptions = {}): Promise<LockWaitResult> {
  const id = normalizeNodeId(nodeId);
  if (!id || typeof window === "undefined") return Promise.resolve(emptyResult("invalid"));
  cancelledWaitNodes.delete(id);
  const existing = state.locks[id];
  if (existing && isOwn(existing)) {
    return Promise.resolve({
      granted: true,
      queued: false,
      position: 0,
      owner: existing,
      timeout: false,
      reason: "owned",
      lock: existing,
      timeoutAt: "",
    });
  }
  if (!state.connected || !socket || socket.readyState !== WebSocket.OPEN) {
    return Promise.resolve(emptyResult("disconnected"));
  }
  // snapshot 之前服务端身份未知，仍发请求让服务端裁决；已知非编辑者则直接拒绝。
  if (thisUserId && !state.isEditor) return Promise.resolve(emptyResult("forbidden"));

  const requested = Math.min(
    MAX_WAIT_TIMEOUT_MS,
    Math.max(1_000, Number(options.timeoutMs) || DEFAULT_WAIT_TIMEOUT_MS)
  );
  const resumable = options.resumable !== false;
  const requestId = nextRequestId();
  const currentQueue = state.queues[id];
  if (currentQueue) options.onUpdate?.({ ...currentQueue });

  return new Promise<LockWaitResult>((resolve) => {
    const item: PendingAcquire = {
      nodeId: id,
      requestId,
      resolve,
      timer: 0,
      queued: Boolean(currentQueue),
      resumable,
      deadlineAt: Date.now() + requested,
      timeoutMs: requested,
      onUpdate: options.onUpdate,
    };
    pending.set(requestId, item);
    armPendingTimer(item, Math.min(requested, ACQUIRE_RESPONSE_TIMEOUT_MS));
    const sent = send({
      type: "acquire",
      nodeId: id,
      requestId,
      timeoutMs: requested,
    });
    if (!sent) {
      finishPending(item, emptyResult("disconnected"));
    }
  });
}

/**
 * 兼容旧 API：返回布尔值。已知被他人持有时立即 false（不排队），
 * 其余情况走服务端队列，取消/超时/拒绝均返回 false。
 */
export function tryAcquire(nodeId: string, options: AcquireOptions = {}): Promise<boolean> {
  const id = normalizeNodeId(nodeId);
  if (!id || typeof window === "undefined") return Promise.resolve(false);
  cancelledWaitNodes.delete(id);
  const existing = state.locks[id];
  if (existing) return Promise.resolve(isOwn(existing));
  if (!state.connected || !socket || socket.readyState !== WebSocket.OPEN) return Promise.resolve(false);
  if (thisUserId && !state.isEditor) return Promise.resolve(false);
  return acquireDetailed(id, { ...options, resumable: false }).then((result) => result.granted);
}

/** 兼容旧 API 命名；等价于 tryAcquire。 */
export const acquire = tryAcquire;

/** 显式等待锁（默认 35s，服务端上限 30s），带队列位置/取消/重连恢复。 */
export function waitForLock(nodeId: string, options: AcquireOptions = {}): Promise<LockWaitResult> {
  return acquireDetailed(nodeId, { resumable: true, ...options });
}

/**
 * 取消某个节点的等待：通知服务端撤销排队，并让进行中的 acquire Promise
 * 立即以 ``reason:"cancelled"`` 结束。
 */
export function cancelWait(nodeId: string): boolean {
  const id = normalizeNodeId(nodeId);
  if (!id) return false;
  const queue = state.queues[id];
  let canceled = false;
  for (const [requestId, item] of [...pending]) {
    if (item.nodeId !== id) continue;
    const result: LockWaitResult = {
      granted: false,
      queued: Boolean(item.queued || queue),
      position: queue?.position ?? 0,
      owner: queue?.owner ?? null,
      timeout: false,
      reason: "cancelled",
      lock: null,
      timeoutAt: queue?.timeoutAt ?? "",
      cancelled: true,
    };
    finishPending(item, result);
    item.onUpdate?.(null);
    canceled = true;
    if (pending.get(requestId) === item) pending.delete(requestId);
  }
  if (queue) {
    const cancelled = setQueueState(id, { status: "cancelled", reason: "cancelled" });
    emitWait({ type: "cancelled", nodeId: id, state: { ...cancelled } });
    delete state.queues[id];
    canceled = true;
  }
  if (canceled && state.connected) {
    markJustCancelled(id);
    send({ type: "cancel", nodeId: id });
  }
  return canceled;
}

export const cancel = cancelWait;

export function cancelAllWaits(): void {
  for (const nodeId of Object.keys(state.queues)) cancelWait(nodeId);
}

/** 显式释放自己持有的锁（服务端只会删除本会话的锁）。 */
export function release(nodeId: string): void {
  const id = normalizeNodeId(nodeId);
  if (!id) return;
  // 显式 release 也意味着不再等待该节点。
  cancelWait(id);
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
  return {
    locks: Object.values(state.locks),
    recovering: state.recovering,
    queues: Object.values(state.queues),
  };
}

/** 当前所有排队节点的只读快照（非响应式）。 */
export function getLockQueues(): LockQueueState[] {
  return Object.values(state.queues);
}

/** 响应式队列集合（供独立组件/组合式使用）。 */
export const lockQueues = computed(() => state.queues);

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
    /** 等待队列：nodeId → { position, owner, timeoutAt, status }。 */
    queues: computed(() => state.queues),
    queueList: computed(() =>
      Object.values(state.queues)
        .filter((queue) => queue.status === "waiting" || queue.status === "reconnecting")
        .sort((a, b) => a.enqueuedAt - b.enqueuedAt)
    ),
    connect,
    disconnect,
    dispose,
    tryAcquire,
    acquire,
    acquireDetailed,
    waitForLock,
    cancelWait,
    cancel,
    cancelAllWaits,
    onLockWait,
    offLockWait,
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
