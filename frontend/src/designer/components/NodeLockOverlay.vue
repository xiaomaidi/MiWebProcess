<template>
  <!--
    服务端权威的多人锁可视化层。
    - 挂载在设计态画布根节点内部（.wp-canvas），坐标与画布同域，随画布缩放。
    - 按 node.id（NodeRenderer 写到 data-wp-node）与 remoteLocks[].nodeId 一一匹配：
      只为「本身被他人锁定」的节点绘制，不会给锁定节点的祖先重复加徽章。
    - 只读：锁归属完全由 lock-session 决定，本组件不申请/释放锁。
    - pointer-events: none，拖拽/选择/删除/缩放等交互全部穿透到节点。
  -->
  <div ref="layerRef" class="wp-node-lock-layer" aria-hidden="true">
    <div
      v-for="ring in rings"
      :key="`ring-${ring.nodeId}`"
      class="wp-node-lock-ring"
      :style="ringStyle(ring)"
    />

    <div
      v-for="badge in badges"
      :key="`badge-${badge.nodeId}`"
      class="wp-node-lock-badge"
      :style="badgeStyle(badge)"
      :data-lock-user="badge.username"
    >
      <svg class="wp-node-lock-icon" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M7.5 10V7.6a4.5 4.5 0 0 1 9 0V10"
          fill="none"
          stroke="currentColor"
          stroke-width="2.6"
          stroke-linecap="round"
        />
        <rect x="4.5" y="10" width="15" height="10.4" rx="2.4" fill="currentColor" />
      </svg>
      <span class="wp-node-lock-name">{{ badge.username }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useEditorStore } from "@/store/editor";
import { useDesignerLocks, type LockInfo } from "../lock-session";

/** 与 designer/collab.ts 的 peer 配色保持一致，同一用户名在头像/徽章上同色。 */
const COLORS = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2", "#db2777", "#4f46e5"];

interface Rect {
  /** 相对画布 padding box 的本地坐标（scale 之前，与节点 CSS px 同域）。 */
  left: number;
  top: number;
  width: number;
  height: number;
  /** 节点是 display: contents 的透明包装（此时没有右上角删除按钮）。 */
  inlineHost: boolean;
}

interface Ring extends Rect {
  nodeId: string;
  color: string;
}

interface Badge extends Rect {
  nodeId: string;
  username: string;
  color: string;
  /** 同一锚点（嵌套祖先与子节点右上角重合）时向下错开的层序。 */
  stack: number;
}

const layerRef = ref<HTMLElement | null>(null);
/** 测量结果：nodeId → 节点在画布内的本地矩形。 */
const positions = ref<Record<string, Rect>>({});
/** 画布缩放比（来自 transform: scale），用于徽章反向缩放，保证任意缩放下可读。 */
const scale = ref(1);
const editor = useEditorStore();
const { remoteLocks } = useDesignerLocks();

const lockList = computed<LockInfo[]>(() => remoteLocks.value.filter((lock) => !!lock?.nodeId));
const invScale = computed(() => 1 / (scale.value > 0 ? scale.value : 1));

function colorFor(lock: LockInfo): string {
  const key = lock.username || String(lock.userId || lock.sessionId || lock.nodeId);
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) % COLORS.length;
  return COLORS[Math.abs(hash) % COLORS.length];
}

