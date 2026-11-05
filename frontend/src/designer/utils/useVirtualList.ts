/**
 * 大纲虚拟滚动组合式函数。
 *
 * 职责：
 * - 维护 scrollTop / 视口高度，输出可见区间（computeVirtualRange）；
 * - 自动测量“面板剩余可用高度”，让虚拟视口恰好填满侧边栏，避免双滚动条；
 * - 提供 scrollToIndex，供键盘上下移动时把目标行滚入窗口。
 *
 * 注意：测量基于最近的可滚动祖先（设计器左侧 el-tabs__content），
 * 标签页隐藏时保留上次高度，重新显示后由 ResizeObserver 再测。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type ComputedRef, type Ref } from "vue";
import { clampScrollTop, computeVirtualRange, OUTLINE_OVERSCAN, type VirtualRange } from "./virtualList";

export interface UseVirtualListOptions {
  /** 总行数（getter，保持对 Pinia 计算属性的响应式）。 */
  count: () => number;
  /** 固定行高（px）。 */
  rowHeight: number;
  /** 上下额外渲染行数，默认 OUTLINE_OVERSCAN。 */
  overscan?: number;
  /** 是否启用固定高度虚拟窗口；false 时列表按内容自然撑开（仅同步 scrollTop）。 */
  enabled: () => boolean;
  /** 视口最小高度（px），避免面板过矮时窗口塌陷。 */
  minViewportHeight?: number;
  /** 视口底部与面板底部的留白（px）。 */
  bottomGap?: number;
}

export interface UseVirtualListResult {
  /** 当前滚动偏移（px）。 */
  scrollTop: Ref<number>;
  /** 虚拟视口高度（px），用于绑定 style.height。 */
  viewportHeight: Ref<number>;
  /** 可见区间。 */
  range: ComputedRef<VirtualRange>;
  /** 滚动事件处理器（模板上用 @scroll.passive）。 */
  onScroll: (event: Event) => void;
  /** 重新测量可用高度（布局变化后由 ResizeObserver 自动调用）。 */
  measure: () => void;
  /** 把第 index 行滚入视口（不改变选择）。 */
  scrollToIndex: (index: number) => void;
  /** 把滚动的实际值写回响应式状态并夹取越界位置。 */
  syncScroll: () => void;
}

const DEFAULT_VIEWPORT_HEIGHT = 320;
const DEFAULT_MIN_VIEWPORT_HEIGHT = 160;
const DEFAULT_BOTTOM_GAP = 8;

/** 向上找第一个可滚动的祖先元素（用作可用高度基准）。 */
function findScrollParent(start: HTMLElement | null): HTMLElement | null {
  if (typeof window === "undefined" || !start) return null;
  let el: HTMLElement | null = start.parentElement;
  while (el && el !== document.body && el !== document.documentElement) {
    const style = window.getComputedStyle(el);
    const overflowY = style.overflowY;
    const scrollable = overflowY === "auto" || overflowY === "scroll" || overflowY === "overlay";
    if (scrollable && el.clientHeight > 0) return el;
    el = el.parentElement;
  }
  return null;
}

