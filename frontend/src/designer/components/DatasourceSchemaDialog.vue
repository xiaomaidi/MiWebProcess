<template>
  <el-dialog
    :model-value="modelValue"
    :title="`数据库结构与查询 · ${ds?.name || ''}`"
    width="980px"
    @update:model-value="emit('update:modelValue', $event)"
    @open="load"
  >
    <div class="wp-ds-schema">
      <aside class="wp-ds-schema-tree">
        <div class="wp-ds-schema-head">表（{{ tables.length }}）</div>
        <el-scrollbar height="430px">
          <div v-for="table in tables" :key="`${table.schema}.${table.name}`" class="wp-ds-table" @click="pick(table)">
            <strong>{{ table.name }}</strong>
            <span>{{ table.schema }} · {{ table.columns.length }} 字段</span>
          </div>
        </el-scrollbar>
      </aside>
      <section class="wp-ds-query">
        <div class="wp-ds-ai-sql">
          <el-input v-model="question" placeholder="用自然语言描述查询，例如：按状态统计订单数量" @keyup.enter="aiSql" />
          <el-button type="primary" plain :loading="aiLoading" @click="aiSql">AI 生成 SQL</el-button>
        </div>
        <el-input v-model="sql" type="textarea" :rows="7" class="wp-ds-sql-editor" placeholder="SELECT * FROM ... LIMIT 100" />
        <div class="wp-ds-query-actions">
          <el-button type="primary" :loading="running" @click="run">执行查询</el-button>
          <span class="wp-ds-query-hint">只允许单条 SELECT</span>
        </div>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
        <el-table v-if="rows.length" :data="rows" size="small" border max-height="280" class="wp-ds-result-table">
          <el-table-column v-for="col in columns" :key="col" :prop="col" :label="col" min-width="120" show-overflow-tooltip />
        </el-table>
        <div v-if="ran && !rows.length && !error" class="wp-ds-query-hint">查询成功，没有返回行。</div>
      </section>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { DataSourceDef } from "@/types";

const props = defineProps<{ modelValue: boolean; ds: DataSourceDef | null }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();
const tables = ref<any[]>([]);
const sql = ref("");
const question = ref("");
const rows = ref<any[]>([]);
const ran = ref(false);
const error = ref("");
const running = ref(false);
const aiLoading = ref(false);
const columns = computed(() => (rows.value.length ? Object.keys(rows.value[0]) : []));

async function load() {
  tables.value = [];
  error.value = "";
  if (!props.ds) return;
  try {
    const res = await api.get<any>(`/datasources/${props.ds.id}/schema/`);
    tables.value = res.tables || [];
    if (tables.value.length) pick(tables.value[0]);
  } catch (e: any) {
    error.value = e?.message || "读取数据库结构失败";
  }
}

function pick(table: any) {
  sql.value = `SELECT * FROM "${table.schema}"."${table.name}" LIMIT 100`;
  rows.value = [];
  ran.value = false;
}

async function aiSql() {
  if (!props.ds || !question.value.trim()) {
    ElMessage.warning("请描述查询需求");
    return;
  }
  aiLoading.value = true;
  error.value = "";
  try {
    const res = await api.post<any>("/ai/datasources/sql/", {
      datasource_id: props.ds.id,
      question: question.value.trim(),
    });
    sql.value = res.sql;
    ElMessage.success("SQL 已生成，请检查后执行");
  } catch (e: any) {
    error.value = e?.message || "AI 生成 SQL 失败";
  } finally {
    aiLoading.value = false;
  }
}

async function run() {
  if (!props.ds || !sql.value.trim()) return;
  running.value = true;
  error.value = "";
  rows.value = [];
  try {
    const res = await api.post<any>(`/datasources/${props.ds.id}/run-sql/`, { sql: sql.value });
    rows.value = res.data || [];
    ran.value = true;
    ElMessage.success(`查询完成，${rows.value.length} 行`);
  } catch (e: any) {
    error.value = e?.message || "查询失败";
  } finally {
    running.value = false;
  }
}
</script>

<style scoped>
.wp-ds-schema {
  display: flex;
  gap: 14px;
}
.wp-ds-schema-tree {
  width: 260px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
  flex-shrink: 0;
}
.wp-ds-schema-head {
  padding: 10px 12px;
  background: #f7f8fa;
  font-size: 13px;
  font-weight: 600;
}
.wp-ds-table {
  padding: 9px 12px;
  border-bottom: 1px solid #f2f3f5;
  cursor: pointer;
}
.wp-ds-table:hover {
  background: #f0f7ff;
}
.wp-ds-table strong {
  display: block;
  font-size: 13px;
}
.wp-ds-table span {
  color: #909399;
  font-size: 11px;
}
.wp-ds-query {
  flex: 1;
  min-width: 0;
}
.wp-ds-ai-sql {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.wp-ds-sql-editor :deep(textarea) {
  font-family: Consolas, monospace;
  font-size: 12px;
}
.wp-ds-query-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 10px 0;
}
.wp-ds-query-hint {
  color: #909399;
  font-size: 12px;
}
.wp-ds-result-table {
  margin-top: 10px;
}
</style>
