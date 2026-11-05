<template>
  <div class="wp-canvas-scroll" ref="scrollRef" :class="{ 'is-drag-over': dragOver }" @dragover.prevent="onDragOver" @dragleave="onDragLeave" @drop.prevent="onDrop" @click="onCanvasClick">
    <div class="wp-canvas-inner" ref="innerRef" :style="innerStyle">
      <div v-if="root" class="wp-canvas-root" :class="{ 'is-large-flow': flowContainmentActive }">
        <NodeRenderer
          :node="root"
          :nodes="canvasNodes"
          mode="design"
          :canvas-style="canvasStyle"
          :layout-mode="layoutMode"
        />
      </div>
      <div v-else class="wp-canvas-empty">尚未加载页面数据</div>

      <!-- 设计态覆盖层：智能辅助线 / 框选 / 拖动坐标反馈 -->
      <div class="wp-canvas-overlay">
        <div
          v-for="(x, i) in guides.v"
          :key="`v-${i}`"
          class="wp-guide wp-guide-v"
          :style="{ left: `${x}px` }"
        />
        <div
          v-for="(y, i) in guides.h"
          :key="`h-${i}`"
          class="wp-guide wp-guide-h"
          :style="{ top: `${y}px` }"
        />
        <div
          v-if="marquee"
          class="wp-marquee"
          :style="{ left: `${marquee.x}px`, top: `${marquee.y}px`, width: `${marquee.width}px`, height: `${marquee.height}px` }"
        />
        <div
          v-if="feedback"
          class="wp-drag-feedback"
          :style="{ left: `${feedback.x}px`, top: `${Math.max(0, feedback.y - 24)}px` }"
        >
          {{ Math.round(feedback.x) }}, {{ Math.round(feedback.y) }}
          <span class="wp-drag-feedback-size">{{ Math.round(feedback.width) }} × {{ Math.round(feedback.height) }}</span>
        </div>
      </div>
    </div>

    <!-- 大页面虚拟化指示（fixed 定位，不随画布滚动） -->
    <div
      v-if="virtualization.active && hudPosition"
      class="wp-virt-hud"
      :style="hudStyle"
      :title="virtualization.title"
      @pointerdown.stop
      @click.stop
    >
      <span class="wp-virt-hud-dot" aria-hidden="true"></span>
      <span class="wp-virt-hud-text">{{ virtualization.label }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { useEditorStore } from "@/store/editor";
import { useComponentStore } from "@/store/component";
import { useHistoryStore } from "@/store/history";
import NodeRenderer from "@/engine/NodeRenderer.vue";
import { droppedComponent, snap, withHistory, DND_NODE_MIME } from "../util";
import {
  absoluteRect,
  intersectsRect,
  snapRect,
  unionRect,
  type Rect,
  type SnapTargets,
} from "../utils/layout";
import type { SchemaNode } from "@/types";
import {
  DEFAULT_OVERSCAN,
  VIEWPORT_CELL,
  computeVisibleNodeIds,
  planVirtualization,
  quantizeViewport,
  type VisibleNodeResult,
} from "../utils/canvasVirtualization";
import { deepClone } from "@/utils";
import {
  acquire as acquireServerLock,
  isRemoteLocked,
  release as releaseServerLock,
  useLockSession,
} from "../lock-session";
import { displayNodes, layoutFor, writeLayout } from "../responsive-layout";

const schema = useSchemaStore();
const editor = useEditorStore();
const compStore = useComponentStore();
const history = useHistoryStore();
/** 服务端锁的只读视图（模块级单例，DesignerView 已负责 connect/dispose）。 */
const lockSession = useLockSession();

const scrollRef = ref<HTMLElement | null>(null);
const innerRef = ref<HTMLElement | null>(null);

const dragOver = ref(false);

function onDragOver() {
  dragOver.value = true;
}
function onDragLeave(e: DragEvent) {
  // 仅当指针真正离开画布（进入外部元素）时清除高亮
  const t = e.relatedTarget as Node | null;
  if (!t || !scrollRef.value?.contains(t)) dragOver.value = false;
}

const root = computed(() => schema.root);
const nodes = computed<Record<string, any>>(() => schema.schema?.nodes || {});
const renderNodes = computed(() => displayNodes(nodes.value, editor.device));
const layoutMode = computed<"flow" | "free">(() => schema.layoutMode);
const gridSize = editor.gridSize || 8;

const canvasStyle = computed<Record<string, string>>(() => {
  const s = schema.schema;
  const w = editor.device === "desktop" ? 1200 : editor.device === "tablet" ? 768 : 375;
  const h = s?.layout?.height || 800;
  const base: Record<string, string> = {};
  const r = root.value;
  if (r?.style) {
    for (const [k, v] of Object.entries(r.style)) if (v != null) base[k] = String(v);
  }
  return { width: `${w}px`, height: `${h}px`, ...base };
});

const pageWidth = computed(() => Number.parseFloat(canvasStyle.value.width) || 1200);
const pageHeight = computed(() => Number.parseFloat(canvasStyle.value.height) || 800);

const innerStyle = computed(() => ({
  transform: `scale(${editor.zoom})`,
  transformOrigin: "0 0",
  width: `${canvasStyle.value.width}`,
  height: `${canvasStyle.value.height}`,
}));

/** 让当前设备宽度的画布适配可用横向空间（只缩小、不放大超过 100%）。 */
function fitCanvas() {
  const el = scrollRef.value;
  if (!el) return;
  const available = Math.max(240, el.clientWidth - 56);
  const width = editor.device === "desktop" ? 1200 : editor.device === "tablet" ? 768 : 375;
  editor.setZoom(Math.min(1, Math.max(0.25, available / width)));
}
watch(() => editor.fitRequest, () => nextTick(fitCanvas));
watch(() => editor.device, () => nextTick(fitCanvas));

// ---------- 大页面虚拟化 ----------
// free 布局：从传给 NodeRenderer 的 nodes map 中移除视口外节点（绝对定位，不影响布局）。
// flow 布局：不改 DOM，只给画布根加类，用 content-visibility 跳过视口外渲染（保持布局）。
// 选中节点 / 祖先容器 / 命名插槽节点 / 无 layout 节点始终保留，见 canvasVirtualization.ts。
const viewport = ref<Rect>({ x: 0, y: 0, width: 0, height: 0 });
const hudPosition = ref<{ left: number; top: number } | null>(null);
let measureRaf = 0;

const virtualizationPlan = computed(() =>
  planVirtualization(Object.keys(renderNodes.value).length, layoutMode.value)
);

/** 以屏幕像素为基准换算 overscan：缩得越小，预渲染的页面范围越大。 */
const overscanPx = computed(() => {
  const zoom = Math.max(0.25, Math.min(3, editor.zoom || 1));
  return Math.round(Math.min(2400, Math.max(320, DEFAULT_OVERSCAN / zoom)));
});

/** 画布可见区域（页面逻辑坐标，未乘 zoom）。 */
function measureCanvasViewport(): Rect | null {
  const scroll = scrollRef.value;
  const inner = innerRef.value;
  if (!scroll || !inner) return null;
  const zoom = editor.zoom || 1;
  const width = scroll.clientWidth / zoom;
  const height = scroll.clientHeight / zoom;
  if (!(width > 0) || !(height > 0)) return null;
  const scrollRect = scroll.getBoundingClientRect();
  const innerRect = inner.getBoundingClientRect();
  const x = (scrollRect.left - innerRect.left) / zoom;
  const y = (scrollRect.top - innerRect.top) / zoom;
  if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
  return { x, y, width, height };
}

function updateHudPosition() {
  const el = scrollRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const left = rect.left + 10;
  const top = rect.bottom - 10;
  const prev = hudPosition.value;
  if (!prev || prev.left !== left || prev.top !== top) hudPosition.value = { left, top };
}

/** 测量视口（量化到网格）与 HUD 位置；scroll / resize / zoom / 节点变化后调用。 */
function measureCanvasViewportAndHud() {
  updateHudPosition();
  const raw = measureCanvasViewport();
  if (!raw) return;
  const next = quantizeViewport(raw, VIEWPORT_CELL);
  const prev = viewport.value;
  if (next.x !== prev.x || next.y !== prev.y || next.width !== prev.width || next.height !== prev.height) {
    viewport.value = next;
  }
}

function scheduleCanvasMeasure() {
  if (typeof window === "undefined") return;
  if (measureRaf) return;
  measureRaf = window.requestAnimationFrame(() => {
    measureRaf = 0;
    measureCanvasViewportAndHud();
  });
}

/** 裁剪结果；仅 free 布局超过阈值且视口已测量时计算。 */
const cullResult = computed<VisibleNodeResult | null>(() => {
  if (virtualizationPlan.value.strategy !== "cull") return null;
  const vp = viewport.value;
  if (!(vp.width > 0) || !(vp.height > 0)) return null;
  return computeVisibleNodeIds(renderNodes.value, vp, overscanPx.value, schema.selectedIds);
});

let cachedCanvasSource: Record<string, SchemaNode> | null = null;
let cachedCulledIds: string[] = [];
let cachedCanvasNodes: Record<string, SchemaNode> | null = null;

function sameIds(a: string[], b: string[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) if (a[i] !== b[i]) return false;
  return true;
}

/**
 * 传给 NodeRenderer 的节点表：free 大页面只保留可见 / 受保护节点。
 * 裁剪集合未变化时复用同一对象，避免滚动时整棵渲染树重渲染。
 */
const canvasNodes = computed<Record<string, SchemaNode>>(() => {
  const all = renderNodes.value as Record<string, SchemaNode>;
  const result = cullResult.value;
  if (!result || result.culledCount === 0) {
    cachedCanvasSource = null;
    cachedCulledIds = [];
    cachedCanvasNodes = null;
    return all;
  }
  if (cachedCanvasSource === all && cachedCanvasNodes && sameIds(cachedCulledIds, result.culledIds)) {
    return cachedCanvasNodes;
  }
  const out: Record<string, SchemaNode> = {};
  for (const id of Object.keys(all)) if (result.visible.has(id)) out[id] = all[id];
  cachedCanvasSource = all;
  cachedCulledIds = result.culledIds;
  cachedCanvasNodes = out;
  return out;
});

const flowContainmentActive = computed(() => virtualizationPlan.value.strategy === "contain");

function formatCount(value: number): string {
  return value >= 10000 ? `${Math.round(value / 100) / 10}k` : String(value);
}

const virtualization = computed(() => {
  const plan = virtualizationPlan.value;
  if (!plan.active) return { active: false, label: "", title: "" };
  if (plan.strategy === "contain") {
    return {
      active: true,
      label: `大页面 · CSS 隔离 · ${formatCount(plan.nodeCount)} 节点`,
      title: `流式布局大页面（>${plan.threshold} 节点）：对节点启用 content-visibility: auto + contain-intrinsic-size，跳过视口外渲染，但不删除 DOM，保持布局与滚动高度。`,
    };
  }
  const result = cullResult.value;
  const culled = result?.culledCount ?? 0;
  const mounted = Math.max(0, plan.nodeCount - culled);
  return {
    active: true,
    label: result
      ? `虚拟渲染 ${formatCount(mounted)}/${formatCount(plan.nodeCount)} · 裁 ${formatCount(culled)}`
      : "虚拟渲染 · 测量中",
    title: `自由布局大页面（>${plan.threshold} 节点）：只挂载视口 + ${overscanPx.value}px 预渲染范围内的节点。选中节点及其祖先、命名插槽节点、无 layout 节点始终保留；非顶层容器不裁撤。被裁节点不在 DOM 中，无法直接点击/拖拽。`,
  };
});

const hudStyle = computed<Record<string, string>>((): Record<string, string> =>
  hudPosition.value ? { left: `${hudPosition.value.left}px`, top: `${hudPosition.value.top}px` } : {}
);

/*
 * 已知取舍 / 限制（大页面虚拟化）：
 * - 裁剪依据 schema layout 计算；祖先处于文档流（无 layout）时绝对坐标不可推断，这类节点一律保留。
 * - 被裁节点不在 DOM 中：点击 / 拖拽命中测试只对已挂载节点生效；视口与 overscan 内的节点始终挂载，
 *   因此正常拖放不受影响；快速滚动（含 HTML5 拖拽自动滚动）期间可能出现短暂空白。
 * - 顶层容器整棵子树被裁时，内部组件会卸载并在滚回时重建：图表实例、折叠状态等局部状态会重置。
 * - 命名插槽子节点（表格列 / 标签页等）与非顶层容器不会被裁，避免破坏父组件渲染协议。
 * - flow 布局的 content-visibility 是浏览器兜底：不支持时自动退化为普通渲染；占位尺寸可能造成
 *   首次滚动到该区域时的高度轻微跳动（contain-intrinsic-size: auto 会记住上次渲染尺寸）。
 */

watch(
  () => [
    editor.zoom,
    editor.device,
    layoutMode.value,
    canvasStyle.value.width,
    canvasStyle.value.height,
    Object.keys(renderNodes.value).length,
  ],
  () => nextTick(scheduleCanvasMeasure)
);

// ---------- 设计态锁定 / 隐藏（只注入到设计画布，运行态不生效） ----------
const designCss = computed(() => {
  const s = schema.schema;
  if (!s) return "";
  const hidden: string[] = [];
  const locked: string[] = [];
  for (const id of Object.keys(s.nodes)) {
    if (id === s.rootId) continue;
    const n = s.nodes[id];
    if (!n) continue;
    if (n.hidden) hidden.push(id);
    if (schema.isNodeLocked(id)) locked.push(id);
  }
  const parts: string[] = [];
  for (const id of hidden) parts.push(`.wp-canvas [data-wp-node="${id}"]{display:none!important}`);
  for (const id of locked) {
    parts.push(
      `.wp-canvas [data-wp-node="${id}"]>.wp-node-close,.wp-canvas [data-wp-node="${id}"]>.wp-resize-handle{display:none!important;pointer-events:none!important}`
    );
  }
  return parts.join("\n");
});

let designStyleEl: HTMLStyleElement | null = null;
function applyDesignCss() {
  if (typeof document === "undefined") return;
  if (!designStyleEl) {
    designStyleEl = document.createElement("style");
    designStyleEl.id = "wp-designer-canvas-state";
    document.head.appendChild(designStyleEl);
  }
  designStyleEl.textContent = designCss.value;
}
watch(designCss, applyDesignCss);

// ---------- 拖放插入 ----------
function nodeFromEvent(e: MouseEvent | DragEvent): { id: string } | null {
  const el = (e.target as HTMLElement | null)?.closest?.(".wp-node");
  if (!el) return null;
  const inst = (el as any).__vueParentComponent;
  const id = inst?.props?.node?.id;
  return typeof id === "string" ? { id } : null;
}

function onDrop(e: DragEvent) {
  dragOver.value = false;
  const s = schema.schema;
  if (!s) return;

  // 已存在节点：拖拽重排 / 移动到其他容器
  const moveId = e.dataTransfer?.getData(DND_NODE_MIME);
  if (moveId) {
    const targetEl = (e.target as HTMLElement | null)?.closest?.(".wp-node") as HTMLElement | null;
    const target = targetEl ? nodeFromEvent(e) : null;
    if (target?.id === moveId) return;
    let parentId = s.rootId;
    let index = s.nodes[s.rootId]?.children?.length ?? 0;
    if (target && target.id !== s.rootId && target.id !== moveId) {
      const targetNode = s.nodes[target.id];
      const targetParent = schema.parentOf(target.id) || s.rootId;
      const targetMeta = targetNode ? compStore.meta(targetNode.type) : undefined;
      const acceptsChildren = !!targetMeta && ((targetMeta.accept_children || targetMeta.accepts || []).length > 0);
      if (acceptsChildren && !(targetNode.children || []).length) {
        parentId = target.id;
        index = 0;
      } else {
        const siblings = s.nodes[targetParent]?.children || [];
        const at = siblings.indexOf(target.id);
        const rect = targetEl?.getBoundingClientRect();
        const after = rect ? e.clientY > rect.top + rect.height / 2 : false;
        parentId = targetParent;
        index = (at >= 0 ? at : siblings.length) + (after ? 1 : 0);
      }
    }
    withHistory("移动组件", () => schema.moveNode(moveId, parentId, index));
    return;
  }

  const type = droppedComponent(e);
  if (!type) return;
  // 落点父节点：拖到可容纳子节点的组件内部则插入该组件，否则根节点
  let parentId = s.rootId;
  const hit = nodeFromEvent(e);
  if (hit && hit.id !== s.rootId) {
    const n = schema.node(hit.id);
    const m = n ? compStore.meta(n.type) : undefined;
    if (n && m && (m.accept_children || []).length > 0) parentId = hit.id;
  }
  const id = withHistory("插入组件", () => {
    const nid = schema.insertComponent(type, parentId, -1);
    // free 模式：把落点（画布内坐标，8px 吸附）写入新节点 layout
    if (nid && s.layout?.mode === "free") {
      const rect = innerRef.value?.getBoundingClientRect();
      if (rect) {
        const x = snap(Math.max(0, (e.clientX - rect.left) / editor.zoom - 100));
        const y = snap(Math.max(0, (e.clientY - rect.top) / editor.zoom - 40));
        const n = schema.node(nid);
        if (n) n.layout = { x, y, width: n.layout?.width || 200, height: n.layout?.height || 80 };
      }
    }
    return nid;
  });
  if (id) {
    const m = compStore.meta(type);
    ElMessage.success(`已插入组件「${m?.label || type}」`);
  }
}

// ---------- free 布局拖动 / 缩放 / 智能辅助线 ----------
interface DragState {
  kind: "move" | "resize";
  id: string;
  ids: string[];
  /** 本次拖动实际申请 / 持有的服务端锁（多选拖动会申请全部选中节点）。 */
  lockIds: string[];
  parentId: string;
  startX: number;
  startY: number;
  orig: Record<string, Rect>;
  bbox: Rect;
  before: any;
  dirtyBefore: boolean;
  moved: boolean;
}

interface PendingDragLock {
  /** 取消 / 被新请求取代后，迟到的 acquire 回执只释放锁，不再启动拖动。 */
  lockIds: string[];
  cancelled: boolean;
}

interface MarqueeState {
  startX: number;
  startY: number;
  additive: boolean;
  baseIds: string[];
  moved: boolean;
}

let dragState: DragState | null = null;
let marqueeState: MarqueeState | null = null;
/** 正在等待服务端锁回执的 pointerdown；用于阻止并发拖动 / 乱序回执。 */
let pendingDragLock: PendingDragLock | null = null;
/** 拖动被远端锁打断后，等 pointerup 再拦截一次 click（避免多选被折叠成单选）。 */
let abortedDragIds: string[] | null = null;
let canvasDisposed = false;
/** 多选整体拖动后浏览器仍会派发 click，捕获阶段拦截一次以免 NodeRenderer 把多选折叠成单选。 */
let suppressClickOnce = false;
let suppressClickTimer = 0;

const guides = ref<{ v: number[]; h: number[] }>({ v: [], h: [] });
const feedback = ref<Rect | null>(null);
const marquee = ref<Rect | null>(null);
const suppressCanvasClick = ref(false);
let suppressCanvasTimer = 0;

function pointFromEvent(e: PointerEvent): { x: number; y: number } | null {
  const el = innerRef.value;
  if (!el) return null;
  const rect = el.getBoundingClientRect();
  return { x: (e.clientX - rect.left) / editor.zoom, y: (e.clientY - rect.top) / editor.zoom };
}

/** 父级在页面坐标系中的偏移（嵌套组合时把页面参考线转换到父级局部坐标）。 */
function parentOffset(parentId: string): { x: number; y: number } {
  let x = 0;
  let y = 0;
  let cur: string | null = parentId;
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const n = schema.node(cur);
    const l = layoutFor(n, editor.device);
    if (l) { x += l.x; y += l.y; }
    cur = schema.parentOf(cur);
  }
  return { x, y };
}

