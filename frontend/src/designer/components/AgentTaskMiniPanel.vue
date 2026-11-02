<template>
  <section class="agent-mini">
    <div class="agent-mini-head">
      <div>
        <strong>高级任务</strong>
        <span>{{ pageId ? "当前页面" : "当前应用" }}</span>
      </div>
      <el-button size="small" text @click="load">刷新</el-button>
    </div>

    <el-empty v-if="!tasks.length && !loading" description="当前页面还没有高级任务" :image-size="50" />

    <div
      v-for="task in tasks"
      :key="task.id"
      class="agent-mini-row"
      :class="{ active: selected?.task?.id === task.id }"
      @click="selectTask(task)"
    >
      <div class="agent-mini-title">
        <span>#{{ task.id }} {{ task.goal }}</span>
        <el-tag size="small" :type="statusType(task.status)">{{ statusText(task.status) }}</el-tag>
      </div>
      <p>
        {{ task.page_name || "未绑定页面" }}
        <span v-if="task.provider">· {{ task.provider }}</span>
        <span v-if="task.created_at">· {{ formatTime(task.created_at) }}</span>
      </p>
    </div>

    <div v-if="selected" class="agent-mini-detail">
      <div class="agent-mini-detail-head">
        <strong>#{{ selected.task.id }} {{ selected.task.goal }}</strong>
        <div>
          <el-tag v-if="streaming" size="small" type="warning">执行中…</el-tag>
          <el-button size="small" text @click="closeDetail">关闭</el-button>
        </div>
      </div>

      <div v-if="selected.events?.length" class="agent-mini-events">
        <div v-for="event in selected.events.slice(-6)" :key="event.id" class="agent-mini-event">
          <span>{{ formatTime(event.created_at) }}</span>
          <em>{{ event.message || event.type }}</em>
        </div>
      </div>

      <el-empty v-if="!selected.proposals?.length" description="还没有提案" :image-size="44" />

      <div v-for="proposal in selected.proposals" :key="proposal.id" class="agent-mini-proposal">
        <div class="agent-mini-proposal-head">
          <span>{{ proposal.summary }}</span>
          <el-tag size="small" :type="proposalTagType(proposal.status)">{{ proposal.status }}</el-tag>
        </div>

        <div class="agent-mini-diff">
          <span class="added">+{{ proposal.diff?.counts?.added || 0 }}</span>
          <span class="removed">-{{ proposal.diff?.counts?.removed || 0 }}</span>
          <span class="changed">~{{ proposal.diff?.counts?.changed || 0 }}</span>
          <span class="risk">{{ proposal.risk }}</span>
        </div>

        <div v-if="proposal.diff?.added?.length" class="agent-mini-nodes">
          <strong>新增</strong>
          <code v-for="id in proposal.diff.added" :key="id">{{ id }}</code>
        </div>
        <div v-if="proposal.diff?.removed?.length" class="agent-mini-nodes">
          <strong>删除</strong>
          <code v-for="id in proposal.diff.removed" :key="id">{{ id }}</code>
        </div>
        <div v-if="proposal.diff?.changed?.length" class="agent-mini-nodes">
          <strong>修改</strong>
          <div v-for="item in proposal.diff.changed" :key="item.id" class="agent-mini-changed">
            <code>{{ item.id }}</code>
            <span>{{ item.fields.join("、") }}</span>
          </div>
        </div>

        <el-alert
          v-if="proposal.diff?.conflicts?.length"
          title="存在并发修改冲突"
          type="error"
          :closable="false"
          show-icon
          class="agent-mini-conflict"
        />

        <div class="agent-mini-proposal-actions">
          <template v-if="proposal.status === 'pending'">
            <el-button size="small" type="primary" @click="applyProposal(proposal, false)">应用草稿</el-button>
            <el-button size="small" type="success" @click="applyProposal(proposal, true)">应用并发布</el-button>
          </template>
          <el-button size="small" @click="verifyProposal(proposal)">截图验证</el-button>
          <el-button size="small" text @click="openWorkbench">完整工作台</el-button>
        </div>

        <div v-if="verification[proposal.id]" class="agent-mini-verify">
          <el-alert
            :title="verification[proposal.id].ok ? '验证通过' : (verification[proposal.id].available ? '验证发现问题' : '浏览器不可用')"
            :type="verification[proposal.id].ok ? 'success' : 'warning'"
            :description="verification[proposal.id].error || ''"
            :closable="false"
            show-icon
          />
          <el-image
            v-if="verification[proposal.id].screenshot"
            :src="verification[proposal.id].screenshot"
            fit="contain"
            class="agent-mini-shot"
            :preview-src-list="[verification[proposal.id].screenshot]"
          />
          <div v-if="verification[proposal.id].errors?.length" class="agent-mini-verify-errors">
            <p v-for="(err, i) in verification[proposal.id].errors" :key="i">{{ err }}</p>
          </div>
        </div>
      </div>
    </div>

    <div class="agent-mini-form">
      <el-input v-model="goal" size="small" type="textarea" :rows="2" placeholder="描述一个复杂任务，交给高级 Agent" />
      <div class="agent-mini-actions">
        <el-button size="small" type="primary" :loading="creating" @click="createTask">创建任务</el-button>
        <el-button size="small" @click="openWorkbench">完整工作台</el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, apiBase, getToken } from "@/api";

