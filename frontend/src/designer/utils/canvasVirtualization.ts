/**
 * 画布大页面虚拟化：可见节点几何计算（纯函数）。
 *
 * 设计约束：
 * - 不依赖 Vue / DOM / Pinia，便于在 Node selftest 中直接验证（见 canvasVirtualization.selftest.mts）；
 * - 只负责「哪些节点可以留在渲染 map 里」，不修改 schema、不删除 DOM；
 * - 节点 layout 是相对父节点的，这里沿 children / slots 反向建立父链并累加得到绝对坐标；
 * - 位置未知（无 layout / layout 非法）的节点一律保留：无法证明它在视口外，就不能裁。
 *
 * 裁撤规则（保守优先）：
 * 1. 与「视口 + overscan」相交的节点及其整条祖先链必定保留；
 * 2. 无 layout 的节点、命名插槽子节点、选中节点及其祖先必定保留；
 * 3. 叶子节点在视口外可裁；
 * 4. 容器节点只有在「顶层」（画布根的直接子节点 / 无父节点）且整棵子树都在视口外时才可整棵裁撤；
 *    非顶层容器永不裁撤，避免卸载深层祖先容器导致布局/交互异常。
 */

import type { SchemaNode } from "@/types";
import type { Rect } from "./layout";

export type CanvasLayoutMode = "flow" | "free";

/** 自由布局（绝对定位）节点数超过该阈值启用 DOM 裁剪：不参与文档流，裁剪不影响布局。 */
export const FREE_LAYOUT_VIRTUALIZE_THRESHOLD = 300;

/** 流式布局节点数超过该阈值启用 content-visibility 兜底：不删 DOM，用占位尺寸跳过视口外渲染。 */
export const FLOW_LAYOUT_CONTAINMENT_THRESHOLD = 500;

/** 视口四周额外预渲染的页面逻辑像素（会按 zoom 换算，保持约 480 屏幕像素）。 */
export const DEFAULT_OVERSCAN = 480;

/** 视口量化格（页面逻辑像素）：滚动跨越格子才重算节点集合，减少 NodeRenderer 重渲染。 */
export const VIEWPORT_CELL = 256;

/** 参与计算的节点字段（SchemaNode 的结构子集）。 */
export type NodeLike = Pick<SchemaNode, "type" | "children" | "slots" | "layout">;

export type NodeMap = Record<string, NodeLike>;

export interface VirtualizationPlan {
  /** 参与判定的节点数（含画布根）。 */
  nodeCount: number;
  layoutMode: CanvasLayoutMode;
  active: boolean;
  /** none：不处理；contain：content-visibility 兜底；cull：从渲染 map 中裁掉视口外节点。 */
  strategy: "none" | "contain" | "cull";
  threshold: number;
}

export interface VisibleNodeResult {
  /** 保留在渲染 map 中的节点 id（= 全部节点 - culledIds）。 */
  visible: Set<string>;
  /** 被裁掉的节点 id（含被裁顶层容器的整棵子树），升序，便于稳定比较与 HUD 计数。 */
  culledIds: string[];
  /** 被裁节点数（= culledIds.length）。 */
  culledCount: number;
  /** 参与判定的节点总数。 */
  total: number;
  /** 与扩展视口直接相交的节点数（祖先保护前）。 */
  hitCount: number;
  /** 扩展后的视口矩形（页面逻辑坐标，便于调试）。 */
  expanded: Rect;
}

export interface NodeTreeIndex {
  ids: string[];
  parentOf: Map<string, string | null>;
  childrenOf: Map<string, string[]>;
}

function isFiniteRect(rect: unknown): rect is Rect {
  if (!rect || typeof rect !== "object") return false;
  const r = rect as Rect;
  return (
    Number.isFinite(r.x) && Number.isFinite(r.y) && Number.isFinite(r.width) && Number.isFinite(r.height)
  );
}

function rectsIntersect(a: Rect, b: Rect): boolean {
  return (
    a.x <= b.x + b.width &&
    a.x + a.width >= b.x &&
    a.y <= b.y + b.height &&
    a.y + a.height >= b.y
  );
}

/** 节点的直接子节点 id（children + 所有槽位，去重前保持顺序）。 */
export function childIdsOf(node: NodeLike | null | undefined): string[] {
  if (!node) return [];
  const out: string[] = [];
  if (Array.isArray(node.children)) out.push(...node.children);
  for (const list of Object.values(node.slots || {})) {
    if (Array.isArray(list)) out.push(...list);
  }
  return out;
}