function topLevelIn(ids: string[]): string[] {
  const set = new Set(ids);
  return ids.filter((id) => {
    let p = schema.parentOf(id);
    const seen = new Set<string>();
    while (p && !seen.has(p)) {
      if (set.has(p)) return false;
      seen.add(p);
      p = schema.parentOf(p);
    }
    return true;
  });
}

/** 收集页面边缘 / 中心 + 同级节点边缘 / 中心参考线（父级局部坐标）。 */
function collectSnapTargets(ids: string[], parentId: string): SnapTargets {
  const offset = parentOffset(parentId);
  const vertical = new Set<number>([-offset.x, pageWidth.value / 2 - offset.x, pageWidth.value - offset.x]);
  const horizontal = new Set<number>([-offset.y, pageHeight.value / 2 - offset.y, pageHeight.value - offset.y]);
  const moving = new Set<string>();
  const addSubtree = (id: string) => {
    if (moving.has(id)) return;
    moving.add(id);
    const n = schema.node(id);
    if (!n) return;
    for (const c of n.children || []) addSubtree(c);
    for (const list of Object.values(n.slots || {})) for (const c of list) addSubtree(c);
  };
  for (const id of ids) addSubtree(id);
  const parents = new Set<string>();
  for (const id of ids) {
    const p = schema.parentOf(id);
    if (p) parents.add(p);
  }
  for (const pid of parents) {
    for (const child of schema.childrenOf(pid)) {
      if (moving.has(child.id) || child.hidden || !child.layout) continue;
      const l = child.layout;
      vertical.add(l.x);
      vertical.add(l.x + l.width / 2);
      vertical.add(l.x + l.width);
      horizontal.add(l.y);
      horizontal.add(l.y + l.height / 2);
      horizontal.add(l.y + l.height);
    }
  }
  return { vertical: [...vertical], horizontal: [...horizontal] };
}

