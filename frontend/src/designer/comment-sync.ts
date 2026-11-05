/**
 * 设计器评论实时同步。
 *
 * 复用既有 `/ws/{app_id}/?token=<JWT>` 应用中继（无新增后端 consumer），
 * 评论主题为 `designer-comments/{pageId}`。
 *
 * 客户端 → 服务端：
 *   {"type":"subscribe","topics":["designer-comments/42"]}
 *   {"type":"comment_created|comment_resolved|comment_updated|comment_deleted",
 *    "topic":"designer-comments/42",
 *    "payload":{"page_id":42,"comment_id":9,"event_key":"...","comment":{...}}}
 * 服务端 → 客户端：后端在 REST 变更后广播同一结构（顶层另带 topic/page_id/comment_id/event_key）。
 *
 * event_key 由 type + comment id + updated_at 确定性生成，本地回显与服务端广播
 * 只会被应用一次，避免重复事件。
 */
import { openAppSocket } from "@/api";

export type CommentEventType =
  | "comment_created"
  | "comment_updated"
  | "comment_resolved"
  | "comment_deleted";

export interface CommentEvent {
  type: CommentEventType;
  pageId: number;
  commentId: number;
  eventKey: string;
  from: string;
  comment: Record<string, any> | null;
}

export interface CommentSyncOptions {
  onEvent: (event: CommentEvent) => void;
  onStatus?: (connected: boolean) => void;
}

const RECONNECT_MAX_MS = 15000;
const PING_MS = 25000;
const SEEN_LIMIT = 500;

export function commentTopic(pageId: number): string {
  return `designer-comments/${Number(pageId) || 0}`;
}

/** 兼容 `comment-created` / `comment_created` 两种写法。 */
export function normalizeCommentEventType(raw: unknown): CommentEventType | null {
  const value = String(raw ?? "").replace(/-/g, "_").toLowerCase();
  if (value === "comment_reopened") return "comment_updated";
  if (
    value === "comment_created" ||
    value === "comment_updated" ||
    value === "comment_resolved" ||
    value === "comment_deleted"
  ) {
    return value;
  }
  return null;
}

/** 与服务端 `collab.views._event_key` 保持一致的确定性事件键。 */
export function commentEventKey(
  type: CommentEventType,
  commentId: number,
  comment?: Record<string, any> | null
): string {
  if (type === "comment_deleted") return `comment_deleted:${commentId}`;
  const stamp = String(comment?.updated_at || comment?.created_at || "");
  return `${type}:${commentId}:${stamp}`;
}

export class CommentSync {
  private socket: WebSocket | null = null;
  private appId = 0;
  private pageId = 0;
  private disposed = false;
  private retry = 0;
  private reconnectTimer: number | undefined;
  private pingTimer: number | undefined;
  private seen = new Set<string>();
  private seenQueue: string[] = [];
  private readonly onEvent: (event: CommentEvent) => void;
  private readonly onStatus?: (connected: boolean) => void;

  constructor(options: CommentSyncOptions) {
    this.onEvent = options.onEvent;
    this.onStatus = options.onStatus;
  }

  /** 切换页面 / 应用时重建连接。 */
  connect(appId: number, pageId: number): void {
    if (typeof window === "undefined") return;
    this.stopSocket();
    this.appId = Number(appId) || 0;
    this.pageId = Number(pageId) || 0;
    this.disposed = false;
    this.retry = 0;
    if (!this.appId || !this.pageId) return;
    this.open();
  }

  disconnect(): void {
    this.disposed = true;
    this.stopSocket();
    this.onStatus?.(false);
  }

  /**
   * 发布本地评论事件（REST 成功后的低延迟回显）；服务端也会广播权威事件，
   * 两端 event_key 相同，接收方只会应用一次。
   */
  publish(type: CommentEventType, comment: Record<string, any> | null | undefined): boolean {
    if (!comment || !this.pageId) return false;
    const commentId = Number(comment.id || 0);
    if (!commentId) return false;
    const topic = commentTopic(this.pageId);
    return this.sendRaw({
      type,
      topic,
      payload: {
        topic,
        page_id: this.pageId,
        comment_id: commentId,
        event_key: commentEventKey(type, commentId, comment),
        comment,
      },
    });
  }

  private open(): void {
    if (this.disposed || !this.appId || !this.pageId) return;
    let socket: WebSocket | null = null;
    try {
      socket = openAppSocket(this.appId, (message) => this.handle(message));
    } catch {
      this.scheduleReconnect();
      return;
    }
    if (!socket) {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      this.retry = 0;
      this.onStatus?.(true);
      const topic = commentTopic(this.pageId);
      this.sendRaw({ type: "subscribe", topics: [topic] });
      // 默认订阅是 "#"（全部消息）；评论连接只保留本页主题，减少无关事件。
      this.sendRaw({ type: "unsubscribe", topics: ["#"] });
      window.clearInterval(this.pingTimer);
      this.pingTimer = window.setInterval(() => this.sendRaw({ type: "ping" }), PING_MS);
    };
    socket.onclose = (event) => {
      this.onStatus?.(false);
      window.clearInterval(this.pingTimer);
      this.pingTimer = undefined;
      if (this.disposed || this.socket !== socket) return;
      this.socket = null;
      // 缺少 token / 非成员：重连没有意义。
      if (event.code === 4401 || event.code === 4403) return;
      this.scheduleReconnect();
    };
    socket.onerror = () => this.onStatus?.(false);
  }

  private sendRaw(payload: Record<string, any>): boolean {
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    try {
      socket.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }

  private handle(message: any): void {
    if (!message || typeof message !== "object") return;
    const type = normalizeCommentEventType(message.type);
    if (!type) return;
    const payload = message.payload;
    if (!payload || typeof payload !== "object") return;
    const topic = String(message.topic || payload.topic || "");
    if (topic && topic !== commentTopic(this.pageId)) return;
    const pageId = Number(payload.page_id ?? message.page_id ?? 0);
    if (pageId && pageId !== this.pageId) return;
    const comment =
      payload.comment && typeof payload.comment === "object" ? payload.comment : null;
    const commentId = Number(payload.comment_id ?? comment?.id ?? 0);
    if (!commentId) return;
    const eventKey = String(
      payload.event_key || message.event_key || commentEventKey(type, commentId, comment)
    );
    if (this.seen.has(eventKey)) return;
    this.remember(eventKey);
    this.onEvent({
      type,
      pageId: this.pageId,
      commentId,
      eventKey,
      from: String(message.from || ""),
      comment,
    });
  }

  private remember(key: string): void {
    this.seen.add(key);
    this.seenQueue.push(key);
    if (this.seenQueue.length > SEEN_LIMIT) {
      const oldest = this.seenQueue.shift();
      if (oldest) this.seen.delete(oldest);
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed) return;
    this.retry += 1;
    const delay = Math.min(RECONNECT_MAX_MS, 1000 * 2 ** Math.min(this.retry, 4));
    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = window.setTimeout(() => this.open(), delay);
  }

  private stopSocket(): void {
    window.clearTimeout(this.reconnectTimer);
    window.clearInterval(this.pingTimer);
    this.reconnectTimer = undefined;
    this.pingTimer = undefined;
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    try {
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(
          JSON.stringify({ type: "unsubscribe", topics: [commentTopic(this.pageId)] })
        );
      }
      socket.onclose = null;
      socket.close();
    } catch {
      /* ignore */
    }
  }
}
