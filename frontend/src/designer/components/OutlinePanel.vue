<template>
  <div ref="rootRef" class="wp-outline">
    <div class="wp-outline-tools">
      <div class="wp-outline-tool-row">
        <span class="wp-outline-tool-label">对齐</span>
        <button type="button" class="wp-outline-btn" title="左对齐" :disabled="!canAlign" @click="doAlign('left')">⇤</button>
        <button type="button" class="wp-outline-btn" title="水平居中" :disabled="!canAlign" @click="doAlign('hcenter')">↔</button>
        <button type="button" class="wp-outline-btn" title="右对齐" :disabled="!canAlign" @click="doAlign('right')">⇥</button>
        <button type="button" class="wp-outline-btn" title="顶对齐" :disabled="!canAlign" @click="doAlign('top')">⇧</button>
        <button type="button" class="wp-outline-btn" title="垂直居中" :disabled="!canAlign" @click="doAlign('vcenter')">↕</button>
        <button type="button" class="wp-outline-btn" title="底对齐" :disabled="!canAlign" @click="doAlign('bottom')">⇩</button>
      </div>
      <div class="wp-outline-tool-row">
        <span class="wp-outline-tool-label">分布</span>
        <button type="button" class="wp-outline-btn is-text" title="水平等距分布（至少 3 个）" :disabled="!canDistribute" @click="doDistribute('x')">横向</button>
        <button type="button" class="wp-outline-btn is-text" title="垂直等距分布（至少 3 个）" :disabled="!canDistribute" @click="doDistribute('y')">纵向</button>
        <span class="wp-outline-sep" />
        <button type="button" class="wp-outline-btn is-text" title="把选中的同父级节点组合为容器" :disabled="!canGroup" @click="doGroup">组合</button>
        <button type="button" class="wp-outline-btn is-text" title="取消组合并还原节点位置" :disabled="!canUngroup" @click="doUngroup">拆分</button>
      </div>
    </div>

    <div class="wp-outline-hint">
      点击选择，Ctrl / Shift 多选；拖动行可排序或移入容器；↑ / ↓ 切换焦点；Delete 删除，Ctrl+C / Ctrl+V 复制粘贴。
    </div>

    <!-- 大型页面提示：只提示、不阻塞；节点数统计包含全部节点（含未挂载的孤立节点）。 -->
    <div v-if="isLargePage" class="wp-outline-large" role="status">
      <span class="wp-outline-large-icon">⚡</span>
      <span>大型页面：{{ nodeCount }} 个节点<span v-if="virtualize">，大纲已启用虚拟滚动</span>，编辑操作可能变慢。</span>
    </div>

    <div v-if="!rows.length" class="wp-outline-empty">页面还没有节点</div>
    <div
      v-else
      ref="viewportRef"
      class="wp-outline-viewport"
      :class="{ 'is-virtual': virtualize }"
      :style="virtualize ? { height: viewportHeight + 'px' } : undefined"
      role="tree"
      aria-label="页面大纲"
      aria-multiselectable="true"
      @scroll.passive="onScroll"
      @click="onRowsClick"
      @keydown="onRowsKeydown"
      @focusin="onRowsFocusIn"
      @dragstart="onDragStart"
      @dragend="onDragEnd"
      @dragover="onDragOver"
      @dragleave="onDragLeave"
      @drop="onDrop"
    >
      <div v-if="virtualize" class="wp-outline-spacer" :style="{ height: range.padTop + 'px' }" aria-hidden="true" />
      <div
        v-for="row in displayRows"
        :key="row.id"
        :data-row-id="row.id"
        role="treeitem"
        :aria-level="row.depth + 1"
        :aria-selected="selectedSet.has(row.id)"
        :tabindex="row.id === rovingId ? 0 : -1"
        class="wp-outline-row"
        :class="{
          selected: selectedSet.has(row.id),
          'is-locked': row.node.locked,
          'is-hidden': row.node.hidden,
          dragging: dragId === row.id,
          'drop-before': dropTarget?.id === row.id && dropTarget.pos === 'before',
          'drop-after': dropTarget?.id === row.id && dropTarget.pos === 'after',
          'drop-inside': dropTarget?.id === row.id && dropTarget.pos === 'inside',
        }"
        :style="{ height: OUTLINE_ROW_HEIGHT + 'px', paddingLeft: 6 + row.depth * 14 + 'px' }"
        :draggable="row.id !== rootId"
      >
        <span class="wp-outline-icon">{{ row.icon }}</span>
        <span class="wp-outline-label" :title="row.label">{{ row.label }}</span>
        <span v-if="row.slot" class="wp-outline-slot">{{ row.slot }}</span>
        <span v-if="row.node.isGroup" class="wp-outline-badge is-group">组</span>
        <span v-if="row.node.locked" class="wp-outline-badge is-lock">锁</span>
        <span v-if="row.node.hidden" class="wp-outline-badge is-hide">隐</span>
        <span class="wp-outline-type">{{ row.node.type }}</span>
        <span v-if="row.id !== rootId" class="wp-outline-ctrls">
          <button
            type="button"
            class="wp-outline-ctrl"
            :class="{ active: row.node.locked }"
            :title="row.node.locked ? '解锁（允许画布拖动/缩放/删除）' : '锁定（禁止画布拖动/缩放/删除）'"
            draggable="false"
            @pointerdown.stop
            @dragstart.stop.prevent
            @click.stop="toggleLock(row)"
          >
            {{ row.node.locked ? "🔒" : "🔓" }}
          </button>
          <button
            type="button"
            class="wp-outline-ctrl"
            :class="{ active: row.node.hidden }"
            :title="row.node.hidden ? '在设计画布显示（运行态不受影响）' : '在设计画布隐藏（运行态仍渲染）'"
            draggable="false"
            @pointerdown.stop
            @dragstart.stop.prevent
            @click.stop="toggleHide(row)"
          >
            {{ row.node.hidden ? "🚫" : "👁" }}
          </button>
        </span>
      </div>
      <div v-if="virtualize" class="wp-outline-spacer" :style="{ height: range.padBottom + 'px' }" aria-hidden="true" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { ComponentMeta, SchemaNode } from "@/types";
