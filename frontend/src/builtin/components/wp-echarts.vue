<template>
  <div class="wp-echarts" :style="{ minHeight: `${heightPx}px` }">
    <div ref="chartEl" class="wp-echarts-canvas" :style="{ height: `${heightPx}px` }"></div>
    <div v-if="error" class="wp-echarts-error">{{ error }}</div>
    <div v-if="loading" class="wp-echarts-loading">图表加载中…</div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = withDefaults(
  defineProps<{
    option?: any;
    chartType?: string;
    height?: number;
    theme?: string;
    renderer?: "canvas" | "svg";
    autoResize?: boolean;
    mapName?: string;
    geoJson?: any;
    loading?: boolean;
  }>(),
  {
    option: () => ({}),
    chartType: "line",
    height: 320,
    theme: "default",
    renderer: "canvas",
    autoResize: true,
    mapName: "custom",
    geoJson: null,
    loading: false,
  }
);

const heightPx = computed(() => {
  const raw = Number(String(props.height ?? "").replace(/px$/i, "").trim());
  return Number.isFinite(raw) && raw > 0 ? raw : 320;
});

const emit = defineEmits<{
  pointClick: [params: any];
  chartEvent: [payload: { type: string; params: any }];
}>();

const chartEl = ref<HTMLElement | null>(null);
const error = ref("");
let chart: any = null;
let echarts: any = null;
let observer: ResizeObserver | null = null;
let resizeHandler: (() => void) | null = null;

function parseOption(value: any): any {
  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return null;
    return JSON.parse(text);
  }
  return value && typeof value === "object" ? value : null;
}

function demoOption(type: string): any {
  const axis = {
    tooltip: { trigger: "axis" },
    legend: { top: 6 },
    grid: { left: 46, right: 24, top: 46, bottom: 36 },
    xAxis: { type: "category", data: ["一月", "二月", "三月", "四月", "五月", "六月"] },
    yAxis: { type: "value" },
  };
  const values = [120, 200, 150, 80, 170, 230];
  switch (type) {
    case "bar":
      return { ...axis, series: [{ type: "bar", name: "数据", data: values, itemStyle: { borderRadius: [4, 4, 0, 0] } }] };
    case "pie":
    case "doughnut":
      return {
        tooltip: { trigger: "item" },
        legend: { bottom: 0 },
        series: [{
          type: "pie",
          radius: type === "doughnut" ? ["42%", "68%"] : "68%",
          label: { show: true, formatter: "{b}: {c}" },
          data: [
            { name: "产品 A", value: 40 }, { name: "产品 B", value: 30 },
            { name: "产品 C", value: 20 }, { name: "其他", value: 10 },
          ],
        }],
      };
    case "scatter":
      return {
        tooltip: { trigger: "item" },
        xAxis: { type: "value" }, yAxis: { type: "value" },
        series: [{ type: "scatter", symbolSize: 14, data: [[10, 20], [30, 45], [50, 30], [70, 80], [90, 60]] }],
      };
    case "radar":
      return {
        tooltip: {},
        radar: { indicator: ["销售", "管理", "技术", "客服", "研发", "市场"].map((name) => ({ name, max: 100 })) },
        series: [{ type: "radar", data: [{ value: [80, 65, 90, 70, 85, 60], name: "能力" }] }],
      };
    case "gauge":
      return { series: [{ type: "gauge", progress: { show: true }, detail: { valueAnimation: true, formatter: "{value}%" }, data: [{ value: 72 }] }] };
    case "funnel":
      return { tooltip: { trigger: "item" }, series: [{ type: "funnel", data: [{ name: "访问", value: 100 }, { name: "咨询", value: 60 }, { name: "下单", value: 30 }, { name: "成交", value: 15 }] }] };
    case "tree":
      return { series: [{ type: "tree", data: [{ name: "根节点", children: [{ name: "分支 A" }, { name: "分支 B" }] }] }] };
    case "sunburst":
      return { series: [{ type: "sunburst", data: [{ name: "根", children: [{ name: "A", value: 10 }, { name: "B", value: 20 }] }] }] };
    case "sankey":
      return { series: [{ type: "sankey", data: [{ name: "A" }, { name: "B" }, { name: "C" }], links: [{ source: "A", target: "B", value: 10 }, { source: "B", target: "C", value: 8 }] }] };
    case "graph":
      return { series: [{ type: "graph", layout: "force", data: [{ name: "A" }, { name: "B" }, { name: "C" }], links: [{ source: "A", target: "B" }, { source: "B", target: "C" }] }] };
    case "heatmap": {
      const data: any[] = [];
      for (let x = 0; x < 6; x++) for (let y = 0; y < 4; y++) data.push([x, y, (x + 1) * (y + 2)]);
      return { tooltip: {}, grid: { left: 60, right: 20, top: 30, bottom: 40 }, xAxis: { type: "category", data: ["一", "二", "三", "四", "五", "六"] }, yAxis: { type: "category", data: ["A", "B", "C", "D"] }, visualMap: { min: 0, max: 30, calculable: true, orient: "horizontal", left: "center", bottom: 0 }, series: [{ type: "heatmap", data }] };
    }
    case "candlestick":
      return { tooltip: { trigger: "axis" }, xAxis: { data: ["周一", "周二", "周三", "周四"] }, yAxis: {}, series: [{ type: "candlestick", data: [[20, 34, 10, 38], [40, 35, 30, 50], [31, 38, 33, 44], [38, 15, 5, 42]] }] };
    case "boxplot":
      return { tooltip: {}, xAxis: { type: "category", data: ["A", "B"] }, yAxis: {}, series: [{ type: "boxplot", data: [[10, 20, 30, 40, 50], [5, 15, 25, 35, 45]] }] };
    case "line":
    default:
      return { ...axis, series: [{ type: "line", name: "数据", smooth: true, areaStyle: { opacity: 0.12 }, data: values }] };
  }
}

