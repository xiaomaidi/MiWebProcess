<template>
  <div class="wp-record-page" v-loading="loading">
    <header class="wp-record-head">
      <div>
        <el-button text @click="goBack">← 返回应用</el-button>
        <h1>{{ model?.name || "数据管理" }}</h1>
        <p v-if="model">
          {{ model.fields?.length || 0 }} 个字段
          <el-tag v-if="model.is_public" size="small" type="success" effect="plain">公开读取</el-tag>
          <el-tag v-if="model.row_owner_field" size="small" type="warning" effect="plain">行级权限：{{ model.row_owner_field }}</el-tag>
        </p>
      </div>
      <div class="wp-record-actions">
        <el-button v-if="canAiWrite" type="primary" plain @click="aiContentOpen = true">✨ AI 写内容</el-button>
        <el-button @click="router.push(`/admin/models/${modelId}/report`)">报表</el-button>
        <el-button type="primary" @click="openCreate">+ 新增记录</el-button>
      </div>
    </header>

    <el-card shadow="never" class="wp-record-card">
      <DataTable
        v-if="model"
        :data-model-id="model.id"
        :columns="columns"
        :remote="true"
        :show-pagination="true"
        :page-size="20"
        :show-search="true"
        :search-placeholder="`搜索 ${model.name}…`"
        :exportable="true"
        :export-name="`${model.name}.csv`"
        :row-key="'id'"
        empty-text="暂无记录"
        @row-action="onRowAction"
      />
    </el-card>

    <AiContentDialog
      v-if="model"
      v-model="aiContentOpen"
      :app-id="model.app_id"
      :model-id="model.id"
      :model-name="model.name"
      @generated="onAiContentGenerated"
      @batch="onAiContentBatch"
    />

    <el-dialog v-model="historyVisible" title="变更历史" width="760px">
      <el-timeline v-if="historyRows.length">
        <el-timeline-item v-for="h in historyRows" :key="h.id" :timestamp="h.created_at" placement="top">
          <div class="wp-history-head">
            <el-tag size="small">{{ h.action }}</el-tag>
            <span>{{ h.username || "系统" }}</span>
            <el-button
              v-if="h.before && h.before.data"
              size="small"
              link
              type="warning"
              @click="revertHistory(h)"
            >回滚到此版本</el-button>
          </div>
          <pre class="wp-history-json">{{ JSON.stringify(h.after ?? h.before, null, 2) }}</pre>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无变更记录" :image-size="50" />
    </el-dialog>

    <el-dialog v-model="importVisible" title="导入记录" width="620px" destroy-on-close>
      <el-alert title="支持 CSV / XLSX；表头可使用字段名或中文字段名。" type="info" :closable="false" show-icon />
      <el-form label-position="top" style="margin-top: 14px">
        <el-form-item label="文件">
          <input type="file" accept=".csv,.xlsx" @change="onImportFile" />
        </el-form-item>
        <el-form-item label="导入模式">
          <el-radio-group v-model="importMode">
            <el-radio label="append">追加</el-radio>
            <el-radio label="upsert">更新或追加</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="importMode === 'upsert'" label="匹配字段（key_field）">
          <el-input v-model="importKeyField" placeholder="例如 code；也可以使用 id" />
        </el-form-item>
      </el-form>
      <el-alert v-if="importResult" :title="`导入完成：创建 ${importResult.created}，更新 ${importResult.updated}，跳过 ${importResult.skipped}`" :type="importResult.errors?.length ? 'warning' : 'success'" :closable="false" show-icon />
      <el-table v-if="importResult?.errors?.length" :data="importResult.errors" size="small" border style="margin-top: 10px; max-height: 220px">
        <el-table-column prop="row" label="行" width="60" />
        <el-table-column prop="field" label="字段" width="120" />
        <el-table-column prop="message" label="错误" min-width="240" show-overflow-tooltip />
      </el-table>
      <template #footer>
        <el-button @click="importVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importing" @click="submitImport">开始导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createVisible" :title="`新增${model?.name || '记录'}`" width="640px" destroy-on-close>
      <AutoForm
        v-if="createVisible && model"
        :model-id="model.id"
        mode="create"
        :field-columns="2"
        :default-values="aiDefaults"
        label-position="top"
        submit-text="保存记录"
        success-message="记录已新增"
        @saved="onCreated"
      />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { getToken } from "@/api";