import { DND_NODE_MIME, withHistory } from "../util";
import {
  OUTLINE_LARGE_PAGE_THRESHOLD,
  OUTLINE_OVERSCAN,
  OUTLINE_ROW_HEIGHT,
  OUTLINE_VIRTUALIZE_THRESHOLD,
} from "../utils/virtualList";
import { useVirtualList } from "../utils/useVirtualList";

/**
 * 大纲面板。
 *
 * 大页面性能策略：
 * 1. 扁平化只保存 id / node / depth / slot，图标与文案延后到“可见行”再算，
 *    避免为不可见的几千行调用 components.meta()；
 * 2. 行数 > OUTLINE_VIRTUALIZE_THRESHOLD 时使用固定 30px 行高的窗口渲染；
 * 3. 选中集合用 Set，避免每行 O(n) 的 includes；
 * 4. 点击 / 键盘 / 拖拽事件统一委托到滚动容器，避免生成大量行内监听器。
 */

interface FlatRow {
  id: string;
  node: SchemaNode;
  depth: number;
  /** 在完整扁平列表中的下标（键盘导航用）。 */
  index: number;
  slot?: string;
}

interface OutlineRow extends FlatRow {
  label: string;
  icon: string;
}

interface DropTarget {
  id: string;
  pos: "before" | "after" | "inside";
}

interface OutlineIndex {
  rows: FlatRow[];
  byId: Map<string, FlatRow>;
  /** 子节点 → 父节点；用于拖拽祖先判断，避免反复调用 O(n) 的 schema.parentOf。 */
  parent: Map<string, string>;
}

const EMPTY_INDEX: OutlineIndex = { rows: [], byId: new Map(), parent: new Map() };

const schema = useSchemaStore();
const components = useComponentStore();
const selectedSet = computed(() => new Set(schema.selectedIds));
const rootId = computed(() => schema.schema?.rootId || "");

const dragId = ref<string | null>(null);
const dropTarget = ref<DropTarget | null>(null);

