<template>
  <div class="wp-piechart">
    <div class="wp-piechart-body">
      <svg :viewBox="`0 0 ${size} ${size}`" class="wp-piechart-svg">
        <g v-for="(seg, i) in segments" :key="i">
          <path
            v-if="!seg.full"
            class="wp-piechart-seg"
            :d="seg.d"
            :fill="seg.color"
            :stroke="seg.color"
            stroke-width="1"
            @click="onPointClick(seg)"
          />
          <circle
            v-else
            class="wp-piechart-seg"
            :cx="center"
            :cy="center"
            :r="radius"
            :fill="seg.color"
            @click="onPointClick(seg)"
          />
        </g>
      </svg>
      <div v-if="rows.length === 0" class="wp-piechart-empty">暂无数据</div>
    </div>
    <div v-if="props.showLegend && segments.length" class="wp-piechart-legend">
      <span v-for="(seg, i) in segments" :key="i" class="wp-piechart-legend-item">
        <i :style="{ background: seg.color }"></i>
        {{ seg.name }}
        <em v-if="props.showPercent">（{{ seg.percent }}%）</em>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";
import { rowsFromScope, type Row } from "../scope-data";

const PALETTE = [
  "#409eff",
  "#67c23a",
  "#e6a23c",
  "#f56c6c",
  "#909399",
  "#8e6bb3",
  "#36cfc9",
  "#d3a440",
];

interface Segment {
  row: Row;
  name: string;
  value: number;
  percent: number;
  color: string;
  d?: string;
  full?: boolean;
}

const props = withDefaults(
  defineProps<{
    nameKey?: string;
    valueKey?: string;
    height?: number;
    showLegend?: boolean;
    showPercent?: boolean;
  }>(),
  {
    nameKey: "name",
    valueKey: "value",
    height: 260,
    showLegend: true,
    showPercent: true,
  }
);

const emit = defineEmits<{
  (e: "pointClick", payload: { row: Row; value: number; percent: number }): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const rows = computed<Row[]>(() => (scope ? rowsFromScope(scope) : []));

function toNumber(value: unknown): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
    return Number(value);
  }
  return 0;
}

const size = computed(() => Math.max(100, Math.round(props.height)));

const center = computed(() => size.value / 2);

const radius = computed(() => size.value / 2 - 4);

const segments = computed<Segment[]>(() => {
  const total = rows.value.reduce((sum, row) => {
    const n = toNumber(row[props.valueKey]);
    return sum + (n > 0 ? n : 0);
  }, 0);
  if (total <= 0) return [];
  let angle = -Math.PI / 2;
  return rows.value
    .map((row, i) => {
      const value = toNumber(row[props.valueKey]);
      const v = value > 0 ? value : 0;
      const frac = v / total;
      const start = angle;
      angle += frac * Math.PI * 2;
      const end = angle;
      const seg: Segment = {
        row,
        name: String(row[props.nameKey] ?? i + 1),
        value: v,
        percent: Math.round(frac * 1000) / 10,
        color: PALETTE[i % PALETTE.length],
      };
      if (frac >= 0.9999) {
        seg.full = true;
      } else {
        const r = radius.value;
        const cx = center.value;
        const cy = center.value;
        const x0 = cx + r * Math.cos(start);
        const y0 = cy + r * Math.sin(start);
        const x1 = cx + r * Math.cos(end);
        const y1 = cy + r * Math.sin(end);
        const large = end - start > Math.PI ? 1 : 0;
        seg.d = `M ${cx} ${cy} L ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)} Z`;
      }
      return seg;
    })
    .filter((seg) => seg.value > 0);
});

function onPointClick(seg: Segment): void {
  emit("pointClick", { row: seg.row, value: seg.value, percent: seg.percent });
}
</script>

<style scoped>
.wp-piechart {
  width: 100%;
}
.wp-piechart-body {
  position: relative;
}
.wp-piechart-svg {
  display: block;
  width: auto;
  height: auto;
  max-width: 100%;
  margin: 0 auto;
}
.wp-piechart-seg {
  cursor: pointer;
}
.wp-piechart-seg:hover {
  opacity: 0.85;
}
.wp-piechart-empty {
  position: absolute;
  left: 0;
  right: 0;
  top: 50%;
  text-align: center;
  font-size: 13px;
  color: #909399;
}
.wp-piechart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  font-size: 12px;
  color: #606266;
}
.wp-piechart-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.wp-piechart-legend-item i {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}
.wp-piechart-legend-item em {
  font-style: normal;
  color: #909399;
}
</style>
