<template>
  <section class="wp-report">
    <header class="wp-report-head">
      <div>
        <h3>{{ title || "数据报表" }}</h3>
        <span class="wp-report-sub">按 {{ groupBy || "全部" }} 分组 · {{ rows.length }} 行 · {{ total }} 条源数据</span>
      </div>
      <div class="wp-report-actions">
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="exportable" size="small" :disabled="!rows.length" @click="exportCsv">导出 CSV</el-button>
      </div>
    </header>
    <ChartRenderer
      v-if="showChart && rows.length && !useCrossTab"
      class="wp-report-chart"
      :chart-type="chartType"
      :data="chartRows"
      x-field="name"
      value-field="value"
      :height="220"
      :show-legend="false"
      :show-grid="true"
    />
    <el-table
      v-if="useCrossTab"
      v-loading="loading"
      :data="crossRows"
      :border="border"
      :stripe="stripe"
      size="small"
      empty-text="暂无数据"
    >
      <el-table-column prop="key" :label="groupLabel" min-width="150" />
      <el-table-column
        v-for="col in crossColumns"
        :key="col"
        :label="col || '未分类'"
        width="130"
        align="right"
      >
        <template #default="{ row }">{{ row[col] ?? "" }}</template>
      </el-table-column>
    </el-table>
    <el-table v-else v-loading="loading" :data="rows" :border="border" :stripe="stripe" size="small" empty-text="暂无数据">
      <el-table-column prop="key" :label="groupLabel" min-width="150">
        <template #default="{ row }">
          <span class="wp-report-key">{{ row.key || "未分类" }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="count" label="记录数" width="100" align="right" />
      <el-table-column
        v-for="col in metricColumns"
        :key="col.key"
        :prop="col.key"
        :label="col.label"
        width="130"
        align="right"
      />
    </el-table>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from "vue";
import type { RuntimeScope } from "@/types";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { contentAppCode } from "../content-api";
import ChartRenderer from "./chart-renderer.vue";

const scope = inject<RuntimeScope | null>("wp.scope", null);

const props = withDefaults(
  defineProps<{
    dataModelId?: number | string;
    groupBy?: string;
    groupBy2?: string;
    crossTab?: boolean;
    groupLabel?: string;
    groupLabel2?: string;
    metrics?: string;
    title?: string;
    filters?: Record<string, any>;
    limit?: number;
    exportable?: boolean;
    border?: boolean;
    stripe?: boolean;
    showChart?: boolean;
    chartType?: string;
  }>(),
  {
    dataModelId: 0,
    groupBy: "",
    groupBy2: "",
    crossTab: false,
    groupLabel: "分组",
    groupLabel2: "列",
    metrics: "count",
    title: "",
    filters: () => ({}),
    limit: 200,
    exportable: true,
    border: false,
    stripe: true,
    showChart: false,
    chartType: "bar",
  }
);

const rows = ref<Record<string, any>[]>([]);
const total = ref(0);
const loading = ref(false);
const crossRows = ref<Record<string, any>[]>([]);
const crossColumns = ref<string[]>([]);
const crossMetric = ref("");
const useCrossTab = computed(() => props.crossTab && !!props.groupBy2);

const chartRows = computed(() => {
  const metric = metricColumns.value[0]?.key || "count";
  return rows.value.map((row) => ({ name: row.key || "未分类", value: Number(row[metric] || 0) }));
});

const metricColumns = computed(() => {
  const names = String(props.metrics || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  const out: { key: string; label: string }[] = [];
  for (const m of names) {
    if (!m.includes(":")) continue;
    const [fn, field] = m.split(":");
    const key = `${fn}_${field}`;
    if (out.some((x) => x.key === key)) continue;
    const fnLabel = { sum: "合计", avg: "平均", min: "最小", max: "最大", count_distinct: "去重" }[fn] || fn;
    out.push({ key, label: `${field} ${fnLabel}` });
  }
  return out;
});

function qs(params: Record<string, any>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    search.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
  }
  return search.toString();
}

async function load() {
  const modelId = Number(props.dataModelId);
  if (!modelId) return;
  loading.value = true;
  try {
    const query = qs({
      group_by: props.groupBy,
      group_by2: props.groupBy2,
      metrics: props.metrics,
      limit: props.limit,
      ...(props.filters || {}),
    });
    const code = contentAppCode(scope);
    const path = code
      ? `/runtime/${code}/content/${modelId}/report/?${query}`
      : `/models/${modelId}/records/report/?${query}`;
    const res = await api.get<any>(path);
    rows.value = Array.isArray(res?.rows) ? res.rows : [];
    crossRows.value = Array.isArray(res?.cross) ? res.cross : [];
    crossColumns.value = Array.isArray(res?.cross_columns) ? res.cross_columns : [];
    crossMetric.value = String(res?.cross_metric || "count");
    total.value = Number(res?.count) || 0;
  } catch (e: any) {
    ElMessage.error(e?.message || "报表加载失败");
  } finally {
    loading.value = false;
  }
}

function exportCsv() {
  const headers = useCrossTab.value
    ? [props.groupLabel, ...crossColumns.value]
    : [props.groupLabel, "记录数", ...metricColumns.value.map((c) => c.label)];
  const body = useCrossTab.value
    ? crossRows.value.map((row) => [row.key ?? "", ...crossColumns.value.map((c) => row[c] ?? "")])
    : rows.value.map((row) => [
        row.key ?? "",
        row.count ?? 0,
        ...metricColumns.value.map((c) => row[c.key] ?? ""),
      ]);
  const escape = (v: any) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const csv = "\ufeff" + [headers, ...body].map((line) => line.map(escape).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${(props.title || "report").replace(/\s+/g, "-")}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

onMounted(load);
watch(
  () => [props.dataModelId, props.groupBy, props.groupBy2, props.metrics, props.crossTab, JSON.stringify(props.filters || {})],
  () => load()
);
</script>

<style scoped>
.wp-report {
  width: 100%;
}
.wp-report-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}
.wp-report-head h3 {
  margin: 0 0 4px;
  font-size: 16px;
}
.wp-report-sub {
  font-size: 11px;
  color: #86909c;
}
.wp-report-actions {
  display: flex;
  gap: 6px;
}
.wp-report-key {
  font-weight: 500;
}
.wp-report-chart {
  margin-bottom: 14px;
}
</style>