const iconMap: Record<string, string> = {
  Grid: "▦", Layout: "◫", EditPen: "✎", DataBoard: "▤", ChatDotRound: "◌",
  Compass: "◎", Picture: "▧", TrendCharts: "◔", MagicStick: "✦", SetUp: "⚙",
  Pointer: "➤", Link: "↗", Document: "▤", CollectionTag: "▣", Bell: "◔",
  User: "◉", Star: "★", Minus: "—", Postcard: "▭", Box: "▢", Top: "⌃",
  Fold: "≡", FullScreen: "▣", Bottom: "⌄", Operation: "⇄", Menu: "≡",
  Sort: "↕", ScaleToOriginal: "◧", Files: "▤", Rank: "▥", ArrowDown: "⌄",
  CircleCheck: "◉", Finished: "☑", Switch: "⇄", Brush: "✎", Calendar: "▦",
  Clock: "◷", Timer: "◷", Share: "⌘", Upload: "⇧", ChatLineSquare: "▣",
  More: "…", DataLine: "◔", Odometer: "◔", Loading: "◌", Warning: "⚠",
  InfoFilled: "ⓘ", QuestionFilled: "?", Guide: "➤", Back: "←", Paperclip: "⌘",
  VideoCamera: "▶", Microphone: "◉", Monitor: "▣", Cpu: "▤", Histogram: "▥",
  PieChart: "◔", MapLocation: "◎", CopyDocument: "⧉", Refresh: "↻",
  SwitchButton: "⇄", Position: "⌖", Stamp: "◇",
};

/**
 * 扁平化节点树。
 * 任何节点变化都会重建；重建只做 O(n) 的引用收集，不计算 label/icon，
 * 也不为每行创建闭包。
 */
const outlineIndex = computed<OutlineIndex>(() => {
  const s = schema.schema;
  if (!s) return EMPTY_INDEX;
  const rows: FlatRow[] = [];
  const byId = new Map<string, FlatRow>();
  const parent = new Map<string, string>();
  const seen = new Set<string>();

  const walk = (id: string, depth: number, parentId: string | null, slot?: string): void => {
    if (seen.has(id)) return;
    seen.add(id);
    const node = s.nodes[id];
    if (!node) return;
    if (parentId) parent.set(id, parentId);
    const row: FlatRow = { id, node, depth, index: rows.length, slot };
    rows.push(row);
    byId.set(id, row);
    for (const child of node.children || []) walk(child, depth + 1, id);
    for (const [slotName, ids] of Object.entries(node.slots || {})) {
      for (const child of ids) walk(child, depth + 1, id, slotName);
    }
  };

  walk(s.rootId, 0, null);
  return { rows, byId, parent };
});

const rows = computed(() => outlineIndex.value.rows);
const nodeCount = computed(() => (schema.schema ? Object.keys(schema.schema.nodes).length : 0));
const isLargePage = computed(() => nodeCount.value > OUTLINE_LARGE_PAGE_THRESHOLD);
const virtualize = computed(() => rows.value.length > OUTLINE_VIRTUALIZE_THRESHOLD);

const rootRef = ref<HTMLElement | null>(null);
const viewportRef = ref<HTMLElement | null>(null);

const { scrollTop, viewportHeight, range, onScroll, scrollToIndex } = useVirtualList(viewportRef, rootRef, {
  count: () => rows.value.length,
  rowHeight: OUTLINE_ROW_HEIGHT,
  overscan: OUTLINE_OVERSCAN,
  enabled: () => virtualize.value,
});

/** 当前渲染的行：非虚拟模式为全部；虚拟模式为 [start, end) 窗口。 */
const windowRows = computed<FlatRow[]>(() => {
  const list = rows.value;
  if (!virtualize.value) return list;
  const { start, end } = range.value;
  return list.slice(start, end);
});

