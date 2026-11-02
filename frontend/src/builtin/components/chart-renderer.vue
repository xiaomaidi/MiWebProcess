<template>
  <div class="wp-chart" :style="{ minHeight: H + 'px' }">
    <div v-if="showLegend && legend.length" class="wp-chart-legend">
      <span v-for="(s, i) in legend" :key="i" class="wp-chart-legend-item">
        <i :style="{ background: s.color, borderRadius: effectiveType === 'pie' || effectiveType === 'doughnut' ? '50%' : '2px' }" />
        {{ s.label }}
      </span>
    </div>

    <svg :viewBox="`0 0 ${W} ${H}`" class="wp-chart-svg" preserveAspectRatio="xMidYMid meet">
      <template v-if="isCartesian">
        <g v-if="showGrid">
          <line
            v-for="i in 5"
            :key="i"
            :x1="PAD.left"
            :x2="W - PAD.right"
            :y1="yFor(maxValue * ((i - 1) / 4))"
            :y2="yFor(maxValue * ((i - 1) / 4))"
            stroke="#e4e7ed"
            stroke-width="1"
          />
        </g>
        <!-- 坐标轴 -->
        <line :x1="PAD.left" :x2="W - PAD.right" :y1="plotBottom" :y2="plotBottom" stroke="#c0c4cc" />
        <line :x1="PAD.left" :x2="PAD.left" :y1="PAD.top" :y2="plotBottom" stroke="#c0c4cc" />
        <text
          v-for="i in 5"
          :key="'y' + i"
          :x="PAD.left - 6"
          :y="yFor(maxValue * ((i - 1) / 4)) + 4"
          text-anchor="end"
          font-size="10"
          fill="#909399"
        >
          {{ formatNumber(maxValue * ((i - 1) / 4)) }}
        </text>

        <!-- 柱状 -->
        <g v-if="effectiveType === 'bar'">
          <g v-for="(row, ri) in rows" :key="ri">
            <rect
              v-for="(s, si) in seriesDefs"
              :key="s.key"
              :x="barX(ri, si)"
              :y="yFor(valueOf(row, s.key))"
              :width="barWidth"
              :height="Math.max(0, plotBottom - yFor(valueOf(row, s.key)))"
              :fill="s.color"
              rx="2"
              class="wp-chart-mark"
              @click="onPointClick(row, s)"
            />
            <text :x="groupX(ri) + groupWidth / 2" :y="H - 8" text-anchor="middle" font-size="11" fill="#606266">
              {{ categoryOf(row, ri) }}
            </text>
          </g>
        </g>

        <!-- 折线 / 面积 -->
        <g v-else-if="effectiveType === 'line'">
          <g v-for="(s, si) in seriesDefs" :key="s.key">
            <path v-if="area" :d="areaPath(s)" :fill="s.color" opacity="0.12" />
            <polyline
              :points="linePoints(s)"
              fill="none"
              :stroke="s.color"
              :stroke-width="2"
              :stroke-linejoin="smooth ? 'round' : 'miter'"
            />
            <circle
              v-for="(row, ri) in rows"
              :key="ri"
              :cx="pointX(ri)"
              :cy="yFor(valueOf(row, s.key))"
              r="3.5"
              :fill="s.color"
              class="wp-chart-mark"
              @click="onPointClick(row, s)"
            />
          </g>
          <text v-for="(row, ri) in rows" :key="'x' + ri" :x="pointX(ri)" :y="H - 8" text-anchor="middle" font-size="11" fill="#606266">
            {{ categoryOf(row, ri) }}
          </text>
        </g>

        <!-- 散点 -->
        <g v-else-if="effectiveType === 'scatter'">
          <circle
            v-for="(p, i) in scatterPoints"
            :key="i"
            :cx="p.x"
            :cy="p.y"
            r="5"
            :fill="p.color"
            opacity="0.75"
            class="wp-chart-mark"
            @click="emit('pointClick', p.row)"
          />
        </g>
      </template>

      <!-- 饼图 / 环形图 -->
      <template v-else-if="effectiveType === 'pie' || effectiveType === 'doughnut'">
        <g v-for="(seg, i) in pieSegments" :key="i" class="wp-chart-mark" @click="emit('pointClick', seg.row)">
          <circle v-if="seg.full" :cx="W / 2" :cy="H / 2" :r="Math.min(W, H) / 2 - 18" :fill="seg.color" stroke="#fff" stroke-width="1" />
          <path v-else :d="seg.d" :fill="seg.color" stroke="#fff" stroke-width="1" />
        </g>
        <circle v-if="innerR > 0" :cx="W / 2" :cy="H / 2" :r="innerR" fill="var(--el-bg-color, #fff)" />
        <text v-if="innerR > 0" :x="W / 2" :y="H / 2 + 5" text-anchor="middle" font-size="13" fill="#606266">
          {{ totalValue }}
        </text>
      </template>

      <!-- 仪表盘 -->
      <template v-else-if="effectiveType === 'gauge'">
        <path :d="gaugeBackground" fill="none" stroke="#e4e7ed" stroke-width="16" stroke-linecap="round" />
        <path :d="gaugeForeground" fill="none" stroke="url(#wp-gauge-gradient)" stroke-width="16" stroke-linecap="round" />
        <defs>
          <linearGradient id="wp-gauge-gradient" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" :stop-color="colors[0] || '#409eff'" />
            <stop offset="100%" :stop-color="colors[1] || '#67c23a'" />
          </linearGradient>
        </defs>
        <text :x="W / 2" :y="H / 2 + 10" text-anchor="middle" font-size="30" font-weight="600" fill="#303133">
          {{ gaugeValue }}{{ unit }}
        </text>
        <text :x="W / 2" :y="H / 2 + 34" text-anchor="middle" font-size="11" fill="#909399">
          {{ min }} - {{ max }}
        </text>
      </template>

      <!-- 地图（轻量占位 + 数据列表） -->
      <template v-else-if="effectiveType === 'map'">
        <rect :x="8" :y="8" :width="W - 16" :height="H - 16" rx="8" fill="#f5f7fa" stroke="#dcdfe6" stroke-dasharray="4 4" />
        <text :x="W / 2" :y="H / 2 - 8" text-anchor="middle" font-size="14" fill="#606266">地图需要 ECharts 地图数据</text>
        <text :x="W / 2" :y="H / 2 + 14" text-anchor="middle" font-size="11" fill="#909399">
          当前已加载 {{ rows.length }} 条数据；可切换到「图表 / ECharts option」
        </text>
      </template>

      <!-- 自定义：option.series 优先 -->
      <template v-else>
        <rect :x="8" :y="8" :width="W - 16" :height="H - 16" rx="8" fill="#f8fafc" stroke="#e2e8f0" />
        <text :x="W / 2" :y="H / 2 - 10" text-anchor="middle" font-size="13" fill="#606266">自定义图表</text>
        <text :x="W / 2" :y="H / 2 + 12" text-anchor="middle" font-size="11" fill="#909399">
          option.series 已配置 {{ optionSeriesCount }} 条；未安装 ECharts 时使用内置换算
        </text>
      </template>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";
