<template>
  <div class="wp-ds-panel">
    <div class="wp-ds-toolbar">
      <el-button size="small" type="primary" @click="openCreate">新建</el-button>
      <el-button size="small" @click="$emit('refresh')">刷新</el-button>
    </div>
    <el-empty v-if="!datasources.length" description="暂无数据源" :image-size="60" />
    <div v-for="ds in datasources" :key="ds.id" class="wp-ds-row">
      <div class="wp-ds-main">
        <span class="wp-ds-name" :title="ds.name">{{ ds.name }}</span>
        <el-tag size="small" :type="tagType(ds.type)">{{ ds.type }}</el-tag>
      </div>
      <div class="wp-ds-ops">
        <el-button v-if="['postgres','mysql','sqlserver'].includes(ds.type)" size="small" @click="openSchema(ds)">结构</el-button>
        <el-button size="small" :loading="testingId === ds.id" @click="onTest(ds)">测试</el-button>
        <el-button size="small" @click="openEdit(ds)">编辑</el-button>
      </div>
    </div>

    <DatasourceSchemaDialog v-model="schemaOpen" :ds="schemaDs" />

    <DatasourceDialog
      v-model="dialogOpen"
      :app-id="appId"
      :editing="editing"
      @saved="$emit('refresh')"
    />

    <el-dialog v-model="resultOpen" title="查询结果" width="560px">
      <div v-if="resultLoading" class="wp-ds-result-tip">查询中…</div>
      <template v-else>
        <el-alert v-if="resultError" :title="resultError" type="error" :closable="false" />
        <pre v-else class="wp-ds-result">{{ resultText }}</pre>
      </template>
      <template #footer>
        <span v-if="resultCache" class="wp-ds-result-tip">缓存：{{ resultCache.from_cache ? "命中" : "未命中" }}</span>
        <el-button @click="resultOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { api, ApiError } from "@/api";
import type { DataSourceDef } from "@/types";
import DatasourceDialog from "./DatasourceDialog.vue";
import DatasourceSchemaDialog from "./DatasourceSchemaDialog.vue";
import { prettyJson } from "../util";

defineProps<{
  datasources: DataSourceDef[];
  appId: number;
}>();
const emit = defineEmits<{ (e: "refresh"): void }>();

const dialogOpen = ref(false);
const schemaOpen = ref(false);
const schemaDs = ref<DataSourceDef | null>(null);
const editing = ref<DataSourceDef | null>(null);
const testingId = ref<number | null>(null);

const resultOpen = ref(false);
const resultLoading = ref(false);
const resultError = ref("");
const resultText = ref("");
const resultCache = ref<{ from_cache: boolean } | null>(null);

function tagType(t: string) {
  return t === "rest" ? "primary" : t === "sql" ? "warning" : "info";
}

function openCreate() {
  editing.value = null;
  dialogOpen.value = true;
}

function openEdit(ds: DataSourceDef) {
  editing.value = ds;
  dialogOpen.value = true;
}

function openSchema(ds: DataSourceDef) {
  schemaDs.value = ds;
  schemaOpen.value = true;
}

async function onTest(ds: DataSourceDef) {
  resultOpen.value = true;
  resultLoading.value = true;
  resultError.value = "";
  resultText.value = "";
  resultCache.value = null;
  testingId.value = ds.id;
  try {
    const res = await api.post<{ data: unknown; from_cache: boolean; cached_at: string | null }>(
      `/datasources/${ds.id}/query/`,
      { params: {} },
      { silent: true }
    );
    resultText.value = prettyJson(res.data);
    resultCache.value = { from_cache: !!res.from_cache };
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : String(e);
    resultError.value = `查询失败：${msg}`;
  } finally {
    resultLoading.value = false;
    testingId.value = null;
  }
}
</script>

<style scoped>
.wp-ds-panel {
  padding: 8px;
  font-size: 13px;
}
.wp-ds-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.wp-ds-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  margin-bottom: 6px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fff;
}
.wp-ds-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.wp-ds-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-ds-ops {
  display: flex;
  gap: 4px;
  flex: none;
}
.wp-ds-result {
  max-height: 320px;
  overflow: auto;
  background: #f7f8fa;
  padding: 8px;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
.wp-ds-result-tip {
  color: #909399;
  font-size: 12px;
  padding: 8px 0;
}
</style>
