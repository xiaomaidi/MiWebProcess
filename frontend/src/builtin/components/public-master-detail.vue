<template>
  <section class="wp-public-md" v-loading="loading">
    <div v-if="error" class="wp-public-md-tip">{{ error }}</div>
    <template v-else-if="master">
      <div class="wp-public-md-crumb">
        <a :href="hrefOf(backPath || listPath || 'data')" @click.prevent="go(backPath || listPath || 'data')">列表</a>
        <span>/</span>
        <span>{{ text(master[titleField]) }}</span>
      </div>
      <header class="wp-public-md-head">
        <h1>{{ text(master[titleField]) }}</h1>
        <p v-if="summaryField && master[summaryField]" class="wp-public-md-summary">{{ text(master[summaryField]) }}</p>
      </header>
      <div v-if="contentField && master[contentField]" class="wp-public-md-content" v-html="contentHtml"></div>
      <div v-else class="wp-public-md-fields">
        <div v-for="field in fields" :key="field.key" class="wp-public-md-field">
          <span class="wp-public-md-label">{{ field.label }}</span>
          <span class="wp-public-md-value">{{ field.value }}</span>
        </div>
      </div>

      <section v-for="(relation, index) in relations" :key="index" class="wp-public-md-relation">
        <div class="wp-public-md-relation-head">
          <h2>{{ relation.title || "明细" }}</h2>
          <el-button v-if="relation.allowAdd" size="small" type="primary" @click="openAdd(relation)">
            + 新增明细
          </el-button>
        </div>
        <el-table :data="relationRows[index] || []" size="small" stripe border empty-text="暂无明细">
          <el-table-column
            v-for="column in relation.columns || []"
            :key="column.prop || column.key"
            :prop="column.prop || column.key"
            :label="column.label || column.prop || column.key"
            show-overflow-tooltip
          />
          <el-table-column v-if="relation.allowAdd" label="操作" width="120" align="right">
            <template #default="{ row }">
              <template v-if="tokenFor(relation.modelId, row.id)">
                <el-button size="small" link type="primary" @click="editChild(relation, row)">编辑</el-button>
                <el-button size="small" link type="danger" @click="removeChild(relation, row)">删除</el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
        <div class="wp-public-md-count">共 {{ (relationRows[index] || []).length }} 条明细</div>
      </section>

      <el-dialog v-model="addVisible" :title="`新增${activeRelation?.title || '明细'}`" width="620px" append-to-body>
        <AutoForm
          v-if="activeRelation"
          :model-id="Number(activeRelation.modelId) || 0"
          :fields="activeRelation.fields || []"
          mode="create"
          :default-values="childDefaults"
          :hidden-fields="activeRelation.foreignKey ? [activeRelation.foreignKey] : []"
          :label-width="'100px'"
          submit-text="提交明细"
          success-message="明细已提交，等待审核"
          @saved="onChildSaved"
        />
      </el-dialog>

      <el-dialog v-model="editVisible" :title="`编辑${editRelation?.title || '明细'}`" width="620px" append-to-body>
        <AutoForm
          v-if="editRelation && editRow"
          :model-id="Number(editRelation.modelId) || 0"
          :fields="editRelation.fields || []"
          mode="edit"
          :record-id="editRow.id"
          :public-token="editToken"
          :default-values="editRow"
          :hidden-fields="[editRelation.foreignKey || 'id']"
          :label-width="'100px'"
          submit-text="保存修改"
          success-message="修改已提交，等待审核"
          @saved="onChildSaved"
        />
      </el-dialog>
    </template>
    <div v-else-if="!loading" class="wp-public-md-tip">内容不存在或尚未发布</div>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { contentAppCode } from "../content-api";
import { sanitizeHtml } from "@/engine/sanitize";
import type { RuntimeScope } from "@/types";
import AutoForm from "./auto-form.vue";

interface RelationDef {
  modelId?: number | string;
  foreignKey?: string;
  title?: string;
  columns?: { prop?: string; key?: string; label?: string }[];
  allowAdd?: boolean;
  fields?: any[];
}

const props = withDefaults(
  defineProps<{
    masterModelId?: number | string;
    masterKeyField?: string;
    titleField?: string;
    summaryField?: string;
    contentField?: string;
    relations?: RelationDef[];
    backPath?: string;
    listPath?: string;
  }>(),
  {
    masterModelId: 0,
    masterKeyField: "id",
    titleField: "title",
    summaryField: "summary",
    contentField: "content",
    relations: () => [],
    backPath: "data",
    listPath: "data",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const route = useRoute();
const router = useRouter();
const loading = ref(false);
const error = ref("");
const master = ref<Record<string, any> | null>(null);
const relationRows = ref<Record<string, any>[][]>([]);
const parentValue = ref<any>("");
const addVisible = ref(false);
const activeRelation = ref<RelationDef | null>(null);
const editVisible = ref(false);
const editRelation = ref<RelationDef | null>(null);
const editRow = ref<Record<string, any> | null>(null);
const editToken = ref("");

const childDefaults = computed<Record<string, any>>(() => {
  const key = activeRelation.value?.foreignKey || "";
  return key ? { [key]: parentValue.value } : {};
});

function currentAppCode(): string {
  const parts = typeof window !== "undefined" ? window.location.pathname.split("/").filter(Boolean) : [];
  return contentAppCode(scope) || String(route.params.appCode || parts[1] || "");
}

function tokenStorageKey(modelId: any): string {
  return `wp_public_tokens:${currentAppCode()}:${String(modelId)}`;
}

function tokenMap(modelId: any): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(tokenStorageKey(modelId)) || "{}");
  } catch {
    return {};
  }
}