import { rowsFromScope, type Row } from "../scope-data";

const props = withDefaults(
  defineProps<{
    chartType?: string;
    option?: any;
    data?: Row[];
    xField?: string;
    yField?: string;
    valueField?: string;
    nameField?: string;
    series?: { key: string; label?: string; color?: string }[];
    height?: number;
    colors?: string[];
    showLegend?: boolean;
    showGrid?: boolean;
    smooth?: boolean;
    area?: boolean;
    innerRadius?: number;
    showPercent?: boolean;
    min?: number;
    max?: number;
    unit?: string;
    value?: number;
  }>(),
  {
    chartType: "bar",
    option: () => ({}),
    data: () => [],
    xField: "name",
    yField: "y",
    valueField: "value",
    nameField: "name",
    series: () => [],
    height: 280,
    colors: () => ["#409eff", "#67c23a", "#e6a23c", "#f56c6c", "#8e6bb3", "#36cfc9", "#d3a440"],
    showLegend: true,
    showGrid: true,
    smooth: true,
    area: false,
    innerRadius: 0,
    showPercent: true,
    min: 0,
    max: 100,
    unit: "",
    value: 0,
  }
);

const emit = defineEmits<{ (e: "pointClick", payload: any): void }>();
const scope = inject<RuntimeScope | null>("wp.scope", null);

const W = 640;
const H = computed(() => Math.max(140, Number(props.height) || 280));
const PAD = { left: 42, right: 18, top: 24, bottom: 34 };
const plotBottom = computed(() => H.value - PAD.bottom);
const plotWidth = computed(() => W - PAD.left - PAD.right);

