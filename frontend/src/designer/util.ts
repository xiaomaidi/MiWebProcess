/** 设计器共享工具（纯函数 + 历史包装）。 */
import { useHistoryStore } from "@/store/history";
import { useSchemaStore } from "@/store/schema";
import { isBindingValue } from "@/engine/binding";
import type { DataBinding, PageSchema } from "@/types";

export { isBindingValue } from "@/engine/binding";

/** 分页 / 纯数组响应归一化为数组。 */
export function asList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object") {
    const o = data as { results?: unknown };
    if (Array.isArray(o.results)) return o.results as T[];
  }
  return [];
}

/** 绑定值 → DataBinding；非绑定返回 null。 */
export function bindingOf(v: unknown): DataBinding | null {
  return isBindingValue(v) ? (v as { __binding__: DataBinding }).__binding__ : null;
}

export function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v ?? null, null, 2);
  } catch {
    return String(v);
  }
}

/** 解析 JSON 文本；失败返回 null。 */
export function parseJson(v: string): unknown | null {
  const s = (v ?? "").trim();
  if (!s) return null;
  try {
    return JSON.parse(s);
  } catch {
    return null;
  }
}

/** 带历史快照的一次变更；返回 apply 的返回值。 */
export function withHistory<T>(label: string, apply: () => T): T {
  return useHistoryStore().run(label, apply);
}

/** 一次带历史快照的变更，并把 schema 标记为 dirty。 */
export function commit(label: string, apply: () => void) {
  withHistory(label, apply);
  useSchemaStore().dirty = true;
}

/** 8px 网格吸附。 */
export function snap(v: number, grid = 8): number {
  return Math.round(v / grid) * grid;
}

/** 组件拖拽 MIME。 */
export const DND_COMPONENT_MIME = "text/wp-component";
export const DND_NODE_MIME = "text/wp-node-move";

export function setComponentDrag(e: DragEvent, name: string) {
  const dt = e.dataTransfer;
  if (!dt) return;
  dt.setData(DND_COMPONENT_MIME, name);
  dt.setData("text/plain", name); // 兼容仅读取 text/plain 的浏览器
  dt.effectAllowed = "copy";
}

export function droppedComponent(e: DragEvent): string | null {
  const dt = e.dataTransfer;
  if (!dt) return null;
  return dt.getData(DND_COMPONENT_MIME) || dt.getData("text/plain") || null;
}

/** 空 schema（后端新建页）：无节点或仅根节点。 */
export function isEmptySchema(s: PageSchema | null | undefined): boolean {
  return !s || Object.keys(s.nodes ?? {}).length <= 1;
}

/** registry props 的 x-ui 扩展键（类型未声明，读取需断言）。 */
export function xUiOf(ps: { "x-ui"?: string } | undefined): string | undefined {
  return (ps as { "x-ui"?: string } | undefined)?.["x-ui"];
}
