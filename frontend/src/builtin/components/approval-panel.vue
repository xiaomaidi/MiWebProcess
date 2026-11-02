<template>
  <section class="wp-approval" v-loading="loading">
    <header class="wp-approval-head">
      <div>
        <span class="wp-approval-kicker">审批流程</span>
        <h3>{{ definition?.name || title || "审批" }}</h3>
        <p v-if="definition?.description" class="wp-approval-desc">{{ definition.description }}</p>
      </div>
      <el-tag :type="statusType" effect="light">{{ statusLabel }}</el-tag>
    </header>

    <div v-if="!businessRecordId || !definitionId" class="wp-approval-tip">
      运行态会根据业务记录自动加载审批流程。
    </div>
    <template v-else>
      <div v-if="!instance && definition?.status !== 'published'" class="wp-approval-tip">
        流程尚未发布，请先在流程设计器中发布。
      </div>
      <div v-else-if="!instance" class="wp-approval-start">
        <el-button type="primary" :loading="starting" @click="start">发起审批</el-button>
        <span>共有 {{ approvalNodes.length }} 个审批节点</span>
      </div>

      <template v-else>
        <div class="wp-approval-progress">
          <div
            v-for="(node, i) in displayNodes"
            :key="node.id"
            class="wp-approval-node"
            :class="nodeClass(node, i)"
          >
            <span class="wp-approval-dot">{{ i + 1 }}</span>
            <div>
              <strong>{{ node.name }}</strong>
              <small>{{ node.assignee_role || "指定人员" }}</small>
            </div>
          </div>
        </div>

        <div v-if="instance.status === 'running'" class="wp-approval-actions">
          <el-input v-model="comment" type="textarea" :rows="2" placeholder="审批意见（可选）" />
          <div class="wp-approval-buttons">
            <el-button :loading="acting" @click="act('reject')">驳回</el-button>
            <el-button type="primary" :loading="acting" @click="act('approve')">同意 / 提交下一节点</el-button>
          </div>
        </div>

        <div class="wp-approval-history">
          <div v-for="task in instance.tasks" :key="task.id" class="wp-approval-history-row">
            <span class="wp-approval-history-dot" :class="task.status"></span>
            <div class="wp-approval-history-main">
              <strong>{{ task.node_name }}</strong>
              <span>{{ taskStatus(task.status) }}</span>
              <small v-if="task.comment">意见：{{ task.comment }}</small>
              <small>{{ task.action_by_name || task.assignee_name || "待分配" }} · {{ formatDate(task.updated_at || task.created_at) }}</small>
            </div>
          </div>
        </div>
      </template>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import type { RuntimeScope, WorkflowDefinition, WorkflowInstance, WorkflowNode } from "@/types";

const props = withDefaults(
  defineProps<{
    definitionId?: number | string;
    businessModelId?: number | string;
    businessRecordId?: number | string;
    title?: string;
  }>(),
  {
    definitionId: 0,
    businessModelId: 0,
    businessRecordId: 0,
    title: "审批",
  }
);

const emit = defineEmits<{
  (e: "started", instance: WorkflowInstance): void;
  (e: "changed", instance: WorkflowInstance): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
const definition = ref<WorkflowDefinition | null>(null);
const instance = ref<WorkflowInstance | null>(null);
const loading = ref(false);
const starting = ref(false);
const acting = ref(false);
const comment = ref("");

const approvalNodes = computed<WorkflowNode[]>(() =>
  (definition.value?.nodes || []).filter((n) => n.type === "approval")
);
const displayNodes = computed<WorkflowNode[]>(() => {
  const nodes = approvalNodes.value;
  if (nodes.length) return nodes;
  return [{ id: "empty", name: "审批", type: "approval" }];
});

const statusLabel = computed(() => {
  if (!instance.value) return definition.value?.status === "published" ? "待发起" : "草稿";
  return { running: "审批中", approved: "已通过", rejected: "已驳回", cancelled: "已撤回" }[instance.value.status] || instance.value.status;
});
const statusType = computed(() => {
  if (!instance.value) return "info";
  return instance.value.status === "approved" ? "success" : instance.value.status === "rejected" ? "danger" : "warning";
});

function currentApprovalIndex(): number {
  const id = instance.value?.current_node_id;
  if (!id) return -1;
  return approvalNodes.value.findIndex((n) => n.id === id);
}

function nodeClass(node: WorkflowNode, index: number) {
  const current = currentApprovalIndex();
  if (instance.value?.status === "approved") return "done";
  if (instance.value?.status === "rejected" && index === current) return "rejected";
  if (index < current) return "done";
  if (index === current) return "current";
  return "";
}

function taskStatus(status: string): string {
  return { pending: "待处理", approved: "已同意", rejected: "已驳回", transferred: "已转办", cancelled: "已取消" }[status] || status;
}

function formatDate(value?: string): string {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 16);
}