const optionRows = computed<Row[]>(() => {
  const opt = props.option || {};
  if (Array.isArray(props.data) && props.data.length) return props.data;
  if (props.data && typeof props.data === "object") {
    for (const key of ["results", "rows", "items", "data", "records"]) {
      if (Array.isArray((props.data as any)[key])) return (props.data as any)[key];
    }
  }
  if (Array.isArray(opt.series?.[0]?.data) && opt.series[0].data.length) {
    const data = opt.series[0].data;
    return data.map((v: any, i: number) => {
      if (v && typeof v === "object") return { name: v.name ?? opt.xAxis?.data?.[i] ?? i, ...v };
      return { name: opt.xAxis?.data?.[i] ?? i, value: v };
    });
  }
  if (Array.isArray(opt.dataset?.source) && opt.dataset.source.length) return opt.dataset.source;
  return scope ? (rowsFromScope(scope) as Row[]) : [];
});

const rows = computed<Row[]>(() => optionRows.value);
const effectiveType = computed(() => {
  const t = props.chartType || props.option?.series?.[0]?.type || "bar";
  return t === "doughnut" ? "doughnut" : t;
});
const isCartesian = computed(() => ["bar", "line", "scatter"].includes(effectiveType.value));
const optionSeriesCount = computed(() => (Array.isArray(props.option?.series) ? props.option.series.length : 0));
const palette = computed(() => (Array.isArray(props.colors) && props.colors.length ? props.colors : ["#409eff", "#67c23a", "#e6a23c", "#f56c6c"]));

const seriesDefs = computed(() => {
  if (Array.isArray(props.series) && props.series.length) {
    return props.series.map((s, i) => ({ key: s.key, label: s.label || s.key, color: s.color || palette.value[i % palette.value.length] }));
  }
  return [{ key: props.valueField || "value", label: props.valueField || "value", color: palette.value[0] }];
});

const legend = computed(() => {
  if (["pie", "doughnut"].includes(effectiveType.value)) {
    return pieSegments.value.map((s) => ({ label: s.name, color: s.color }));
  }
  return seriesDefs.value.map((s) => ({ label: s.label, color: s.color }));
});

function toNumber(v: any): number {
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}
function categoryOf(row: Row, i: number): string {
  return String(row[props.xField] ?? row.name ?? i + 1);
}
function valueOf(row: Row, key: string): number {
  return Math.max(0, toNumber(row[key]));
}
function formatNumber(v: number): string {
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(1) + "w";
  return String(Math.round(v * 100) / 100);
}

const maxValue = computed(() => {
  let m = 0;
  for (const row of rows.value) for (const s of seriesDefs.value) m = Math.max(m, toNumber(row[s.key]));
  return m > 0 ? m : 1;
});
function yFor(v: number): number {
  return PAD.top + (plotBottom.value - PAD.top) * (1 - v / maxValue.value);
}
const groupWidth = computed(() => Math.max(24, Math.min(90, plotWidth.value / Math.max(1, rows.value.length))));
const barWidth = computed(() => Math.max(4, Math.min(28, (groupWidth.value - 8) / Math.max(1, seriesDefs.value.length) - 3)));
function groupX(i: number): number {
  return PAD.left + i * groupWidth.value + 4;
}
function barX(i: number, si: number): number {
  return groupX(i) + si * (barWidth.value + 3);
}
function pointX(i: number): number {
  return PAD.left + (plotWidth.value * (i + 0.5)) / Math.max(1, rows.value.length);
}
function linePoints(s: any): string {
  return rows.value.map((row, i) => `${pointX(i)},${yFor(valueOf(row, s.key))}`).join(" ");
}
function areaPath(s: any): string {
  const pts = rows.value.map((row, i) => `${pointX(i)},${yFor(valueOf(row, s.key))}`);
  if (!pts.length) return "";
  return `M ${pointX(0)},${plotBottom.value} L ${pts.join(" L ")} L ${pointX(rows.value.length - 1)},${plotBottom.value} Z`;
}

