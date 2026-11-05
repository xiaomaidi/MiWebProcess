/**
 * 虚拟列表纯函数：可见区间、overscan、滚动夹取。
 *
 * 这里刻意不依赖 Vue / DOM / Pinia，便于在 Node selftest 中直接验证，
 * 也方便大纲之外的长列表（组件库、素材等）复用。
 */

/** 大纲固定行高（px）；OutlinePanel.vue 用它给每行设置 height，虚拟计算与视觉保持一致。 */
export const OUTLINE_ROW_HEIGHT = 30;

/** 可见窗口上下各多渲染的行数，减少快速滚动时的空白闪烁。 */
export const OUTLINE_OVERSCAN = 6;

/** 大纲行数超过该阈值时启用虚拟滚动。 */
export const OUTLINE_VIRTUALIZE_THRESHOLD = 150;

/** 页面节点数超过该阈值时显示“大型页面”提示（不阻塞任何操作）。 */
export const OUTLINE_LARGE_PAGE_THRESHOLD = 500;

export interface VirtualRangeInput {
  /** 总行数。 */
  total: number;
  /** 固定行高（px）。 */
  rowHeight: number;
  /** 当前滚动偏移（px）。 */
  scrollTop: number;
  /** 滚动视口高度（px）。 */
  viewportHeight: number;
  /** 上下额外渲染的行数，默认 OUTLINE_OVERSCAN。 */
  overscan?: number;
}

export interface VirtualRange {
  /** 起始行下标（包含）。 */
  start: number;
  /** 结束行下标（不包含）。 */
  end: number;
  /** 顶部占位高度（px）。 */
  padTop: number;
  /** 底部占位高度（px）。 */
  padBottom: number;
  /** 列表内容总高度（px）。 */
  totalHeight: number;
  /** 实际渲染的行数。 */
  visibleCount: number;
}

function normalizeCount(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.floor(value);
}

function normalizeRowHeight(value: number): number {
  return Number.isFinite(value) && value > 0 ? value : 1;
}

/**
 * 把滚动偏移夹取到 [0, totalHeight - viewportHeight]。
 * 滚动越界（删除行、切换页面后）时避免窗口落在列表外。
 */
export function clampScrollTop(scrollTop: number, total: number, rowHeight: number, viewportHeight: number): number {
  const totalHeight = normalizeCount(total) * normalizeRowHeight(rowHeight);
  const viewport = Number.isFinite(viewportHeight) ? Math.max(0, viewportHeight) : 0;
  const max = Math.max(0, totalHeight - viewport);
  if (!Number.isFinite(scrollTop) || scrollTop <= 0) return 0;
  return Math.min(scrollTop, max);
}

/**
 * 计算虚拟窗口：返回可见行区间 [start, end)、上下占位高度。
 * 行为约定：
 * - 空列表返回全 0；
 * - scrollTop 超出范围时按 clampScrollTop 夹取；
 * - 即使 viewportHeight 为 0 也至少渲染一行（再加 overscan），避免布局测量前闪烁。
 */
export function computeVirtualRange(input: VirtualRangeInput): VirtualRange {
  const total = normalizeCount(input.total);
  const rowHeight = normalizeRowHeight(input.rowHeight);
  const viewportHeight = Number.isFinite(input.viewportHeight) ? Math.max(0, input.viewportHeight) : 0;
  const overscan = normalizeCount(input.overscan ?? OUTLINE_OVERSCAN);
  const totalHeight = total * rowHeight;

  if (total === 0) {
    return { start: 0, end: 0, padTop: 0, padBottom: 0, totalHeight: 0, visibleCount: 0 };
  }

  const scrollTop = clampScrollTop(input.scrollTop, total, rowHeight, viewportHeight);
  const firstVisible = Math.min(total - 1, Math.floor(scrollTop / rowHeight));
  const lastVisible = Math.max(
    firstVisible + 1,
    Math.min(total, Math.ceil((scrollTop + viewportHeight) / rowHeight))
  );

  const start = Math.max(0, firstVisible - overscan);
  const end = Math.min(total, lastVisible + overscan);

  return {
    start,
    end,
    padTop: start * rowHeight,
    padBottom: Math.max(0, (total - end) * rowHeight),
    totalHeight,
    visibleCount: end - start,
  };
}