/** 只为可见行计算 label / icon，并在同一次渲染内按 type 缓存 meta 查询。 */
const displayRows = computed<OutlineRow[]>(() => {
  const metaCache = new Map<string, ComponentMeta | undefined>();
  return windowRows.value.map((row) => {
    const node = row.node;
    if (!metaCache.has(node.type)) metaCache.set(node.type, components.meta(node.type));
    const meta = metaCache.get(node.type);
    return {
      ...row,
      label: node.type === "wp-canvas" ? "页面画布" : node.isGroup ? "组合" : meta?.label || node.type,
      icon: iconMap[meta?.icon || ""] || (node.type === "wp-canvas" ? "▣" : node.isGroup ? "▣" : "◻"),
    };
  });
});

/** 标准 roving tabindex：Tab 进入大纲时停在当前选中行。 */
const rovingId = computed(() => schema.selectedId || rows.value[0]?.id || "");

const selectedFreeNodes = computed<SchemaNode[]>(() =>
  schema.topLevelSelectedIds
    .map((id) => schema.schema?.nodes[id])
    .filter((n): n is SchemaNode => !!n?.layout && !schema.isNodeLocked(n.id))
);
const canAlign = computed(() => selectedFreeNodes.value.length >= 2);
const canDistribute = computed(() => selectedFreeNodes.value.length >= 3);
const canGroup = computed(() => schema.canGroupSelection());
const canUngroup = computed(() => schema.canUngroupSelection());

function doAlign(mode: "left" | "hcenter" | "right" | "top" | "vcenter" | "bottom") {
  if (!canAlign.value) return;
  withHistory("对齐组件", () => schema.alignSelection(mode));
}

function doDistribute(axis: "x" | "y") {
  if (!canDistribute.value) return;
  withHistory("分布组件", () => schema.distributeSelection(axis));
}

function doGroup() {
  if (!canGroup.value) {
    ElMessage.warning("组合需要同一父级下至少两个自由布局节点");
    return;
  }
  const id = withHistory("组合组件", () => schema.groupSelection());
  if (!id) ElMessage.warning("组合失败：请确认节点同属一个父级且拥有自由布局位置");
}

function doUngroup() {
  if (!canUngroup.value) return;
  withHistory("取消组合", () => schema.ungroupSelection());
}

function toggleLock(row: OutlineRow) {
  if (row.id === rootId.value) return;
  withHistory(row.node.locked ? "解锁组件" : "锁定组件", () => schema.toggleNodeLocked(row.id));
}

function toggleHide(row: OutlineRow) {
  if (row.id === rootId.value) return;
  withHistory(row.node.hidden ? "显示组件" : "隐藏组件", () => schema.toggleNodeHidden(row.id));
}

// ---------- 事件委托辅助 ----------

function rowElementFromEvent(event: Event): HTMLElement | null {
  const viewport = viewportRef.value;
  const target = event.target as HTMLElement | null;
  if (!viewport || !target?.closest) return null;
  const row = target.closest<HTMLElement>(".wp-outline-row");
  return row && viewport.contains(row) ? row : null;
}

function rowFromEvent(event: Event): FlatRow | null {
  const id = rowElementFromEvent(event)?.dataset.rowId;
  return id ? outlineIndex.value.byId.get(id) ?? null : null;
}

function rowElementById(id: string): HTMLElement | null {
  const viewport = viewportRef.value;
  if (!viewport || !id) return null;
  for (const child of Array.from(viewport.children)) {
    if (child instanceof HTMLElement && child.dataset.rowId === id) return child;
  }
  return null;
}

function isControlTarget(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  return !!target?.closest?.(".wp-outline-ctrl");
}

// ---------- 选择 / 键盘 ----------

function onRowsClick(event: MouseEvent) {
  const row = rowFromEvent(event);
  if (!row) return;
  schema.select(row.id, event.ctrlKey || event.metaKey || event.shiftKey);
}