const props = defineProps<{ appId: number; pageId?: number }>();
const emit = defineEmits<{ (e: "applied", schema: any): void }>();
const tasks = ref<any[]>([]);
const selected = ref<any>(null);
const verification = ref<Record<number, any>>({});
const loading = ref(false);
const creating = ref(false);
const goal = ref("");
const streaming = ref(false);
let streamController: AbortController | null = null;

async function load() {
  if (!props.appId) return;
  loading.value = true;
  try {
    const data = await api.get<any>(`/ai/agent/tasks/?app_id=${props.appId}`);
    const rows = data.results || [];
    tasks.value = rows.filter((x: any) => !props.pageId || Number(x.page_id) === Number(props.pageId)).slice(0, 6);
  } catch {
    tasks.value = [];
  } finally {
    loading.value = false;
  }
}

async function selectTask(task: any) {
  try {
    selected.value = await api.get<any>(`/ai/agent/tasks/${task.id}/`);
    verification.value = {};
    if (["pending", "running"].includes(selected.value.task?.status)) startStream(task.id);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载任务失败");
  }
}

function closeDetail() {
  streamController?.abort();
  streaming.value = false;
  selected.value = null;
}

async function startStream(taskId: number) {
  streamController?.abort();
  streamController = new AbortController();
  streaming.value = true;
  try {
    const resp = await fetch(`${apiBase()}/api/ai/agent/tasks/${taskId}/stream/`, {
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
      signal: streamController.signal,
    });
    if (!resp.ok || !resp.body) throw new Error(`流式响应失败 ${resp.status}`);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((x) => x.startsWith("data:"));
        if (!line) continue;
        let payload: any;
        try { payload = JSON.parse(line.slice(5).trim()); } catch { continue; }
        if (payload.type === "done") continue;
        if (selected.value?.events) selected.value.events.push(payload);
      }
    }
  } catch (e: any) {
    if (e?.name !== "AbortError") console.warn("agent stream", e);
  } finally {
    streaming.value = false;
    await load();
    if (selected.value?.task?.id === taskId) {
      try { selected.value = await api.get<any>(`/ai/agent/tasks/${taskId}/`); } catch { /* ignore */ }
    }
  }
}

async function createTask() {
  if (!goal.value.trim()) {
    ElMessage.warning("请填写高级任务目标");
    return;
  }
  creating.value = true;
  try {
    const task = await api.post<any>("/ai/agent/tasks/", {
      app_id: props.appId,
      page_id: props.pageId || null,
      mode: props.pageId ? "page_edit" : "page_build",
      goal: goal.value.trim(),
    });
    ElMessage.success("高级任务已创建");
    goal.value = "";
    await load();
    await selectTask(task);
  } catch (e: any) {
    ElMessage.error(e?.message || "创建失败");
  } finally {
    creating.value = false;
  }
}