import { api } from "@/api";
import type { DataModelField, DataModelInfo } from "@/types";
import AiContentDialog from "@/views/AiContentDialog.vue";

const DataTable = defineAsyncComponent(() => import("@/builtin/components/data-table.vue"));
const AutoForm = defineAsyncComponent(() => import("@/builtin/components/auto-form.vue"));

const route = useRoute();
const router = useRouter();
const modelId = Number(route.params.modelId);
const model = ref<DataModelInfo | null>(null);
const loading = ref(false);
const createVisible = ref(false);
const importVisible = ref(false);
const importing = ref(false);
const importFile = ref<File | null>(null);
const importMode = ref<"append" | "upsert">("append");
const importKeyField = ref("");
const importResult = ref<any>(null);
const aiContentOpen = ref(false);
const aiDefaults = ref<Record<string, any>>({});
const historyVisible = ref(false);
const historyRows = ref<any[]>([]);
const historyRecordId = ref<number | null>(null);

const canAiWrite = computed(() =>
  (model.value?.fields || []).some((f) => ["title", "content", "summary"].includes(f.name))
);

const columns = computed(() => {
  const fields = model.value?.fields || [];
  const cols: any[] = fields.map((f: DataModelField) => {
    const optionMap = Array.isArray(f.options)
      ? Object.fromEntries(f.options.map((o: any) => [String(o.value), o.label ?? o.value]))
      : undefined;
    const isImage = f.type === "image" || f.type === "signature";
    const isFile = f.type === "file";
    const isAttachments = f.type === "attachments";
    return {
      key: f.name,
      prop: f.name,
      label: f.label || f.name,
      minWidth: ["json", "geolocation", "longtext", "richtext"].includes(f.type) ? 220 : 120,
      cellType: isImage ? "image" : isFile ? "link" : isAttachments ? "attachments" : ["boolean", "select", "color"].includes(f.type) ? "tag" : "text",
      showOverflowTooltip: !isAttachments,
      hrefField: isFile ? f.name : undefined,
      target: isFile ? "_blank" : undefined,
      ...(f.type === "boolean"
        ? { valueMap: { true: "是", false: "否" }, tagType: "success" }
        : optionMap
          ? { valueMap: optionMap }
          : {}),
      prefix: f.type === "money" ? "¥" : undefined,
      suffix: f.type === "percent" ? "%" : f.unit || undefined,
    };
  });
  const hasPublish = fields.some((f) => f.name === "status");
  const actions: any[] = [{ label: "编辑", kind: "edit", type: "primary" }];
  if (hasPublish) {
    actions.push({ label: "发布", kind: "publish", type: "success" });
    actions.push({ label: "定时", kind: "schedule", type: "info" });
    actions.push({ label: "下线", kind: "unpublish", type: "warning" });
  }
  actions.push({ label: "历史", kind: "history", type: "info" });
  actions.push({ label: "删除", kind: "delete", type: "danger", confirm: "确认删除这条记录？" });
  cols.push({
    key: "_actions",
    label: "操作",
    width: hasPublish ? 300 : 170,
    cellType: "actions",
    rowActions: actions,
  });
  return cols;
});

