/**
 * 可复用页面区块（PageBlock）前端 API 与 schema 工具。
 *
 * 与后端 pages/block_urls.py 对应：
 * - GET/POST  /api/apps/{app_id}/blocks/
 * - GET/PATCH/DELETE /api/blocks/{id}/
 * - GET       /api/runtime/{app_code}/blocks/{code}/
 *
 * 本文件只负责数据访问与纯函数，不依赖设计器 store，便于 wp-block 渲染器与
 * BlockLibrary / 集成方共用。
 */
import { api, apiBase, getToken } from "@/api";
import type { PageSchema, SchemaNode } from "@/types";

/** 区块 schema：节点子树（rootId + nodes），与后端约定一致。 */
export interface BlockSchema {
  rootId: string;
  nodes: Record<string, SchemaNode>;
}

export interface BindingPageBrief {
  id: number;
  name: string;
  path: string;
  type: string;
  status: string;
  version: number;
}

export interface BlockSummary {
  id: number;
  app_id: number;
  name: string;
  code: string;
  description: string;
  page_id: number | null;
  version: number;
  created_by_id: number | null;
  created_at: string;
  updated_at: string;
}

export interface BlockDetail extends BlockSummary {
  schema: BlockSchema;
  root_id: string;
  node_count: number;
  backing_page: BindingPageBrief | null;
}

export interface BlockListPage {
  count: number;
  results: BlockSummary[];
  page: number;
  size: number;
}

export interface BlockCreatePayload {
  name: string;
  code?: string;
  description?: string;
  /** 从指定页面的选区节点拷贝（与 node_ids 搭配）。 */
  source_page_id?: number;
  node_ids?: string[];
  /** 直接提供 {rootId, nodes} 子树。 */
  source_nodes?: BlockSchema;
}

export interface BlockCreateResult {
  block: BlockDetail;
  page: BindingPageBrief | null;
  warnings: string[];
}

export interface BlockUpdatePayload {
  name?: string;
  code?: string;
  description?: string;
  schema?: BlockSchema;
}

