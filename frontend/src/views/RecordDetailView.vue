<template>
  <div class="record-detail" v-loading="loading">
    <header class="record-head">
      <div>
        <el-button text @click="back">← 返回</el-button>
        <h1>{{ title }}</h1>
        <p>{{ appName }} · {{ model?.name || "" }} · 记录 #{{ recordId }}</p>
      </div>
      <div class="record-head-actions">
        <el-tag v-if="model?.workflow_definition_id" size="small" type="success" effect="plain">已绑定审批流程</el-tag>
        <el-button @click="reload">刷新</el-button>
      </div>
    </header>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="record-error" />

    <template v-if="!loading && !error">
      <el-row :gutter="16">
        <el-col :span="16">
          <el-card shadow="never" class="record-card">
            <template #header><strong>业务信息</strong></template>
            <el-descriptions :column="2" border>
              <el-descriptions-item v-for="field in fields" :key="field.name" :label="field.label || field.name">
                {{ displayValue(record?.data?.[field.name]) }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-card shadow="never" class="record-card">
            <template #header><strong>编辑记录</strong></template>
            <AutoForm
              :model-id="modelId"
              :record-id="recordId"
              mode="edit"
              submit-text="保存修改"
              success-message="记录已保存"
              label-position="top"
              :columns="2"
              @saved="reload"
            />
          </el-card>
        </el-col>

        <el-col :span="8">
          <el-card v-if="model?.workflow_definition_id" shadow="never" class="record-card">
            <template #header><strong>审批</strong></template>
            <ApprovalPanel
              :definition-id="model.workflow_definition_id"
              :business-model-id="modelId"
              :business-record-id="String(recordId)"
              :title="title"
              @changed="reload"
              @started="reload"
            />
          </el-card>
          <el-card v-else shadow="never" class="record-card">
            <el-empty description="该数据模型还没有绑定审批流程" :image-size="60" />
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import AutoForm from "@/builtin/components/auto-form.vue";
import ApprovalPanel from "@/builtin/components/approval-panel.vue";

interface FieldDef {
  name: string;
  label?: string;
  type?: string;
}
interface ModelDef {
  id: number;
  name: string;
  fields: FieldDef[];
  workflow_definition_id?: number | null;
}

const route = useRoute();
const router = useRouter();
const appCode = String(route.params.appCode || "");
const modelId = Number(route.params.modelId);
const recordId = Number(route.params.recordId);

const loading = ref(true);
const error = ref("");
const appName = ref(appCode);
const model = ref<ModelDef | null>(null);
const record = ref<any>(null);

const title = computed(() => {
  const data = record.value?.data || {};
  return data.title || data.name || data.no || `${model.value?.name || "记录"} #${recordId}`;
});
const fields = computed<FieldDef[]>(() => (model.value?.fields || []).filter((f) => f.name));

function displayValue(value: any): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [modelData, recordData, authConfig] = await Promise.all([
      api.get<ModelDef>(`/models/${modelId}/`),
      api.get<any>(`/models/${modelId}/records/${recordId}/`),
      api.get<any>(`/runtime/${appCode}/auth-config/`, { silent: true }).catch(() => null),
    ]);
    model.value = modelData;
    record.value = recordData;
    appName.value = authConfig?.app_name || appCode;
    if (typeof document !== "undefined") document.title = `${title.value} · ${appName.value}`;
  } catch (e: any) {
    error.value = e?.message || "加载记录失败";
    ElMessage.error(error.value);
  } finally {
    loading.value = false;
  }
}

async function reload() {
  try {
    record.value = await api.get<any>(`/models/${modelId}/records/${recordId}/`);
  } catch (e: any) {
    ElMessage.error(e?.message || "刷新失败");
  }
}

function back() {
  if (window.history.length > 1) router.back();
  else router.push(`/run/${appCode}/dashboard`);
}

onMounted(load);
</script>

<style scoped>
.record-detail {
  min-height: 100vh;
  padding: 24px;
  background: #f4f6fb;
}
.record-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  max-width: 1280px;
  margin: 0 auto 18px;
}
.record-head h1 {
  margin: 6px 0 4px;
  font-size: 26px;
  color: #0f172a;
}
.record-head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}
.record-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.record-card {
  max-width: 1280px;
  margin-bottom: 16px;
  border-radius: 12px;
}
.record-error {
  max-width: 1280px;
  margin: 0 auto 16px;
}
:deep(.el-descriptions__label) {
  width: 120px;
  color: #64748b;
}
</style>