async function load() {
  loading.value = true;
  try {
    model.value = await api.get<DataModelInfo>(`/models/${modelId}/`);
  } catch (e: any) {
    ElMessage.error(e?.message || "模型加载失败");
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  aiDefaults.value = {};
  createVisible.value = true;
}

function onAiContentGenerated(draft: Record<string, any>) {
  aiDefaults.value = draft;
  aiContentOpen.value = false;
  createVisible.value = true;
}

async function onAiContentBatch(drafts: Record<string, any>[]) {
  aiContentOpen.value = false;
  let created = 0;
  for (const data of drafts) {
    try {
      await api.post(`/models/${modelId}/records/`, { data });
      created += 1;
    } catch (e: any) {
      ElMessage.error(`第 ${created + 1} 篇创建失败：${e?.message || e}`);
      break;
    }
  }
  if (created) {
    ElMessage.success(`已创建 ${created} 篇内容草稿`);
    window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
  }
}

function onCreated() {
  createVisible.value = false;
  aiDefaults.value = {};
  window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
}

async function revertHistory(log: any) {
  if (!historyRecordId.value) return;
  try {
    await api.post(`/models/${modelId}/records/${historyRecordId.value}/revert/`, { audit_id: log.id });
    ElMessage.success("已回滚");
    historyVisible.value = false;
    window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
  } catch (e: any) {
    ElMessage.error(e?.message || "回滚失败");
  }
}

function onImportFile(event: Event) {
  const input = event.target as HTMLInputElement;
  importFile.value = input.files?.[0] || null;
  importResult.value = null;
}
async function submitImport() {
  if (!importFile.value) {
    ElMessage.warning("请选择 CSV 或 XLSX 文件");
    return;
  }
  importing.value = true;
  importResult.value = null;
  try {
    const extra: Record<string, string> = { mode: importMode.value };
    if (importMode.value === "upsert" && importKeyField.value.trim()) extra.key_field = importKeyField.value.trim();
    importResult.value = await api.upload<any>(`/models/${modelId}/records/import/`, importFile.value, "file", extra);
    ElMessage.success("导入完成");
    window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId } }));
  } catch (e: any) {
    ElMessage.error(e?.detail || e?.message || "导入失败");
  } finally {
    importing.value = false;
  }
}
async function downloadFile(base: string, filename: string) {
  const resp = await fetch(base, { headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {} });
  if (!resp.ok) throw new Error(`导出失败 (${resp.status})`);
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
async function exportRecords(format: "xlsx" | "csv" | "pdf") {
  try {
    const ext = format;
    await downloadFile(`/api/models/${modelId}/records/export/?format=${format}`, `${model.value?.name || "records"}.${ext}`);
  } catch (e: any) {
    ElMessage.error(e?.message || "导出失败");
  }
}
async function printRecords() {
  try {
    const resp = await fetch(`/api/models/${modelId}/records/print/`, { headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {} });
    if (!resp.ok) throw new Error(`打印视图加载失败 (${resp.status})`);
    const html = await resp.text();
    const win = window.open("", "_blank");
    if (win) { win.document.open(); win.document.write(html); win.document.close(); }
  } catch (e: any) {
    ElMessage.error(e?.message || "打印失败");
  }
}

async function onRowAction({ action, row }: any) {
  if (action?.kind !== "history") return;
  historyRecordId.value = Number(row.id);
  try {
    const res = await api.get<any>(
      `/audit-logs/?object_type=datamodel_record&object_id=${row.id}` +
        (model.value?.app_id ? `&app_id=${model.value.app_id}` : "")
    );
    historyRows.value = Array.isArray(res?.results) ? res.results : Array.isArray(res) ? res : [];
    historyVisible.value = true;
  } catch (e: any) {
    ElMessage.error(e?.message || "历史加载失败");
  }
}

function goBack() {
  if (model.value?.app_id) router.push(`/admin/apps/${model.value.app_id}`);
  else router.back();
}

onMounted(load);
</script>

<style scoped>
.wp-record-page {
  max-width: 1300px;
  margin: 0 auto;
}
.wp-record-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.wp-record-head h1 {
  margin: 2px 0 4px;
  font-size: 22px;
}
.wp-record-head p {
  margin: 0;
  display: flex;
  gap: 8px;
  align-items: center;
  color: #86909c;
  font-size: 12px;
}
.wp-record-card {
  border-radius: 6px;
}
.wp-history-head {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #606266;
  font-size: 12px;
}
.wp-history-json {
  margin: 6px 0 0;
  max-height: 220px;
  overflow: auto;
  background: #f7f8fa;
  padding: 8px;
  font-size: 11px;
  border-radius: 4px;
}
</style>