function nodeLabel(id: string): string {
  const node = schema.node(id);
  if (!node) return id;
  const meta = compStore.meta(node.type);
  return meta?.label || node.type || id;
}

function lockOwner(nodeId: string): string {
  const lock = lockSession.locks.value[nodeId];
  return lock ? String(lock.username || "").trim() : "";
}

/** 统一的服务端锁冲突提示：能拿到 owner 时带上，否则说明连接/权限原因。 */
function warnLockConflict(nodeId: string, action: string): void {
  const label = nodeLabel(nodeId);
  const owner = lockOwner(nodeId);
  if (owner) ElMessage.warning(`节点「${label}」已被 ${owner} 锁定，${action}`);
  else ElMessage.warning(`无法锁定节点「${label}」（可能已被他人编辑或协作连接已断开），${action}`);
}

/**
 * 释放本次涉及、且已无当前拖动 / 新申请依赖的锁。
 * 迟到的旧回执不能释放已被新一轮拖动或待回执申请接管的同一节点。
 */
function releaseIdleLocks(lockIds: string[]): void {
  for (const id of lockIds) {
    if (dragState?.lockIds.includes(id)) continue;
    if (pendingDragLock?.lockIds.includes(id)) continue;
    releaseServerLock(id);
  }
}

/** 取消尚未回执的锁申请；迟到的回执由 beginGuardedDrag 负责释放。 */
function cancelPendingDragLock(): void {
  if (!pendingDragLock) return;
  pendingDragLock.cancelled = true;
  pendingDragLock = null;
}

