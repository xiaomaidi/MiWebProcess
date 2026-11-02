/** 内容门户数据访问：运行态走公开 content API，设计态用登录态 models API 预览。 */
import { api } from "@/api";
import type { Paged, RuntimeScope } from "@/types";

export interface ContentRecord {
  id: number;
  data: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export function contentAppCode(scope: RuntimeScope | null): string {
  const app = scope?.variables?.app as { code?: string } | undefined;
  return String(app?.code || "");
}

function qs(params: Record<string, any>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    search.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
  }
  return search.toString();
}

export function contentRows(res: any): Record<string, any>[] {
  const rows = Array.isArray(res?.results) ? res.results : Array.isArray(res) ? res : [];
  return rows.map((row: any) => {
    if (row && row.data && typeof row.data === "object" && !Array.isArray(row.data)) {
      return { ...row.data, id: row.id, _record: row };
    }
    return row;
  });
}

const listCache = new Map<string, { at: number; data: Paged<ContentRecord> }>();
const listInflight = new Map<string, Promise<Paged<ContentRecord>>>();

export async function fetchContentList(
  scope: RuntimeScope | null,
  modelId: number,
  params: Record<string, any> = {}
): Promise<Paged<ContentRecord>> {
  const query = qs(params);
  const code = contentAppCode(scope);
  const key = `${code || "design"}:${modelId}:${query}`;
  const cached = listCache.get(key);
  if (cached && Date.now() - cached.at < 2000) return cached.data;
  const running = listInflight.get(key);
  if (running) return running;
  const task = (async () => {
    const result = scope && code
      ? await api.get<Paged<ContentRecord>>(`/runtime/${code}/content/${modelId}/?${query}`)
      : await api.get<Paged<ContentRecord>>(`/models/${modelId}/records/?${query}`);
    listCache.set(key, { at: Date.now(), data: result });
    if (listCache.size > 80) {
      const oldest = [...listCache.entries()].sort((a, b) => a[1].at - b[1].at)[0];
      if (oldest) listCache.delete(oldest[0]);
    }
    return result;
  })();
  listInflight.set(key, task);
  try {
    return await task;
  } finally {
    listInflight.delete(key);
  }
}

export async function fetchContentRecord(
  scope: RuntimeScope | null,
  modelId: number,
  id: number
): Promise<ContentRecord | null> {
  const code = contentAppCode(scope);
  try {
    if (scope && code) {
      return await api.get<ContentRecord>(`/runtime/${code}/content/${modelId}/${id}/`);
    }
    return await api.get<ContentRecord>(`/models/${modelId}/records/${id}/`);
  } catch {
    return null;
  }
}

export async function fetchContentBySlug(
  scope: RuntimeScope | null,
  modelId: number,
  slugField: string,
  slug: string
): Promise<Record<string, any> | null> {
  const res = await fetchContentList(scope, modelId, { [slugField]: slug, page: 1, size: 1 });
  return contentRows(res)[0] || null;
}

export function formatContentDate(value: any): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function contentText(value: any): string {
  return value === null || value === undefined ? "" : String(value);
}
