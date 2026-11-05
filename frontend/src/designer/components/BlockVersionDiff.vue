<template>
  <div v-loading="loading" class="wp-bvd">
    <div v-if="error" class="wp-bvd-error">
      <span>{{ error }}</span>
      <el-button link type="primary" size="small" @click="load">重试</el-button>
    </div>

    <template v-else-if="diff">
      <div class="wp-bvd-bar">
        <div class="wp-bvd-summary">
          <span>v{{ fromVersion }} → v{{ toVersion }}</span>
          <span class="added">+{{ summary.added }} 新增</span>
          <span class="removed">-{{ summary.removed }} 删除</span>
          <span class="changed">~{{ summary.changed }} 修改</span>
          <span>{{ summary.unchanged }} 未变</span>
          <span v-if="diff.layoutChanged" class="changed">根节点已更换</span>
        </div>
        <el-radio-group v-model="mode" size="small" class="wp-bvd-modes">
          <el-radio-button v-for="item in modes" :key="item.value" :value="item.value">
            {{ item.label }}
          </el-radio-button>
        </el-radio-group>
      </div>

      <!-- 列表：保留原有逐条字段差异 -->
      <template v-if="mode === 'list'">
        <div v-if="addedRows.length" class="wp-bvd-section">
          <strong>新增节点</strong>
          <div v-for="row in addedRows" :key="`a-${row.id}`" class="wp-bvd-row is-added">
            <code>{{ row.id }}</code><span>{{ row.type }}</span><em>{{ row.label }}</em>
          </div>
        </div>
        <div v-if="removedRows.length" class="wp-bvd-section">
          <strong>删除节点</strong>
          <div v-for="row in removedRows" :key="`r-${row.id}`" class="wp-bvd-row is-removed">
            <code>{{ row.id }}</code><span>{{ row.type }}</span><em>{{ row.label }}</em>
          </div>
        </div>
        <div v-if="changedRows.length" class="wp-bvd-section">
          <strong>修改节点</strong>
          <div v-for="row in changedRows" :key="`c-${row.id}`" class="wp-bvd-row is-changed">
            <div class="wp-bvd-row-head">
              <code>{{ row.id }}</code><span>{{ row.type }}</span><em>{{ row.label }}</em>
            </div>
            <div v-for="(field, name) in row.fields" :key="name" class="wp-bvd-field">
              <b>{{ name }}</b>
              <span class="wp-bvd-old">{{ field.from }}</span>
              <span>→</span>
              <span class="wp-bvd-new">{{ field.to }}</span>
            </div>
          </div>
        </div>
        <el-empty
          v-if="!hasDiff"
          description="两个版本没有差异"
          :image-size="48"
        />
      </template>

      <!-- 结构 / 视觉：旧新双栏 -->
      <template v-else>
        <p v-if="!hasDiff" class="wp-bvd-same">
          两个版本没有差异（仍展示两侧真实结构，便于核对）。
        </p>

        <div class="wp-bvd-panels">
          <section v-for="side in sides" :key="side.key" class="wp-bvd-panel">
            <header class="wp-bvd-panel-head">
              <strong>{{ side.label }}</strong>
              <span v-if="side.changelog" class="wp-bvd-changelog" :title="side.changelog">
                {{ side.changelog }}
              </span>
            </header>

            <div v-if="side.error" class="wp-bvd-panel-error">
              <span>版本快照加载失败：{{ side.error }}</span>
              <el-button link type="primary" size="small" @click="load">重试</el-button>
            </div>

            <el-empty
              v-else-if="!side.tree.rows.length"
              description="该版本没有节点"
              :image-size="40"
            />

            <!-- 结构：缩进层级树 -->
            <div
              v-else-if="mode === 'structure'"
              class="wp-bvd-tree"
              role="tree"
              :aria-label="`${side.label} 结构`"
            >
              <button
                v-for="node in side.tree.rows"
                :key="node.id"
                type="button"
                class="wp-bvd-tree-node"
                :class="[statusClass(node.status), { 'is-selected': isSelected(side.key, node.id) }]"
                :style="{ paddingLeft: treeIndent(node) }"
                :title="`${node.id} · ${node.type} · ${node.label}`"
                @click="selectNode(side.key, node)"
              >
                <span class="wp-bvd-dot" aria-hidden="true" />
                <span class="wp-bvd-type">{{ node.type }}</span>
                <span class="wp-bvd-label" :class="{ 'is-muted': node.label === node.type }">
                  {{ node.label === node.type ? node.id : node.label }}
                </span>
                <span v-if="node.slot" class="wp-bvd-slot">{{ node.slot }}</span>
                <span v-if="node.orphan" class="wp-bvd-badge">孤立</span>
                <span
                  v-if="node.status !== 'unchanged'"
                  class="wp-bvd-badge"
                  :class="statusClass(node.status)"
                >{{ statusLabel(node.status) }}</span>
              </button>
            </div>

            <!-- 视觉 + 自由布局：只读迷你画布 -->
            <div
              v-else-if="side.tree.free && side.geometry.boxes.length"
              class="wp-bvd-canvas-wrap"
            >
              <div class="wp-bvd-canvas" :style="canvasStyle">
                <button
                  v-for="box in side.geometry.boxes"
                  :key="box.node.id"
                  type="button"
                  class="wp-bvd-box"
                  :class="[statusClass(box.node.status), { 'is-selected': isSelected(side.key, box.node.id) }]"
                  :style="boxStyle(box)"
                  :title="`${box.node.id} · ${box.node.type} · ${box.node.label}`"
                  @click="selectNode(side.key, box.node)"
                >
                  <span v-if="box.showLabel" class="wp-bvd-box-label">{{ box.node.label }}</span>
                </button>
              </div>
              <p v-if="side.tree.unpositioned" class="wp-bvd-note">
                {{ side.tree.unpositioned }} 个节点没有自由布局坐标，未在迷你画布中显示。
              </p>
            </div>

            <!-- 视觉 + 流式布局：缩进盒子示意 -->
            <div v-else class="wp-bvd-flow-wrap">
              <p class="wp-bvd-note">该版本未提供足够的自由布局坐标，按缩进示意。</p>
              <div class="wp-bvd-flow">
                <button
                  v-for="node in side.tree.rows"
                  :key="node.id"
                  type="button"
                  class="wp-bvd-flow-node"
                  :class="[statusClass(node.status), { 'is-selected': isSelected(side.key, node.id) }]"
                  :style="{ marginLeft: flowIndent(node) }"
                  :title="`${node.id} · ${node.type} · ${node.label}`"
                  @click="selectNode(side.key, node)"
                >
                  <span class="wp-bvd-dot" aria-hidden="true" />
                  <span class="wp-bvd-type">{{ node.type }}</span>
                  <span class="wp-bvd-label" :class="{ 'is-muted': node.label === node.type }">
                    {{ node.label === node.type ? node.id : node.label }}
                  </span>
                  <span v-if="node.slot" class="wp-bvd-slot">{{ node.slot }}</span>
                  <span
                    v-if="node.status !== 'unchanged'"
                    class="wp-bvd-badge"
                    :class="statusClass(node.status)"
                  >{{ statusLabel(node.status) }}</span>
                </button>
              </div>
            </div>
          </section>
        </div>

        <div class="wp-bvd-legend">
          <span class="is-added">新增</span>
          <span class="is-removed">删除</span>
          <span class="is-changed">修改</span>
          <span>未变</span>
        </div>

        <p v-if="previewTruncated" class="wp-bvd-truncated">
          预览有界：每侧最多渲染 {{ PREVIEW_NODE_LIMIT }} 个节点，其余节点未显示。
        </p>
        <p v-if="mode === 'visual' && hasVisualCanvas" class="wp-bvd-note">
          迷你画布按快照 layout 等比缩放，仅示意节点位置与层级，不是像素级还原。
        </p>

        <!-- 点击节点：字段差异 -->
        <div v-if="selectedInfo" ref="detailRef" class="wp-bvd-detail">
          <div class="wp-bvd-detail-head">
            <strong>节点字段</strong>
            <code>{{ selectedInfo.node.id }}</code>
            <span class="wp-bvd-type">{{ selectedInfo.node.type }}</span>
            <span class="wp-bvd-badge" :class="statusClass(selectedInfo.status)">
              {{ statusLabel(selectedInfo.status) || "未变" }}
            </span>
            <span class="wp-bvd-detail-side">
              {{ selectedInfo.side === "from" ? "旧版本" : "新版本" }}
            </span>
            <el-button link size="small" class="wp-bvd-detail-close" @click="clearSelection">关闭</el-button>
          </div>

          <div v-if="selectedInfo.fields.length" class="wp-bvd-fields">
            <div
              v-for="field in selectedInfo.fields"
              :key="field.name"
              class="wp-bvd-field"
            >
              <b>{{ field.name }}</b>
              <span class="wp-bvd-old">{{ field.from }}</span>
              <span>→</span>
              <span class="wp-bvd-new">{{ field.to }}</span>
            </div>
          </div>
          <p v-else-if="selectedInfo.status === 'added'" class="wp-bvd-note">
            新增节点，没有旧版本字段可对比。
          </p>
          <p v-else-if="selectedInfo.status === 'removed'" class="wp-bvd-note">
            已删除节点，没有新版本字段可对比。
          </p>
          <p v-else-if="selectedInfo.status === 'changed'" class="wp-bvd-note">
            字段差异未包含在接口结果中（差异列表可能已截断）。
          </p>
          <p v-else class="wp-bvd-note">该节点字段没有变化。</p>
        </div>
      </template>

      <p v-if="diff.truncated" class="wp-bvd-truncated">差异过多，仅展示前 500 条。</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "@/api";
