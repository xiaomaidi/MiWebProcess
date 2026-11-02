<template>
  <div class="wp-task-page">
    <header class="wp-task-head">
      <div>
        <h1>工作流待办</h1>
        <p>当前账号可处理的审批任务。通过任务操作会推进流程并回写业务记录。</p>
      </div>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </header>

    <el-table :data="tasks" v-loading="loading" border stripe empty-text="暂无待办">
      <el-table-column prop="instance_title" label="流程 / 业务" min-width="180" />
      <el-table-column prop="definition_name" label="流程定义" min-width="130" />
      <el-table-column prop="node_name" label="当前节点" width="100" />
      <el-table-column prop="assignee_role" label="审批角色" width="80" />
      <el-table-column label="发起时间" width="130">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="时限" width="145">
        <template #default="{ row }">
          <el-tag v-if="row.is_overdue" size="small" type="danger">已超时</el-tag>
          <span v-else-if="row.due_at">{{ formatDate(row.due_at) }}</span>
          <span v-else class="wp-muted">不限</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="330" align="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" @click="act(row, 'approve')">通过</el-button>
          <el-button size="small" type="danger" plain @click="openReject(row)">驳回</el-button>
          <el-button size="small" text @click="delegate(row, 'transfer')">转办</el-button>
          <el-button size="small" text @click="delegate(row, 'add-sign')">加签</el-button>
          <el-button size="small" text @click="remind(row)">催办</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="rejectVisible" title="驳回审批" width="460px">
      <el-form label-position="top">
        <el-form-item label="驳回原因">
          <el-input v-model="rejectComment" type="textarea" :rows="3" placeholder="请输入驳回原因" />
        </el-form-item>
        <el-form-item label="回退节点（可选）">
          <el-select v-model="rejectTarget" clearable placeholder="不回退，直接结束流程" style="width: 100%">
            <el-option v-for="n in rollbackOptions" :key="n.id" :label="n.name || n.id" :value="n.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button type="danger" :loading="acting" @click="confirmReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import type { WorkflowTask } from "@/types";

const tasks = ref<WorkflowTask[]>([]);
const loading = ref(false);
const rejectVisible = ref(false);
const rejectTask = ref<WorkflowTask | null>(null);
const rejectComment = ref("");
const rejectTarget = ref("");
const acting = ref(false);

const rollbackOptions = computed(() => {
  const nodes = rejectTask.value?.definition_nodes || [];
  return nodes.filter((n) => n.type === "approval" && n.id !== rejectTask.value?.node_id);
});

function formatDate(value?: string) {
  return value ? value.replace("T", " ").slice(0, 16) : "";
}

async function load() {
  loading.value = true;
  try {
    tasks.value = await api.get<WorkflowTask[]>("/workflows/tasks/");
  } catch (e: any) {
    ElMessage.error(e?.message || "待办加载失败");
  } finally {
    loading.value = false;
  }
}

async function delegate(task: WorkflowTask, action: "transfer" | "add-sign") {
  let value = "";
  try {
    const r = await ElMessageBox.prompt(
      "输入用户 ID 或角色（viewer/editor/owner）",
      action === "transfer" ? "转办任务" : "加签",
      { inputPlaceholder: "例如：12 或 owner" }
    );
    value = String(r.value || "").trim();
  } catch {
    return;
  }
  if (!value) return;
  const payload: Record<string, any> = /^\d+$/.test(value)
    ? { assignee_user_id: Number(value) }
    : { assignee_role: value };
  try {
    await api.post(`/workflows/tasks/${task.id}/${action}/`, payload);
    ElMessage.success(action === "transfer" ? "已转办" : "已加签");
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

function openReject(task: WorkflowTask) {
  rejectTask.value = task;
  rejectComment.value = "";
  rejectTarget.value = "";
  rejectVisible.value = true;
}

async function confirmReject() {
  if (!rejectTask.value) return;
  acting.value = true;
  try {
    await api.post(`/workflows/tasks/${rejectTask.value.id}/action/`, {
      action: "reject",
      comment: rejectComment.value,
      rollback_to: rejectTarget.value || undefined,
    });
    ElMessage.success(rejectTarget.value ? "已驳回并回退" : "已驳回");
    rejectVisible.value = false;
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "驳回失败");
  } finally {
    acting.value = false;
  }
}

async function remind(task: WorkflowTask) {
  try {
    await api.post(`/workflows/tasks/${task.id}/remind/`, {});
    ElMessage.success("已催办");
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "催办失败");
  }
}

async function act(task: WorkflowTask, action: "approve" | "reject") {
  if (action === "reject") {
    openReject(task);
    return;
  }
  try {
    await api.post(`/workflows/tasks/${task.id}/action/`, { action, comment: "" });
    ElMessage.success("已通过");
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

onMounted(load);
</script>

<style scoped>
.wp-task-page {
  max-width: 1100px;
  margin: 0 auto;
}
.wp-task-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.wp-task-head h1 {
  margin: 0 0 4px;
  font-size: 22px;
}
.wp-task-head p {
  margin: 0;
  color: #86909c;
  font-size: 12px;
}
.wp-muted {
  color: #aab1bb;
  font-size: 12px;
}
</style>
