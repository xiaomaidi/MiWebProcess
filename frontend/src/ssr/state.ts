/** SSR 水合状态：服务端写入、浏览器端一次性消费。 */
export interface SsrState {
  url: string;
  payload: any;
  prefetch?: Record<string, any>;
}

let state: SsrState | null = null;

export function setSsrState(next: SsrState | null): void {
  state = next;
}

export function peekSsrState(): SsrState | null {
  return state;
}

/** 读取后清空，避免客户端路由跳转后复用旧页面的首屏数据。 */
export function consumeSsrState(): SsrState | null {
  const current = state;
  state = null;
  return current;
}