import {
  PREVIEW_CANVAS,
  PREVIEW_NODE_LIMIT,
  buildPreviewTree,
  fitPreviewLayout,
  type BlockSnapshot,
  type DiffSide,
  type DiffStatus,
  type PreviewBox,
  type PreviewNode,
} from "@/designer/utils/blockDiffPreview";

const props = defineProps<{ blockId: number; from: number; to: number }>();

type DiffMode = "structure" | "visual" | "list";

interface DiffField {
  from: string;
  to: string;
}

interface DiffRow {
  id: string;
  type?: string;
  label?: string;
  fields?: Record<string, DiffField>;
}

interface DiffSummary {
  added: number;
  removed: number;
  changed: number;
  unchanged: number;
}

interface DiffPayload {
  from?: { version?: number; changelog?: string; rootId?: string; nodeCount?: number };
  to?: { version?: number; changelog?: string; rootId?: string; nodeCount?: number };
  summary: DiffSummary;
  added?: DiffRow[];
  removed?: DiffRow[];
  changed?: DiffRow[];
  truncated?: boolean;
  layoutChanged?: boolean;
}

interface VersionDetail {
  version?: number;
  changelog?: string;
  snapshot?: BlockSnapshot;
}

const modes: { value: DiffMode; label: string }[] = [
  { value: "structure", label: "结构" },
  { value: "visual", label: "视觉" },
  { value: "list", label: "列表" },
];

