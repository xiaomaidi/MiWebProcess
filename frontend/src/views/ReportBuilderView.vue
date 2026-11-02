<template>
  <div class="wp-report-page" v-loading="loading">
    <header class="wp-report-head">
      <div>
        <el-button text @click="goBack">← 返回应用</el-button>
        <h1>报表设计器</h1>
        <p>{{ model?.name }} · 选择分组字段和指标，实时预览聚合结果</p>
      </div>
      <div>
        <el-button @click="subVisible = true">订阅</el-button>
        <el-button @click="router.push(`/admin/models/${modelId}`)">数据管理</el-button>
      </div>
    </header>

    <el-card shadow="never" class="wp-report-config">
      <div class="wp-report-form">
        <label>分组字段</label>
        <el-select v-model="groupBy" style="width: 220px" clearable placeholder="不分组（汇总一行）">
          <el-option v-for="f in model?.fields || []" :key="f.name" :label="`${f.label || f.name} (${f.name})`" :value="f.name" />
        </el-select>
        <label>第二维</label>
        <el-select v-model="groupBy2" style="width: 200px" clearable placeholder="不启用交叉表">
          <el-option v-for="f in model?.fields || []" :key="f.name" :label="`${f.label || f.name} (${f.name})`" :value="f.name" />
        </el-select>
        <el-checkbox v-model="crossTab" :disabled="!groupBy2">交叉表</el-checkbox>
        <label>指标</label>
        <el-checkbox-group v-model="selectedMetrics">
          <el-checkbox v-for="f in numericFields" :key="f.name" :value="`sum:${f.name}`">
            {{ f.label || f.name }} 合计
          </el-checkbox>
          <el-checkbox value="count">记录数</el-checkbox>
        </el-checkbox-group>
      </div>
    </el-card>

    <el-card shadow="never" class="wp-report-preview" v-if="model">
      <ReportTable
        :data-model-id="model.id"
        :group-by="groupBy"
        :group-by2="groupBy2"
        :cross-tab="crossTab"
        :group-label="groupLabel"
        :metrics="metrics"
        :title="`${model.name} 报表`"
        :exportable="true"
        :show-chart="true"
        chart-type="bar"
      />
    </el-card>

    <el-card shadow="never" class="wp-report-qa">
      <template #header><span>AI 数据问答</span></template>
      <div class="wp-report-qa-bar">
        <el-input v-model="question" placeholder="例如：有多少订单？金额合计多少？" @keyup.enter="ask" />
        <el-button type="primary" :loading="asking" @click="ask">提问</el-button>
      </div>
      <el-alert v-if="answer" type="success" :closable="false" class="wp-report-answer">
        <template #title>{{ answer }}</template>
      </el-alert>
      <div v-if="answerMeta" class="wp-report-answer-meta">
        {{ answerMeta.provider }} · 样本 {{ answerMeta.rows }} 条
        <span v-if="answerMeta.warnings?.length"> · {{ answerMeta.warnings.join("；") }}</span>
      </div>
    </el-card>

    <el-card shadow="never" class="wp-report-subs">
      <template #header>
        <div class="wp-subs-head">
          <span>报表订阅</span>
          <el-button size="small" @click="loadSubscriptions">刷新</el-button>
        </div>
      </template>
      <el-table :data="subscriptions" size="small" empty-text="暂无订阅">
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="频率" width="90">
          <template #default="{ row }">{{ frequencyLabel(row.frequency) }}</template>
        </el-table-column>
        <el-table-column prop="recipients" label="接收人" min-width="160" />
        <el-table-column label="上次执行" width="160">
          <template #default="{ row }">{{ row.last_run_at ? new Date(row.last_run_at).toLocaleString() : "未执行" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="runSubscription(row)">运行</el-button>
            <el-button size="small" link type="danger" @click="deleteSubscription(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="subVisible" title="保存报表订阅" width="460px">
      <el-form label-position="top">
        <el-form-item label="订阅名称"><el-input v-model="subName" placeholder="例如 采购金额周报" /></el-form-item>
        <el-form-item label="频率">
          <el-select v-model="subFrequency" style="width: 100%">
            <el-option label="每日" value="daily" />
            <el-option label="每周" value="weekly" />
            <el-option label="每月" value="monthly" />
          </el-select>
        </el-form-item>
        <el-form-item label="接收人（邮箱/用户名，逗号分隔）">
          <el-input v-model="subRecipients" placeholder="a@example.com,b@example.com" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="subVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingSub" @click="saveSubscription">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import ReportTable from "@/builtin/components/report-table.vue";
import type { DataModelField, DataModelInfo } from "@/types";

