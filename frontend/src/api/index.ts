/** 统一 API 客户端：JWT 自动附加、错误归一化。 */
import { ElMessage } from "element-plus";

export class ApiError extends Error {
  status: number;
  data?: any;
  constructor(status: number, message: string, data?: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

const TOKEN_KEY = "wp_token";

/** SSR 时由 entry-server 注入后端绝对地址；浏览器端为空（同源 /api）。 */
export function apiBase(): string {
  return String((globalThis as any).__WP_API_BASE__ || "");
}

export function getToken(): string {
  if (typeof localStorage === "undefined") return "";
  return localStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(token: string) {
  if (typeof localStorage === "undefined") return;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request<T = any>(
  method: string,
  path: string,
  body?: unknown,
  opts: { raw?: boolean; silent?: boolean; form?: boolean } = {}
): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (opts.form && body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let resp: Response;
  try {
    resp = await fetch(`${apiBase()}/api${path}`, { method, headers, body: payload });
  } catch (e) {
    throw new ApiError(0, "网络错误，无法连接服务器");
  }
  if (resp.status === 401 && !path.startsWith("/auth/")) {
    setToken("");
    if (location.pathname !== "/login") location.href = "/login";
    throw new ApiError(401, "登录已过期");
  }
  if (!resp.ok) {
    let msg = `请求失败（${resp.status}）`;
    let errorData: any = null;
    try {
      const data = await resp.json();
      errorData = data;
      if (typeof data.detail === "string") msg = data.detail;
      else if (Array.isArray(data.detail)) msg = data.detail.map((d: any) => String(d.detail ?? d)).join("；");
      else if (typeof data.detail === "object" && data.detail) {
        const parts: string[] = [];
        for (const v of Object.values(data.detail)) {
          parts.push(Array.isArray(v) ? v.map((x: any) => String(x)).join("，") : String(v));
        }
        if (parts.length) msg = parts.join("；");
      } else if (data.message) msg = String(data.message);
    } catch {
      /* ignore */
    }
    if (!opts.silent) ElMessage.error(msg);
    throw new ApiError(resp.status, msg, errorData);
  }
  if (opts.raw) return (await resp.text()) as unknown as T;
  if (resp.status === 204) return undefined as T;
  const text = await resp.text();
  if (!text) return undefined as T;
  return JSON.parse(text) as T;
}

export const api = {
  get: <T = any>(path: string, opts?: { silent?: boolean }) => request<T>("GET", path, undefined, opts),
  post: <T = any>(path: string, body?: unknown, opts?: { silent?: boolean; form?: boolean }) =>
    request<T>("POST", path, body, opts),
  put: <T = any>(path: string, body?: unknown, opts?: { silent?: boolean; form?: boolean }) =>
    request<T>("PUT", path, body, opts),
  patch: <T = any>(path: string, body?: unknown, opts?: { silent?: boolean }) =>
    request<T>("PATCH", path, body, opts),
  del: <T = any>(path: string, opts?: { silent?: boolean }) => request<T>("DELETE", path, undefined, opts),
  upload: <T = any>(path: string, file: File, fieldName = "file", extra?: Record<string, string>) => {
    const fd = new FormData();
    fd.append(fieldName, file);
    for (const [k, v] of Object.entries(extra || {})) fd.append(k, v);
    return request<T>("POST", path, fd, { form: true });
  },
};

/** WebSocket 连接（JWT 走 query）。 */
export function openAppSocket(appId: number, onMessage: (msg: any) => void): WebSocket | null {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const url = `${proto}://${location.host}/ws/${appId}/?token=${encodeURIComponent(getToken())}`;
  const ws = new WebSocket(url);
  ws.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data));
    } catch {
      /* ignore */
    }
  };
  return ws;
}