async function applyProposal(proposal: any, publish: boolean) {
  try {
    await ElMessageBox.confirm(publish ? "应用提案并发布页面？" : "应用提案到页面草稿？", "确认应用");
    const result = await api.post<any>(`/ai/agent/proposals/${proposal.id}/apply/`, { publish });
    ElMessage.success(publish ? "已应用并发布" : "已应用到草稿");
    if (result.schema) emit("applied", result.schema);
    if (result.verification?.browser) verification.value[proposal.id] = result.verification.browser;
    await load();
    if (selected.value) await selectTask(selected.value.task);
  } catch (e: any) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.message || "应用失败");
  }
}

async function verifyProposal(proposal: any) {
  ElMessage.info("正在启动浏览器验证…");
  try {
    const result = await api.post<any>(`/ai/agent/proposals/${proposal.id}/verify/`);
    verification.value[proposal.id] = result;
  } catch (e: any) {
    ElMessage.error(e?.message || "验证失败");
  }
}

function openTask(task: any) {
  window.open(`/admin/agent?task_id=${task.id}&app_id=${props.appId}`, "_blank");
}

function openWorkbench() {
  window.open(`/admin/agent?app_id=${props.appId}${props.pageId ? `&page_id=${props.pageId}` : ""}`, "_blank");
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

onMounted(load);
</script>

<style scoped>
.agent-mini {
  margin: 8px 0 12px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.agent-mini-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.agent-mini-head strong {
  font-size: 13px;
}
.agent-mini-head span {
  margin-left: 6px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.agent-mini-row {
  padding: 7px 8px;
  margin-bottom: 6px;
  border-radius: 6px;
  background: var(--el-bg-color);
  cursor: pointer;
}
.agent-mini-row:hover,
.agent-mini-row.active {
  border: 1px solid var(--el-color-primary);
}
.agent-mini-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.agent-mini-title span {
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-mini-row p {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.agent-mini-events {
  margin-bottom: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  font-size: 11px;
}
.agent-mini-event {
  display: flex;
  gap: 8px;
  margin: 3px 0;
  color: var(--el-text-color-secondary);
}
.agent-mini-event em {
  flex: 1;
  overflow: hidden;
  color: var(--el-text-color-regular);
  font-style: normal;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-mini-detail {
  margin: 8px 0;
  padding: 8px;
  border: 1px solid var(--el-border-color);
  border-radius: 8px;
  background: var(--el-bg-color);
}
.agent-mini-detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.agent-mini-detail-head strong {
  font-size: 12px;
  line-height: 1.5;
}
.agent-mini-proposal {
  padding: 8px 0;
  border-top: 1px dashed var(--el-border-color-lighter);
}
.agent-mini-proposal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.agent-mini-diff {
  display: flex;
  gap: 10px;
  margin: 6px 0;
  font-size: 11px;
}
.agent-mini-diff .added { color: var(--el-color-success); }
.agent-mini-diff .removed { color: var(--el-color-danger); }
.agent-mini-diff .changed { color: var(--el-color-warning); }
.agent-mini-diff .risk { color: var(--el-text-color-secondary); }
.agent-mini-nodes {
  margin-bottom: 5px;
  font-size: 11px;
}
.agent-mini-nodes strong {
  display: block;
  margin-bottom: 3px;
  color: var(--el-text-color-secondary);
}
.agent-mini-nodes code {
  display: inline-block;
  margin: 0 4px 4px 0;
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--el-fill-color-light);
}
.agent-mini-changed {
  display: flex;
  gap: 6px;
  margin-bottom: 2px;
}
.agent-mini-changed span {
  color: var(--el-text-color-secondary);
}
.agent-mini-conflict {
  margin: 6px 0;
}
.agent-mini-proposal-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
}
.agent-mini-verify {
  margin-top: 8px;
}
.agent-mini-shot {
  width: 100%;
  max-height: 260px;
  margin-top: 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
}
.agent-mini-verify-errors {
  margin-top: 6px;
  color: var(--el-color-danger);
  font-size: 11px;
  word-break: break-all;
}
.agent-mini-verify-errors p {
  margin: 3px 0;
}
.agent-mini-actions {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
</style>
