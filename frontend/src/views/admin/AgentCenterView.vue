<template>
  <div class="wp-admin-page agent-center">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>高级 Agent</h2>
        <p class="wp-page-desc">
          任务队列、提案审批、Diff 预览、自动验证和回滚。
          <el-tag size="small" effect="plain">沙箱：{{ sandbox.mode || "…" }}</el-tag>
        </p>
      </div>
      <div class="wp-page-actions">
        <el-select v-model="appId" style="width: 220px" @change="loadTasks">
          <el-option v-for="app in apps" :key="app.id" :label="app.name" :value="app.id" />
        </el-select>
        <el-button @click="$router.push('/admin/agent/evals')">评估集</el-button>
        <el-button type="primary" @click="openCreate">新建任务</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="never" class="task-list-card">
          <template #header><strong>任务</strong></template>
          <el-empty v-if="!tasks.length" description="还没有任务" :image-size="60" />
          <div
            v-for="item in tasks"
            :key="item.id"
            class="task-row"
            :class="{ active: selected?.task?.id === item.id }"
            @click="selectTask(item.id)"
          >
            <div class="task-row-head">
              <strong>#{{ item.id }} {{ item.goal }}</strong>
              <el-tag size="small" :type="statusType(item.status)">{{ statusText(item.status) }}</el-tag>
            </div>
            <p>{{ item.page_name || "未绑定页面" }} · {{ formatTime(item.created_at) }}</p>
          </div>
        </el-card>
      </el-col>

      <el-col :span="16">
        <el-empty v-if="!selected" description="选择一个任务查看详情" />
        <template v-else>
          <el-card shadow="never" class="detail-card">
            <template #header>
              <div class="detail-head">
                <strong>#{{ selected.task.id }} {{ selected.task.goal }}</strong>
                <div>
                  <el-button v-if="pendingCount > 1" type="success" size="small" @click="applyAll">全部应用</el-button>
                  <el-button v-if="runActive" size="small" @click="cancelTask">取消</el-button>
                  <el-button v-if="canRetry" size="small" @click="retryTask">重跑</el-button>
                  <el-button size="small" @click="loadDetail(selected.task.id)">刷新</el-button>
                </div>
              </div>
            </template>
            <el-descriptions :column="3" border size="small">
              <el-descriptions-item label="应用">{{ selected.task.app_name }}</el-descriptions-item>
              <el-descriptions-item label="页面">{{ selected.task.page_name || "—" }}</el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="statusType(selected.task.status)">{{ statusText(selected.task.status) }}</el-tag>
              </el-descriptions-item>
            </el-descriptions>
            <p v-if="selected.task.error" class="task-error">{{ selected.task.error }}</p>
          </el-card>

          <el-card shadow="never" class="detail-card">
            <template #header><strong>执行时间线</strong></template>
            <el-timeline>
              <el-timeline-item
                v-for="event in selected.events"
                :key="event.id"
                :timestamp="formatTime(event.created_at)"
                :type="event.type.includes('failed') ? 'danger' : event.type.includes('approval') ? 'warning' : 'primary'"
              >
                {{ event.message || event.type }}
              </el-timeline-item>
            </el-timeline>
          </el-card>

          <el-card v-for="proposal in selected.proposals" :key="proposal.id" shadow="never" class="detail-card proposal-card">
            <template #header>
              <div class="detail-head">
                <strong>提案 #{{ proposal.id }} · {{ proposal.summary }}</strong>
                <el-tag :type="proposalTagType(proposal.status)">{{ proposal.status }}</el-tag>
              </div>
            </template>

            <el-alert
              v-if="proposal.diff?.conflicts?.length"
              title="检测到并发修改冲突，请重新生成提案"
              type="error"
              show-icon
              :closable="false"
              class="conflict-alert"
            />
            <div class="diff-stats">
              <span class="added">+{{ proposal.diff?.counts?.added || 0 }} 新增</span>
              <span class="removed">-{{ proposal.diff?.counts?.removed || 0 }} 删除</span>
              <span class="changed">~{{ proposal.diff?.counts?.changed || 0 }} 修改</span>
              <span class="risk">风险：{{ proposal.risk }}</span>
            </div>

            <div v-if="proposal.diff?.added?.length" class="diff-block">
              <strong>新增节点</strong>
              <code v-for="id in proposal.diff.added" :key="id">{{ id }}</code>
            </div>
            <div v-if="proposal.diff?.removed?.length" class="diff-block">
              <strong>删除节点</strong>
              <code v-for="id in proposal.diff.removed" :key="id">{{ id }}</code>
            </div>
            <div v-if="proposal.diff?.changed?.length" class="diff-block">
              <strong>修改节点</strong>
              <div v-for="item in proposal.diff.changed" :key="item.id" class="changed-row">
                <code>{{ item.id }}</code>
                <span>{{ item.fields.join("、") }}</span>
              </div>
            </div>

            <div class="proposal-actions">
              <template v-if="proposal.status === 'pending'">
                <el-button type="primary" size="small" @click="applyProposal(proposal, false)">应用草稿</el-button>
                <el-button type="success" size="small" @click="applyProposal(proposal, true)">应用并发布</el-button>
                <el-button type="danger" plain size="small" @click="rejectProposal(proposal)">拒绝</el-button>
              </template>
              <el-button v-if="proposal.status === 'applied'" size="small" @click="verifyProposal(proposal)">截图验证</el-button>
              <el-button v-if="proposal.status === 'applied'" size="small" @click="rollbackProposal(proposal)">回滚</el-button>
            </div>
          </el-card>
        </template>
      </el-col>
    </el-row>

    <el-dialog v-model="createOpen" title="新建高级 Agent 任务" width="560px">
      <el-form label-position="top">
        <el-form-item label="目标页面">
          <el-select v-model="form.pageId" clearable filterable placeholder="不绑定页面" style="width: 100%">
            <el-option v-for="page in pages" :key="page.id" :label="`${page.name} /${page.path}`" :value="page.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="任务目标">
          <el-input v-model="form.goal" type="textarea" :rows="5" placeholder="例如：把流量来源饼图改成柱状图，保留原数据" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createTask">创建任务</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="verifyOpen" title="浏览器验证" width="720px">
      <el-alert
        v-if="verifyResult"
        :title="verifyResult.ok ? '验证通过' : (verifyResult.available ? '验证发现问题' : '浏览器不可用')"
        :type="verifyResult.ok ? 'success' : 'warning'"
        :description="verifyResult.error || ''"
        :closable="false"
        show-icon
        class="verify-alert"
      />
      <el-image v-if="verifyResult?.screenshot" :src="verifyResult.screenshot" fit="contain" class="verify-shot" :preview-src-list="[verifyResult.screenshot]" />
      <div v-if="verifyResult?.errors?.length" class="verify-errors">
        <strong>控制台 / 页面错误</strong>
        <p v-for="(err, i) in verifyResult.errors" :key="i">{{ err }}</p>
      </div>
      <div v-if="verifyResult?.page" class="verify-meta">
        页面：{{ verifyResult.page.title || verifyResult.page.path }} · 图表：{{ verifyResult.page.charts }} · 图表错误：{{ verifyResult.page.chartErrors }}
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";

