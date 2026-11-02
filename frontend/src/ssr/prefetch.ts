/**
 * SSR 预取缓存：服务端渲染时数据组件把结果写入，序列化进 __WP_SSR__，
 * 浏览器端在水合前灌回，保证首屏 DOM 与服务端一致（不闪空列表）。
 */
const store: Record<string, any> = {};

export function clearPrefetch(): void {
  for (const key of Object.keys(store)) delete store[key];
}

export function setPrefetch(map: Record<string, any> | null | undefined): void {
  clearPrefetch();
  if (map && typeof map === "object") Object.assign(store, map);
}

export function cachePrefetch(key: string, value: any): void {
  store[key] = value;
}

export function getPrefetch<T = any>(key: string): T | null {
  return (store[key] as T) ?? null;
}

export function dumpPrefetch(): Record<string, any> {
  return { ...store };
}
