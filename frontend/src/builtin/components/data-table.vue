<template>
  <div class="wp-data-table" :style="{ height: height && !showPagination ? height : undefined }">
    <div v-if="showSearch || exportable" class="wp-data-table-tools">
      <el-input
        v-if="showSearch"
        v-model="searchValue"
        class="wp-data-table-search"
        :placeholder="searchPlaceholder"
        clearable
        @change="onSearchChange"
        @clear="onSearchChange"
      />
      <el-button v-if="exportable" size="small" :disabled="!Number(dataModelId)" @click="exportCsv">
        导出 CSV
      </el-button>
    </div>
    <el-table
      v-loading="loading"
      :data="rows"
      :stripe="stripe"
      :border="border"
      :size="size"
      :height="height || undefined"
      :max-height="maxHeight || undefined"
      :show-header="showHeader"
      :empty-text="emptyText"
      :row-key="rowKey || (remote ? 'id' : undefined)"
      :highlight-current-row="highlightCurrentRow"
      @row-click="onRowClick"
      @selection-change="(v: any[]) => emit('selectionChange', v)"
      @sort-change="onSortChange"
      @current-change="(v: any) => emit('currentChange', v)"
    >
      <el-table-column
        v-for="(col, i) in resolvedColumns"
        :key="col.key || col.prop || i"
        :type="col.type || undefined"
        :prop="col.prop || col.key || undefined"
        :label="col.label || col.title || col.key || ''"
        :width="col.width || undefined"
        :min-width="col.minWidth || col.min_width || undefined"
        :fixed="col.fixed || undefined"
        :sortable="col.sortable || false"
        :align="col.align || 'left'"
        :header-align="col.headerAlign || col.align || 'left'"
        :show-overflow-tooltip="col.showOverflowTooltip !== false"
      >
        <template #default="scope">
          <template v-if="!col.type">
            <el-tag
              v-if="col.cellType === 'tag'"
              :type="cellTagType(col, scope.row)"
              :effect="col.tagEffect || 'light'"
              size="small"
            >
              {{ cellText(col, scope.row) }}
            </el-tag>

            <el-button
              v-else-if="col.cellType === 'button'"
              :type="col.buttonType || 'primary'"
              :size="col.buttonSize || 'small'"
              link
              @click.stop="runCellAction(col, scope.row)"
            >
              {{ cellText(col, scope.row) || col.buttonText || '操作' }}
            </el-button>

            <el-link
              v-else-if="col.cellType === 'link'"
              :href="cellHref(col, scope.row)"
              :target="col.target || '_blank'"
              type="primary"
            >
              {{ cellText(col, scope.row) }}
            </el-link>

            <el-image
              v-else-if="col.cellType === 'image'"
              :src="String(cellValue(col, scope.row) || '')"
              :style="{ width: (col.imageWidth || 48) + 'px', height: (col.imageHeight || 36) + 'px' }"
              fit="cover"
              preview-teleported
              :preview-src-list="[String(cellValue(col, scope.row) || '')]"
            />

            <el-progress
              v-else-if="col.cellType === 'progress'"
              :percentage="Math.max(0, Math.min(100, Number(cellValue(col, scope.row)) || 0))"
              :stroke-width="6"
              :status="Number(cellValue(col, scope.row)) >= 100 ? 'success' : ''"
            />

            <div v-else-if="col.cellType === 'actions'" class="wp-row-actions">
              <el-button
                v-for="(action, ai) in col.rowActions || []"
                :key="ai"
                :type="action.type || 'primary'"
                :size="col.buttonSize || 'small'"
                link
                @click.stop="runRowAction(action, scope.row)"
              >
                {{ action.label || action.kind || '操作' }}
              </el-button>
            </div>

            <component
              v-else-if="col.cellType === 'component'"
              :is="cellComponent(col)"
              v-bind="cellComponentProps(col, scope.row)"
            >
              {{ cellText(col, scope.row) }}
            </component>

            <span v-else class="wp-cell-text">{{ cellText(col, scope.row) }}</span>
          </template>
        </template>
      </el-table-column>
      <template #empty>
        <UiState state="empty" :title="emptyText" />
      </template>
    </el-table>

    <el-dialog v-model="editVisible" title="编辑记录" width="560px" destroy-on-close>
      <AutoForm
        v-if="editRow"
        :model-id="Number(dataModelId) || 0"
        mode="edit"
        :record-id="editRow.id"
        :label-width="'90px'"
        submit-text="保存修改"
        :show-reset="false"
        success-message="修改已保存"
        @saved="onEditSaved"
      />
    </el-dialog>

    <div v-if="showPagination && total > 0" class="wp-data-table-pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSizeValue"
        :page-sizes="pageSizes"
        :total="total"
        :layout="remote ? 'total, sizes, prev, pager, next' : 'total, prev, pager, next'"
        :small="size === 'small'"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import UiState from "./ui-state.vue";
