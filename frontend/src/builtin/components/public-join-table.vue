<template>
  <section class="wp-public-join" v-loading="loading">
    <header class="wp-public-join-head">
      <h2>{{ title || "主从汇总" }}</h2>
      <div class="wp-public-join-actions">
        <el-input v-model="query" size="small" placeholder="搜索…" clearable style="width: 200px" @keyup.enter="load" />
        <el-button size="small" @click="load">刷新</el-button>
        <el-button v-if="exportable" size="small" @click="exportCsv">导出 CSV</el-button>
      </div>
      <span>共 {{ total }} 行</span>
    </header>
    <div class="wp-public-join-filters">
      <el-select v-model="filterField" size="small" filterable placeholder="筛选字段" style="width: 160px">
        <el-option v-for="column in columns" :key="column.prop" :label="column.label" :value="column.prop" />
      </el-select>
      <el-select v-model="filterOp" size="small" style="width: 110px">
        <el-option label="等于" value="eq" />
        <el-option label="包含" value="contains" />
        <el-option label="大于等于" value="gte" />
        <el-option label="小于等于" value="lte" />
        <el-option label="多值" value="in" />
      </el-select>
      <el-input v-model="filterValue" size="small" placeholder="筛选值" style="width: 180px" @keyup.enter="addFilter" />
      <el-button size="small" @click="addFilter">+ 筛选</el-button>
      <el-tag
        v-for="(filter, index) in activeFilters"
        :key="index"
        closable
        size="small"
        @close="removeFilter(index)"
      >
        {{ filter.field }} {{ filter.op }} {{ filter.value }}
      </el-tag>
    </div>
    <el-table :data="rows" size="small" stripe border empty-text="暂无数据" @sort-change="onSort">
      <el-table-column
        v-for="column in columns"
        :key="column.prop"
        :prop="column.prop"
        :label="column.label"
        min-width="120"
        sortable="custom"
        show-overflow-tooltip
      />
    </el-table>
    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next"
      class="wp-public-join-pager"
      @current-change="load"
    />
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { api } from "@/api";
import { contentAppCode } from "../content-api";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    masterModelId?: number | string;
    childModelId?: number | string;
    foreignKey?: string;
    masterKeyField?: string;
    relations?: { modelId?: number | string; foreignKey?: string; parentKey?: string }[];
    title?: string;
    pageSize?: number;
    exportable?: boolean;
  }>(),
  {
    masterModelId: 0,
    childModelId: 0,
    foreignKey: "",
    masterKeyField: "id",
    relations: () => [],
    title: "主从汇总",
    pageSize: 20,
    exportable: true,
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const route = useRoute();
const loading = ref(false);
const rows = ref<Record<string, any>[]>([]);
const columns = ref<{ prop: string; label: string }[]>([]);
const total = ref(0);
const page = ref(1);
const query = ref("");
const sort = ref("");
const filterField = ref("");
const filterOp = ref("eq");
const filterValue = ref("");
const activeFilters = ref<{ field: string; op: string; value: string }[]>([]);

function appendFilters(params: URLSearchParams): void {
  for (const filter of activeFilters.value) {
    params.set(`filter_${filter.field}__${filter.op}`, filter.value);
  }
}

function addFilter(): void {
  if (!filterField.value || !filterValue.value.trim()) return;
  activeFilters.value.push({
    field: filterField.value,
    op: filterOp.value,
    value: filterValue.value.trim(),
  });
  filterValue.value = "";
  page.value = 1;
  load();
}

function removeFilter(index: number): void {
  activeFilters.value.splice(index, 1);
  page.value = 1;
  load();
}

async function load(): Promise<void> {
  const masterId = Number(props.masterModelId);
  const childId = Number(props.childModelId);
  if (!masterId || (!childId && !props.relations.length)) return;
  const parts = typeof window !== "undefined" ? window.location.pathname.split("/").filter(Boolean) : [];
  const code = contentAppCode(scope) || String(route.params.appCode || parts[1] || "");
  if (!code) return;
  loading.value = true;
  try {
    const params = new URLSearchParams({
      page: String(page.value),
      size: String(props.pageSize || 20),
    });
    if (query.value.trim()) params.set("q", query.value.trim());
    if (sort.value) params.set("sort", sort.value);
    appendFilters(params);
    if (props.relations.length) {
      params.set("relations", JSON.stringify(props.relations));
    } else {
      params.set("foreign_key", props.foreignKey);
      params.set("master_key", props.masterKeyField || "id");
    }
    const result: any = await api.get(`/runtime/${code}/content/${masterId}/join/${childId}/?${params.toString()}`);
    columns.value = Array.isArray(result?.columns) ? result.columns : [];
    if (!filterField.value && columns.value.length) filterField.value = columns.value[0].prop;
    rows.value = Array.isArray(result?.rows) ? result.rows : [];
    total.value = Number(result?.total) || rows.value.length;
  } finally {
    loading.value = false;
  }
}

function onSort(event: { prop: string; order: string | null }): void {
  sort.value = event.order === "ascending" ? event.prop : event.order === "descending" ? `-${event.prop}` : "";
  page.value = 1;
  load();
}

function exportCsv(): void {
  const masterId = Number(props.masterModelId);
  const childId = Number(props.childModelId);
  if (!masterId || !childId) return;
  const parts = typeof window !== "undefined" ? window.location.pathname.split("/").filter(Boolean) : [];
  const code = contentAppCode(scope) || String(route.params.appCode || parts[1] || "");
  const params = new URLSearchParams({ export: "1" });
  if (query.value.trim()) params.set("q", query.value.trim());
  if (sort.value) params.set("sort", sort.value);
  appendFilters(params);
  if (props.relations.length) {
    params.set("relations", JSON.stringify(props.relations));
  } else {
    params.set("foreign_key", props.foreignKey);
    params.set("master_key", props.masterKeyField || "id");
  }
  window.open(`/api/runtime/${code}/content/${masterId}/join/${childId}/?${params.toString()}`, "_blank");
}

onMounted(load);
watch(() => [props.masterModelId, props.childModelId, props.foreignKey, props.relations], load);
</script>

<style scoped>
.wp-public-join {
  max-width: 1240px;
  margin: 0 auto;
  padding: 24px 16px;
}
.wp-public-join-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}
.wp-public-join-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.wp-public-join-filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.wp-public-join-head h2 {
  margin: 0;
  font-size: 22px;
}
.wp-public-join-head span {
  font-size: 12px;
  color: #94a3b8;
}
.wp-public-join-pager {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
