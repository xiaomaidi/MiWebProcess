<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>Agent 评估集</h2>
        <p class="wp-page-desc">固定任务集回归：生成提案、关键词命中、人工撤销率。</p>
      </div>
      <div class="wp-page-actions">
        <el-select v-model="appId" style="width: 220px" @change="loadCases">
          <el-option v-for="app in apps" :key="app.id" :label="app.name" :value="app.id" />
        </el-select>
        <el-button @click="router.push('/admin/agent')">返回 Agent</el-button>
        <el-button @click="runAll">全部运行</el-button>
        <el-button @click="scoreAll">全部评分</el-button>
        <el-button type="primary" @click="createOpen = true">新建评估</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <el-table :data="cases" v-loading="loading" border stripe>
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="goal" label="任务目标" min-width="260" show-overflow-tooltip />
        <el-table-column prop="expected" label="期望关键词" width="150" />
        <el-table-column label="最近运行" width="150">
          <template #default="{ row }">
            <template v-if="row.runs?.length">
              <el-tag :type="row.runs[0].status === 'passed' ? 'success' : 'warning'" size="small">
                {{ row.runs[0].score }} 分
              </el-tag>
              <span class="run-status">{{ row.runs[0].status }}</span>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="runCase(row)">运行</el-button>
            <el-button size="small" @click="scoreLatest(row)">评分</el-button>
            <el-button size="small" type="danger" link @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="还没有评估任务" :image-size="60" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="createOpen" title="新建评估任务" width="560px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="目标页面">
          <el-select v-model="form.pageId" clearable filterable style="width: 100%">
            <el-option v-for="page in pages" :key="page.id" :label="`${page.name} /${page.path}`" :value="page.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务目标"><el-input v-model="form.goal" type="textarea" :rows="4" /></el-form-item>
        <el-form-item label="期望关键词（可选）"><el-input v-model="form.expected" placeholder="例如：柱状图" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createCase">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";

const router = useRouter();
const apps = ref<any[]>([]);
const pages = ref<any[]>([]);
const appId = ref(0);
const cases = ref<any[]>([]);
const loading = ref(false);
const saving = ref(false);
const createOpen = ref(false);
const form = reactive({ name: "", goal: "", pageId: null as number | null, expected: "" });

async function loadApps() {
  const data = await api.get<any>("/apps/");
  apps.value = Array.isArray(data) ? data : data.results || [];
  appId.value = apps.value.find((x) => x.code === "mi-admin")?.id || apps.value[0]?.id || 0;
  await loadPages();
  await loadCases();
}

async function loadPages() {
  if (!appId.value) return;
  const data = await api.get<any>(`/apps/${appId.value}/pages/`);
  pages.value = Array.isArray(data) ? data : data.results || [];
}

async function loadCases() {
  if (!appId.value) return;
  loading.value = true;
  try {
    const data = await api.get<any>(`/ai/agent/evals/?app_id=${appId.value}`);
    cases.value = data.results || [];
  } finally {
    loading.value = false;
  }
}

async function createCase() {
  if (!form.name.trim() || !form.goal.trim()) {
    ElMessage.warning("名称和任务目标必填");
    return;
  }
  saving.value = true;
  try {
    await api.post("/ai/agent/evals/", { app_id: appId.value, name: form.name, goal: form.goal, page_id: form.pageId, expected: form.expected });
    createOpen.value = false;
    Object.assign(form, { name: "", goal: "", pageId: null, expected: "" });
    await loadCases();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function runCase(row: any) {
  try {
    const res = await api.post<any>(`/ai/agent/evals/${row.id}/run/`);
    ElMessage.success(`已创建评估任务 #${res.task_id}`);
    await loadCases();
  } catch (e: any) {
    ElMessage.error(e?.message || "运行失败");
  }
}

async function scoreLatest(row: any) {
  if (!row.runs?.length) {
    ElMessage.warning("还没有运行记录");
    return;
  }
  try {
    const res = await api.post<any>(`/ai/agent/eval-runs/${row.runs[0].id}/score/`);
    ElMessage.success(`评分：${res.score}`);
    await loadCases();
  } catch (e: any) {
    ElMessage.error(e?.message || "评分失败");
  }
}

async function runAll() {
  try {
    const res = await api.post<any>("/ai/agent/evals/run-all/", { app_id: appId.value });
    ElMessage.success(`已创建 ${res.count} 个评估任务`);
    await loadCases();
  } catch (e: any) {
    ElMessage.error(e?.message || "批量运行失败");
  }
}

async function scoreAll() {
  try {
    const res = await api.post<any>("/ai/agent/evals/score-all/", { app_id: appId.value });
    ElMessage.success(`已评分 ${res.count} 条`);
    await loadCases();
  } catch (e: any) {
    ElMessage.error(e?.message || "批量评分失败");
  }
}

async function deleteCase(row: any) {
  await ElMessageBox.confirm(`删除评估 ${row.name}？`, "确认");
  await api.del(`/ai/agent/evals/${row.id}/`);
  await loadCases();
}

onMounted(loadApps);
</script>

<style scoped>
.run-status {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