const route = useRoute();
const apps = ref<any[]>([]);
const sandbox = ref<any>({});
const pages = ref<any[]>([]);
const appId = ref<number>(0);
const tasks = ref<any[]>([]);
const selected = ref<any>(null);
const createOpen = ref(false);
const verifyOpen = ref(false);
const verifyResult = ref<any>(null);
const creating = ref(false);
const form = reactive({ pageId: null as number | null, goal: "" });
let timer: any = null;

const runActive = computed(() => ["pending", "running"].includes(selected.value?.task?.status));
const pendingCount = computed(() => (selected.value?.proposals || []).filter((x: any) => x.status === "pending").length);
const canRetry = computed(() => ["failed", "cancelled", "applied"].includes(selected.value?.task?.status));

async function loadApps() {
  try { sandbox.value = await api.get<any>("/ai/agent/sandbox/"); } catch { sandbox.value = {}; }
  const data = await api.get<any>("/apps/");
  apps.value = Array.isArray(data) ? data : data.results || [];
  if (!appId.value && apps.value.length) appId.value = apps.value.find((x) => x.code === "mi-admin")?.id || apps.value[0].id;
  await loadPages();
  await loadTasks();
}

async function loadPages() {
  if (!appId.value) return;
  const data = await api.get<any>(`/apps/${appId.value}/pages/`);
  pages.value = Array.isArray(data) ? data : data.results || [];
}

async function loadTasks() {
  if (!appId.value) return;
  selected.value = null;
  const data = await api.get<any>(`/ai/agent/tasks/?app_id=${appId.value}`);
  tasks.value = data.results || [];
  if (tasks.value.length) await selectTask(tasks.value[0].id);
  await loadPages();
}

async function selectTask(id: number) {
  await loadDetail(id);
}

async function loadDetail(id: number) {
  const data = await api.get<any>(`/ai/agent/tasks/${id}/`);
  selected.value = data;
}

function openCreate() {
  form.pageId = pages.value[0]?.id || null;
  form.goal = "";
  createOpen.value = true;
}

async function createTask() {
  if (!form.goal.trim()) {
    ElMessage.warning("请填写任务目标");
    return;
  }
  creating.value = true;
  try {
    const task = await api.post<any>("/ai/agent/tasks/", {
      app_id: appId.value,
      page_id: form.pageId,
      goal: form.goal.trim(),
      mode: form.pageId ? "page_edit" : "page_build",
    });
    createOpen.value = false;
    ElMessage.success("任务已创建");
    await loadTasks();
    await selectTask(task.id);
  } catch (e: any) {
    ElMessage.error(e?.message || "创建失败");
  } finally {
    creating.value = false;
  }
}

async function cancelTask() {
  if (!selected.value) return;
  await api.post(`/ai/agent/tasks/${selected.value.task.id}/cancel/`);
  await loadDetail(selected.value.task.id);
  await loadTasks();
}

