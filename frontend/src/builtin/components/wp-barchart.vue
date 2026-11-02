<template>
  <div class="wp-barchart">
    <div v-if="props.showLegend && series.length" class="wp-barchart-legend">
      <span v-for="s in series" :key="s.key" class="wp-barchart-legend-item">
        <i :style="{ background: s.color }"></i>{{ s.label }}
      </span>
    </div>
    <svg
      :viewBox="`0 0 ${viewW} ${viewH}`"
      class="wp-barchart-svg"
      preserveAspectRatio="xMidYMid meet"
    >
      <g v-if="props.showGrid">
        <line
          v-for="i in 4"
          :key="i"
          :x1="padLeft"
          :x2="viewW - 4"
          :y1="yFor((maxValue * i) / 4)"
          :y2="yFor((maxValue * i) / 4)"
          stroke="#e4e7ed"
          stroke-width="1"
        />
      </g>
      <g v-for="(row, ri) in rows" :key="ri">
        <rect
          v-for="(s, si) in series"
          :key="s.key"
          class="wp-barchart-bar"
          :x="barX(ri, si)"
          :y="yFor(valueOf(row, s.key))"
          :width="props.barWidth"
          :height="plotBottom - yFor(valueOf(row, s.key))"
          :fill="s.color"
          @click="onPointClick(row, s)"
        />
        <text
          :x="groupX(ri) + groupW / 2"
          :y="viewH - 8"
          text-anchor="middle"
          font-size="12"
          fill="#606266"
        >
          {{ String(row[props.nameKey] ?? ri) }}
        </text>
      </g>
      <line :x1="padLeft" :x2="viewW - 4" :y1="plotBottom" :y2="plotBottom" stroke="#c0c4cc" stroke-width="1" />
    </svg>
    <div v-if="rows.length === 0" class="wp-barchart-empty">暂无数据</div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";
import { rowsFromScope, type Row } from "../scope-data";

interface SeriesDef {
  key: string;
  label: string;
  color: string;
}

const props = withDefaults(
  defineProps<{
    series?: SeriesDef[];
    nameKey?: string;
    height?: number;
    showLegend?: boolean;
    showGrid?: boolean;
    barWidth?: number;
  }>(),
  {
    series: () => [{ key: "value", label: "值", color: "#409eff" }],
    nameKey: "name",
    height: 260,
    showLegend: true,
    showGrid: true,
    barWidth: 24,
  }
);

const emit = defineEmits<{
  (
    e: "pointClick",
    payload: { row: Row; key: string; label: string; value: number }
  ): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const rows = computed<Row[]>(() => (scope ? rowsFromScope(scope) : []));

const series = computed<SeriesDef[]>(() => props.series);

const PAD_TOP = 16;
const PAD_BOTTOM = 24;
const PAD_LEFT = 8;
const GROUP_GAP = 16;
const BAR_GAP = 4;

/** 模板引用的左内边距 */
const padLeft = PAD_LEFT;

const viewH = computed(() => Math.max(100, props.height));

const plotH = computed(() => viewH.value - PAD_TOP - PAD_BOTTOM);

const plotBottom = computed(() => viewH.value - PAD_BOTTOM);

const groupW = computed(
  () => series.value.length * props.barWidth + Math.max(0, series.value.length - 1) * BAR_GAP
);

const viewW = computed(() =>
  Math.max(320, PAD_LEFT + rows.value.length * (groupW.value + GROUP_GAP) + 8)
);

const maxValue = computed(() => {
  let max = 0;
  for (const row of rows.value) {
    for (const s of series.value) {
      max = Math.max(max, toNumber(row[s.key]));
    }
  }
  return max > 0 ? max : 1;
});

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return 0;
}

function valueOf(row: Row, key: string): number {
  const n = toNumber(row[key]);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function yFor(value: number): number {
  return PAD_TOP + plotH.value * (1 - value / maxValue.value);
}

function groupX(ri: number): number {
  return PAD_LEFT + ri * (groupW.value + GROUP_GAP);
}

function barX(ri: number, si: number): number {
  return groupX(ri) + si * (props.barWidth + BAR_GAP);
}

function onPointClick(row: Row, s: SeriesDef): void {
  emit("pointClick", { row, key: s.key, label: s.label, value: valueOf(row, s.key) });
}
</script>

<style scoped>
.wp-barchart {
  position: relative;
  width: 100%;
}
.wp-barchart-legend {
  display: flex;
  gap: 12px;
  margin-bottom: 4px;
  font-size: 12px;
  color: #606266;
}
.wp-barchart-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.wp-barchart-legend-item i {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.wp-barchart-svg {
  display: block;
  width: 100%;
  height: auto;
}
.wp-barchart-bar {
  cursor: pointer;
}
.wp-barchart-bar:hover {
  opacity: 0.85;
}
.wp-barchart-empty {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  text-align: center;
  font-size: 13px;
  color: #909399;
}
</style>
