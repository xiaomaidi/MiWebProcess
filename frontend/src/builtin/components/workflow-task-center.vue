<template>
  <section class="wftc">
    <header class="wftc-head">
      <div>
        <h2>审批中心</h2>
        <p>真实审批待办与流程实例，数据来自 WorkflowTask / WorkflowInstance。</p>
      </div>
      <el-button size="small" :loading="loading" @click="loadAll">刷新</el-button>
    </header>

    <el-tabs v-model="tab" @tab-change="onTab">
      <el-tab-pane name="pending">
        <template #label>
          待我审批
          <el-badge v-if="tasks.length" :value="tasks.length" class="wftc-badge" />
        </template>
        <el-table :data="tasks" v-loading="loading" border stripe size="small">
          <el-table-column prop="instance_title" label="审批事项" min-width="180" show-overflow-tooltip />
          <el-table-column prop="definition_name" label="流程" min-width="140" show-overflow-tooltip />
          <el-table-column prop="node_name" label="当前节点" min-width="110" />
          <el-table-column label="审批人" min-width="110">
            <template #default="{ row }">{{ row.assignee_name || row.assignee_role || "角色审批" }}</template>
          </el-table-column>
          <el-table-column label="截止时间" min-width="150">
            <template #default="{ row }">
              <span :class="{ overdue: row.is_overdue }">{{ formatTime(row.due_at) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="250" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" @click="act(row, 'approve')">同意</el-button>
              <el-button size="small" type="danger" plain @click="act(row, 'reject')">驳回</el-button>
              <el-button v-if="row.business_model_id && row.business_record_id" size="small" @click="openRecord(row)">业务详情</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty description="没有待办审批" :image-size="60" /></template>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="流程实例" name="instances">
        <el-table :data="instances" v-loading="loading" border stripe size="small">
          <el-table-column prop="title" label="事项" min-width="180" show-overflow-tooltip />
          <el-table-column prop="definition_name" label="流程" min-width="140" show-overflow-tooltip />
          <el-table-column prop="initiator_name" label="发起人" width="120" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row.status)">{{ statusText(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="当前节点" width="120">
            <template #default="{ row }">{{ row.current_node_id || "—" }}</template>
          </el-table-column>
          <el-table-column label="发起时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" fixed="right">
            <template #default="{ row }">
              <el-button v-if="row.business_model_id && row.business_record_id" size="small" @click="openRecord(row)">业务详情</el-button>
            </template>
          </el-table-column>
          <template #empty><el-empty description="暂无流程实例" :image-size="60" /></template>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import type { RuntimeScope } from "@/types";

const scope = inject<RuntimeScope | null>("wp.scope", null);
const tab = ref("pending");
const loading = ref(false);
const tasks = ref<any[]>([]);
const instances = ref<any[]>([]);

function appId(): number {
  return Number((scope?.variables?.app as any)?.id) || 0;
}

async function loadTasks() {
  if (!appId()) return;
  const data = await api.get<any[]>(`/workflows/tasks/?app_id=${appId()}`, { silent: true });
  tasks.value = Array.isArray(data) ? data : [];
}

async function loadInstances() {
  if (!appId()) return;
  const data = await api.get<any[]>(`/workflows/instances/?app_id=${appId()}`, { silent: true });
  instances.value = Array.isArray(data) ? data : [];
}

async function loadAll() {
  loading.value = true;
  try {
    await Promise.all([loadTasks(), loadInstances()]);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载审批中心失败");
  } finally {
    loading.value = false;
  }
}

function onTab() {
  void loadAll();
}

async function act(task: any, action: "approve" | "reject") {
  try {
    const { value } = await ElMessageBox.prompt(
      action === "approve" ? "请输入审批意见（可选）" : "请输入驳回原因",
      action === "approve" ? "同意审批" : "驳回审批",
      { inputType: "textarea", inputValue: "", confirmButtonText: action === "approve" ? "同意" : "驳回" }
    );
    await api.post(`/workflows/tasks/${task.id}/action/`, { action, comment: value || "" });
    ElMessage.success(action === "approve" ? "已同意" : "已驳回");
    await loadAll();
  } catch (e: any) {
    if (e === "cancel" || e === "close") return;
    ElMessage.error(e?.message || "审批失败");
  }
}

function openRecord(item: any) {
  if (!item.business_model_id || !item.business_record_id) return;
  scope?.navigate(`record/${item.business_model_id}/${item.business_record_id}`);
}

function formatTime(value?: string) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("zh-CN", { hour12: false });
}

function statusText(status: string) {
  return ({ running: "审批中", approved: "已通过", rejected: "已驳回", cancelled: "已撤回" } as Record<string, string>)[status] || status;
}

function statusType(status: string) {
  return ({ running: "warning", approved: "success", rejected: "danger", cancelled: "info" } as Record<string, any>)[status] || "info";
}

onMounted(loadAll);
</script>

<style scoped>
.wftc {
  padding: 4px 0;
}
.wftc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.wftc-head h2 {
  margin: 0;
  font-size: 18px;
  color: var(--el-text-color-primary);
}
.wftc-head p {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wftc-badge {
  margin-left: 6px;
}
.overdue {
  color: var(--el-color-danger);
}
</style>
