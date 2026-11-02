<template>
  <div class="wp-table">
    <el-table
      :data="pagedRows"
      :border="props.bordered"
      :stripe="props.stripe"
      :size="props.size"
      empty-text="暂无数据"
      @row-click="onRowClick"
    >
      <el-table-column v-if="props.showIndex" type="index" label="#" width="60" align="center" />
      <el-table-column
        v-for="col in props.columns"
        :key="col.key"
        :prop="col.key"
        :label="col.label"
        show-overflow-tooltip
      />
    </el-table>
    <div v-if="total > 0" class="wp-table-pager">
      <el-pagination
        v-model:current-page="page"
        :page-size="props.pageSize"
        :total="total"
        layout="prev, pager, next"
        @current-change="onPageChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref } from "vue";
import type { RuntimeScope } from "@/types";
import { rowsFromScope } from "../scope-data";

interface ColumnDef {
  key: string;
  label: string;
}

const props = withDefaults(
  defineProps<{
    columns?: ColumnDef[];
    pageSize?: number;
    bordered?: boolean;
    stripe?: boolean;
    showIndex?: boolean;
    size?: "large" | "default" | "small";
  }>(),
  {
    columns: () => [
      { key: "name", label: "名称" },
      { key: "value", label: "值" },
    ],
    pageSize: 10,
    bordered: true,
    stripe: true,
    showIndex: false,
    size: "default",
  }
);

const emit = defineEmits<{
  (e: "rowClick", row: Record<string, any>): void;
  (e: "pageChange", page: number): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const page = ref(1);

const rows = computed(() => (scope ? rowsFromScope(scope) : []));

const total = computed(() => rows.value.length);

const pagedRows = computed(() => {
  const start = (page.value - 1) * props.pageSize;
  return rows.value.slice(start, start + props.pageSize);
});

function onRowClick(row: Record<string, any>): void {
  emit("rowClick", row);
}

function onPageChange(p: number): void {
  emit("pageChange", p);
}
</script>

<style scoped>
.wp-table {
  width: 100%;
}
.wp-table-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
