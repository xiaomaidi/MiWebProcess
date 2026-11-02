/** 运行时桥：给导入的 Web Component 提供页面状态、数据源和事件协作。 */
import { watch, type WatchStopHandle } from "vue";
import type { RuntimeScope } from "@/types";
import { getBreakpoint, onBreakpoint, type Breakpoint } from "@/design/breakpoints";

export interface WpRuntimeBridge {
  getState(key?: string): any;
  setState(key: string, value: any): void;
  watchState(key: string, handler: (value: any) => void): () => void;
  emit(name: string, detail?: any): void;
  on(name: string, handler: (detail: any) => void): () => void;
  callDatasource(id: number, params?: Record<string, any>): Promise<any>;
  subscribeDatasource(id: number, params: Record<string, any>, handler: (data: any, raw?: any) => void): () => void;
  request(path: string, init?: RequestInit): Promise<any>;
  navigate(path: string): void;
  message(text: string, type?: string): void;
  breakpoint: Breakpoint;
  onBreakpoint(handler: (value: Breakpoint) => void): () => void;
  user: any;
  page: any;
  app: any;
}

let currentCleanup: (() => void) | null = null;

export function installRuntimeBridge(scope: RuntimeScope): () => void {
  const listeners = new Map<string, Set<(detail: any) => void>>();
  const stateStops: WatchStopHandle[] = [];

  const bridge: WpRuntimeBridge = {
    getState(key?: string) {
      return key === undefined ? scope.variables : scope.variables[key];
    },
    setState(key: string, value: any) {
      scope.setVariable(key, value);
    },
    watchState(key: string, handler: (value: any) => void) {
      const stop = watch(() => scope.variables[key], handler, { deep: true, immediate: true });
      stateStops.push(stop);
      return stop;
    },
    emit(name: string, detail?: any) {
      for (const handler of listeners.get(name) || []) handler(detail);
      window.dispatchEvent(new CustomEvent("wp:event", { detail: { name, detail } }));
    },
    on(name: string, handler: (detail: any) => void) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name)!.add(handler);
      const off = () => listeners.get(name)?.delete(handler);
      stateStops.push(off);
      return off;
    },
    async callDatasource(id: number, params?: Record<string, any>) {
      return scope.callDatasource(id, params);
    },
    subscribeDatasource(id: number, params: Record<string, any>, handler: (data: any, raw?: any) => void) {
      if (!scope.subscribeDatasource) throw new Error("当前页面不支持 WebSocket 订阅");
      const off = scope.subscribeDatasource(id, params, handler);
      stateStops.push(off);
      return off;
    },
    async request(path: string, init: RequestInit = {}) {
      const token = localStorage.getItem("wp_token") || "";
      const headers = new Headers(init.headers || {});
      if (token) headers.set("Authorization", `Bearer ${token}`);
      if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      const url = path.startsWith("/") ? path : `/api/${path.replace(/^\/+/, "")}`;
      const response = await fetch(url, { ...init, headers });
      const text = await response.text();
      let data: any = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        data = text;
      }
      if (!response.ok) {
        const detail = data && typeof data === "object" ? data.detail || data.message : "";
        throw new Error(detail || `请求失败（${response.status}）`);
      }
      return data;
    },
    navigate(path: string) {
      scope.navigate(path);
    },
    message(text: string, type: string = "info") {
      scope.message(text, type as any);
    },
    get breakpoint() {
      return getBreakpoint();
    },
    onBreakpoint(handler: (value: Breakpoint) => void) {
      const off = onBreakpoint(handler);
      stateStops.push(off);
      return off;
    },
    get user() {
      return scope.variables.user || (scope as any).user || null;
    },
    get page() {
      return scope.variables.page || null;
    },
    get app() {
      return scope.variables.app || null;
    },
  };

  currentCleanup?.();
  (window as any).__WP_BRIDGE__ = bridge;
  const cleanup = () => {
    for (const stop of stateStops.splice(0)) {
      try {
        stop();
      } catch {
        /* ignore */
      }
    }
    listeners.clear();
    if ((window as any).__WP_BRIDGE__ === bridge) delete (window as any).__WP_BRIDGE__;
    if (currentCleanup === cleanup) currentCleanup = null;
  };
  currentCleanup = cleanup;
  return cleanup;
}