import { api, getToken } from "@/api";
import AutoForm from "./auto-form.vue";
import type { ActionStep, DataModelField, DataModelInfo, RuntimeScope } from "@/types";
import { getElementComponent } from "@/engine/element-components";
import { runSteps } from "@/engine/actions";
import { rowsFromScope } from "../scope-data";

export interface RowActionDef {
  label?: string;
  type?: "primary" | "success" | "warning" | "danger" | "info";
  kind?: "edit" | "delete" | "view" | "step" | "publish" | "unpublish" | "schedule" | "history" | "openRecord";
  confirm?: string;
  steps?: ActionStep[];
  navigatePattern?: string;
}

export interface ColumnDef {
  key?: string;
  prop?: string;
  label?: string;
  title?: string;
  type?: "selection" | "index" | "expand";
  width?: number | string;
  minWidth?: number | string;
  min_width?: number | string;
  fixed?: boolean | "left" | "right";
  sortable?: boolean | "custom";
  align?: "left" | "center" | "right";
  headerAlign?: "left" | "center" | "right";
  showOverflowTooltip?: boolean;
  /** text | tag | button | link | image | progress | actions | component */
  cellType?: string;
  tagType?: string;
  tagTypeField?: string;
  tagEffect?: "dark" | "light" | "plain";
  valueMap?: Record<string, any>;
  hrefField?: string;
  href?: string;
  target?: string;
  imageWidth?: number;
  imageHeight?: number;
  buttonText?: string;
  buttonType?: string;
  buttonSize?: "large" | "default" | "small";
  steps?: ActionStep[];
  /** 行内跳转：erp/orders/{id}，由组件在运行时替换行字段。 */
  navigatePattern?: string;
  rowActions?: RowActionDef[];
  component?: string;
  componentProps?: Record<string, any>;
  prefix?: string;
  suffix?: string;
}

const props = withDefaults(
  defineProps<{
    data?: Record<string, any>[];
    columns?: ColumnDef[];
    stripe?: boolean;
    border?: boolean;
    size?: "large" | "default" | "small";
    height?: string | number;
    maxHeight?: string | number;
    showHeader?: boolean;
    emptyText?: string;
    rowKey?: string;
    highlightCurrentRow?: boolean;
    /** 数据模型：配置后可用 remote/autoColumns/行内删除。 */
    dataModelId?: number | string;
    /** 服务端分页/排序。 */
    remote?: boolean;
    autoColumns?: boolean;
    pageSize?: number;
    pageSizes?: number[];
    showPagination?: boolean;
    filters?: Record<string, any>;
    search?: string;
    showSearch?: boolean;
    searchPlaceholder?: string;
    exportable?: boolean;
    exportName?: string;
    /** Element Plus 兼容字段（忽略） */
    field?: string;
    label?: string;
  }>(),
  {
    data: () => [],
    columns: () => [
      { key: "name", label: "名称" },
      { key: "value", label: "值" },
    ],
    stripe: true,
    border: true,
    size: "default",
    height: "",
    maxHeight: "",
    showHeader: true,
    emptyText: "暂无数据",
    rowKey: "",
    highlightCurrentRow: false,
    dataModelId: 0,
    remote: false,
    autoColumns: false,
    pageSize: 10,
    pageSizes: () => [10, 20, 50, 100],
    showPagination: false,
    filters: () => ({}),
    search: "",
    showSearch: false,
    searchPlaceholder: "搜索关键字…",
    exportable: false,
    exportName: "export.csv",
  }
);

