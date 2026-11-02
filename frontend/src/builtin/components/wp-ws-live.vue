<template>
  <section class="wp-ws-live">
    <header>
      <strong>{{ title || "实时数据" }}</strong>
      <el-tag size="small" :type="rows.length ? 'success' : 'info'" effect="plain">
        {{ rows.length ? `已接收 ${rows.length} 条` : "等待数据" }}
      </el-tag>
    </header>
    <div v-if="error" class="wp-ws-error">{{ error }}</div>
    <el-table v-else-if="rows.length" :data="rows" size="small" border max-height="320">
      <el-table-column
        v-for="key in columns"
        :key="key"
        :prop="key"
        :label="key"
        min-width="110"
        show-overflow-tooltip
      />
    </el-table>
    <el-empty v-else description="暂无实时数据" :image-size="50" />
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    datasourceId?: number;
    title?: string;
    field?: string;
    limit?: number;
  }>(),
  { datasourceId: 0, title: "实时数据", field: "", limit: 100 }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const rows = ref<Record<string, any>[]>([]);
const error = ref("");
let unsubscribe: (() => void) | null = null;

const columns = computed(() => {
  const first = rows.value[0];
  if (!first) return [];
  return Object.keys(first).slice(0, 8);
});

function pushData(data: any) {
  const value = props.field && data && typeof data === "object" ? data[props.field] : data;
  const list = Array.isArray(value) ? value : [value];
  for (const item of list) {
    if (item === undefined || item === null) continue;
    rows.value.push(item && typeof item === "object" ? item : { value: item });
  }
  const limit = Math.max(1, Number(props.limit) || 100);
  if (rows.value.length > limit) rows.value.splice(0, rows.value.length - limit);
}

onMounted(() => {
  if (!scope?.subscribeDatasource) {
    error.value = "当前环境不支持 WebSocket 数据源";
    return;
  }
  if (!props.datasourceId) {
    error.value = "请配置 WebSocket 数据源 ID";
    return;
  }
  try {
    unsubscribe = scope.subscribeDatasource(Number(props.datasourceId), {}, pushData);
  } catch (e: any) {
    error.value = e?.message || "WebSocket 订阅失败";
  }
});

onBeforeUnmount(() => {
  unsubscribe?.();
  unsubscribe = null;
});
</script>

<style scoped>
.wp-ws-live {
  padding: 14px;
  border: 1px solid var(--wp-border, #e4e7ed);
  border-radius: var(--wp-radius-lg, 10px);
  background: var(--wp-surface, #fff);
}
.wp-ws-live header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.wp-ws-error {
  padding: 10px;
  color: var(--wp-color-danger, #f56c6c);
  font-size: 12px;
}
</style>