/**
 * pointerdown 的异步锁守卫：
 * 1. 先向服务端申请锁（单节点 / 多选全部节点），期间不改 layout、不建 dragState；
 * 2. 被拒绝、等待期间节点消失/被本地锁定/被远端抢占 → 释放已拿到的锁并放弃拖动；
 * 3. 等待期间 pointerup / pointercancel / 新 pointerdown → 标记取消，回执到达后只释放锁。
 */
async function beginGuardedDrag(
  e: PointerEvent,
  hitId: string,
  resizing: boolean,
  ids: string[],
  parentId: string
): Promise<void> {
  const lockIds = resizing ? [hitId] : [...new Set(ids)];
  const request: PendingDragLock = { lockIds, cancelled: false };
  pendingDragLock = request;

  let results: boolean[] = [];
  try {
    results = await Promise.all(lockIds.map((id) => acquireServerLock(id)));
  } catch {
    results = lockIds.map(() => false);
  }

  if (request.cancelled || pendingDragLock !== request || canvasDisposed) {
    if (pendingDragLock === request) pendingDragLock = null;
    releaseIdleLocks(lockIds);
    return;
  }
  pendingDragLock = null;

  const deniedIndex = results.findIndex((granted) => !granted);
  if (deniedIndex >= 0) {
    releaseIdleLocks(lockIds);
    const action =
      lockIds.length > 1
        ? `已取消本次拖动（多选 ${lockIds.length} 个节点）`
        : resizing
          ? "无法缩放"
          : "无法拖动";
    warnLockConflict(lockIds[deniedIndex], action);
    return;
  }

  // 回执与 lock 事件可能乱序：等锁期间节点被删除 / 本地锁定 / 远端抢占时同样放弃。
  if (lockIds.some((id) => !schema.node(id))) {
    releaseIdleLocks(lockIds);
    ElMessage.warning("节点已不存在，本次拖动已取消");
    return;
  }
  const conflictId = lockIds.find((id) => schema.isNodeLocked(id) || isRemoteLocked(id));
  if (conflictId) {
    releaseIdleLocks(lockIds);
    warnLockConflict(conflictId, resizing ? "无法缩放" : "无法拖动");
    return;
  }

  const orig: Record<string, Rect> = {};
  for (const id of ids) {
    const layout = layoutFor(schema.node(id), editor.device);
    if (layout) orig[id] = { x: layout.x, y: layout.y, width: layout.width || 0, height: layout.height || 0 };
  }
  const bbox = unionRect(Object.values(orig));
  if (!bbox) {
    releaseIdleLocks(lockIds);
    return;
  }

  dragState = {
    kind: resizing ? "resize" : "move",
    id: hitId,
    ids,
    lockIds,
    parentId,
    startX: e.clientX,
    startY: e.clientY,
    orig,
    bbox,
    before: deepClone(schema.schema),
    dirtyBefore: schema.dirty,
    moved: false,
  };
}

