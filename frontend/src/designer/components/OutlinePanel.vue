<template>
  <div class="wp-outline">
    <div class="wp-outline-hint">
      点击选择，Ctrl / Shift 点击多选；Delete 删除，Ctrl+C / Ctrl+V 复制粘贴。
    </div>
    <div v-if="!rows.length" class="wp-outline-empty">页面还没有节点</div>
    <div
      v-for="row in rows"
      :key="row.id"
      class="wp-outline-row"
      :class="{ selected: selectedIds.includes(row.id) }"
      :style="{ paddingLeft: 8 + row.depth * 14 + 'px' }"
      @click="onSelect(row.id, $event)"
    >
      <span class="wp-outline-icon">{{ row.icon }}</span>
      <span class="wp-outline-label">{{ row.label }}</span>
      <span v-if="row.slot" class="wp-outline-slot">{{ row.slot }}</span>
      <span class="wp-outline-type">{{ row.node.type }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { SchemaNode } from "@/types";

interface Row {
  id: string;
  node: SchemaNode;
  depth: number;
  label: string;
  icon: string;
  slot?: string;
}

const schema = useSchemaStore();
const components = useComponentStore();
const selectedIds = computed(() => schema.selectedIds);

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

const rows = computed<Row[]>(() => {
  const s = schema.schema;
  if (!s) return [];
  const out: Row[] = [];
  const seen = new Set<string>();
  const walk = (id: string, depth: number, slot?: string) => {
    if (seen.has(id)) return;
    seen.add(id);
    const node = s.nodes[id];
    if (!node) return;
    const meta = components.meta(node.type);
    out.push({
      id,
      node,
      depth,
      label: node.type === "wp-canvas" ? "页面画布" : meta?.label || node.type,
      icon: iconMap[meta?.icon || ""] || (node.type === "wp-canvas" ? "▣" : "◻"),
      slot,
    });
    for (const child of node.children || []) walk(child, depth + 1);
    for (const [slotName, ids] of Object.entries(node.slots || {})) {
      for (const child of ids) walk(child, depth + 1, slotName);
    }
  };
  walk(s.rootId, 0);
  return out;
});

function onSelect(id: string, e: MouseEvent) {
  schema.select(id, e.ctrlKey || e.metaKey || e.shiftKey);
}
</script>

<style scoped>
.wp-outline {
  padding: 8px;
  font-size: 12px;
}
.wp-outline-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.6;
  margin-bottom: 8px;
}
.wp-outline-empty {
  color: var(--el-text-color-secondary);
  text-align: center;
  padding: 24px 0;
}
.wp-outline-row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 6px;
  border-radius: 3px;
  cursor: pointer;
  border: 1px solid transparent;
  min-width: 0;
}
.wp-outline-row:hover {
  background: var(--el-fill-color-light);
}
.wp-outline-row.selected {
  background: var(--el-color-primary-light-9);
  border-color: var(--el-color-primary-light-7);
}
.wp-outline-icon {
  flex: none;
  width: 16px;
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
.wp-outline-type {
  flex: none;
  max-width: 72px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-placeholder);
  font-size: 10px;
}
</style>
