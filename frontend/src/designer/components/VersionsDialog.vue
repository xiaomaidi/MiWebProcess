<template>
  <el-dialog v-model="visible" title="版本历史" width="640px">
    <div v-if="loading" class="wp-versions-tip">加载中…</div>
    <el-table v-else :data="rows" size="small" border>
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column prop="changelog" label="发布说明" min-width="180" show-overflow-tooltip />
      <el-table-column prop="published_at" label="发布时间" width="170">
        <template #default="{ row }">{{ fmtTime(row.published_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button size="small" @click="viewSchema(row)">查看</el-button>
          <el-button size="small" type="warning" :loading="rollingId === row.version" @click="rollback(row)">回滚到此版本</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="schemaOpen" title="版本 schema 快照" width="640px" append-to-body>
      <pre class="wp-versions-schema">{{ schemaText }}</pre>
    </el-dialog>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { asList, prettyJson } from "../util";

interface VersionRow {
  id: number;
  page_id?: number;
  version: number;
  schema?: unknown;
  schema_version?: number;
  publisher_id?: number;
  published_at?: string;
  changelog?: string;
}

const props = defineProps<{ modelValue: boolean; pageId: number }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "rolled-back", info: { version: number }): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

const loading = ref(false);
const rows = ref<VersionRow[]>([]);
const rollingId = ref<number | null>(null);
const schemaOpen = ref(false);
const schemaText = ref("");

watch(visible, (v) => {
  if (v) load();
});

async function load() {
  if (!props.pageId) return;
  loading.value = true;
  try {
    const res = await api.get(`/pages/${props.pageId}/versions/?page=1&size=50`);
    rows.value = asList<VersionRow>(res);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载版本失败");
    rows.value = [];
  } finally {
    loading.value = false;
  }
}

function fmtTime(t?: string) {
  return t ? t.replace("T", " ").slice(0, 19) : "";
}

function viewSchema(row: VersionRow) {
  schemaText.value = prettyJson(row.schema ?? null);
  schemaOpen.value = true;
}

async function rollback(row: VersionRow) {
  if (!props.pageId) return;
  rollingId.value = row.version;
  try {
    await api.post(`/pages/${props.pageId}/versions/${row.version}/rollback/`);
    ElMessage.success(`已回滚到 v${row.version}（草稿已更新，请检查后保存/发布）`);
    emit("rolled-back", { version: row.version });
    visible.value = false;
  } catch (e: any) {
    ElMessage.error(e?.message || "回滚失败");
  } finally {
    rollingId.value = null;
  }
}
</script>

<style scoped>
.wp-versions-tip {
  color: var(--el-text-color-secondary);
  padding: 16px 0;
}
.wp-versions-schema {
  max-height: 420px;
  overflow: auto;
  background: #f7f8fa;
  padding: 8px;
  border-radius: 6px;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