const loading = ref(false);
const error = ref("");
const diff = ref<DiffPayload | null>(null);
const fromSnapshot = ref<BlockSnapshot | null>(null);
const toSnapshot = ref<BlockSnapshot | null>(null);
const snapshotErrors = ref<Record<DiffSide, string>>({ from: "", to: "" });
const mode = ref<DiffMode>("visual");
const selected = ref<{ side: DiffSide; id: string } | null>(null);
const detailRef = ref<HTMLElement | null>(null);

/** 防止快速切换版本时旧请求覆盖新结果。 */
let requestSeq = 0;

const summary = computed<DiffSummary>(
  () => diff.value?.summary ?? { added: 0, removed: 0, changed: 0, unchanged: 0 }
);
const addedRows = computed<DiffRow[]>(() => diff.value?.added ?? []);
const removedRows = computed<DiffRow[]>(() => diff.value?.removed ?? []);
const changedRows = computed<DiffRow[]>(() => diff.value?.changed ?? []);
const fromVersion = computed(() => Number(diff.value?.from?.version ?? props.from) || 0);
const toVersion = computed(() => Number(diff.value?.to?.version ?? props.to) || 0);
const hasDiff = computed(
  () => summary.value.added + summary.value.removed + summary.value.changed > 0
);

const diffIdSets = computed(() => ({
  added: new Set(addedRows.value.map((row) => row.id)),
  removed: new Set(removedRows.value.map((row) => row.id)),
  changed: new Set(changedRows.value.map((row) => row.id)),
}));

/** 旧版本侧：只可能出现 removed / changed / unchanged。 */
function statusOf(side: DiffSide, id: string): DiffStatus {
  const sets = diffIdSets.value;
  if (side === "from") {
    if (sets.removed.has(id)) return "removed";
    return sets.changed.has(id) ? "changed" : "unchanged";
  }
  if (sets.added.has(id)) return "added";
  return sets.changed.has(id) ? "changed" : "unchanged";
}