const scatterPoints = computed(() => {
  const xs = rows.value.map((r) => toNumber(r[props.xField] ?? r.x));
  const ys = rows.value.map((r) => toNumber(r[props.yField] ?? r.y));
  const maxX = Math.max(1, ...xs);
  const maxY = Math.max(1, ...ys);
  return rows.value.map((row, i) => ({
    row,
    x: PAD.left + (xs[i] / maxX) * plotWidth.value,
    y: plotBottom.value - (ys[i] / maxY) * (plotBottom.value - PAD.top),
    color: palette.value[i % palette.value.length],
  }));
});

const totalValue = computed(() => rows.value.reduce((acc, row) => acc + Math.max(0, toNumber(row[props.valueField] ?? row.value)), 0));
const innerR = computed(() => {
  const r = Math.min(W, H.value) / 2 - 18;
  return effectiveType.value === "doughnut" ? Math.max(0, (r * Math.min(90, Math.max(0, props.innerRadius))) / 100) : 0;
});

interface PieSeg {
  row: Row;
  name: string;
  value: number;
  percent: number;
  color: string;
  d: string;
  full?: boolean;
}
const pieSegments = computed<PieSeg[]>(() => {
  const radius = Math.min(W, H.value) / 2 - 18;
  const total = totalValue.value;
  if (total <= 0) return [];
  let angle = -Math.PI / 2;
  const out: PieSeg[] = [];
  rows.value.forEach((row, i) => {
    const v = Math.max(0, toNumber(row[props.valueField] ?? row.value));
    if (v <= 0) return;
    const frac = v / total;
    const start = angle;
    const end = angle + frac * Math.PI * 2;
    angle = end;
    const cx = W / 2;
    const cy = H.value / 2;
    const x0 = cx + radius * Math.cos(start);
    const y0 = cy + radius * Math.sin(start);
    const x1 = cx + radius * Math.cos(end);
    const y1 = cy + radius * Math.sin(end);
    const large = end - start > Math.PI ? 1 : 0;
    const ir = innerR.value;
    const ix1 = cx + ir * Math.cos(end);
    const iy1 = cy + ir * Math.sin(end);
    const ix0 = cx + ir * Math.cos(start);
    const iy0 = cy + ir * Math.sin(start);
    const d =
      ir > 0
        ? `M ${x0} ${y0} A ${radius} ${radius} 0 ${large} 1 ${x1} ${y1} L ${ix1} ${iy1} A ${ir} ${ir} 0 ${large} 0 ${ix0} ${iy0} Z`
        : `M ${cx} ${cy} L ${x0} ${y0} A ${radius} ${radius} 0 ${large} 1 ${x1} ${y1} Z`;
    out.push({
      row,
      name: String(row[props.nameField] ?? row.name ?? i + 1),
      value: v,
      percent: Math.round(frac * 1000) / 10,
      color: palette.value[i % palette.value.length],
      d,
      full: frac >= 0.9999 && ir <= 0,
    });
  });
  return out;
});

const gaugeValue = computed(() => Math.max(props.min, Math.min(props.max, Number(props.value) || 0)));
const gaugePercent = computed(() => (props.max > props.min ? (gaugeValue.value - props.min) / (props.max - props.min) : 0));
function gaugeArc(percent: number): string {
  const cx = W / 2;
  const cy = H.value / 2 + 20;
  const r = Math.min(W, H.value) / 2 - 40;
  const start = Math.PI;
  const end = Math.PI + Math.PI * percent;
  const x0 = cx + r * Math.cos(start);
  const y0 = cy + r * Math.sin(start);
  const x1 = cx + r * Math.cos(end);
  const y1 = cy + r * Math.sin(end);
  const large = percent > 0.5 ? 1 : 0;
  return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
}
const gaugeBackground = computed(() => gaugeArc(1));
const gaugeForeground = computed(() => gaugeArc(Math.max(0.001, gaugePercent.value)));

function onPointClick(row: Row, s: any) {
  emit("pointClick", { row, key: s.key, label: s.label, value: valueOf(row, s.key) });
}
</script>

<style scoped>
.wp-chart {
  width: 100%;
  position: relative;
}
.wp-chart-svg {
  display: block;
  width: 100%;
  height: auto;
  overflow: visible;
}
.wp-chart-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 2px;
  font-size: 12px;
  color: #606266;
}
.wp-chart-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.wp-chart-legend-item i {
  display: inline-block;
  width: 10px;
  height: 10px;
}
.wp-chart-mark {
  cursor: pointer;
}
.wp-chart-mark:hover {
  opacity: 0.82;
}
</style>