const route = useRoute();
const router = useRouter();
const modelId = Number(route.params.modelId);
const model = ref<DataModelInfo | null>(null);
const loading = ref(false);
const groupBy = ref("");
const groupBy2 = ref("");
const crossTab = ref(false);
const selectedMetrics = ref<string[]>(["count"]);
const subscriptions = ref<any[]>([]);
const subVisible = ref(false);
const subName = ref("");
const subFrequency = ref("weekly");
const subRecipients = ref("");
const savingSub = ref(false);
const question = ref("");
const answer = ref("");
const asking = ref(false);
const answerMeta = ref<any>(null);

const numericFields = computed<DataModelField[]>(() =>
  (model.value?.fields || []).filter((f) => f.type === "number")
);
const metrics = computed(() => {
  const nums = selectedMetrics.value.filter((m) => m !== "count");
  return ["count", ...nums].join(",");
});
const groupLabel = computed(() => {
  const f = (model.value?.fields || []).find((x) => x.name === groupBy.value);
  return f?.label || f?.name || "分组";
});

async function load() {
  loading.value = true;
  try {
    model.value = await api.get<DataModelInfo>(`/models/${modelId}/`);
    const firstNumber = (model.value.fields || []).find((f) => f.type === "number");
    if (firstNumber) selectedMetrics.value = ["count", `sum:${firstNumber.name}`];
    const firstGroup = (model.value.fields || []).find((f) => f.type === "string");
    if (firstGroup) groupBy.value = firstGroup.name;
  } catch (e: any) {
    ElMessage.error(e?.message || "模型加载失败");
  } finally {
    loading.value = false;
  }
}

async function ask() {
  if (!model.value || !question.value.trim()) {
    ElMessage.warning("请先输入问题");
    return;
  }
  asking.value = true;
  answer.value = "";
  try {
    const res = await api.post<any>("/ai/reports/ask/", {
      app_id: model.value.app_id,
      model_id: model.value.id,
      question: question.value.trim(),
    });
    answer.value = res.answer;
    answerMeta.value = res;
  } catch (e: any) {
    ElMessage.error(e?.message || "AI 问答失败");
  } finally {
    asking.value = false;
  }
}

function frequencyLabel(value: string) {
  return { daily: "每日", weekly: "每周", monthly: "每月" }[value] || value;
}

async function loadSubscriptions() {
  if (!model.value) return;
  try {
    const res = await api.get<any>(`/models/${model.value.id}/report/subscriptions/`);
    subscriptions.value = Array.isArray(res) ? res : Array.isArray(res?.results) ? res.results : [];
  } catch {
    subscriptions.value = [];
  }
}

async function saveSubscription() {
  if (!model.value || !subName.value.trim()) {
    ElMessage.warning("请填写订阅名称");
    return;
  }
  savingSub.value = true;
  try {
    await api.post(`/models/${model.value.id}/report/subscriptions/`, {
      name: subName.value.trim(),
      frequency: subFrequency.value,
      recipients: subRecipients.value,
      config: {
        group_by: groupBy.value,
        group_by2: groupBy2.value,
        metrics: metrics.value,
        filters: {},
      },
    });
    ElMessage.success("订阅已保存");
    subVisible.value = false;
    subName.value = "";
    await loadSubscriptions();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    savingSub.value = false;
  }
}

async function runSubscription(row: any) {
  try {
    const res = await api.post<any>(`/models/report-subscriptions/${row.id}/run/`, {});
    ElMessage.success(`已执行，本次 ${res.count} 条源数据`);
    await loadSubscriptions();
  } catch (e: any) {
    ElMessage.error(e?.message || "执行失败");
  }
}

async function delSubscription(row: any) {
  try {
    await api.del(`/models/report-subscriptions/${row.id}/`);
    await loadSubscriptions();
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

const deleteSubscription = delSubscription;

function goBack() {
  if (model.value?.app_id) router.push(`/admin/apps/${model.value.app_id}`);
  else router.back();
}

onMounted(async () => {
  await load();
  await loadSubscriptions();
});
</script>

<style scoped>
.wp-report-page {
  max-width: 1100px;
  margin: 0 auto;
}
.wp-report-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 14px;
}
.wp-report-head h1 {
  margin: 2px 0 4px;
  font-size: 22px;
}
.wp-report-head p {
  margin: 0;
  color: #86909c;
  font-size: 12px;
}
.wp-report-config {
  margin-bottom: 14px;
}
.wp-report-form {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.wp-report-form label {
  font-size: 12px;
  color: #6b7280;
}
.wp-report-qa {
  margin-top: 14px;
}
.wp-report-qa-bar {
  display: flex;
  gap: 10px;
}
.wp-report-answer {
  margin-top: 12px;
}
.wp-report-answer-meta {
  margin-top: 6px;
  color: #909399;
  font-size: 11px;
}
.wp-report-subs {
  margin-top: 14px;
}
.wp-subs-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
</style>