/**
 * 建立 id → 父 id / 子 id 索引。
 * - 同一节点被多个父引用时以第一条为准（与 schema 树的渲染顺序一致）；
 * - 自引用直接丢弃，环由绝对坐标的 seen 集合兜底。
 */
export function buildNodeTree(nodes: NodeMap): NodeTreeIndex {
  const ids = Object.keys(nodes);
  const parentOf = new Map<string, string | null>();
  const childrenOf = new Map<string, string[]>();
  for (const id of ids) {
    parentOf.set(id, null);
    childrenOf.set(id, []);
  }
  for (const id of ids) {
    for (const child of childIdsOf(nodes[id])) {
      if (child === id || !nodes[child]) continue;
      if (parentOf.get(child) !== null) continue;
      parentOf.set(child, id);
      childrenOf.get(id)!.push(child);
    }
  }
  return { ids, parentOf, childrenOf };
}

/**
 * 计算每个节点在页面坐标系中的绝对矩形：own.layout + 所有祖先 layout 偏移。
 *
 * 只有当「自身到画布根之间的每个非根祖先都有合法 layout」时才返回矩形；
 * 画布根（wp-canvas）即页面原点，不参与偏移。祖先没有 layout 意味着它仍处于
 * 文档流中，DOM 位置无法由 schema 推出，因此返回 null（调用方必须保守保留）。
 */
export function computeAbsoluteRects(
  nodes: NodeMap,
  parentOf: Map<string, string | null>
): Map<string, Rect | null> {
  const memo = new Map<string, Rect | null>();

  const resolve = (id: string): Rect | null => {
    const cached = memo.get(id);
    if (cached !== undefined) return cached;
    // 画布根自身由 canvasStyle 定位，layout 不参与渲染。
    if (nodes[id]?.type === "wp-canvas") {
      memo.set(id, null);
      return null;
    }
    const own = nodes[id]?.layout;
    let out: Rect | null = null;
    if (isFiniteRect(own)) {
      let x = own.x;
      let y = own.y;
      let cur = parentOf.get(id) ?? null;
      const seen = new Set<string>([id]);
      let positioned = true;
      while (cur && !seen.has(cur)) {
        seen.add(cur);
        const parent = nodes[cur];
        if (!parent) {
          positioned = false;
          break;
        }
        if (parent.type === "wp-canvas") break; // 画布根 = 页面原点
        // 设计态的 conditional 不渲染定位 wrapper（子节点直接铺在父级流里），layout 不生效。
        if (parent.type === "conditional") {
          positioned = false;
          break;
        }
        if (!isFiniteRect(parent.layout)) {
          positioned = false;
          break;
        }
        x += parent.layout.x;
        y += parent.layout.y;
        cur = parentOf.get(cur) ?? null;
      }
      if (positioned) out = { x, y, width: own.width, height: own.height };
    }
    memo.set(id, out);
    return out;
  };

  for (const id of Object.keys(nodes)) resolve(id);
  return memo;
}

/** 顶层节点：画布根（wp-canvas）的直接子节点，或无父节点（孤立根）。 */
function isTopLevelNode(id: string, parentOf: Map<string, string | null>, nodes: NodeMap): boolean {
  const parent = parentOf.get(id) ?? null;
  if (!parent) return true;
  return nodes[parent]?.type === "wp-canvas";
}

/**
 * 视口量化：向外取整到 cell 网格，避免滚动每个像素都重建渲染节点集合。
 * 返回的矩形一定完整包含传入视口。
 */
export function quantizeViewport(viewport: Rect, cell: number = VIEWPORT_CELL): Rect {
  const size = Number.isFinite(cell) && cell > 0 ? cell : VIEWPORT_CELL;
  const left = Math.floor(viewport.x / size) * size;
  const top = Math.floor(viewport.y / size) * size;
  const right = Math.ceil((viewport.x + viewport.width) / size) * size;
  const bottom = Math.ceil((viewport.y + viewport.height) / size) * size;
  return {
    x: left,
    y: top,
    width: Math.max(size, right - left),
    height: Math.max(size, bottom - top),
  };
}

/** 节点数 + 布局模式 → 虚拟化策略（阈值集中在这里，便于调整）。 */
export function planVirtualization(nodeCount: number, layoutMode: CanvasLayoutMode): VirtualizationPlan {
  const count = Number.isFinite(nodeCount) ? Math.max(0, Math.floor(nodeCount)) : 0;
  if (layoutMode === "flow") {
    const active = count > FLOW_LAYOUT_CONTAINMENT_THRESHOLD;
    return {
      nodeCount: count,
      layoutMode,
      active,
      strategy: active ? "contain" : "none",
      threshold: FLOW_LAYOUT_CONTAINMENT_THRESHOLD,
    };
  }
  const active = count > FREE_LAYOUT_VIRTUALIZE_THRESHOLD;
  return {
    nodeCount: count,
    layoutMode,
    active,
    strategy: active ? "cull" : "none",
    threshold: FREE_LAYOUT_VIRTUALIZE_THRESHOLD,
  };
}

