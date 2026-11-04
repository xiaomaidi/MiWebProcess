import { computed, reactive, ref } from "vue";
import { openAppSocket } from "@/api";
import { useAuthStore } from "@/store/auth";

export interface CollabPeer {
  username: string;
  color: string;
  lastSeen: number;
  cursor?: { x: number; y: number };
  selection?: string[];
}

const COLORS = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2", "#db2777", "#4f46e5"];
const state = reactive({
  connected: false,
  peers: {} as Record<string, CollabPeer>,
  locks: {} as Record<string, string>,
});
const disposed = ref(false);
let socket: WebSocket | null = null;
let pageId = 0;
let appId = 0;
let reconnectTimer: number | undefined;
let heartbeatTimer: number | undefined;
let cursorAt = 0;
let retry = 0;

function colorFor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) % COLORS.length;
  return COLORS[Math.abs(hash) % COLORS.length];
}

function send(kind: string, data: Record<string, any> = {}) {
  if (socket?.readyState !== WebSocket.OPEN || !pageId) return;
  socket.send(JSON.stringify({
    type: "designer",
    topic: `designer/${pageId}`,
    payload: { pageId, kind, ...data },
  }));
}

function touchPeer(username: string, patch: Partial<CollabPeer> = {}) {
  state.peers[username] = {
    ...(state.peers[username] || { username, color: colorFor(username), lastSeen: Date.now() }),
    ...patch,
    lastSeen: Date.now(),
  };
}

function onMessage(message: any) {
  if (!message || message.type === "presence" || message.type === "joined" || message.type === "pong") {
    if (message?.type === "joined") state.connected = true;
    return;
  }
  const payload = message.payload || {};
  if (Number(payload.pageId) !== pageId) return;
  const username = String(message.from || "");
  if (!username || username === "server") return;
  const self = useAuthStore().displayName;
  if (username === self) return;
  touchPeer(username);
  const peer = state.peers[username];
  if (payload.kind === "hello") {
    send("hello");
  } else if (payload.kind === "cursor") {
    peer.cursor = { x: Number(payload.x) || 0, y: Number(payload.y) || 0 };
  } else if (payload.kind === "selection") {
    peer.selection = Array.isArray(payload.ids) ? payload.ids.map(String) : [];
  } else if (payload.kind === "lock") {
    if (payload.action === "acquire" && payload.nodeId) {
      state.locks[String(payload.nodeId)] = username;
    } else if (payload.nodeId) {
      delete state.locks[String(payload.nodeId)];
    }
  } else if (payload.kind === "leave") {
    delete state.peers[username];
    for (const [nodeId, owner] of Object.entries(state.locks)) {
      if (owner === username) delete state.locks[nodeId];
    }
  }
}

function prune() {
  const cutoff = Date.now() - 12000;
  for (const [username, peer] of Object.entries(state.peers)) {
    if (peer.lastSeen < cutoff) {
      delete state.peers[username];
      for (const [nodeId, owner] of Object.entries(state.locks)) {
        if (owner === username) delete state.locks[nodeId];
      }
    }
  }
}

function scheduleReconnect() {
  if (disposed.value) return;
  retry += 1;
  const delay = Math.min(15000, 1000 * 2 ** Math.min(retry, 4));
  reconnectTimer = window.setTimeout(() => connectDesignerCollab(appId, pageId), delay);
}

export function connectDesignerCollab(nextAppId: number, nextPageId: number) {
  if (typeof window === "undefined") return;
  appId = nextAppId;
  pageId = nextPageId;
  disposed.value = false;
  if (!appId || !pageId) return;
  if (socket && socket.readyState <= WebSocket.OPEN) return;
  try {
    socket = openAppSocket(appId, onMessage);
  } catch {
    scheduleReconnect();
    return;
  }
  if (!socket) return;
  socket.onopen = () => {
    state.connected = true;
    retry = 0;
    send("hello");
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = window.setInterval(() => {
      send("hello");
      prune();
    }, 5000);
  };
  socket.onclose = () => {
    state.connected = false;
    window.clearInterval(heartbeatTimer);
    scheduleReconnect();
  };
  socket.onerror = () => {
    state.connected = false;
  };
}

export function disconnectDesignerCollab() {
  disposed.value = true;
  window.clearTimeout(reconnectTimer);
  window.clearInterval(heartbeatTimer);
  try {
    if (socket?.readyState === WebSocket.OPEN) send("leave");
    socket?.close();
  } catch {
    /* ignore */
  }
  socket = null;
  state.connected = false;
  state.peers = {};
  state.locks = {};
}

export function sendCollabCursor(x: number, y: number) {
  const now = Date.now();
  if (now - cursorAt < 50) return;
  cursorAt = now;
  send("cursor", { x, y });
}

export function sendCollabSelection(ids: string[]) {
  send("selection", { ids });
}

export function acquireDesignerLock(nodeId: string): boolean {
  const owner = state.locks[nodeId];
  if (owner) return false;
  send("lock", { nodeId, action: "acquire" });
  return true;
}

export function releaseDesignerLock(nodeId: string) {
  if (state.locks[nodeId]) return;
  send("lock", { nodeId, action: "release" });
}

export function isRemoteLocked(nodeId: string): boolean {
  return !!state.locks[nodeId];
}

export function useDesignerCollab() {
  return {
    state,
    peers: computed(() => Object.values(state.peers)),
    remoteLocks: computed(() => state.locks),
    connected: computed(() => state.connected),
    connect: connectDesignerCollab,
    disconnect: disconnectDesignerCollab,
    sendCursor: sendCollabCursor,
    sendSelection: sendCollabSelection,
    acquireLock: acquireDesignerLock,
    releaseLock: releaseDesignerLock,
    isRemoteLocked,
  };
}