function focusRow(row: FlatRow) {
  if (virtualize.value) scrollToIndex(row.index);
  void nextTick(() => {
    const el = rowElementById(row.id);
    if (!el) return;
    el.focus({ preventScroll: true });
    // 非虚拟模式没有自己的滚动容器，需要手动把行滚进侧边栏可视区。
    if (!virtualize.value) el.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
}

function onRowsFocusIn(event: FocusEvent) {
  if (isControlTarget(event) || !virtualize.value) return;
  const row = rowFromEvent(event);
  if (!row) return;
  // Tab 进来的行如果刚好在窗口边缘，顺带滚入视口。
  scrollToIndex(row.index);
}

function onRowsKeydown(event: KeyboardEvent) {
  if (isControlTarget(event)) return;
  const row = rowFromEvent(event);
  if (!row) return;
  let nextIndex: number;
  switch (event.key) {
    case "ArrowDown":
      nextIndex = Math.min(rows.value.length - 1, row.index + 1);
      break;
    case "ArrowUp":
      nextIndex = Math.max(0, row.index - 1);
      break;
    case "Home":
      nextIndex = 0;
      break;
    case "End":
      nextIndex = rows.value.length - 1;
      break;
    case "Enter":
    case " ":
      event.preventDefault();
      schema.select(row.id);
      return;
    default:
      return;
  }
  event.preventDefault();
  const next = rows.value[nextIndex];
  if (!next) return;
  schema.select(next.id);
  focusRow(next);
}

// ---------- HTML5 拖拽排序 ----------

function acceptsChildren(node: SchemaNode): boolean {
  if (node.isGroup) return true;
  const meta = components.meta(node.type);
  return !!(meta && ((meta.accept_children || []).length > 0 || (meta.accepts || []).length > 0));
}

/** 有效锁定：自身或祖先锁定；用扁平化时缓存的 parent map，避免 O(n) 扫描。 */
function isEffectiveLocked(id: string): boolean {
  const s = schema.schema;
  if (!s) return false;
  const parent = outlineIndex.value.parent;
  let cur: string | null = id;
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const node = s.nodes[cur];
    if (!node) return false;
    if (node.locked) return true;
    cur = parent.get(cur) ?? null;
  }
  return false;
}

/** ancestorId 是否为 nodeId 本身或祖先。 */
function isSelfOrAncestor(ancestorId: string, nodeId: string): boolean {
  const parent = outlineIndex.value.parent;
  let cur: string | null = nodeId;
  const seen = new Set<string>();
  while (cur && !seen.has(cur)) {
    if (cur === ancestorId) return true;
    seen.add(cur);
    cur = parent.get(cur) ?? null;
  }
  return false;
}

// ---- 拖拽到视口上下边缘时自动滚动（仅虚拟模式需要）----
const AUTO_SCROLL_EDGE = 28;
const AUTO_SCROLL_STEP = 12;
let autoScrollDir = 0;
let autoScrollRaf = 0;

function stopAutoScroll() {
  autoScrollDir = 0;
  if (autoScrollRaf) {
    window.cancelAnimationFrame(autoScrollRaf);
    autoScrollRaf = 0;
  }
}

function runAutoScroll() {
  autoScrollRaf = 0;
  const viewport = viewportRef.value;
  if (!viewport || !autoScrollDir) return;
  const before = viewport.scrollTop;
  viewport.scrollTop = before + autoScrollDir * AUTO_SCROLL_STEP;
  if (viewport.scrollTop === before) {
    autoScrollDir = 0;
    return;
  }
  scrollTop.value = viewport.scrollTop;
  autoScrollRaf = window.requestAnimationFrame(runAutoScroll);
}

function updateAutoScroll(event: DragEvent) {
  if (!virtualize.value) {
    stopAutoScroll();
    return;
  }
  const viewport = viewportRef.value;
  if (!viewport) return;
  const rect = viewport.getBoundingClientRect();
  autoScrollDir =
    event.clientY < rect.top + AUTO_SCROLL_EDGE ? -1 : event.clientY > rect.bottom - AUTO_SCROLL_EDGE ? 1 : 0;
  if (!autoScrollDir) {
    stopAutoScroll();
    return;
  }
  if (!autoScrollRaf) autoScrollRaf = window.requestAnimationFrame(runAutoScroll);
}

function onDragStart(event: DragEvent) {
  const row = rowFromEvent(event);
  if (!row || isControlTarget(event)) {
    event.preventDefault();
    return;
  }
  if (row.id === rootId.value || isEffectiveLocked(row.id)) {
    event.preventDefault();
    return;
  }
  dragId.value = row.id;
  dropTarget.value = null;
  const dt = event.dataTransfer;
  if (!dt) return;
  dt.setData(DND_NODE_MIME, row.id);
  dt.setData("text/plain", row.id);
  dt.effectAllowed = "move";
}

function onDragEnd() {
  dragId.value = null;
  dropTarget.value = null;
  stopAutoScroll();
}

function onDragOver(event: DragEvent) {
  const id = dragId.value;
  if (!id) return;
  updateAutoScroll(event);
  const row = rowFromEvent(event);
  if (!row || row.id === id) {
    dropTarget.value = null;
    return;
  }
  // 不能把节点拖进自己 / 自己的后代；锁定节点或锁定容器不可排序。
  if (isSelfOrAncestor(id, row.id)) {
    dropTarget.value = null;
    return;
  }
  if (isEffectiveLocked(row.id) || isEffectiveLocked(id)) {
    dropTarget.value = null;
    return;
  }
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  if (row.id === rootId.value) {
    dropTarget.value = { id: row.id, pos: "inside" };
    return;
  }
  const el = rowElementFromEvent(event);
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const ratio = (event.clientY - rect.top) / Math.max(1, rect.height);
  const container = acceptsChildren(row.node);
  let pos: DropTarget["pos"] = ratio < 0.5 ? "before" : "after";
  if (container && ratio > 0.22 && ratio < 0.78) pos = "inside";
  dropTarget.value = { id: row.id, pos };
}

function onDragLeave(event: DragEvent) {
  const rowEl = rowElementFromEvent(event);
  const row = rowFromEvent(event);
  const related = event.relatedTarget as Node | null;
  if (rowEl && related && rowEl.contains(related)) return;
  if (row && dropTarget.value?.id === row.id) dropTarget.value = null;
  const viewport = viewportRef.value;
  if (!viewport || !related || !viewport.contains(related)) stopAutoScroll();
}

function onDrop(event: DragEvent) {
  event.preventDefault();
  event.stopPropagation();
  const s = schema.schema;
  const row = rowFromEvent(event);
  const id = dragId.value || event.dataTransfer?.getData(DND_NODE_MIME) || "";
  const target = dropTarget.value;
  stopAutoScroll();
  dragId.value = null;
  dropTarget.value = null;
  if (!s || !row || !id || id === row.id) return;
  if (isSelfOrAncestor(id, row.id) && row.id !== s.rootId) return;
  // 自动滚动可能让 dropTarget 指向已经离开指针的行，只有与落点行一致时才采信 pos。
  const pos = target?.id === row.id ? target.pos : undefined;

  let parentId: string;
  let index: number;
  if (row.id === s.rootId) {
    parentId = s.rootId;
    index = s.nodes[s.rootId]?.children?.length ?? 0;
  } else if (pos === "inside") {
    parentId = row.id;
    index = s.nodes[row.id]?.children?.length ?? 0;
  } else {
    parentId = outlineIndex.value.parent.get(row.id) || s.rootId;
    const siblings = s.nodes[parentId]?.children || [];
    const at = siblings.indexOf(row.id);
    index = (at >= 0 ? at : siblings.length) + (pos === "after" ? 1 : 0);
  }
  if (parentId === id || isSelfOrAncestor(id, parentId)) return;
  if (isEffectiveLocked(id) || isEffectiveLocked(parentId)) return;
  withHistory("移动组件", () => schema.moveNode(id, parentId, index));
}

// 拖拽源行可能因虚拟滚动被移出窗口（浏览器可能不再派发 dragend），
// 用 document 级监听兜底清理拖拽状态，避免行一直停留在半透明状态。
onMounted(() => document.addEventListener("dragend", onDragEnd, true));
onBeforeUnmount(() => {
  document.removeEventListener("dragend", onDragEnd, true);
  stopAutoScroll();
});
</script>

<style scoped>
.wp-outline {
  padding: 8px;
  font-size: 12px;
}
.wp-outline-tools {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 4px;
  margin-bottom: 8px;
  background: var(--el-fill-color-lighter);
}
.wp-outline-tool-row {
  display: flex;
  align-items: center;
  gap: 2px;
  min-height: 24px;
}
.wp-outline-tool-label {
  flex: none;
  width: 28px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-outline-btn {
  flex: none;
  height: 22px;
  min-width: 22px;
  padding: 0 4px;
  border: 1px solid transparent;
  border-radius: 3px;
  background: transparent;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 20px;
  cursor: pointer;
}
.wp-outline-btn.is-text {
  font-size: 11px;
  padding: 0 5px;
}
.wp-outline-btn:hover:not(:disabled) {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
  color: var(--el-color-primary);
}
.wp-outline-btn:disabled {
  color: var(--el-text-color-placeholder);
  cursor: not-allowed;
}
.wp-outline-sep {
  flex: none;
  width: 1px;
  height: 14px;
  margin: 0 4px;
  background: var(--el-border-color);
}
.wp-outline-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.6;
  margin-bottom: 8px;
}
.wp-outline-large {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin-bottom: 6px;
  padding: 4px 6px;
  border: 1px solid var(--el-color-warning-light-7);
  border-radius: 4px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  font-size: 11px;
  line-height: 1.45;
}
.wp-outline-large-icon {
  flex: none;
  line-height: 1.45;
}
.wp-outline-empty {
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 24px 0;
}
/* 虚拟滚动视口：只有 .is-virtual 时才有固定高度和自己的滚动条 */
.wp-outline-viewport {
  position: relative;
}
.wp-outline-viewport.is-virtual {
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  border-radius: 3px;
}
.wp-outline-spacer {
  pointer-events: none;
}
.wp-outline-row {
  display: flex;
  align-items: center;
  gap: 4px;
  box-sizing: border-box;
  padding: 0 4px;
  border-radius: 3px;
  cursor: pointer;
  border: 1px solid transparent;
  min-width: 0;
  position: relative;
}
.wp-outline-row:hover {
  background: var(--el-fill-color-light);
}
.wp-outline-row.selected {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}
.wp-outline-row:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: -2px;
}
.wp-outline-row.is-hidden .wp-outline-label,
.wp-outline-row.is-hidden .wp-outline-icon {
  opacity: 0.5;
  text-decoration: line-through;
}
.wp-outline-row.dragging {
  opacity: 0.45;
}
.wp-outline-row.drop-before::before,
.wp-outline-row.drop-after::after {
  content: "";
  position: absolute;
  left: 4px;
  right: 4px;
  height: 2px;
  border-radius: 1px;
  background: var(--el-color-primary);
  z-index: 2;
}
.wp-outline-row.drop-before::before {
  top: 0;
}
.wp-outline-row.drop-after::after {
  bottom: 0;
}
.wp-outline-row.drop-inside {
  background: var(--el-color-primary-light-8);
  border-color: var(--el-color-primary);
}
.wp-outline-icon {
  flex: none;
  width: 15px;
  text-align: center;
  color: var(--el-color-primary);
}
.wp-outline-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-outline-slot {
  flex: none;
  font-size: 10px;
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
  border-radius: 2px;
  padding: 0 3px;
}
.wp-outline-badge {
  flex: none;
  font-size: 10px;
  line-height: 14px;
  padding: 0 3px;
  border-radius: 2px;
}
.wp-outline-badge.is-group {
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.wp-outline-badge.is-lock {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}
.wp-outline-badge.is-hide {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}
.wp-outline-type {
  flex: none;
  max-width: 56px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-placeholder);
  font-size: 10px;
}
.wp-outline-ctrls {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 1px;
}
.wp-outline-ctrl {
  width: 18px;
  height: 18px;
  padding: 0;
  border: none;
  border-radius: 3px;
  background: transparent;
  font-size: 11px;
  line-height: 18px;
  cursor: pointer;
  opacity: 0.55;
}
.wp-outline-ctrl:hover {
  background: var(--el-fill-color-dark);
  opacity: 1;
}
.wp-outline-ctrl.active {
  opacity: 1;
  background: var(--el-color-warning-light-9);
}
</style>