function onNodePointerDown(e: PointerEvent) {
  if (layoutMode.value !== "free" || e.button !== 0) return;
  // 新的按压一律作废尚未回执的锁申请，保证同一时刻只有一次拖动可能启动。
  cancelPendingDragLock();
  abortedDragIds = null;
  if (dragState) return;

  const targetEl = e.target as HTMLElement | null;
  if (targetEl?.closest?.(".wp-node-close") != null) return; // × 按钮不触发拖动
  if (targetEl?.closest?.(".wp-resize-handle") == null && targetEl?.closest?.(".wp-node") == null) {
    startMarquee(e);
    return;
  }
  const hit = nodeFromEvent(e);
  if (!hit) {
    startMarquee(e);
    return;
  }
  const n = schema.node(hit.id);
  if (!n || !layoutFor(n, editor.device) || hit.id === schema.schema?.rootId) return;
  if (schema.isNodeLocked(hit.id)) return; // 本地锁定：保持原有静默行为

  const resizing = targetEl?.closest?.(".wp-resize-handle") != null;
  const additive = e.ctrlKey || e.metaKey || e.shiftKey;

  // 先检查他人实时锁：已知被远端持有时不再发 acquire，直接提示 owner。
  if (isRemoteLocked(hit.id)) {
    warnLockConflict(hit.id, resizing ? "无法缩放" : "无法拖动");
    return;
  }

  if (!resizing && !schema.selectedIds.includes(hit.id)) {
    // Ctrl 点击只做选择（交给 NodeRenderer 的 click），普通点击先选中再等待锁
    if (additive) return;
    schema.select(hit.id);
  }
  if (resizing && !schema.selectedIds.includes(hit.id)) return;

  let ids: string[] = [hit.id];
  const parentId = schema.parentOf(hit.id) || (schema.schema?.rootId as string);
  if (!resizing) {
    const top = schema.topLevelSelectedIds;
    const candidates = top.length ? top : [hit.id];
    const movable = candidates.filter((id) => {
      const node = schema.node(id);
      return (
        !!node?.layout &&
        (schema.parentOf(id) || (schema.schema?.rootId as string)) === parentId &&
        !schema.isNodeLocked(id) &&
        !schema.isNodeHiddenDeep(id)
      );
    });
    if (movable.includes(hit.id)) ids = movable;
  }

  // 关键：layout / dragState 都不在这里改，等 acquire 成功后再进入 beginGuardedDrag 的提交段。
  void beginGuardedDrag(e, hit.id, resizing, ids, parentId);
}

