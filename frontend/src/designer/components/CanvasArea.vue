<template>
  <div class="wp-canvas-scroll" ref="scrollRef" :class="{ 'is-drag-over': dragOver }" @dragover.prevent="onDragOver" @dragleave="onDragLeave" @drop.prevent="onDrop" @click="onCanvasClick">
    <div class="wp-canvas-inner" ref="innerRef" :style="innerStyle">
      <div v-if="root" class="wp-canvas-root">
        <NodeRenderer
          :node="root"
          :nodes="nodes"
          mode="design"
          :canvas-style="canvasStyle"
          :layout-mode="layoutMode"
        />
      </div>
      <div v-else class="wp-canvas-empty">尚未加载页面数据</div>
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
import { deepClone } from "@/utils";

const schema = useSchemaStore();
const editor = useEditorStore();
const compStore = useComponentStore();
const history = useHistoryStore();

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

// ---------- free 布局拖动 / 缩放 ----------
let dragState: {
  kind: "move" | "resize";
  id: string;
  startX: number;
  startY: number;
  orig: { x: number; y: number; width?: number; height?: number };
  before: any;
  moved: boolean;
} | null = null;

function onNodePointerDown(e: PointerEvent) {
  if (layoutMode.value !== "free" || e.button !== 0) return;
  if ((e.target as HTMLElement | null)?.closest?.(".wp-node-close") != null) return; // × 按钮不触发拖动
  const hit = nodeFromEvent(e);
  if (!hit) return;
  const n = schema.node(hit.id);
  if (!n?.layout || hit.id === schema.schema?.rootId) return;
  const resizing = (e.target as HTMLElement | null)?.closest?.(".wp-resize-handle") != null;
  dragState = {
    kind: resizing ? "resize" : "move",
    id: hit.id,
    startX: e.clientX,
    startY: e.clientY,
    orig: { ...n.layout },
    before: deepClone(schema.schema),
    moved: false,
  };
}

function onPointerMove(e: PointerEvent) {
  if (!dragState) return;
  const dx = (e.clientX - dragState.startX) / editor.zoom;
  const dy = (e.clientY - dragState.startY) / editor.zoom;
  if (!dragState.moved && Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
  dragState.moved = true;
  const n = schema.node(dragState.id);
  if (!n?.layout) return;
  if (dragState.kind === "move") {
    n.layout.x = Math.max(0, snap(dragState.orig.x + dx));
    n.layout.y = Math.max(0, snap(dragState.orig.y + dy));
  } else {
    n.layout.width = Math.max(24, snap((dragState.orig.width ?? 100) + dx, 4));
    n.layout.height = Math.max(24, snap((dragState.orig.height ?? 60) + dy, 4));
  }
  schema.dirty = true;
}

function onPointerUp() {
  if (!dragState) return;
  if (dragState.moved) {
    const after = deepClone(schema.schema);
    if (JSON.stringify(after) !== JSON.stringify(dragState.before)) {
      history.push(dragState.kind === "move" ? "拖动节点" : "调整大小", dragState.before, after);
    }
  }
  dragState = null;
}

// 事件绑定（事件委托，避免逐个节点挂 handler）
const wrapperEl = () => scrollRef.value;
function pd(e: PointerEvent) { onNodePointerDown(e); }
function pm(e: PointerEvent) { onPointerMove(e); }
function pu(e: PointerEvent) { onPointerUp(); }
let fitObserver: ResizeObserver | null = null;
let fitTimer = 0;
onMounted(() => {
  const el = wrapperEl();
  el?.addEventListener("pointerdown", pd);
  window.addEventListener("pointermove", pm);
  window.addEventListener("pointerup", pu);
  nextTick(() => {
    fitCanvas();
    // 首次挂载时左右面板宽度可能尚未完成布局，再补一次。
    window.setTimeout(fitCanvas, 150);
  });
  if (el && typeof ResizeObserver !== "undefined") {
    fitObserver = new ResizeObserver(() => {
      window.clearTimeout(fitTimer);
      fitTimer = window.setTimeout(fitCanvas, 80);
    });
    fitObserver.observe(el);
  }
});
onBeforeUnmount(() => {
  const el = wrapperEl();
  el?.removeEventListener("pointerdown", pd);
  window.removeEventListener("pointermove", pm);
  window.removeEventListener("pointerup", pu);
  fitObserver?.disconnect();
  window.clearTimeout(fitTimer);
});

// 点击空白画布 → 选中根
function onCanvasClick(e: MouseEvent) {
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
.wp-node:hover .wp-node-close,
.wp-node-selected .wp-node-close {
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
</style>
