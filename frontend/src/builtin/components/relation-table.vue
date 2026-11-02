<template>
  <section class="wp-relation-table">
    <header v-if="title || allowAdd" class="wp-relation-head">
      <h3 v-if="title">{{ title }}</h3>
      <el-button v-if="allowAdd && effectiveParentId" size="small" type="primary" @click="openAdd">
        + {{ addText }}
      </el-button>
    </header>
    <el-table
      v-loading="loading"
      :data="rows"
      :height="height || undefined"
      :max-height="maxHeight || undefined"
      :show-header="showHeader"
      :stripe="stripe"
      :border="border"
      :empty-text="emptyText"
      size="small"
    >
      <el-table-column
        v-for="(col, i) in normalizedColumns"
        :key="col.prop || col.key || i"
        :prop="col.prop || col.key"
        :label="col.label || col.prop || col.key"
        :width="col.width || undefined"
        :min-width="col.minWidth || col.min_width || 100"
        :align="col.align || 'left'"
      >
        <template #default="scope">
          <el-tag v-if="col.cellType === 'tag'" size="small" :type="col.tagType || 'info'">
            {{ valueOf(col, scope.row) }}
          </el-tag>
          <el-button v-else-if="col.cellType === 'button'" size="small" link type="primary" @click="emit('cellAction', { column: col, row: scope.row })">
            {{ valueOf(col, scope.row) || col.buttonText }}
          </el-button>
          <span v-else>{{ valueOf(col, scope.row) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="editable || allowDelete" label="操作" width="120" align="right">
        <template #default="scope">
          <el-button v-if="editable" size="small" link type="primary" @click="openEdit(scope.row)">编辑</el-button>
          <el-button v-if="allowDelete" size="small" link type="danger" @click="removeRow(scope.row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="wp-relation-foot">
      <span>共 {{ total }} 条明细</span>
      <span v-if="!effectiveParentId" class="wp-relation-hint">运行态会按路由中的主记录自动加载明细</span>
    </div>

    <el-dialog v-model="formVisible" :title="editingRow ? '编辑明细' : '新增明细'" width="560px" destroy-on-close>
      <AutoForm
        v-if="formVisible"
        :model-id="Number(modelId) || 0"
        :mode="editingRow ? 'edit' : 'create'"
        :record-id="editingRow?.id || 0"
        :default-values="defaults"
        :hidden-fields="[foreignKey]"
        :label-width="'96px'"
        :submit-text="editingRow ? '保存修改' : '新增明细'"
        :show-reset="false"
        :success-message="editingRow ? '明细已更新' : '明细已新增'"
        @saved="onSaved"
      />
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useRoute } from "vue-router";
import { api } from "@/api";
import { contentAppCode } from "../content-api";
import type { RuntimeScope } from "@/types";
import AutoForm from "./auto-form.vue";

interface RelationColumn {
  prop?: string;
  key?: string;
  label?: string;
  width?: number | string;
  minWidth?: number | string;
  min_width?: number | string;
  align?: "left" | "center" | "right";
  cellType?: string;
  tagType?: string;
  buttonText?: string;
}

const props = withDefaults(
  defineProps<{
    modelId?: number | string;
    masterModelId?: number | string;
    foreignKey?: string;
    parentId?: number | string;
    parentField?: string;
    columns?: RelationColumn[];
    title?: string;
    addText?: string;
    editable?: boolean;
    allowAdd?: boolean;
    allowDelete?: boolean;
    pageSize?: number;
    height?: string | number;
    maxHeight?: string | number;
    showHeader?: boolean;
    stripe?: boolean;
    border?: boolean;
    emptyText?: string;
  }>(),
  {
    modelId: 0,
    masterModelId: 0,
    foreignKey: "parent_id",
    parentId: "",
    parentField: "",
    columns: () => [],
    title: "明细",
    addText: "新增明细",
    editable: true,
    allowAdd: true,
    allowDelete: true,
    pageSize: 100,
    height: "",
    maxHeight: "",
    showHeader: true,
    stripe: false,
    border: true,
    emptyText: "暂无明细",
  }
);

const emit = defineEmits<{
  (e: "saved", row?: any): void;
  (e: "cellAction", payload: { column: RelationColumn; row: any }): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
const route = useRoute();
const effectiveParentId = computed(() => props.parentId || route.params.id || scope?.routeParams?.id || "");
const rows = ref<Record<string, any>[]>([]);
const total = ref(0);
const loading = ref(false);
const formVisible = ref(false);
const editingRow = ref<Record<string, any> | null>(null);
const modelColumns = ref<RelationColumn[]>([]);

const normalizedColumns = computed<RelationColumn[]>(() =>
  Array.isArray(props.columns) && props.columns.length
    ? props.columns
    : modelColumns.value.length
      ? modelColumns.value
      : [
          { prop: "name", label: "名称" },
          { prop: "quantity", label: "数量", width: 100 },
          { prop: "price", label: "单价", width: 120 },
        ]
);

const defaults = computed<Record<string, any>>(() => ({
  [props.foreignKey]: Number(effectiveParentId.value) || effectiveParentId.value,
}));

function normalize(row: any): Record<string, any> {
  if (row && row.data && typeof row.data === "object") return { ...row.data, id: row.id, _record: row };
  return row;
}

function valueOf(col: RelationColumn, row: Record<string, any>): any {
  const v = row?.[col.prop || col.key || ""];
  return v === null || v === undefined ? "" : v;
}

async function loadColumns() {
  if (Array.isArray(props.columns) && props.columns.length) return;
  if (!Number(props.modelId)) return;
  try {
    const model = await api.get<any>(`/models/${Number(props.modelId)}/`);
    modelColumns.value = (model.fields || []).map((f: any) => ({
      prop: f.name,
      label: f.label || f.name,
      cellType: f.type === "boolean" ? "tag" : "text",
      tagType: "success",
    }));
  } catch {
    /* ignore */
  }
}

async function load() {
  const modelId = Number(props.modelId);
  let parentId = effectiveParentId.value;
  if (!modelId || !props.foreignKey || !parentId) {
    rows.value = [];
    total.value = 0;
    return;
  }
  loading.value = true;
  try {
    const code = contentAppCode(scope);
    if (code && props.masterModelId && props.parentField) {
      try {
        const master = await api.get<any>(`/runtime/${code}/content/${props.masterModelId}/${parentId}/`);
        parentId = String(master?.data?.[props.parentField] ?? parentId);
      } catch {
        /* fallback to route id */
      }
    }
    const params = {
      page: 1,
      size: props.pageSize,
      [props.foreignKey]: parentId,
      sort: "id",
    } as Record<string, any>;
    let res: any;
    if (scope && code) {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) qs.set(k, String(v));
      res = await api.get(`/runtime/${code}/content/${modelId}/?${qs.toString()}`);
    } else if (scope) {
      res = await scope.record.list(modelId, params);
    } else {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) qs.set(k, String(v));
      res = await api.get(`/models/${modelId}/records/?${qs.toString()}`);
    }
    rows.value = (res?.results || []).map(normalize);
    total.value = Number(res?.count) || rows.value.length;
  } catch (e: any) {
    ElMessage.error(e?.message || "明细加载失败");
  } finally {
    loading.value = false;
  }
}