function startMarquee(e: PointerEvent) {
  if (layoutMode.value !== "free") return;
  const el = innerRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) return;
  const p = pointFromEvent(e);
  if (!p) return;
  if (p.x < 0 || p.y < 0 || p.x > pageWidth.value || p.y > pageHeight.value) return;
  marqueeState = {
    startX: p.x,
    startY: p.y,
    additive: !!(e.ctrlKey || e.metaKey || e.shiftKey),
    baseIds: [...schema.selectedIds],
    moved: false,
  };
  marquee.value = { x: p.x, y: p.y, width: 0, height: 0 };
}

function restoreDragStartLayout(state: DragState): void {
  const beforeNodes: Record<string, any> = state.before?.nodes || {};
  for (const id of state.ids) {
    const node = schema.node(id);
    const snapshot = beforeNodes[id];
    if (!node || !snapshot) continue;
    // layout 与多端覆盖都按拖动开始时的快照精确还原，避免响应式布局被写入脏覆盖。
    if (snapshot.layout) node.layout = deepClone(snapshot.layout);
    else delete (node as any).layout;
    if (snapshot.responsiveLayout) (node as any).responsiveLayout = deepClone(snapshot.responsiveLayout);
    else delete (node as any).responsiveLayout;
  }
}

/** 拖动中途锁被他人抢占：还原起始 layout、停拖、清辅助线、释放锁并提示。 */
function abortDragForLostLock(nodeId: string): void {
  const state = dragState;
  if (!state) return;
  dragState = null;
  restoreDragStartLayout(state);
  guides.value = { v: [], h: [] };
  feedback.value = null;
  schema.dirty = state.dirtyBefore;
  abortedDragIds = [...state.ids];
  for (const id of state.lockIds) releaseServerLock(id);
  warnLockConflict(nodeId, `本次${state.kind === "move" ? "拖动" : "缩放"}已撤销`);
}

/** 被远端锁打断的拖动结束后，浏览器仍可能派发 click；多选时拦截一次以免折叠成单选。 */
function applyAbortedDragClickGuard(): void {
  const ids = abortedDragIds;
  abortedDragIds = null;
  if (!ids || ids.length <= 1) return;
  suppressClickOnce = true;
  window.clearTimeout(suppressClickTimer);
  suppressClickTimer = window.setTimeout(() => {
    suppressClickOnce = false;
  }, 150);
}

// 锁归属变化时立即检查当前拖动（pointermove 中还有同步兜底检查）。
watch(
  () => lockSession.remoteLocks.value,
  () => {
    if (!dragState) return;
    const conflictId = dragState.ids.find((id) => isRemoteLocked(id));
    if (conflictId) abortDragForLostLock(conflictId);
  }
);

