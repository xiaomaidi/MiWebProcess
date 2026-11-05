/**
 * LockWaitToast 的单例挂载器。
 *
 * 设计器当前把 lock-session 的 connect() 放在 DesignerView 里，而本任务的
 * 文件 ownership 不允许修改 DesignerView，因此由 lock-session connect() 动态
 * 调用 ``mountLockWaitToast()`` 自动挂载。组件本身只读取 lock-session 的响应式
 * state.queues，不依赖父组件传参；后续若把 <LockWaitToast /> 放进 DesignerView，
 * 可调用 ``unmountLockWaitToast()`` 或全局设置 ``__WP_LOCK_WAIT_TOAST__ = false``
 * 关闭自动挂载，避免重复实例。
 */
import { createApp, type App as VueApp } from "vue";
import LockWaitToast from "./components/LockWaitToast.vue";

const HOST_ID = "wp-lock-wait-toast-root";

let app: VueApp | null = null;
let host: HTMLElement | null = null;

/** 挂载（幂等）。返回是否处于已挂载状态。 */
export function mountLockWaitToast(): boolean {
  if (typeof document === "undefined" || !document.body) return false;
  if (app && host && host.isConnected) return true;

  if (host) {
    try {
      app?.unmount();
    } catch {
      /* 已卸载 */
    }
    host.remove();
    app = null;
    host = null;
  }

  const existing = document.getElementById(HOST_ID);
  if (existing) existing.remove();

  host = document.createElement("div");
  host.id = HOST_ID;
  host.setAttribute("data-wp-lock-wait-toast", "1");
  document.body.appendChild(host);
  app = createApp(LockWaitToast);
  app.mount(host);
  return true;
}

export function unmountLockWaitToast(): void {
  if (app) {
    try {
      app.unmount();
    } catch {
      /* 忽略重复卸载 */
    }
  }
  app = null;
  if (host) host.remove();
  host = null;
  if (typeof document !== "undefined") {
    const existing = document.getElementById(HOST_ID);
    if (existing) existing.remove();
  }
}

export function isLockWaitToastMounted(): boolean {
  return Boolean(app && host && host.isConnected);
}