function currentOption(): any {
  let option: any = parseOption(props.option);
  if (!option || !Object.keys(option).length) option = demoOption(props.chartType);
  // ECharts 可能给 option 补默认字段；克隆避免反向修改 props，触发深度 watch 循环。
  try {
    option = JSON.parse(JSON.stringify(option));
  } catch {
    /* 保留原始对象 */
  }
  if (props.geoJson) {
    try {
      const geo = typeof props.geoJson === "string" ? JSON.parse(props.geoJson) : props.geoJson;
      echarts?.registerMap(props.mapName || "custom", geo);
    } catch (e: any) {
      error.value = `地图数据解析失败：${e?.message || e}`;
    }
  }
  return option;
}

async function init() {
  if (!chartEl.value || echarts) return;
  try {
    echarts = await import("echarts");
    chart = echarts.init(chartEl.value, props.theme && props.theme !== "default" ? props.theme : undefined, {
      renderer: props.renderer,
    });
    render();
    bindEvents();
    if (props.autoResize && typeof ResizeObserver !== "undefined") {
      observer = new ResizeObserver(() => chart?.resize());
      observer.observe(chartEl.value);
    }
    resizeHandler = () => chart?.resize();
    window.addEventListener("resize", resizeHandler);
  } catch (e: any) {
    error.value = `ECharts 初始化失败：${e?.message || e}`;
  }
}

function render() {
  if (!chart) return;
  try {
    error.value = "";
    chart.setOption(currentOption(), { notMerge: true, lazyUpdate: false });
  } catch (e: any) {
    error.value = `ECharts 配置错误：${e?.message || e}`;
  }
}

function bindEvents() {
  if (!chart) return;
  for (const name of ["click", "dblclick", "legendselectchanged", "datazoom", "brushselected", "geoselectchanged"]) {
    chart.on(name, (params: any) => {
      emit("chartEvent", { type: name, params });
      if (name === "click") emit("pointClick", params);
    });
  }
}

watch(
  () => [JSON.stringify(props.option ?? {}), props.chartType, JSON.stringify(props.geoJson ?? null), props.mapName],
  async () => {
    if (!chart) return init();
    await nextTick();
    render();
  }
);

watch(
  () => [props.theme, props.renderer],
  async () => {
    if (!chart) return;
    chart.dispose();
    chart = null;
    echarts = null;
    await init();
  }
);

watch(
  () => props.height,
  async () => {
    await nextTick();
    chart?.resize();
  }
);

onMounted(init);

onBeforeUnmount(() => {
  observer?.disconnect();
  observer = null;
  if (resizeHandler) window.removeEventListener("resize", resizeHandler);
  resizeHandler = null;
  chart?.dispose();
  chart = null;
  echarts = null;
});

defineExpose({ getChart: () => chart, resize: () => chart?.resize() });
</script>

<style scoped>
.wp-echarts {
  position: relative;
  width: 100%;
  min-height: 160px;
}
.wp-echarts-canvas {
  width: 100%;
}
.wp-echarts-error {
  position: absolute;
  inset: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  border: 1px dashed var(--el-color-danger);
  border-radius: 6px;
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  font-size: 12px;
  text-align: center;
}
.wp-echarts-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