export interface RuntimeBlockResult {
  code: string;
  name: string;
  version: number;
  app: { id: number; code: string; name: string };
  rootId: string;
  nodes: Record<string, SchemaNode>;
  schema: BlockSchema;
  draft: boolean;
  published: boolean;
  node_count: number;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// CRUD
// ---------------------------------------------------------------------------
export async function listBlocks(
  appId: number,
  opts: { search?: string; page?: number; size?: number } = {}
): Promise<BlockListPage> {
  const params = new URLSearchParams();
  if (opts.search) params.set("search", opts.search);
  params.set("page", String(opts.page || 1));
  params.set("size", String(opts.size || 50));
  return api.get<BlockListPage>(`/apps/${appId}/blocks/?${params.toString()}`);
}

export async function getBlock(blockId: number): Promise<BlockDetail> {
  const data = await api.get<{ block: BlockDetail }>(`/blocks/${blockId}/`);
  return data.block;
}

export async function createBlock(appId: number, payload: BlockCreatePayload): Promise<BlockCreateResult> {
  return api.post<BlockCreateResult>(`/apps/${appId}/blocks/`, payload);
}

export async function updateBlock(blockId: number, payload: BlockUpdatePayload): Promise<BlockDetail> {
  const data = await api.patch<{ block: BlockDetail; warnings: string[] }>(`/blocks/${blockId}/`, payload);
  return data.block;
}

export interface DeleteBlockResult {
  detail: string;
  page_id: number | null;
  page_archived: boolean;
  page_deleted: boolean;
}

/**
 * 删除区块。默认只归档承载页面（不丢设计稿）；只有显式 deletePage=true
 * 才会删除 `__blocks__/<code>` 下的 fragment 页面（后端还会校验引用）。
 */
export async function deleteBlock(blockId: number, deletePage = false): Promise<DeleteBlockResult> {
  const suffix = deletePage ? "?delete_page=true" : "";
  return api.del<DeleteBlockResult>(`/blocks/${blockId}/${suffix}`);
}

// ---------------------------------------------------------------------------
// 运行时读取（匿名可用，不触发登录跳转）
// ---------------------------------------------------------------------------
/** 已发布区块的短缓存：同一页面多个实例共享一次请求。 */
const runtimeCache = new Map<string, { at: number; value: RuntimeBlockResult }>();
const RUNTIME_CACHE_TTL = 30_000;

export async function fetchRuntimeBlock(
  appCode: string,
  code: string,
  opts: { draft?: boolean; silent?: boolean } = {}
): Promise<RuntimeBlockResult> {
  const params = new URLSearchParams();
  if (opts.draft) params.set("draft", "1");
  const cacheKey = `${appCode}/${code}${opts.draft ? "?draft" : ""}`;
  if (!opts.draft) {
    const hit = runtimeCache.get(cacheKey);
    if (hit && Date.now() - hit.at < RUNTIME_CACHE_TTL) return hit.value;
  }
  const url = `${apiBase()}/api/runtime/${encodeURIComponent(appCode)}/blocks/${encodeURIComponent(
    code
  )}/${params.size ? `?${params.toString()}` : ""}`;
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  let resp: Response;
  try {
    resp = await fetch(url, { headers });
  } catch {
    throw new Error("网络错误，无法加载区块");
  }
  if (!resp.ok) {
    let message = resp.status === 404 ? "区块不存在或尚未发布" : `区块加载失败（${resp.status}）`;
    try {
      const data = await resp.json();
      if (typeof data?.detail === "string") message = data.detail;
    } catch {
      /* ignore */
    }
    const error = new Error(message) as Error & { status?: number };
    error.status = resp.status;
    throw error;
  }
  const value = (await resp.json()) as RuntimeBlockResult;
  if (!opts.draft) runtimeCache.set(cacheKey, { at: Date.now(), value });
  return value;
}

// ---------------------------------------------------------------------------
// 集成辅助
// ---------------------------------------------------------------------------
/**
 * 从当前页面的选区节点创建区块（供 BlockLibrary 或右键菜单使用）。
 * 后端会创建 `__blocks__/<code>` 的 fragment 承载页面，区块可直接在设计器编辑。
 */
export async function createBlockFromCurrentPage(
  appId: number,
  pageId: number,
  nodeIds: string[],
  name: string,
  opts: { code?: string; description?: string } = {}
): Promise<BlockCreateResult> {
  return createBlock(appId, {
    name,
    code: opts.code,
    description: opts.description,
    source_page_id: pageId,
    node_ids: nodeIds.filter(Boolean),
  });
}

/** 选区 id 过滤：去掉缺失/画布根，保留调用方顺序并去重。 */
export function normalizeSelectedIds(schema: PageSchema | null | undefined, ids: string[]): string[] {
  if (!schema) return [];
  const out: string[] = [];
  for (const id of ids || []) {
    if (!id || id === schema.rootId || !schema.nodes?.[id]) continue;
    if (!out.includes(id)) out.push(id);
  }
  return out;
}

/** 生成 wp-block 引用节点（插入页面 schema 用；调用方负责写入 store）。 */
export function buildBlockReferenceNode(
  block: Pick<BlockSummary, "id" | "code" | "name">,
  opts: { id?: string; componentVersion?: string } = {}
): SchemaNode {
  const id = opts.id || `blkref-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  return {
    id,
    type: "wp-block",
    componentVersion: opts.componentVersion || "1.0.0",
    props: {
      blockCode: block.code,
      blockId: block.id,
      blockName: block.name,
    },
    children: [],
  };
}

/**
 * 给区块子树内所有节点 id 加实例前缀并重写 children/slots 引用。
 * 渲染时每个 wp-block 实例独立前缀，避免多实例之间、以及与页面节点之间的 id 冲突。
 */
export function prefixBlockSchema(schema: BlockSchema | null | undefined, prefix: string): BlockSchema {
  if (!schema || !schema.rootId || !schema.nodes) return { rootId: "", nodes: {} };
  const mapping: Record<string, string> = {};
  for (const id of Object.keys(schema.nodes)) mapping[id] = `${prefix}${id}`;
  const nodes: Record<string, SchemaNode> = {};
  for (const [oldId, node] of Object.entries(schema.nodes)) {
    const clone: SchemaNode = JSON.parse(JSON.stringify(node));
    clone.id = mapping[oldId] || oldId;
    clone.children = (node.children || []).map((cid) => mapping[cid]).filter(Boolean);
    if (node.slots && Object.keys(node.slots).length) {
      clone.slots = {};
      for (const [name, ids] of Object.entries(node.slots)) {
        const mapped = (ids || []).map((cid) => mapping[cid]).filter(Boolean);
        if (mapped.length) clone.slots[name] = mapped;
      }
    }
    nodes[clone.id] = clone;
  }
  return { rootId: mapping[schema.rootId] || "", nodes };
}

/** 按 code 精确查找区块（列表接口只返回摘要，命中后再取详情拿 schema）。 */
export async function findBlockByCode(appId: number, code: string): Promise<BlockDetail | null> {
  if (!appId || !code) return null;
  const page = await listBlocks(appId, { search: code, size: 100 });
  const hit = (page.results || []).find((item) => item.code === code);
  if (!hit) return null;
  return getBlock(hit.id);
}