function onPointerMove(e: PointerEvent) {
  if (marqueeState) {
    const p = pointFromEvent(e);
    if (!p) return;
    const x = Math.max(0, Math.min(pageWidth.value, p.x));
    const y = Math.max(0, Math.min(pageHeight.value, p.y));
    const rect: Rect = {
      x: Math.min(marqueeState.startX, x),
      y: Math.min(marqueeState.startY, y),
      width: Math.abs(x - marqueeState.startX),
      height: Math.abs(y - marqueeState.startY),
    };
    if (rect.width > 2 || rect.height > 2) marqueeState.moved = true;
    marquee.value = rect;
    return;
  }
  if (!dragState) return;
  const state = dragState;
  // 兜底：lock 事件与 pointermove 可能乱序，移动前同步确认锁仍属于自己。
  const conflictId = state.ids.find((id) => isRemoteLocked(id));
  if (conflictId) {
    abortDragForLostLock(conflictId);
    return;
  }
  const dx = (e.clientX - state.startX) / editor.zoom;
  const dy = (e.clientY - state.startY) / editor.zoom;
  if (!state.moved && Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
  state.moved = true;

  if (state.kind === "resize") {
    const n = schema.node(state.id);
    const base = state.orig[state.id];
    if (!n || !base) return;
    const current = layoutFor(n, editor.device) || base;
    const next = { x: current.x, y: current.y, width: Math.max(24, snap(base.width + dx, 4)), height: Math.max(24, snap(base.height + dy, 4)) };
    writeLayout(n, editor.device, next);
    feedback.value = next;
  } else {
    const targets = collectSnapTargets(state.ids, state.parentId);
    const raw: Rect = { x: state.bbox.x + dx, y: state.bbox.y + dy, width: state.bbox.width, height: state.bbox.height };
    const snapped = snapRect(raw, targets, 6);
    // 有辅助线时优先吸附参考线，否则保持原有 8px 网格吸附。
    let moveX = snapped.v.length ? snapped.x - state.bbox.x : snap(dx, gridSize);
    let moveY = snapped.h.length ? snapped.y - state.bbox.y : snap(dy, gridSize);
    moveX = Math.max(moveX, -state.bbox.x);
    moveY = Math.max(moveY, -state.bbox.y);
    for (const id of state.ids) {
      const n = schema.node(id);
      const base = state.orig[id];
      if (!n || !base) continue;
      const current = layoutFor(n, editor.device) || base;
      writeLayout(n, editor.device, { x: base.x + moveX, y: base.y + moveY, width: current.width, height: current.height });
    }
    guides.value = { v: snapped.v, h: snapped.h };
    feedback.value = {
      x: state.bbox.x + moveX,
      y: state.bbox.y + moveY,
      width: state.bbox.width,
      height: state.bbox.height,
    };
  }
  schema.dirty = true;
}

function onPointerUp() {
  // 等待锁期间松手 / 取消：作废本次申请（回执到达后只释放锁）。
  cancelPendingDragLock();
  if (marqueeState) {
    const state = marqueeState;
    const rect = marquee.value;
    marqueeState = null;
    marquee.value = null;
    if (state.moved && rect) {
      const s = schema.schema;
      const hits: string[] = [];
      if (s) {
        for (const [id, node] of Object.entries(s.nodes)) {
          if (id === s.rootId || !node.layout || schema.isNodeHiddenDeep(id)) continue;
          const abs = absoluteRect(id, s.nodes, schema.parentOf);
          if (abs && intersectsRect(abs, rect)) hits.push(id);
        }
      }
      const filtered = topLevelIn(hits);
      const finalIds = state.additive
        ? [...new Set([...state.baseIds, ...filtered])].filter((id) => id !== schema.schema?.rootId)
        : filtered;
      schema.selectMany(finalIds);
      suppressCanvasClick.value = true;
      window.clearTimeout(suppressCanvasTimer);
      suppressCanvasTimer = window.setTimeout(() => {
        suppressCanvasClick.value = false;
      }, 200);
    }
    return;
  }
  if (!dragState) {
    applyAbortedDragClickGuard();
    return;
  }
  const state = dragState;
  if (state.moved) {
    const after = deepClone(schema.schema);
    if (JSON.stringify(after) !== JSON.stringify(state.before)) {
      history.push(state.kind === "move" ? "拖动节点" : "调整大小", state.before, after);
    }
    if (state.kind === "move" && state.ids.length > 1) {
      suppressClickOnce = true;
      window.clearTimeout(suppressClickTimer);
      suppressClickTimer = window.setTimeout(() => {
        suppressClickOnce = false;
      }, 150);
    }
  }
  // 多选拖动按申请到的全部锁释放，避免只释放被按住的那个节点。
  for (const id of state.lockIds) releaseServerLock(id);
  dragState = null;
  guides.value = { v: [], h: [] };
  feedback.value = null;
}

// capture 阶段拦截多选拖动结束后误触发的 click
function onClickCapture(e: MouseEvent) {
  if (!suppressClickOnce) return;
  suppressClickOnce = false;
  window.clearTimeout(suppressClickTimer);
  e.stopPropagation();
}

// 事件绑定（事件委托，避免逐个节点挂 handler）
const wrapperEl = () => scrollRef.value;
function pd(e: PointerEvent) { onNodePointerDown(e); }
function pm(e: PointerEvent) { onPointerMove(e); }
function pu() { onPointerUp(); }
let fitObserver: ResizeObserver | null = null;
let fitTimer = 0;
onMounted(() => {
  applyDesignCss();
  const el = wrapperEl();
  el?.addEventListener("pointerdown", pd);
  el?.addEventListener("click", onClickCapture, true);
  el?.addEventListener("scroll", scheduleCanvasMeasure, { passive: true });
  window.addEventListener("resize", scheduleCanvasMeasure);
  window.addEventListener("pointermove", pm);
  window.addEventListener("pointerup", pu);
  window.addEventListener("pointercancel", pu);
  nextTick(() => {
    fitCanvas();
    scheduleCanvasMeasure();
    // 首次挂载时左右面板宽度可能尚未完成布局，再补一次。
    window.setTimeout(() => {
      fitCanvas();
      measureCanvasViewportAndHud();
    }, 150);
  });
  if (el && typeof ResizeObserver !== "undefined") {
    fitObserver = new ResizeObserver(() => {
      scheduleCanvasMeasure();
      window.clearTimeout(fitTimer);
      fitTimer = window.setTimeout(fitCanvas, 80);
    });
    fitObserver.observe(el);
  }
});
onBeforeUnmount(() => {
  canvasDisposed = true;
  cancelPendingDragLock();
  abortedDragIds = null;
  if (dragState) {
    // 卸载时仍在拖动：还原起始 layout（不上历史）并释放本次持有的锁。
    const state = dragState;
    dragState = null;
    restoreDragStartLayout(state);
    schema.dirty = state.dirtyBefore;
    for (const id of state.lockIds) releaseServerLock(id);
  }
  const el = wrapperEl();
  el?.removeEventListener("pointerdown", pd);
  el?.removeEventListener("click", onClickCapture, true);
  el?.removeEventListener("scroll", scheduleCanvasMeasure);
  window.removeEventListener("resize", scheduleCanvasMeasure);
  window.removeEventListener("pointermove", pm);
  window.removeEventListener("pointerup", pu);
  window.removeEventListener("pointercancel", pu);
  if (measureRaf) window.cancelAnimationFrame(measureRaf);
  measureRaf = 0;
  fitObserver?.disconnect();
  window.clearTimeout(fitTimer);
  window.clearTimeout(suppressClickTimer);
  window.clearTimeout(suppressCanvasTimer);
  designStyleEl?.remove();
  designStyleEl = null;
});

// 点击空白画布 → 选中根（框选结束后不触发）
function onCanvasClick(e: MouseEvent) {
  if (suppressCanvasClick.value) {
    suppressCanvasClick.value = false;
    window.clearTimeout(suppressCanvasTimer);
    return;
  }
  const t = e.target as HTMLElement | null;
  if (!t) return;
  if (t.closest?.(".wp-node")) return; // 节点自身处理
  if (schema.schema) schema.select(schema.schema.rootId);
}
</script>

<style scoped>
.wp-canvas-scroll {
  flex: 1;
  overflow: auto;
  background: var(--el-fill-color-blank);
  background-image: radial-gradient(circle, var(--el-border-color-light) 1px, transparent 1px);
  background-size: 24px 24px;
  padding: 24px;
  user-select: none;
}
.wp-canvas-scroll.is-drag-over {
  outline: 2px dashed var(--el-color-primary);
  outline-offset: -6px;
  background-color: var(--el-color-primary-light-9);
}
.wp-canvas-inner {
  display: inline-block;
  margin: 0 auto;
  position: relative;
}
.wp-canvas-root {
  display: inline-block;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.12);
  background: var(--wp-canvas-sheet);
}
.wp-canvas-empty {
  color: var(--el-text-color-secondary);
  padding: 40px;
}
/* 大页面虚拟化指示（compact HUD）：固定定位在画布区左下角，不遮挡画布内容。 */
.wp-virt-hud {
  position: fixed;
  z-index: 30;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 320px;
  padding: 3px 9px;
  border-radius: 10px;
  border: 1px solid var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 11px;
  line-height: 16px;
  white-space: nowrap;
  transform: translateY(-100%);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.1);
  cursor: default;
}
.wp-virt-hud-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.wp-virt-hud-text {
  overflow: hidden;
  text-overflow: ellipsis;
}
.wp-canvas-overlay {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
  z-index: 20;
}
.wp-guide {
  position: absolute;
  background: #ff4d8d;
  box-shadow: 0 0 0 1px rgba(255, 77, 141, 0.25);
}
.wp-guide-v {
  top: 0;
  bottom: 0;
  width: 1px;
}
.wp-guide-h {
  left: 0;
  right: 0;
  height: 1px;
}
.wp-marquee {
  position: absolute;
  border: 1px solid var(--el-color-primary);
  background: rgba(64, 158, 255, 0.12);
  box-sizing: border-box;
}
.wp-drag-feedback {
  position: absolute;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}
