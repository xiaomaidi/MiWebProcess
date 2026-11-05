/**
 * 区块版本差异的只读预览构建器（纯函数，无 DOM / store 依赖）。
 *
 * 后端版本快照为 `{rootId, nodes}`（与 BlockSchema 一致）；差异接口只返回
 * added / removed / changed 行，不包含快照，所以组件会额外拉取 from/to 版本
 * 详情再交给本模块。本模块把快照压平成可渲染的层级行，并计算自由布局节点
 * 在迷你画布中的等比坐标。所有输出都有界（默认每侧 200 个节点），避免大
 * 区块拖慢版本弹窗。
 */
export type DiffStatus = "added" | "removed" | "changed" | "unchanged";
export type DiffSide = "from" | "to";

export interface NodeLayout {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 版本快照里的节点：只读取展示需要的字段，其余保持透明。 */
export interface SnapshotNode {
  id?: string;
  type?: string;
  props?: Record<string, unknown>;
  children?: string[];
  slots?: Record<string, string[]>;
  layout?: NodeLayout | null;
  [key: string]: unknown;
}

export interface BlockSnapshot {
  rootId?: string;
  nodes?: Record<string, SnapshotNode>;
}

export interface PreviewNode {
  id: string;
  type: string;
  label: string;
  status: DiffStatus;
  depth: number;
  parentId: string | null;
  /** 来自 slots 时的插槽名。 */
  slot: string | null;
  /** 不在 rootId 子树内（快照里的未挂载节点）。 */
  orphan: boolean;
  /** 节点自身的 layout（仅自由布局）。 */
  layout: NodeLayout | null;
  /** 累加祖先 layout 偏移后的绝对 layout（迷你画布定位用）。 */
  absoluteLayout: NodeLayout | null;
}

export interface PreviewTree {
  rows: PreviewNode[];
  /** 快照 nodes 总数（未截断时等于 rows.length）。 */
  rawCount: number;
  /** 是否因为渲染上限而丢弃了节点。 */
  truncated: boolean;
  /** 是否按自由布局绘制（多个定位节点，或单节点自身有 layout）。 */
  free: boolean;
  /** 带 layout 的节点数。 */
  positioned: number;
  unpositioned: number;
}

export interface PreviewCanvas {
  width: number;
  height: number;
  /** 画布内边距（逻辑像素）。 */
  padding: number;
}

export interface PreviewBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PreviewBox {
  node: PreviewNode;
  /** 以下均为画布逻辑坐标（0..canvas.width / height）。 */
  left: number;
  top: number;
  width: number;
  height: number;
  /** 盒子足够大时才显示文字，避免小盒子里文字溢出。 */
  showLabel: boolean;
}

export interface PreviewGeometry {
  boxes: PreviewBox[];
  bounds: PreviewBounds | null;
  scale: number;
}

/** 每侧最多渲染的节点数。 */
export const PREVIEW_NODE_LIMIT = 200;

/** 迷你画布逻辑尺寸；组件按 340 / 240 的宽高比等比缩放。 */
export const PREVIEW_CANVAS: PreviewCanvas = { width: 340, height: 240, padding: 10 };

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    if (typeof item === "string" && item) out.push(item);
  }
  return out;
}

function slotMap(value: unknown): Record<string, string[]> {
  if (!isRecord(value)) return {};
  const out: Record<string, string[]> = {};
  for (const [name, ids] of Object.entries(value)) {
    const list = stringList(ids);
    if (list.length) out[name] = list;
  }
  return out;
}