function rgba(hex: string, alpha: number): string {
  const raw = hex.replace("#", "");
  const r = Number.parseInt(raw.slice(0, 2), 16) || 0;
  const g = Number.parseInt(raw.slice(2, 4), 16) || 0;
  const b = Number.parseInt(raw.slice(4, 6), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const rings = computed<Ring[]>(() => {
  const out: Ring[] = [];
  for (const lock of lockList.value) {
    const rect = positions.value[lock.nodeId];
    if (!rect) continue;
    out.push({ ...rect, nodeId: lock.nodeId, color: colorFor(lock) });
  }
  return out;
});

const badges = computed<Badge[]>(() => {
  const out: Badge[] = [];
  for (const lock of lockList.value) {
    const rect = positions.value[lock.nodeId];
    if (!rect) continue;
    out.push({
      ...rect,
      nodeId: lock.nodeId,
      username: lock.username || `用户 ${lock.userId || "?"}`,
      color: colorFor(lock),
      stack: 0,
    });
  }
  // 锁定祖先与锁定子节点的右上角完全重合时，把后一枚徽章下移，避免看起来像重复徽章。
  const anchors = new Map<string, number>();
  for (const item of out) {
    const key = `${Math.round(item.left + item.width)}:${Math.round(item.top)}`;
    const index = anchors.get(key) ?? 0;
    anchors.set(key, index + 1);
    item.stack = index;
  }
  return out;
});

function ringStyle(ring: Ring): Record<string, string> {
  // 反向补偿缩放，让描边在 25%–200% 缩放下都保持约 1.5px 的视觉粗细。
  const width = Math.max(1, 1.5 * invScale.value);
  return {
    left: `${ring.left}px`,
    top: `${ring.top}px`,
    width: `${ring.width}px`,
    height: `${ring.height}px`,
    borderRadius: `${Math.max(2, 4 * invScale.value)}px`,
    outlineWidth: `${width}px`,
    outlineStyle: "solid",
    outlineColor: rgba(ring.color, 0.65),
    boxShadow: `0 0 0 ${Math.max(1, 2 * invScale.value)}px ${rgba(ring.color, 0.12)}`,
  };
}

function badgeStyle(badge: Badge): Record<string, string> {
  const inv = invScale.value;
  // 普通节点右上角有 18×18 的删除按钮（top/right: -9px，随画布缩放），
  // 徽章从节点顶部 +10 本地像素开始，避免选中锁定节点时视觉上压住 ×；
  // display: contents 包装没有 ×，可更贴近顶部。
  const topPad = badge.inlineHost ? 2 : 10;
  // transform 由右向左生效：先以右上角为原点 scale，再左移自身宽度，最终右上角仍钉在 (left, top)。
  return {
    left: `${badge.left + badge.width - 2 * inv}px`,
    top: `${badge.top + topPad + badge.stack * 18 * inv}px`,
    maxWidth: `${140 * inv}px`,
    background: badge.color,
    transform: `translateX(-100%) scale(${inv})`,
  };
}

function sameRects(a: Record<string, Rect>, b: Record<string, Rect>): boolean {
  const keysA = Object.keys(a);
  const keysB = Object.keys(b);
  if (keysA.length !== keysB.length) return false;
  for (const key of keysA) {
    const x = a[key];
    const y = b[key];
    if (!y) return false;
    if (x.inlineHost !== y.inlineHost) return false;
    if (
      Math.abs(x.left - y.left) > 0.5 ||
      Math.abs(x.top - y.top) > 0.5 ||
      Math.abs(x.width - y.width) > 0.5 ||
      Math.abs(x.height - y.height) > 0.5
    ) {
      return false;
    }
  }
  return true;
}

/** 以画布 padding box 为原点，量出所有被远程锁定节点在画布本地坐标系中的位置。 */
function measure(): void {
  if (typeof window === "undefined") return;
  const canvas = layerRef.value?.parentElement;
  if (!canvas) return;
  const locks = lockList.value;
  if (!locks.length) {
    if (Object.keys(positions.value).length) positions.value = {};
    return;
  }
  const canvasRect = canvas.getBoundingClientRect();
  if (canvasRect.width < 1 || canvasRect.height < 1) return;
  const nextScale = canvas.offsetWidth > 0 ? canvasRect.width / canvas.offsetWidth : 1;
  if (Number.isFinite(nextScale) && nextScale > 0) scale.value = nextScale;

  const style = window.getComputedStyle(canvas);
  const borderLeft = Number.parseFloat(style.borderLeftWidth) || 0;
  const borderTop = Number.parseFloat(style.borderTopWidth) || 0;

  if (!elementCache) elementCache = collectElements(canvas);
  const elements = elementCache;
  const next: Record<string, Rect> = {};
  for (const lock of locks) {
    const host = elements.get(lock.nodeId);
    if (!host) continue;
    const inlineHost = host.classList.contains("wp-node-inline");
    let box: HTMLElement = host;
    let rect = box.getBoundingClientRect();
    // 设计态无自定义样式的节点包在 display: contents 的 .wp-node-inline 里，
    // 它自身没有盒子，退回到真实组件根节点的盒子。
    if ((rect.width < 1 || rect.height < 1) && host.firstElementChild instanceof HTMLElement) {
      box = host.firstElementChild;
      rect = box.getBoundingClientRect();
    }
    if (rect.width < 1 || rect.height < 1) continue;
    next[lock.nodeId] = {
      left: (rect.left - canvasRect.left) / nextScale - borderLeft,
      top: (rect.top - canvasRect.top) / nextScale - borderTop,
      width: rect.width / nextScale,
      height: rect.height / nextScale,
      inlineHost,
    };
  }
  if (!sameRects(next, positions.value)) positions.value = next;
}

let rafId = 0;
let observer: MutationObserver | null = null;
let pollTimer = 0;
/** nodeId → 画布内的宿主元素；仅在子节点增删时失效，避免拖拽期间每帧全画布扫描。 */
let elementCache: Map<string, HTMLElement> | null = null;

function collectElements(canvas: HTMLElement): Map<string, HTMLElement> {
  const map = new Map<string, HTMLElement>();
  for (const el of Array.from(canvas.querySelectorAll<HTMLElement>("[data-wp-node]"))) {
    const id = el.dataset.wpNode;
    if (id && !map.has(id)) map.set(id, el);
  }
  return map;
}

function scheduleMeasure(): void {
  if (typeof window === "undefined") return;
  if (!lockList.value.length || rafId) return;
  rafId = window.requestAnimationFrame(() => {
    rafId = 0;
    measure();
  });
}

function startPolling(): void {
  if (pollTimer || typeof window === "undefined") return;
  // 兜底：节点被 head 里的样式规则隐藏/显示、图片加载等不产生画布内变更的情况。
  pollTimer = window.setInterval(scheduleMeasure, 1000);
}

function stopPolling(): void {
  if (pollTimer) window.clearInterval(pollTimer);
  pollTimer = 0;
}

watch(
  lockList,
  (list) => {
    if (list.length) startPolling();
    else stopPolling();
    if (!list.length && Object.keys(positions.value).length) positions.value = {};
    scheduleMeasure();
  },
  { flush: "post" }
);

// 画布缩放由祖先 .wp-canvas-inner 的 transform 完成，不会触发画布内的 DOM 变更，
// 因此单独监听 zoom 以刷新徽章的反向缩放系数。
watch(
  () => editor.zoom,
  () => scheduleMeasure(),
  { flush: "post" }
);

onMounted(() => {
  const layer = layerRef.value;
  const canvas = layer?.parentElement;
  if (!layer || !canvas) return;
  measure();
  if (lockList.value.length) startPolling();
  if (typeof MutationObserver !== "undefined") {
    observer = new MutationObserver((records) => {
      let relevant = false;
      for (const record of records) {
        // 徽章/描边自身的 style/增删不属于节点布局变化，忽略以免自激。
        if (layer.contains(record.target)) continue;
        if (record.type === "childList") elementCache = null;
        relevant = true;
      }
      if (relevant) scheduleMeasure();
    });
    observer.observe(canvas, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["style", "class"],
    });
  }
  window.addEventListener("resize", scheduleMeasure);
  // 捕获阶段监听，才能收到节点所在内层滚动容器的 scroll（主画布滚动时本地坐标不变）。
  window.addEventListener("scroll", scheduleMeasure, true);
});

onBeforeUnmount(() => {
  if (rafId) window.cancelAnimationFrame(rafId);
  rafId = 0;
  observer?.disconnect();
  observer = null;
  elementCache = null;
  stopPolling();
  window.removeEventListener("resize", scheduleMeasure);
  window.removeEventListener("scroll", scheduleMeasure, true);
});
</script>

<style scoped>
/*
 * 覆盖层位于 .wp-canvas 内部：随画布一起被 transform: scale()，坐标天然与节点一致。
 * z-index 9000 高于画布节点（含 .wp-node-close 的 10）与框选辅助线（20）。
 * 画布祖先 .wp-canvas-inner 的 transform 已形成独立层叠上下文，
 * 因此无论该值多大，都低于挂在 body 上、z-index 2000+ 的 Element Plus 弹窗。
 */
.wp-node-lock-layer {
  position: absolute;
  inset: 0;
  z-index: 9000;
  pointer-events: none;
  overflow: visible;
}

.wp-node-lock-ring {
  position: absolute;
  z-index: 0;
  box-sizing: border-box;
  pointer-events: none;
}

.wp-node-lock-badge {
  position: absolute;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  height: 18px;
  padding: 0 6px 0 5px;
  box-sizing: border-box;
  border: 1px solid rgba(255, 255, 255, 0.82);
  border-radius: 999px;
  color: #fff;
  font-size: 11px;
  font-weight: 600;
  line-height: 16px;
  white-space: nowrap;
  user-select: none;
  pointer-events: none;
  transform-origin: 100% 0;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.28);
}

.wp-node-lock-icon {
  flex: none;
  width: 9px;
  height: 9px;
  display: block;
}

.wp-node-lock-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