/**
 * 计算需要保留在渲染 map 中的节点。
 *
 * @param nodes      当前渲染用的节点表（调用方已应用多端 layout 覆盖）
 * @param viewport   可见画布区域（页面逻辑坐标，未乘 zoom）
 * @param overscan   四周额外预渲染的页面逻辑像素
 * @param selectedIds 选中节点：无论是否在视口内都必须挂载（含其祖先链）
 */
export function computeVisibleNodeIds(
  nodes: NodeMap,
  viewport: Rect,
  overscan: number = DEFAULT_OVERSCAN,
  selectedIds: Iterable<string> = []
): VisibleNodeResult {
  const tree = buildNodeTree(nodes);
  const absolute = computeAbsoluteRects(nodes, tree.parentOf);
  const total = tree.ids.length;
  const pad = Number.isFinite(overscan) && overscan > 0 ? Math.min(overscan, 100000) : 0;
  const expanded: Rect = {
    x: viewport.x - pad,
    y: viewport.y - pad,
    width: viewport.width + pad * 2,
    height: viewport.height + pad * 2,
  };

  const viewportReady = isFiniteRect(viewport) && viewport.width > 0 && viewport.height > 0;
  if (!viewportReady) {
    // 首帧 / 画布隐藏 / 尺寸为 0：不做裁剪，避免误伤整页。
    return {
      visible: new Set(tree.ids),
      culledIds: [],
      culledCount: 0,
      total,
      hitCount: 0,
      expanded,
    };
  }

  const keep = new Set<string>();
  const keepChain = (id: string) => {
    let cur: string | null = id;
    const seen = new Set<string>();
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      keep.add(cur);
      cur = tree.parentOf.get(cur) ?? null;
    }
  };

  // 画布根 / 孤立根始终保留（根节点通常没有 layout）。
  for (const id of tree.ids) {
    if (!tree.parentOf.get(id)) keepChain(id);
  }

  // 1) 与扩展视口相交的节点 → 保留整条祖先链（容器永远不因祖先被裁而卸载）。
  let hitCount = 0;
  for (const id of tree.ids) {
    const rect = absolute.get(id) ?? null;
    if (!rect) continue;
    if (rectsIntersect(rect, expanded)) {
      hitCount += 1;
      keepChain(id);
    }
  }

  // 2) 位置未知的节点：保守保留（通常是无 layout 的流内节点）。
  for (const id of tree.ids) {
    if (!absolute.get(id)) keepChain(id);
  }

  // 3) 选中节点（多选 / 框选 / 拖动中）必须始终挂载。
  for (const id of selectedIds) {
    if (nodes[id]) keepChain(id);
  }

  // 4) 命名插槽子节点是父组件渲染协议的一部分（如表格列 / 标签页），不参与裁剪。
  for (const node of Object.values(nodes)) {
    const slots = node?.slots;
    if (!slots) continue;
    for (const [name, list] of Object.entries(slots)) {
      if (name === "default" || !Array.isArray(list)) continue;
      for (const child of list) if (nodes[child]) keepChain(child);
    }
  }

  // 5) 只裁「视口外叶子」和「整棵子树都在视口外的顶层容器」。
  const culled = new Set<string>();
  for (const id of tree.ids) {
    if (keep.has(id)) continue;
    if (!absolute.get(id)) continue;
    // conditional 没有定位 wrapper，其 layout 与实际 DOM 无关，永不作为裁剪起点。
    if (nodes[id]?.type === "conditional") continue;
    const children = tree.childrenOf.get(id) ?? [];
    if (children.length && !isTopLevelNode(id, tree.parentOf, nodes)) continue;
    culled.add(id);
  }

  // 6) 被裁顶层容器的整棵子树都不会挂载，计入裁剪数（HUD 数值才准确）。
  const stack = [...culled];
  while (stack.length) {
    const id = stack.pop()!;
    for (const child of tree.childrenOf.get(id) ?? []) {
      if (culled.has(child) || keep.has(child)) continue;
      culled.add(child);
      stack.push(child);
    }
  }

  const culledIds = [...culled].sort();
  const visible = new Set(tree.ids.filter((id) => !culled.has(id)));
  return { visible, culledIds, culledCount: culledIds.length, total, hitCount, expanded };
}