export function useVirtualList(
  viewportRef: Ref<HTMLElement | null>,
  rootRef: Ref<HTMLElement | null>,
  options: UseVirtualListOptions
): UseVirtualListResult {
  const scrollTop = ref(0);
  const viewportHeight = ref(DEFAULT_VIEWPORT_HEIGHT);
  const rowHeight = Math.max(1, options.rowHeight || 1);
  const overscan = options.overscan ?? OUTLINE_OVERSCAN;
  const minViewportHeight = options.minViewportHeight ?? DEFAULT_MIN_VIEWPORT_HEIGHT;
  const bottomGap = options.bottomGap ?? DEFAULT_BOTTOM_GAP;

  const range = computed<VirtualRange>(() =>
    computeVirtualRange({
      total: options.count(),
      rowHeight,
      scrollTop: scrollTop.value,
      viewportHeight: viewportHeight.value,
      overscan,
    })
  );

  let scrollParent: HTMLElement | null = null;
  let resizeObserver: ResizeObserver | null = null;
  let measureRaf = 0;
  const observed = new Set<Element>();

  function observe(target: Element | null): void {
    if (!resizeObserver || !target || observed.has(target)) return;
    observed.add(target);
    resizeObserver.observe(target);
  }

  /** 把测量推迟到下一帧，避免在 ResizeObserver 回调里同步改尺寸触发循环告警。 */
  function scheduleMeasure(): void {
    if (measureRaf) return;
    measureRaf = window.requestAnimationFrame(() => {
      measureRaf = 0;
      measure();
    });
  }

  function measure(): void {
    const root = rootRef.value;
    const viewport = viewportRef.value;
    if (!root || !viewport) return;
    // 标签页隐藏（display:none）时 getClientRects() 为空，保留上次测量值。
    if (root.getClientRects().length === 0) return;
    if (!scrollParent) scrollParent = findScrollParent(viewport);
    observe(scrollParent);

    const viewportRect = viewport.getBoundingClientRect();
    let available: number;
    if (scrollParent) {
      const parentRect = scrollParent.getBoundingClientRect();
      if (parentRect.height <= 0) return;
      // 用“面板底边 - 视口顶边”算剩余空间：面板已经滚动时也保持底部对齐；
      // 再以面板自身高度封顶，避免视口比面板还高造成滚动反馈。
      const visible = Math.min(parentRect.height, parentRect.bottom - viewportRect.top);
      available = visible - bottomGap;
    } else if (typeof window !== "undefined") {
      available = window.innerHeight - viewportRect.top - bottomGap;
    } else {
      return;
    }
    const next = Math.max(minViewportHeight, Math.floor(available));
    if (next !== viewportHeight.value) viewportHeight.value = next;
  }

  function onScroll(event: Event): void {
    const el = event.target as HTMLElement | null;
    if (el) scrollTop.value = el.scrollTop;
  }

  function syncScroll(): void {
    const el = viewportRef.value;
    if (!el) return;
    const viewport = options.enabled() ? viewportHeight.value : el.clientHeight;
    const next = clampScrollTop(el.scrollTop, options.count(), rowHeight, viewport);
    if (next !== el.scrollTop) el.scrollTop = next;
    if (scrollTop.value !== next) scrollTop.value = next;
  }

  function scrollToIndex(index: number): void {
    if (!options.enabled()) return;
    const el = viewportRef.value;
    if (!el) return;
    const total = options.count();
    if (total <= 0) return;
    const target = Math.max(0, Math.min(total - 1, Math.floor(index)));
    const top = target * rowHeight;
    const bottom = top + rowHeight;
    const viewH = viewportHeight.value;
    let next = el.scrollTop;
    if (top < next) next = top;
    else if (bottom > next + viewH) next = bottom - viewH;
    if (next !== el.scrollTop) {
      el.scrollTop = next;
      scrollTop.value = next;
    }
  }

  watch(options.count, () => {
    // 行数变化（删除节点 / 切换页面）后滚动位置可能越界，下一帧重新夹取并测量。
    void nextTick(() => {
      syncScroll();
      measure();
    });
  });

  watch(
    () => options.enabled(),
    (enabled) => {
      if (enabled) {
        void nextTick(() => {
          measure();
          syncScroll();
        });
      }
    }
  );

  onMounted(() => {
    if (typeof window === "undefined") return;
    scrollParent = findScrollParent(viewportRef.value);
    if (typeof ResizeObserver !== "undefined") {
      resizeObserver = new ResizeObserver(() => scheduleMeasure());
      observe(rootRef.value);
      observe(scrollParent);
    }
    window.addEventListener("resize", scheduleMeasure);
    scheduleMeasure();
    syncScroll();
  });

  onBeforeUnmount(() => {
    if (measureRaf) window.cancelAnimationFrame(measureRaf);
    measureRaf = 0;
    resizeObserver?.disconnect();
    resizeObserver = null;
    observed.clear();
    if (typeof window !== "undefined") window.removeEventListener("resize", scheduleMeasure);
  });

  return { scrollTop, viewportHeight, range, onScroll, measure, scrollToIndex, syncScroll };
}