async function retryTask() {
  if (!selected.value) return;
  await api.post(`/ai/agent/tasks/${selected.value.task.id}/retry/`);
  await loadDetail(selected.value.task.id);
  await loadTasks();
}

async function applyProposal(proposal: any, publish: boolean) {
  try {
    await ElMessageBox.confirm(
      publish ? "应用提案并发布页面？" : "应用提案到页面草稿？",
      "确认应用"
    );
    await api.post(`/ai/agent/proposals/${proposal.id}/apply/`, { publish });
    ElMessage.success(publish ? "已应用并发布" : "已应用到草稿");
    await loadDetail(selected.value.task.id);
  } catch (e: any) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.message || "应用失败");
  }
}

async function applyAll() {
  try {
    await ElMessageBox.confirm("一次性应用本任务全部待审批提案？", "确认批量应用");
    await api.post(`/ai/agent/tasks/${selected.value.task.id}/apply-all/`, { publish: true });
    ElMessage.success("全部提案已应用并发布");
    await loadDetail(selected.value.task.id);
  } catch (e: any) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.message || "批量应用失败");
  }
}

async function rejectProposal(proposal: any) {
  await ElMessageBox.confirm("拒绝这个提案？", "确认");
  await api.post(`/ai/agent/proposals/${proposal.id}/reject/`);
  await loadDetail(selected.value.task.id);
}

async function verifyProposal(proposal: any) {
  ElMessage.info("正在启动浏览器验证，请稍候…");
  try {
    verifyResult.value = await api.post<any>(`/ai/agent/proposals/${proposal.id}/verify/`);
    verifyOpen.value = true;
  } catch (e: any) {
    ElMessage.error(e?.message || "验证失败");
  }
}

async function rollbackProposal(proposal: any) {
  await ElMessageBox.confirm("回滚这次修改？", "确认");
  await api.post(`/ai/agent/proposals/${proposal.id}/rollback/`);
  await loadDetail(selected.value.task.id);
}

function statusText(status: string) {
  return ({ pending: "待执行", running: "执行中", waiting_approval: "待审批", applied: "已应用", failed: "失败", cancelled: "已取消" } as Record<string, string>)[status] || status;
}

function statusType(status: string) {
  return ({ pending: "info", running: "warning", waiting_approval: "warning", applied: "success", failed: "danger", cancelled: "info" } as Record<string, any>)[status] || "info";
}

function proposalTagType(status: string) {
  return ({ pending: "warning", applied: "success", rejected: "info", rolled_back: "info", failed: "danger" } as Record<string, any>)[status] || "info";
}

function formatTime(value?: string) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString("zh-CN", { hour12: false });
}

onMounted(async () => {
  await loadApps();
  const queryApp = Number(route.query.app_id);
  if (queryApp) {
    appId.value = queryApp;
    await loadPages();
    await loadTasks();
  }
  const queryTask = Number(route.query.task_id);
  if (queryTask) await loadDetail(queryTask);
  const queryPage = Number(route.query.page_id);
  if (queryPage) form.pageId = queryPage;
  if (route.query.goal) {
    form.goal = String(route.query.goal);
    createOpen.value = true;
  }
  timer = setInterval(() => {
    if (runActive.value && selected.value) loadDetail(selected.value.task.id);
  }, 2500);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<style scoped>
.task-list-card {
  min-height: 520px;
}
.task-row {
  padding: 10px;
  margin-bottom: 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  cursor: pointer;
}
.task-row:hover,
.task-row.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.task-row-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.task-row-head strong {
  overflow: hidden;
  color: var(--el-text-color-primary);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-row p {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.detail-card {
  margin-bottom: 14px;
}
.detail-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.task-error {
  margin: 12px 0 0;
  color: var(--el-color-danger);
  font-size: 12px;
}
.diff-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 12px;
}
.diff-stats .added { color: var(--el-color-success); }
.diff-stats .removed { color: var(--el-color-danger); }
.diff-stats .changed { color: var(--el-color-warning); }
.diff-stats .risk { color: var(--el-text-color-secondary); }
.diff-block {
  margin-bottom: 10px;
}
.diff-block strong {
  display: block;
  margin-bottom: 5px;
  font-size: 12px;
}
.diff-block code {
  display: inline-block;
  margin: 0 6px 6px 0;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-size: 12px;
}
.changed-row {
  display: flex;
  gap: 8px;
  margin-bottom: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.verify-alert {
  margin-bottom: 12px;
}
.verify-shot {
  width: 100%;
  max-height: 460px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.verify-errors {
  margin-top: 12px;
  padding: 10px;
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
  color: var(--el-color-danger);
  font-size: 12px;
}
.verify-errors p {
  margin: 4px 0;
  word-break: break-all;
}
.verify-meta {
  margin-top: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.conflict-alert {
  margin-bottom: 10px;
}
.proposal-actions {
  display: flex;
  gap: 8px;
  margin-top: 10px;
}
</style>