const emit = defineEmits<{
  (e: "rowClick", row: Record<string, any>): void;
  (e: "selectionChange", rows: Record<string, any>[]): void;
  (e: "sortChange", payload: any): void;
  (e: "currentChange", payload: any): void;
  (e: "rowEdit", row: Record<string, any>): void;
  (e: "rowDelete", row: Record<string, any>): void;
  (e: "rowView", row: Record<string, any>): void;
  (e: "rowAction", payload: { action: RowActionDef; row: Record<string, any> }): void;
  (e: "cellAction", payload: { column: ColumnDef; row: Record<string, any> }): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
const remoteRows = ref<Record<string, any>[]>([]);
const remoteTotal = ref(0);
const page = ref(1);
const pageSizeValue = ref(Number(props.pageSize) || 10);
const loading = ref(false);
const sortProp = ref("");
const sortOrder = ref<"ascending" | "descending" | null>(null);
const modelFields = ref<DataModelField[]>([]);
const editVisible = ref(false);
const editRow = ref<Record<string, any> | null>(null);
const searchValue = ref(props.search || "");

function normalizeRow(row: any): Record<string, any> {
  if (row && row.data && typeof row.data === "object" && !Array.isArray(row.data)) {
    return { ...row.data, id: row.id, _record: row };
  }
  return row;
}

const localRows = computed<Record<string, any>[]>(() => {
  let raw: any[] = [];
  if (Array.isArray(props.data) && props.data.length) raw = props.data;
  else if (props.data && typeof props.data === "object") {
    for (const key of ["results", "rows", "items", "data", "records"]) {
      if (Array.isArray((props.data as any)[key])) {
        raw = (props.data as any)[key];
        break;
      }
    }
  } else if (scope) {
    raw = rowsFromScope(scope) as Record<string, any>[];
  }
  const normalized = raw.map(normalizeRow);
  const q = searchValue.value.trim().toLowerCase();
  if (!q || props.remote) return normalized;
  return normalized.filter((row) => Object.values(row).some((v) => String(v ?? "").toLowerCase().includes(q)));
});

const total = computed(() => (props.remote ? remoteTotal.value : localRows.value.length));

const rows = computed<Record<string, any>[]>(() => {
  if (props.remote) return remoteRows.value;
  if (!props.showPagination) return localRows.value;
  const start = (page.value - 1) * pageSizeValue.value;
  return localRows.value.slice(start, start + pageSizeValue.value);
});

const autoColumnDefs = computed<ColumnDef[]>(() =>
  modelFields.value.map((f) => {
    const optionMap = Array.isArray(f.options)
      ? Object.fromEntries(f.options.map((o: any) => [String(o.value), o.label ?? o.value]))
      : undefined;
    const isImage = f.type === "image" || f.type === "signature";
    const isFile = f.type === "file";
    const isTag = ["boolean", "select", "color"].includes(f.type);
    return {
      key: f.name,
      prop: f.name,
      label: f.label || f.name,
      width: f.type === "boolean" ? 90 : isImage ? 90 : isFile ? 150 : undefined,
      cellType: isImage ? "image" : isFile ? "link" : isTag ? "tag" : "text",
      hrefField: isFile ? f.name : undefined,
      target: isFile ? "_blank" : undefined,
      valueMap: f.type === "boolean" ? { true: "是", false: "否" } : optionMap,
      tagType: f.type === "boolean" ? "success" : f.type === "color" ? "info" : undefined,
      prefix: f.type === "money" ? "¥" : undefined,
      suffix: f.type === "percent" ? "%" : f.unit || undefined,
      sortable: true,
    };
  })
);

const resolvedColumns = computed<ColumnDef[]>(() => {
  if (props.autoColumns && autoColumnDefs.value.length) return autoColumnDefs.value;
  return Array.isArray(props.columns) && props.columns.length
    ? props.columns
    : [{ key: "name", label: "名称" }, { key: "value", label: "值" }];
});

function cellValue(col: ColumnDef, row: Record<string, any>): any {
  const key = col.prop || col.key || "";
  let value = key ? row?.[key] : undefined;
  if (col.valueMap && value !== undefined && value !== null && col.valueMap[String(value)] !== undefined) {
    value = col.valueMap[String(value)];
  }
  if (col.cellType === "text" && value === undefined) value = "";
  const prefix = col.prefix || "";
  const suffix = col.suffix || "";
  if (value === null || value === undefined) return value === 0 ? 0 : "";
  return `${prefix}${value}${suffix}`;
}

function cellText(col: ColumnDef, row: Record<string, any>): string {
  const value = cellValue(col, row);
  return value === null || value === undefined ? "" : String(value);
}

function cellTagType(col: ColumnDef, row: Record<string, any>): any {
  if (col.tagType) return col.tagType;
  if (col.tagTypeField) return row?.[col.tagTypeField] || "info";
  return "info";
}

function cellHref(col: ColumnDef, row: Record<string, any>): string {
  let href = col.href || (col.hrefField ? String(row?.[col.hrefField] ?? "") : "");
  href = href.replace(/\{([\w.]+)\}/g, (_m, key) => String(row?.[key] ?? ""));
  return href || "#";
}

function cellComponent(col: ColumnDef): any {
  return getElementComponent(col.component) || "span";
}

function cellComponentProps(col: ColumnDef, row: Record<string, any>): Record<string, any> {
  const propsOut = { ...(col.componentProps || {}) };
  if (col.cellType === "component" && col.component === "ElTag" && col.tagType) propsOut.type = col.tagType;
  return propsOut;
}

async function runActionSteps(steps: ActionStep[] | undefined, row: Record<string, any>) {
  if (!steps?.length || !scope) return;
  await runSteps(steps, scope, { row, item: row, $row: row });
}

async function confirmAction(text: string): Promise<boolean> {
  if (scope?.confirm) return await scope.confirm(text, "确认");
  try {
    await ElMessageBox.confirm(text, "确认", { type: "warning" });
    return true;
  } catch {
    return false;
  }
}

function navigatePattern(pattern: string, row: Record<string, any>): string {
  return pattern.replace(/\{([\w.]+)\}/g, (_m, key) => String(row?.[key] ?? ""));
}

async function runCellAction(col: ColumnDef, row: Record<string, any>) {
  if (col.navigatePattern && scope) {
    scope.navigate(navigatePattern(col.navigatePattern, row));
    return;
  }
  if (col.steps?.length) await runActionSteps(col.steps, row);
  else emit("cellAction", { column: col, row });
}

async function runRowAction(action: RowActionDef, row: Record<string, any>) {
  if (action.confirm) {
    const ok = await confirmAction(action.confirm);
    if (!ok) return;
  }
  if (action.navigatePattern && scope) {
    scope.navigate(navigatePattern(action.navigatePattern, row));
    emit("rowAction", { action, row });
    return;
  }
  if (action.steps?.length) {
    await runActionSteps(action.steps, row);
    emit("rowAction", { action, row });
    return;
  }
  if (action.kind === "edit") {
    if (Number(props.dataModelId) && row?.id != null) {
      editRow.value = row;
      editVisible.value = true;
    } else {
      emit("rowEdit", row);
    }
  } else if (action.kind === "view") {
    emit("rowView", row);
  } else if (action.kind === "openRecord") {
    const modelId = Number(props.dataModelId);
    if (modelId && row?.id != null && scope) {
      scope.navigate(`record/${modelId}/${row.id}`);
    }
  } else if (action.kind === "schedule") {
    const modelId = Number(props.dataModelId);
    if (modelId && row?.id != null) {
      try {
        const r = await ElMessageBox.prompt("发布时间（ISO，例如 2026-11-01T09:00:00）", "定时发布", {
          inputValue: new Date(Date.now() + 3600_000).toISOString().slice(0, 19),
        });
        await api.post(`/models/${modelId}/records/${row.id}/publish/`, {
          action: "schedule",
          published_at: r.value,
        });
        ElMessage.success("已定时发布");
        window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
        await reload();
      } catch (e: any) {
        if (e !== "cancel" && e !== "close") ElMessage.error(e?.message || "操作失败");
      }
    }
  } else if (action.kind === "publish" || action.kind === "unpublish") {
    const modelId = Number(props.dataModelId);
    if (modelId && row?.id != null) {
      try {
        const res = await api.post<any>(`/models/${modelId}/records/${row.id}/publish/`, { action: action.kind });
        if (res?.review) ElMessage.info(res.detail || "内容已提交审核");
        else ElMessage.success(action.kind === "publish" ? "已发布" : "已下线");
        window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
        await reload();
      } catch (e: any) {
        ElMessage.error(e?.message || "操作失败");
      }
    }
  } else if (action.kind === "delete") {
    const modelId = Number(props.dataModelId);
    if (modelId && row?.id != null && scope) {
      try {
        await scope.record.remove(modelId, Number(row.id));
        scope.message("删除成功", "success");
        window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
        await reload();
      } catch (e: any) {
        scope.message(`删除失败：${e?.message || e}`, "error");
      }
    } else {
      emit("rowDelete", row);
    }
  }
  emit("rowAction", { action, row });
}

async function loadModelFields() {
  const modelId = Number(props.dataModelId);
  if (!modelId) return;
  try {
    const model = await api.get<DataModelInfo>(`/models/${modelId}/`);
    modelFields.value = Array.isArray(model.fields) ? model.fields : [];
  } catch {
    modelFields.value = [];
  }
}

async function reload() {
  if (!props.remote) return;
  const modelId = Number(props.dataModelId);
  if (!modelId) return;
  loading.value = true;
  try {
    const params: Record<string, any> = {
      page: page.value,
      size: pageSizeValue.value,
      ...(props.filters || {}),
    };
    if (props.search || searchValue.value) params.search = props.search || searchValue.value;
    if (sortProp.value && sortOrder.value) params.sort = sortOrder.value === "ascending" ? sortProp.value : `-${sortProp.value}`;
    const res = scope
      ? await scope.record.list(modelId, params)
      : await api.get<any>(`/models/${modelId}/records/`, { silent: true });
    const rawRows = Array.isArray(res?.results) ? res.results : Array.isArray(res) ? res : [];
    remoteRows.value = rawRows.map(normalizeRow);
    remoteTotal.value = Number(res?.count) || remoteRows.value.length;
  } catch (e: any) {
    const msg = e?.message || "加载数据失败";
    if (scope) scope.message(msg, "error");
    else ElMessage.error(msg);
  } finally {
    loading.value = false;
  }
}

function onRowClick(row: Record<string, any>) {
  emit("rowClick", row);
}

async function onEditSaved() {
  editVisible.value = false;
  editRow.value = null;
  await reload();
}

function onSortChange(payload: { prop?: string; order?: "ascending" | "descending" | null }) {
  emit("sortChange", payload);
  if (!props.remote) return;
  sortProp.value = payload.prop || "";
  sortOrder.value = payload.order || null;
  page.value = 1;
  reload();
}

async function exportCsv() {
  const modelId = Number(props.dataModelId);
  if (!modelId) return;
  const params: Record<string, string> = {};
  if (searchValue.value) params.search = searchValue.value;
  if (props.search) params.search = props.search;
  for (const [k, v] of Object.entries(props.filters || {})) {
    if (v !== null && v !== undefined && v !== "") params[k] = String(v);
  }
  if (sortProp.value && sortOrder.value) params.sort = sortOrder.value === "ascending" ? sortProp.value : `-${sortProp.value}`;
  try {
    const resp = await fetch(`/api/models/${modelId}/records/export/?${new URLSearchParams(params)}`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
    });
    if (!resp.ok) throw new Error(`导出失败 (${resp.status})`);
    const blob = await resp.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = props.exportName || `model-${modelId}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  } catch (e: any) {
    ElMessage.error(e?.message || "导出失败");
  }
}

function onSearchChange() {
  page.value = 1;
  reload();
}

function onPageChange() {
  reload();
}

function onSizeChange() {
  page.value = 1;
  reload();
}

function onDataChanged(e: Event) {
  const detail = (e as CustomEvent).detail || {};
  if (!props.remote) return;
  if (detail.modelId && Number(detail.modelId) !== Number(props.dataModelId)) return;
  void reload();
}

onMounted(async () => {
  if (props.autoColumns) await loadModelFields();
  if (props.remote) await reload();
  window.addEventListener("wp:data-changed", onDataChanged);
});
onUnmounted(() => window.removeEventListener("wp:data-changed", onDataChanged));

watch(
  () => [props.dataModelId, props.autoColumns, props.remote, props.search, JSON.stringify(props.filters || {})],
  async () => {
    page.value = 1;
    if (props.autoColumns) await loadModelFields();
    if (props.remote) await reload();
  }
);
watch(
  () => [props.pageSize, props.search],
  () => {
    pageSizeValue.value = Number(props.pageSize) || 10;
    searchValue.value = props.search || "";
    page.value = 1;
    if (props.remote) reload();
  }
);
</script>

<style scoped>
.wp-data-table {
  width: 100%;
  overflow: hidden;
}
.wp-cell-text {
  word-break: break-word;
}
.wp-row-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
}
.wp-data-table-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.wp-data-table-search {
  max-width: 260px;
}
.wp-data-table-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 10px;
}
</style>
