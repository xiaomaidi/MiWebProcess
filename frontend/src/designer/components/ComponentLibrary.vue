<template>
  <div class="wp-libs">
    <el-input v-model="keyword" size="small" clearable placeholder="搜索组件 / 标签 / 类型" class="wp-libs-search">
      <template #prefix>⌕</template>
    </el-input>
    <div class="wp-libs-hint">拖拽到画布；点击插入到当前选中容器（否则画布根）。</div>
    <template v-for="group in grouped" :key="group.category.key">
      <div class="wp-libs-cat">
        <span>{{ group.category.label }}</span>
        <span class="wp-libs-count">{{ group.items.length }}</span>
      </div>
      <div
        v-for="m in group.items"
        :key="m.name"
        class="wp-lib-card"
        draggable="true"
        :title="`${m.label}（${m.name}）`"
        @dragstart="onDragStart($event, m.name)"
        @click="onClick(m.name)"
      >
        <span class="wp-lib-icon">{{ iconOf(m) }}</span>
        <span class="wp-lib-label">{{ m.label }}</span>
        <span v-if="m.source && m.source !== 'element-plus'" class="wp-lib-badge">{{ sourceLabel(m.source || "element-plus") }}</span>
        <span class="wp-lib-name">{{ m.name }}</span>
      </div>
    </template>
    <el-empty v-if="!grouped.length" description="没有匹配的组件" :image-size="60" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { ComponentCategory, ComponentMeta, ComponentSource } from "@/types";
import { setComponentDrag, withHistory } from "../util";

const schema = useSchemaStore();
const components = useComponentStore();
const keyword = ref("");

const iconMap: Record<string, string> = {
  Grid: "▦", Layout: "◫", EditPen: "✎", DataBoard: "▤", ChatDotRound: "◌",
  Compass: "◎", Picture: "▧", TrendCharts: "◔", MagicStick: "✦", SetUp: "⚙",
  Pointer: "➤", Link: "↗", Document: "▤", CollectionTag: "▣", Bell: "◔",
  User: "◉", Star: "★", Minus: "—", Postcard: "▭", Box: "▢", Top: "⌃",
  Fold: "≡", FullScreen: "▣", Bottom: "⌄", Operation: "⇄", Menu: "≡",
  Sort: "↕", ScaleToOriginal: "◧", Files: "▤", Rank: "▥", ArrowDown: "⌄",
  CircleCheck: "◉", Finished: "☑", Switch: "⇄", Brush: "✎", Calendar: "▦",
  Clock: "◷", Timer: "◷", Share: "⌘", Upload: "⇧", Selection: "☑",
  ChatLineSquare: "▣", More: "…", DataLine: "◔", Odometer: "◔", Loading: "◌",
  CircleCheckFilled: "✓", Warning: "⚠", InfoFilled: "ⓘ", QuestionFilled: "?",
  Guide: "➤", Back: "←", Paperclip: "⌘", VideoCamera: "▶", Microphone: "◉",
  Monitor: "▣", Cpu: "▤", Histogram: "▥", PieChart: "◔", MapLocation: "◎",
  CopyDocument: "⧉", Refresh: "↻", SwitchButton: "⇄", Position: "⌖",
  Stamp: "◇",
};

function iconOf(m: ComponentMeta): string {
  return iconMap[m.icon || ""] || "▣";
}

function sourceLabel(s: ComponentSource): string {
  return { native: "HTML", chart: "图表", rich: "富文本", advanced: "高级", legacy: "旧版", custom: "自定义", "custom-sandbox": "沙箱", "element-plus": "EP" }[s] || s;
}

const grouped = computed<{ category: ComponentCategory; items: ComponentMeta[] }[]>(() => {
  const kw = keyword.value.trim().toLowerCase();
  const by = components.byCategory;
  const out: { category: ComponentCategory; items: ComponentMeta[] }[] = [];
  for (const cat of components.categories) {
    const items = (by[cat.key] || []).filter((m) => {
      if (!kw) return true;
      return [m.label, m.name, m.category, m.source || "", m.element || ""].join(" ").toLowerCase().includes(kw);
    });
    if (items.length) out.push({ category: cat, items });
  }
  return out;
});

function onDragStart(e: DragEvent, name: string) {
  setComponentDrag(e, name);
}

/** 当前选中节点若可容纳子节点则插入其中，否则画布根。 */
function resolveParentId(): string {
  const s = schema.schema;
  if (!s) return "";
  const selId = schema.selectedId;
  if (selId && selId !== s.rootId) {
    const sel = s.nodes[selId];
    const m = sel ? components.meta(sel.type) : undefined;
    const accepts = m?.accept_children || m?.accepts || [];
    if (sel && m && (accepts.length > 0 || m.is_container)) return selId;
  }
  return s.rootId;
}

function onClick(name: string) {
  const parentId = resolveParentId();
  if (!parentId) return;
  withHistory("添加组件", () => {
    schema.insertComponent(name, parentId);
  });
  ElMessage.success("已添加组件");
}
</script>

<style scoped>
.wp-libs {
  padding: 8px;
  font-size: 13px;
}
.wp-libs-search {
  margin-bottom: 6px;
}
.wp-libs-hint {
  color: #909399;
  font-size: 12px;
  margin-bottom: 8px;
  line-height: 1.5;
}
.wp-libs-cat {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: #606266;
  margin: 10px 0 6px;
  font-size: 12px;
}
.wp-libs-count {
  color: #a8abb2;
  font-weight: 400;
}
.wp-lib-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  margin-bottom: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fff;
  cursor: grab;
  user-select: none;
}
.wp-lib-card:hover {
  border-color: var(--wp-accent, #409eff);
  box-shadow: 0 1px 4px rgba(64, 158, 255, 0.25);
}
.wp-lib-icon {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: #f0f7ff;
  border-radius: 4px;
  font-size: 14px;
  flex: none;
}
.wp-lib-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-lib-badge {
  font-size: 10px;
  color: #8e6bb3;
  border: 1px solid #e6dcf5;
  background: #f8f4ff;
  border-radius: 3px;
  padding: 0 3px;
  flex: none;
}
.wp-lib-name {
  color: #909399;
  font-size: 11px;
  max-width: 78px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