const fromTree = computed(() => buildPreviewTree(fromSnapshot.value, (id) => statusOf("from", id)));
const toTree = computed(() => buildPreviewTree(toSnapshot.value, (id) => statusOf("to", id)));
const fromGeometry = computed(() => fitPreviewLayout(fromTree.value.rows));
const toGeometry = computed(() => fitPreviewLayout(toTree.value.rows));

const sides = computed(() => [
  {
    key: "from" as DiffSide,
    label: `旧版本 v${fromVersion.value}`,
    changelog: diff.value?.from?.changelog || "",
    tree: fromTree.value,
    geometry: fromGeometry.value,
    error: snapshotErrors.value.from,
  },
  {
    key: "to" as DiffSide,
    label: `新版本 v${toVersion.value}`,
    changelog: diff.value?.to?.changelog || "",
    tree: toTree.value,
    geometry: toGeometry.value,
    error: snapshotErrors.value.to,
  },
]);

const previewTruncated = computed(() => fromTree.value.truncated || toTree.value.truncated);
const hasVisualCanvas = computed(() =>
  sides.value.some((side) => side.tree.free && side.geometry.boxes.length > 0)
);
const changedById = computed(() => {
  const map = new Map<string, DiffRow>();
  for (const row of changedRows.value) map.set(row.id, row);
  return map;
});

const selectedInfo = computed(() => {
  const current = selected.value;
  if (!current) return null;
  const tree = current.side === "from" ? fromTree.value : toTree.value;
  const node = tree.rows.find((row) => row.id === current.id);
  if (!node) return null;
  const change = changedById.value.get(node.id) ?? null;
  return {
    node,
    side: current.side,
    status: statusOf(current.side, node.id),
    change,
    fields: change?.fields
      ? Object.entries(change.fields).map(([name, field]) => ({ name, ...field }))
      : [],
  };
});

const canvasStyle = { aspectRatio: `${PREVIEW_CANVAS.width} / ${PREVIEW_CANVAS.height}` };

function statusLabel(status: DiffStatus): string {
  if (status === "added") return "新增";
  if (status === "removed") return "删除";
  if (status === "changed") return "修改";
  return "";
}

function statusClass(status: DiffStatus): string {
  return `is-${status}`;
}

function isSelected(side: DiffSide, id: string): boolean {
  return selected.value?.side === side && selected.value.id === id;
}