function openAdd() {
  editingRow.value = null;
  formVisible.value = true;
}

function openEdit(row: Record<string, any>) {
  editingRow.value = row;
  formVisible.value = true;
}

async function removeRow(row: Record<string, any>) {
  try {
    await ElMessageBox.confirm("确认删除这条明细？", "确认", { type: "warning" });
  } catch {
    return;
  }
  const modelId = Number(props.modelId);
  try {
    if (scope) await scope.record.remove(modelId, Number(row.id));
    else await api.del(`/models/${modelId}/records/${row.id}/`);
    ElMessage.success("明细已删除");
    await load();
    emit("saved", row);
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

async function onSaved(row: any) {
  formVisible.value = false;
  editingRow.value = null;
  await load();
  emit("saved", row);
}

onMounted(async () => {
  await loadColumns();
  await load();
});

watch(
  () => [props.modelId, props.parentId, props.foreignKey],
  () => {
    load();
  }
);
</script>

<style scoped>
.wp-relation-table {
  width: 100%;
}
.wp-relation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.wp-relation-head h3 {
  margin: 0;
  font-size: 16px;
}
.wp-relation-foot {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #86909c;
  font-size: 12px;
  margin-top: 8px;
}
.wp-relation-hint {
  color: #c0c4cc;
}
</style>