function tokenFor(modelId: any, recordId: any): string {
  return tokenMap(modelId)[String(recordId)] || "";
}

function rememberToken(modelId: any, recordId: any, token: string): void {
  if (!token) return;
  const map = tokenMap(modelId);
  map[String(recordId)] = token;
  localStorage.setItem(tokenStorageKey(modelId), JSON.stringify(map));
}

function forgetToken(modelId: any, recordId: any): void {
  const map = tokenMap(modelId);
  delete map[String(recordId)];
  localStorage.setItem(tokenStorageKey(modelId), JSON.stringify(map));
}

function openAdd(relation: RelationDef): void {
  activeRelation.value = relation;
  addVisible.value = true;
}

function editChild(relation: RelationDef, row: Record<string, any>): void {
  editRelation.value = relation;
  editRow.value = row;
  editToken.value = tokenFor(relation.modelId, row.id);
  editVisible.value = true;
}

async function removeChild(relation: RelationDef, row: Record<string, any>): Promise<void> {
  const token = tokenFor(relation.modelId, row.id);
  if (!token) return;
  try {
    await ElMessageBox.confirm("确认删除这条明细？", "确认", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.post(`/runtime/${currentAppCode()}/content/${Number(relation.modelId)}/${row.id}/delete/`, {
      public_token: token,
    });
    forgetToken(relation.modelId, row.id);
    ElMessage.success("明细已删除");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "删除失败");
  }
}

function onChildSaved(record?: any): void {
  if (record?.public_token && editRelation.value) {
    rememberToken(editRelation.value.modelId, record.id, record.public_token);
  } else if (record?.public_token && activeRelation.value) {
    rememberToken(activeRelation.value.modelId, record.id, record.public_token);
  }
  addVisible.value = false;
  editVisible.value = false;
  load();
}

function text(value: any): string {
  return value === null || value === undefined ? "" : String(value);
}

const fields = computed(() => {
  const row = master.value || {};
  return Object.entries(row)
    .filter(([key, value]) => !key.startsWith("_") && !["content", "summary"].includes(key) && value !== null && value !== undefined && value !== "")
    .slice(0, 16)
    .map(([key, value]) => ({ key, label: key, value: text(value) }));
});

const contentHtml = computed(() => sanitizeHtml(text(master.value?.[props.contentField])));

function hrefOf(path: string): string {
  return `/run/${scope?.variables?.app?.code || route.params.appCode || ""}/${String(path || "").replace(/^\//, "")}`;
}

function go(path: string): void {
  const url = hrefOf(path);
  if (scope) scope.navigate(path);
  else router.push(url);
}

async function load(): Promise<void> {
  const modelId = Number(props.masterModelId);
  const parts = typeof window !== "undefined" ? window.location.pathname.split("/").filter(Boolean) : [];
  const routeId = Number(parts[parts.length - 1] || 0);
  const id = Number(scope?.routeParams?.id || route.params.id || routeId || 0);
  if (!modelId || !id) return;
  const code = contentAppCode(scope) || String(route.params.appCode || parts[1] || "");
  if (!code) return;
  loading.value = true;
  error.value = "";
  try {
    const raw: any = await api.get(`/runtime/${code}/content/${modelId}/${id}/`);
    const row = raw?.data && typeof raw.data === "object" ? { ...raw.data, _recordId: raw.id } : raw;
    master.value = row || null;
    if (!row) return;
    parentValue.value = row[props.masterKeyField] ?? row.id ?? id;
    const nextRows: Record<string, any>[][] = [];
    for (const relation of props.relations || []) {
      const childId = Number(relation.modelId);
      if (!childId || !relation.foreignKey) {
        nextRows.push([]);
        continue;
      }
      try {
        const params = new URLSearchParams({
          page: "1",
          size: "50",
          [relation.foreignKey]: String(parentValue.value),
        });
        const res: any = await api.get(`/runtime/${code}/content/${childId}/?${params.toString()}`);
        nextRows.push((res?.results || []).map((item: any) => (item?.data ? { ...item.data, id: item.id } : item)));
      } catch {
        nextRows.push([]);
      }
    }
    relationRows.value = nextRows;
  } catch (exc: any) {
    error.value = exc?.message || "内容加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
watch(() => [props.masterModelId, scope?.routeParams?.id, route.params.id], load);
</script>

<style scoped>
.wp-public-md {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px 16px 48px;
}
.wp-public-md-crumb {
  font-size: 12px;
  color: #94a3b8;
  display: flex;
  gap: 6px;
  margin-bottom: 12px;
}
.wp-public-md-crumb a {
  color: #cbd5e1;
}
.wp-public-md-head h1 {
  margin: 0 0 8px;
  color: inherit;
  font-size: 30px;
}
.wp-public-md-summary {
  color: #94a3b8;
  margin: 0 0 16px;
}
.wp-public-md-content {
  line-height: 1.9;
  color: inherit;
}
.wp-public-md-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 24px;
  padding: 16px 0;
}
.wp-public-md-field {
  display: flex;
  gap: 10px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.2);
  padding-bottom: 6px;
}
.wp-public-md-label {
  color: #94a3b8;
  min-width: 96px;
}
.wp-public-md-value {
  word-break: break-all;
}
.wp-public-md-relation {
  margin-top: 28px;
}
.wp-public-md-relation h2 {
  font-size: 18px;
  margin: 0 0 10px;
}
.wp-public-md-relation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.wp-public-md-count {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 6px;
}
.wp-public-md-tip {
  padding: 48px 0;
  text-align: center;
  color: #94a3b8;
}
</style>