function selectNode(side: DiffSide, node: PreviewNode) {
  selected.value = { side, id: node.id };
  // 详情在预览下方；点击后滚动到可见位置，避免长树里“点了没反应”。
  void nextTick(() => {
    detailRef.value?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

function clearSelection() {
  selected.value = null;
}

function treeIndent(node: PreviewNode): string {
  return `${6 + Math.min(node.depth, 14) * 14}px`;
}

function flowIndent(node: PreviewNode): string {
  return `${Math.min(node.depth, 10) * 10}px`;
}

function boxStyle(box: PreviewBox) {
  return {
    left: `${(box.left / PREVIEW_CANVAS.width) * 100}%`,
    top: `${(box.top / PREVIEW_CANVAS.height) * 100}%`,
    width: `${(box.width / PREVIEW_CANVAS.width) * 100}%`,
    height: `${(box.height / PREVIEW_CANVAS.height) * 100}%`,
  };
}

function errorMessage(reason: unknown, fallback: string): string {
  if (reason instanceof Error && reason.message) return reason.message;
  return fallback;
}

async function load() {
  if (!props.blockId || !props.from || !props.to) return;
  const seq = ++requestSeq;
  loading.value = true;
  error.value = "";
  diff.value = null;
  fromSnapshot.value = null;
  toSnapshot.value = null;
  snapshotErrors.value = { from: "", to: "" };
  selected.value = null;

  const base = `/blocks/${props.blockId}/versions`;
  const [diffResult, fromResult, toResult] = await Promise.allSettled([
    api.get<DiffPayload>(`${base}/diff/?from=${props.from}&to=${props.to}`),
    api.get<VersionDetail>(`${base}/${props.from}/`, { silent: true }),
    api.get<VersionDetail>(`${base}/${props.to}/`, { silent: true }),
  ]);

  if (seq !== requestSeq) return;

  if (diffResult.status === "rejected") {
    error.value = errorMessage(diffResult.reason, "版本差异加载失败");
    loading.value = false;
    return;
  }

  diff.value = diffResult.value;
  if (fromResult.status === "fulfilled") {
    fromSnapshot.value = fromResult.value?.snapshot ?? null;
  } else {
    snapshotErrors.value.from = errorMessage(fromResult.reason, "版本快照加载失败");
  }
  if (toResult.status === "fulfilled") {
    toSnapshot.value = toResult.value?.snapshot ?? null;
  } else {
    snapshotErrors.value.to = errorMessage(toResult.reason, "版本快照加载失败");
  }
  loading.value = false;
}

watch(
  () => [props.blockId, props.from, props.to],
  () => void load()
);
onMounted(() => void load());
onBeforeUnmount(() => {
  requestSeq += 1;
});
</script>

<style scoped>
.wp-bvd { min-height: 100px; display: flex; flex-direction: column; gap: 8px; }
.wp-bvd-error {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #dc2626;
  font-size: 12px;
}
.wp-bvd-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.wp-bvd-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 7px 9px;
  border-radius: 7px;
  background: #f8fafc;
  color: #475569;
  font-size: 10px;
}
.wp-bvd-summary .added { color: #15803d; }
.wp-bvd-summary .removed { color: #b91c1c; }
.wp-bvd-summary .changed { color: #b45309; }
.wp-bvd-modes { flex: none; }
.wp-bvd-same {
  margin: 0;
  padding: 6px 9px;
  border-radius: 6px;
  background: #f0fdf4;
  color: #15803d;
  font-size: 11px;
}

.wp-bvd-panels {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  align-items: start;
}
@media (max-width: 720px) {
  .wp-bvd-panels { grid-template-columns: 1fr; }
}
.wp-bvd-panel {
  min-width: 0;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.wp-bvd-panel-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.wp-bvd-panel-head strong { flex: none; color: #334155; font-size: 11px; }
.wp-bvd-changelog {
  min-width: 0;
  overflow: hidden;
  color: #94a3b8;
  font-size: 9px;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.wp-bvd-panel-error {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  color: #b91c1c;
  font-size: 11px;
}

.wp-bvd-tree,
.wp-bvd-flow {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 6px;
  max-height: 310px;
  overflow: auto;
}
.wp-bvd-tree-node,
.wp-bvd-flow-node {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 3px 6px;
  border: 1px solid #eef2f8;
  border-left-width: 3px;
  border-radius: 5px;
  background: #fff;
  color: #475569;
  font-size: 10px;
  text-align: left;
  cursor: pointer;
}
.wp-bvd-tree-node:hover,
.wp-bvd-flow-node:hover { border-color: #bfdbfe; background: #f8fafc; }
.wp-bvd-tree-node.is-selected,
.wp-bvd-flow-node.is-selected,
.wp-bvd-box.is-selected {
  outline: 2px solid #2563eb;
  outline-offset: -1px;
}
.wp-bvd-flow-wrap { padding: 6px; }
.wp-bvd-flow-wrap .wp-bvd-flow { padding: 0; max-height: 280px; }
.wp-bvd-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}
.wp-bvd-type {
  flex: none;
  padding: 0 4px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #64748b;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 9px;
}
.wp-bvd-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  color: #334155;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.wp-bvd-label.is-muted { color: #94a3b8; font-size: 9px; }
.wp-bvd-slot {
  flex: none;
  padding: 0 3px;
  border-radius: 3px;
  background: #f5f3ff;
  color: #7c3aed;
  font-size: 8px;
}
.wp-bvd-badge {
  flex: none;
  padding: 0 3px;
  border-radius: 3px;
  background: #f1f5f9;
  color: #64748b;
  font-size: 8px;
}

.wp-bvd-tree-node.is-added,
.wp-bvd-flow-node.is-added,
.wp-bvd-box.is-added {
  border-color: #86efac;
  border-left-color: #22c55e;
  background: #f0fdf4;
}
.wp-bvd-tree-node.is-removed,
.wp-bvd-flow-node.is-removed,
.wp-bvd-box.is-removed {
  border-color: #fca5a5;
  border-left-color: #ef4444;
  background: #fef2f2;
}
.wp-bvd-tree-node.is-changed,
.wp-bvd-flow-node.is-changed,
.wp-bvd-box.is-changed {
  border-color: #fcd34d;
  border-left-color: #f59e0b;
  background: #fffbeb;
}
.wp-bvd-tree-node.is-unchanged,
.wp-bvd-flow-node.is-unchanged { border-left-color: #e2e8f0; }
.wp-bvd-tree-node.is-added .wp-bvd-dot { background: #22c55e; }
.wp-bvd-tree-node.is-removed .wp-bvd-dot { background: #ef4444; }
.wp-bvd-tree-node.is-changed .wp-bvd-dot { background: #f59e0b; }
.wp-bvd-badge.is-added { background: #dcfce7; color: #15803d; }
.wp-bvd-badge.is-removed { background: #fee2e2; color: #b91c1c; }
.wp-bvd-badge.is-changed { background: #fef3c7; color: #b45309; }

.wp-bvd-canvas-wrap { padding: 8px; }
.wp-bvd-canvas {
  position: relative;
  width: 100%;
  max-width: 340px;
  margin: 0 auto;
  overflow: hidden;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  background: #f8fafc;
}
.wp-bvd-box {
  position: absolute;
  display: block;
  box-sizing: border-box;
  overflow: hidden;
  padding: 1px 2px;
  border: 1px solid #94a3b8;
  border-radius: 3px;
  background: rgba(248, 250, 252, 0.92);
  color: #334155;
  font-size: 8px;
  line-height: 1.2;
  text-align: left;
  cursor: pointer;
}
.wp-bvd-box-label {
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.wp-bvd-box.is-added { border-color: #22c55e; background: rgba(220, 252, 231, 0.92); }
.wp-bvd-box.is-removed { border-color: #ef4444; background: rgba(254, 226, 226, 0.92); }
.wp-bvd-box.is-changed { border-color: #f59e0b; background: rgba(254, 243, 199, 0.94); }

.wp-bvd-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  color: #64748b;
  font-size: 9px;
}
.wp-bvd-legend span::before {
  content: "";
  display: inline-block;
  width: 7px;
  height: 7px;
  margin-right: 3px;
  border-radius: 2px;
  background: #cbd5e1;
  vertical-align: middle;
}
.wp-bvd-legend .is-added::before { background: #22c55e; }
.wp-bvd-legend .is-removed::before { background: #ef4444; }
.wp-bvd-legend .is-changed::before { background: #f59e0b; }
.wp-bvd-note {
  margin: 0;
  color: #94a3b8;
  font-size: 9px;
  line-height: 1.5;
}

.wp-bvd-detail {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
}
.wp-bvd-detail-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  color: #475569;
  font-size: 10px;
}
.wp-bvd-detail-head strong { color: #334155; font-size: 11px; }
.wp-bvd-detail-head code { color: #64748b; font-size: 9px; }
.wp-bvd-detail-side { color: #94a3b8; font-size: 9px; }
.wp-bvd-detail-close { margin-left: auto; }
.wp-bvd-fields { display: flex; flex-direction: column; gap: 4px; }
.wp-bvd-field {
  display: flex;
  gap: 5px;
  color: #64748b;
  font-size: 9px;
  word-break: break-all;
}
.wp-bvd-field b { flex: none; color: #475569; }
.wp-bvd-old { color: #b91c1c; text-decoration: line-through; }
.wp-bvd-new { color: #15803d; }

.wp-bvd-section { display: flex; flex-direction: column; gap: 4px; }
.wp-bvd-section > strong { color: #334155; font-size: 11px; }
.wp-bvd-row { padding: 5px 7px; border: 1px solid #eef2f8; border-radius: 6px; font-size: 10px; }
.wp-bvd-row code { margin-right: 6px; color: #64748b; font-size: 9px; }
.wp-bvd-row em { margin-left: 6px; color: #94a3b8; font-style: normal; }
.wp-bvd-row.is-added { border-left: 3px solid #22c55e; }
.wp-bvd-row.is-removed { border-left: 3px solid #ef4444; }
.wp-bvd-row.is-changed { border-left: 3px solid #f59e0b; }
.wp-bvd-row-head { display: flex; align-items: center; gap: 6px; }
.wp-bvd-truncated { color: #94a3b8; font-size: 9px; }
</style>