async function loadDefinition() {
  const id = Number(props.definitionId);
  if (!id) return;
  definition.value = await api.get<WorkflowDefinition>(`/workflows/definitions/${id}/`);
}

async function loadInstance() {
  const id = Number(props.definitionId);
  const modelId = Number(props.businessModelId);
  const recordId = Number(props.businessRecordId);
  if (!id || !recordId) {
    instance.value = null;
    return;
  }
  const qs = new URLSearchParams({ business_model_id: String(modelId || ""), business_record_id: String(recordId) });
  const res = await api.get<{ instance: WorkflowInstance | null }>(`/workflows/definitions/${id}/instance/?${qs.toString()}`);
  instance.value = res?.instance || null;
}

async function load() {
  if (!Number(props.definitionId)) return;
  loading.value = true;
  try {
    await loadDefinition();
    await loadInstance();
  } catch (e: any) {
    ElMessage.error(e?.message || "审批流程加载失败");
  } finally {
    loading.value = false;
  }
}

async function start() {
  starting.value = true;
  try {
    const res = await api.post<WorkflowInstance>(`/workflows/definitions/${Number(props.definitionId)}/start/`, {
      title: props.title,
      business_model_id: Number(props.businessModelId) || null,
      business_record_id: Number(props.businessRecordId) || null,
      data: instance.value?.data || {},
    });
    instance.value = res;
    ElMessage.success("已发起审批");
    emit("started", res);
  } catch (e: any) {
    ElMessage.error(e?.message || "发起失败");
  } finally {
    starting.value = false;
  }
}

async function act(action: "approve" | "reject") {
  if (!instance.value) return;
  if (action === "reject") {
    try {
      const r = await ElMessageBox.prompt("请输入驳回原因", "驳回审批", { inputPlaceholder: "驳回原因" });
      comment.value = r.value || "";
    } catch {
      return;
    }
  }
  acting.value = true;
  try {
    const res = await api.post<WorkflowInstance>(`/workflows/instances/${instance.value.id}/action/`, {
      action,
      comment: comment.value,
    });
    instance.value = res;
    comment.value = "";
    ElMessage.success(action === "approve" ? "已同意" : "已驳回");
    emit("changed", res);
  } catch (e: any) {
    ElMessage.error(e?.message || "审批操作失败");
  } finally {
    acting.value = false;
  }
}

onMounted(load);
watch(
  () => [props.definitionId, props.businessModelId, props.businessRecordId],
  () => load()
);
</script>

<style scoped>
.wp-approval {
  width: 100%;
  padding: 4px 0;
  color: #1f2329;
}
.wp-approval-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.wp-approval-kicker {
  color: #86909c;
  font-size: 11px;
  letter-spacing: 1px;
}
.wp-approval-head h3 {
  margin: 2px 0 4px;
  font-size: 18px;
}
.wp-approval-desc {
  margin: 0;
  color: #6b7280;
  font-size: 12px;
}
.wp-approval-tip {
  padding: 18px;
  background: #f7f8fa;
  color: #86909c;
  font-size: 12px;
  border-radius: 4px;
  margin-top: 12px;
}
.wp-approval-start {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 14px;
  color: #86909c;
  font-size: 12px;
}
.wp-approval-progress {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin: 18px 0 14px;
  overflow-x: auto;
}
.wp-approval-node {
  display: flex;
  gap: 7px;
  flex: 1;
  min-width: 130px;
  color: #86909c;
}
.wp-approval-dot {
  flex: none;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #eef0f3;
  color: #86909c;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
}
.wp-approval-node strong {
  display: block;
  font-size: 12px;
  color: inherit;
}
.wp-approval-node small {
  font-size: 10px;
  color: #aab1bb;
}
.wp-approval-node.current {
  color: #2f6fed;
}
.wp-approval-node.current .wp-approval-dot {
  background: #2f6fed;
  color: #fff;
}
.wp-approval-node.done {
  color: #00a870;
}
.wp-approval-node.done .wp-approval-dot {
  background: #00a870;
  color: #fff;
}
.wp-approval-node.rejected {
  color: #e4393c;
}
.wp-approval-node.rejected .wp-approval-dot {
  background: #e4393c;
  color: #fff;
}
.wp-approval-actions {
  padding: 12px;
  background: #f7f8fa;
  border-radius: 5px;
}
.wp-approval-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}
.wp-approval-history {
  margin-top: 16px;
}
.wp-approval-history-row {
  display: flex;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px dashed #eef0f3;
}
.wp-approval-history-dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-top: 5px;
  border-radius: 50%;
  background: #c0c4cc;
}
.wp-approval-history-dot.approved {
  background: #00a870;
}
.wp-approval-history-dot.rejected {
  background: #e4393c;
}
.wp-approval-history-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}
.wp-approval-history-main span,
.wp-approval-history-main small {
  color: #86909c;
}
</style>