function childIds(node: SnapshotNode): string[] {
  const out = stringList(node.children);
  for (const ids of Object.values(slotMap(node.slots))) out.push(...ids);
  return out;
}

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeLayout(raw: unknown): NodeLayout | null {
  if (!isRecord(raw)) return null;
  const x = numberOrNull(raw.x);
  const y = numberOrNull(raw.y);
  const width = numberOrNull(raw.width);
  const height = numberOrNull(raw.height);
  if (x === null || y === null || width === null || height === null) return null;
  if (width <= 0 || height <= 0) return null;
  // 离谱坐标（例如导入数据错误）会让缩放后所有节点不可见，直接丢弃。
  if (Math.abs(x) > 1e7 || Math.abs(y) > 1e7 || width > 1e7 || height > 1e7) return null;
  return { x, y, width, height };
}

function typeOf(node: SnapshotNode): string {
  const type = typeof node.type === "string" ? node.type.trim() : "";
  return type || "node";
}

function clip(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** 节点展示文案：props 中常见文本字段优先，回退到组件类型。 */
export function previewNodeLabel(node: SnapshotNode | null | undefined): string {
  if (!node) return "node";
  const props = isRecord(node.props) ? node.props : {};
  for (const key of ["text", "label", "content", "title", "value", "placeholder", "alt"]) {
    const value = props[key];
    if (typeof value === "string" && value.trim()) return clip(value.trim(), 60);
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return typeOf(node);
}

function resolveRootId(
  ids: string[],
  nodes: Record<string, SnapshotNode>,
  explicit: string | undefined
): string {
  if (typeof explicit === "string" && explicit && nodes[explicit]) return explicit;
  const referenced = new Set<string>();
  for (const node of Object.values(nodes)) {
    for (const id of childIds(node)) referenced.add(id);
  }
  return ids.find((id) => !referenced.has(id)) ?? ids[0];
}

interface WalkFrame {
  id: string;
  depth: number;
  parentId: string | null;
  slot: string | null;
  baseX: number;
  baseY: number;
}

/**
 * 把版本快照压平成按前序遍历的层级行。
 *
 * - 优先从 rootId 开始；rootId 缺失时自动寻找未被引用的节点；
 * - 未被挂载的节点追加到末尾（depth=0、orphan=true），避免快照有数据却空白；
 * - 超出 limit 时停止并标记 truncated。
 */
export function buildPreviewTree(
  snapshot: BlockSnapshot | null | undefined,
  statusOf: (id: string) => DiffStatus,
  limit: number = PREVIEW_NODE_LIMIT
): PreviewTree {
  const safeLimit = Math.max(1, Math.floor(limit));
  const nodes = isRecord(snapshot?.nodes) ? (snapshot?.nodes as Record<string, SnapshotNode>) : {};
  const ids = Object.keys(nodes);
  if (!ids.length) {
    return { rows: [], rawCount: 0, truncated: false, free: false, positioned: 0, unpositioned: 0 };
  }

  const rootId = resolveRootId(ids, nodes, snapshot?.rootId);
  const rows: PreviewNode[] = [];
  const seen = new Set<string>();
  const stack: WalkFrame[] = [{ id: rootId, depth: 0, parentId: null, slot: null, baseX: 0, baseY: 0 }];

  while (stack.length && rows.length < safeLimit) {
    const frame = stack.pop();
    if (!frame || seen.has(frame.id)) continue;
    const node = nodes[frame.id];
    if (!node) continue;
    seen.add(frame.id);

    const layout = normalizeLayout(node.layout);
    const absoluteLayout = layout
      ? { x: frame.baseX + layout.x, y: frame.baseY + layout.y, width: layout.width, height: layout.height }
      : null;
    rows.push({
      id: frame.id,
      type: typeOf(node),
      label: previewNodeLabel(node),
      status: statusOf(frame.id),
      depth: frame.depth,
      parentId: frame.parentId,
      slot: frame.slot,
      orphan: false,
      layout,
      absoluteLayout,
    });

    const childBaseX = absoluteLayout ? absoluteLayout.x : frame.baseX;
    const childBaseY = absoluteLayout ? absoluteLayout.y : frame.baseY;
    const next: WalkFrame[] = [];
    for (const childId of stringList(node.children)) {
      next.push({
        id: childId,
        depth: frame.depth + 1,
        parentId: frame.id,
        slot: null,
        baseX: childBaseX,
        baseY: childBaseY,
      });
    }
    for (const [slotName, list] of Object.entries(slotMap(node.slots))) {
      for (const childId of list) {
        next.push({
          id: childId,
          depth: frame.depth + 1,
          parentId: frame.id,
          slot: slotName,
          baseX: childBaseX,
          baseY: childBaseY,
        });
      }
    }
    // 栈是后进先出：倒序压入，保持 children / slots 的声明顺序。
    for (let i = next.length - 1; i >= 0; i -= 1) stack.push(next[i]);
  }

  if (rows.length < safeLimit) {
    for (const id of ids) {
      if (rows.length >= safeLimit) break;
      if (seen.has(id)) continue;
      const node = nodes[id];
      if (!node) continue;
      seen.add(id);
      const layout = normalizeLayout(node.layout);
      rows.push({
        id,
        type: typeOf(node),
        label: previewNodeLabel(node),
        status: statusOf(id),
        depth: 0,
        parentId: null,
        slot: null,
        orphan: true,
        layout,
        absoluteLayout: layout ? { ...layout } : null,
      });
    }
  }

  const positioned = rows.reduce((count, row) => count + (row.absoluteLayout ? 1 : 0), 0);
  return {
    rows,
    rawCount: ids.length,
    truncated: ids.length > rows.length,
    // 仅一个带 layout 的容器 + 一堆流式子节点时，画布只会剩一个大盒子，
    // 缩进流程反而更能表达层级；真正的自由布局通常有多个定位节点。
    free: positioned >= 2 || (positioned === 1 && rows.length === 1),
    positioned,
    unpositioned: rows.length - positioned,
  };
}

/**
 * 把带 absoluteLayout 的节点等比缩放并居中到迷你画布，返回逻辑坐标盒子。
 * 组件再把逻辑坐标换算成百分比，从而在任意面板宽度下保持比例一致。
 */
export function fitPreviewLayout(
  rows: PreviewNode[],
  canvas: PreviewCanvas = PREVIEW_CANVAS
): PreviewGeometry {
  const positioned = rows.filter((row): row is PreviewNode & { absoluteLayout: NodeLayout } =>
    !!row.absoluteLayout
  );
  if (!positioned.length) return { boxes: [], bounds: null, scale: 0 };

  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const row of positioned) {
    const layout = row.absoluteLayout;
    minX = Math.min(minX, layout.x);
    minY = Math.min(minY, layout.y);
    maxX = Math.max(maxX, layout.x + layout.width);
    maxY = Math.max(maxY, layout.y + layout.height);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY) || !Number.isFinite(maxX) || !Number.isFinite(maxY)) {
    return { boxes: [], bounds: null, scale: 0 };
  }

  const bounds: PreviewBounds = {
    x: minX,
    y: minY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY),
  };
  const innerWidth = Math.max(1, canvas.width - canvas.padding * 2);
  const innerHeight = Math.max(1, canvas.height - canvas.padding * 2);
  const scale = Math.min(innerWidth / bounds.width, innerHeight / bounds.height);
  if (!Number.isFinite(scale) || scale <= 0) return { boxes: [], bounds: null, scale: 0 };

  const offsetX = canvas.padding + (innerWidth - bounds.width * scale) / 2 - bounds.x * scale;
  const offsetY = canvas.padding + (innerHeight - bounds.height * scale) / 2 - bounds.y * scale;

  const boxes: PreviewBox[] = positioned.map((row) => {
    const layout = row.absoluteLayout;
    const width = Math.max(2, layout.width * scale);
    const height = Math.max(2, layout.height * scale);
    return {
      node: row,
      left: offsetX + layout.x * scale,
      top: offsetY + layout.y * scale,
      width,
      height,
      showLabel: width >= 42 && height >= 16,
    };
  });

  return { boxes, bounds, scale };
}