.wp-drag-feedback-size {
  margin-left: 4px;
  opacity: 0.85;
}
</style>

<style>
/* 设计态选中/悬停高亮（NodeRenderer 设计模式输出 .wp-node-selected） */
.wp-node {
  cursor: pointer;
  position: relative; /* 锚定右上角 × 按钮 / 右下角缩放手柄 */
}
/* 右上角 × 删除按钮（悬停/选中时显示） */
.wp-node-close {
  position: absolute;
  top: -9px;
  right: -9px;
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: #f56c6c;
  color: #fff;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  display: none;
  align-items: center;
  justify-content: center;
  z-index: 10;
}
.wp-node-selected > .wp-node-close {
  display: flex;
}
.wp-node-close:hover {
  background: #f23c3c;
}
/* free 布局：未选中节点也显示边界，便于定位 */
.wp-node-free {
  outline: 1px dashed var(--el-border-color);
  outline-offset: -1px;
  background-color: rgba(255, 255, 255, 0.4);
}
/* free 布局：节点内的组件撑满外框，改框大小即改组件大小 */
.wp-node-free > :not(.wp-node-close):not(.wp-resize-handle) {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
}
.wp-node-selected,
.wp-canvas .wp-node-selected {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}
/* 设计态透明包装：不破坏 ElRow/ElCol 等布局，选中态描边落在真实组件根节点。 */
.wp-node-inline {
  display: contents;
}
.wp-node-inline.wp-node-selected > * {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}
.wp-node-inline > .wp-node-close {
  display: none !important;
}
/* 右下角缩放手柄（悬停/选中时显示） */
.wp-resize-handle {
  position: absolute;
  right: -5px;
  bottom: -5px;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  background: var(--el-color-primary);
  border: 1px solid #fff;
  cursor: nwse-resize;
  display: none;
  z-index: 5;
}
.wp-node-free:hover .wp-resize-handle,
.wp-node-free.wp-node-selected .wp-resize-handle {
  display: block;
}
/* 流式大页面兜底：content-visibility 跳过视口外渲染，DOM 与布局保留（不裁剪节点）。 */
.wp-canvas-root.is-large-flow .wp-canvas .wp-node {
  content-visibility: auto;
  contain-intrinsic-size: auto 160px;
}
/* 选中节点即使在视口外也保持渲染，选择 / 拖拽状态不因滚动丢失。 */
.wp-canvas-root.is-large-flow .wp-canvas .wp-node.wp-node-selected {
  content-visibility: visible;
}
</style>
