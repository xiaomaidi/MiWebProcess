<template>
  <div class="wp-wf-page">
    <header class="wp-wf-top">
      <div>
        <el-button text @click="goBack">← 返回应用</el-button>
        <h1>工作流设计器</h1>
        <p>线性审批流：发起 → 审批节点 → 结束。审批通过后自动回写业务记录状态。</p>
      </div>
      <div class="wp-wf-top-actions">
        <el-button type="primary" plain @click="aiOpen = true">✨ AI 生成流程</el-button>
        <el-button @click="createNew">新建流程</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        <el-button type="success" :disabled="!selected" :loading="publishing" @click="publish">发布</el-button>
      </div>
    </header>

    <div class="wp-wf-body">
      <aside class="wp-wf-list">
        <div class="wp-wf-list-head">流程定义 <span>{{ definitions.length }}</span></div>
        <button
          v-for="def in definitions"
          :key="def.id"
          type="button"
          class="wp-wf-list-item"
          :class="{ active: selected?.id === def.id }"
          @click="select(def)"
        >
          <strong>{{ def.name }}</strong>
          <span>{{ def.code }} · {{ statusLabel(def.status) }}</span>
        </button>
        <el-empty v-if="!definitions.length" description="暂无流程" :image-size="50" />
      </aside>

      <main class="wp-wf-editor" v-if="selected">
        <div class="wp-wf-editor-head">
          <div>
            <h2>{{ selected.id ? selected.name : "新建流程" }}</h2>
            <span class="wp-wf-status" :class="selected.status">{{ statusLabel(selected.status) }}</span>
          </div>
        </div>

        <div class="wp-wf-form">
          <label>流程名称</label>
          <el-input v-model="form.name" placeholder="例如：采购订单审批" />
          <label>流程编码</label>
          <el-input v-model="form.code" placeholder="purchase_approval" :disabled="!!selected.id" />
          <label>说明</label>
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </div>

        <div class="wp-wf-steps-head">
          <h3>流程节点</h3>
          <div class="wp-wf-add-actions">
            <el-button size="small" type="primary" plain @click="addNode('approval')">+ 审批节点</el-button>
            <el-button size="small" plain @click="addNode('condition')">+ 条件节点</el-button>
          </div>
        </div>

        <div class="wp-wf-steps">
          <div class="wp-wf-endpoint">开始 · 发起人提交</div>
          <div v-for="(node, index) in flowNodes" :key="node.id" class="wp-wf-step" :class="`type-${node.type}`">
            <div class="wp-wf-step-index">{{ node.type === "condition" ? "?" : index + 1 }}</div>
            <div class="wp-wf-step-main">
              <div class="wp-wf-step-title">
                <el-input v-model="node.name" size="small" placeholder="节点名称" />
                <el-select v-model="node.type" size="small" style="width: 100px" @change="normalizeNode(node)">
                  <el-option label="审批" value="approval" />
                  <el-option label="条件" value="condition" />
                </el-select>
              </div>

              <template v-if="node.type === 'condition'">
                <div class="wp-wf-step-row">
                  <span>字段</span>
                  <el-input v-model="conditionOf(node).field" size="small" placeholder="status" style="width: 130px" />
                  <el-select v-model="conditionOf(node).operator" size="small" style="width: 100px">
                    <el-option label="等于" value="eq" />
                    <el-option label="不等于" value="ne" />
                    <el-option label="包含" value="contains" />
                    <el-option label="大于" value="gt" />
                    <el-option label="小于" value="lt" />
                  </el-select>
                  <el-input v-model="conditionOf(node).value" size="small" placeholder="值" style="width: 130px" />
                </div>
                <div class="wp-wf-step-row">
                  <span>不满足时跳转</span>
                  <el-select v-model="node.false_next" size="small" clearable placeholder="默认继续下一节点" style="width: 220px">
                    <el-option v-for="opt in nextOptions(node)" :key="opt.value" :label="opt.label" :value="opt.value" />
                  </el-select>
                </div>
              </template>

              <template v-else>
                <div class="wp-wf-step-row">
                  <span>审批人</span>
                  <el-select v-model="node.assignee_type" size="small" style="width: 110px">
                    <el-option label="按角色" value="role" />
                    <el-option label="指定用户" value="user" />
                    <el-option label="发起人" value="initiator" />
                    <el-option label="部门负责人" value="dept_leader" />
                  </el-select>
                  <template v-if="node.assignee_type === 'role' || node.assignee_type === 'user'">
                    <el-select v-model="node.assignee_role" size="small" style="width: 100px">
                      <el-option label="查看者" value="viewer" />
                      <el-option label="编辑者" value="editor" />
                      <el-option label="所有者" value="owner" />
                    </el-select>
                    <span class="wp-wf-hint">或用户 ID</span>
                    <el-input-number v-model="node.assignee_user_id" :min="0" size="small" controls-position="right" style="width: 95px" />
                  </template>
                  <span v-else-if="node.assignee_type === 'dept_leader'" class="wp-wf-hint">
                    按业务数据 dept 字段 / 发起人主部门解析负责人
                  </span>
                  <el-select v-model="node.mode" size="small" style="width: 105px" title="多人审批模式">
                    <el-option label="全部通过" value="all" />
                    <el-option label="任一人通过" value="any" />
                  </el-select>
                  <span class="wp-wf-hint">时限(h)</span>
                  <el-input-number v-model="node.timeout_hours" :min="0" size="small" controls-position="right" style="width: 95px" />
                </div>
                <div class="wp-wf-step-row wp-wf-approvers-row">
                  <span>并行审批人</span>
                  <div class="wp-wf-approvers">
                    <div v-for="(approver, ai) in node.approvers || []" :key="ai" class="wp-wf-approver">
                      <el-select v-model="approver.assignee_role" size="small" style="width: 100px">
                        <el-option label="查看者" value="viewer" />
                        <el-option label="编辑者" value="editor" />
                        <el-option label="所有者" value="owner" />
                      </el-select>
                      <el-input-number v-model="approver.assignee_user_id" :min="0" size="small" controls-position="right" style="width: 100px" placeholder="用户 ID" />
                      <el-button size="small" text type="danger" @click="removeApprover(node, ai)">×</el-button>
                    </div>
                    <el-button size="small" text type="primary" @click="addApprover(node)">+ 添加审批人</el-button>
                  </div>
                </div>
              </template>
            </div>
            <div class="wp-wf-step-actions">
              <el-button size="small" text :disabled="index === 0" @click="move(index, -1)">↑</el-button>
              <el-button size="small" text :disabled="index === flowNodes.length - 1" @click="move(index, 1)">↓</el-button>
              <el-button size="small" text type="danger" @click="removeNode(index)">×</el-button>
            </div>
          </div>
          <div class="wp-wf-endpoint">结束 · 回写业务状态（通过：已审批 / 驳回：已驳回）</div>
        </div>

        <div class="wp-wf-tip">
          审批人按角色匹配应用成员；并行审批可填多个审批人。条件节点按业务数据字段判断，不满足时跳到指定节点。
        </div>
      </main>
      <main v-else class="wp-wf-empty">
        <el-empty description="选择或新建一个流程开始设计" />
      </main>
    </div>

    <AiWorkflowDialog v-model="aiOpen" :app-id="appId" @generated="onAiGenerated" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { WorkflowDefinition, WorkflowNode } from "@/types";
import AiWorkflowDialog from "@/views/AiWorkflowDialog.vue";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId);
const definitions = ref<WorkflowDefinition[]>([]);
const selected = ref<WorkflowDefinition | null>(null);
const saving = ref(false);
const publishing = ref(false);
const form = reactive({ name: "", code: "", description: "" });
const flowNodes = ref<WorkflowNode[]>([]);
const aiOpen = ref(false);

function statusLabel(status: string): string {
  return { draft: "草稿", published: "已发布", archived: "已归档" }[status] || status;
}

async function load() {
  try {
    definitions.value = await api.get<WorkflowDefinition[]>(`/workflows/definitions/?app_id=${appId}`);
    if (!selected.value && definitions.value.length) select(definitions.value[0]);
  } catch (e: any) {
    ElMessage.error(e?.message || "流程加载失败");
  }
}

function select(def: WorkflowDefinition) {
  selected.value = def;
  form.name = def.name;
  form.code = def.code;
  form.description = def.description || "";
  flowNodes.value = (def.nodes || [])
    .filter((n) => n.type === "approval" || n.type === "condition")
    .map((n) => normalizeNode({ ...n }));
}

function normalizeNode(node: WorkflowNode): WorkflowNode {
  if (node.type === "condition" && (!node.condition || typeof node.condition !== "object")) {
    node.condition = { field: "status", operator: "eq", value: "" };
  }
  if (node.type === "approval") {
    node.mode = node.mode || "all";
    node.assignee_type = node.assignee_type || (node.assignee_user_id ? "user" : "role");
    node.assignee_role = node.assignee_role || "editor";
  }
  return node;
}

function conditionOf(node: WorkflowNode): Record<string, any> {
  if (!node.condition || typeof node.condition !== "object") node.condition = { field: "status", operator: "eq", value: "" };
  return node.condition;
}

function addApprover(node: WorkflowNode) {
  if (!Array.isArray(node.approvers)) node.approvers = [];
  node.approvers.push({ assignee_role: "owner", assignee_user_id: null });
}

function removeApprover(node: WorkflowNode, index: number) {
  node.approvers?.splice(index, 1);
}

function nextOptions(node: WorkflowNode): { label: string; value: string }[] {
  return [
    { label: "结束（通过）", value: "end" },
    ...flowNodes.value
      .filter((n) => n.id !== node.id)
      .map((n) => ({ label: `${n.type === "condition" ? "[条件] " : ""}${n.name || n.id}`, value: n.id })),
  ];
}

function onAiGenerated(draft: any) {
  selected.value = {
    id: 0,
    app_id: appId,
    name: draft.name,
    code: draft.code,
    description: draft.description || "",
    nodes: [],
    status: "draft",
    version: 1,
  };
  form.name = draft.name;
  form.code = draft.code;
  form.description = draft.description || "";
  flowNodes.value = (draft.nodes || []).map((n: WorkflowNode) => normalizeNode({ ...n }));
  ElMessage.success("AI 流程已填入设计器，请检查后保存/发布");
}

function createNew() {
  selected.value = { id: 0, app_id: appId, name: "", code: "", description: "", nodes: [], status: "draft", version: 1 };
  form.name = "";
  form.code = "";
  form.description = "";
  flowNodes.value = [normalizeNode({ id: `approval_${Date.now()}`, name: "部门审批", type: "approval", assignee_role: "editor" })];
}

function addNode(type: "approval" | "condition" = "approval") {
  const id = `${type}_${Date.now()}`;
  flowNodes.value.push(normalizeNode({
    id,
    name: type === "condition" ? `条件 ${flowNodes.value.length + 1}` : `审批节点 ${flowNodes.value.length + 1}`,
    type,
    assignee_role: "editor",
    assignee_user_id: null,
  }));
}

function removeNode(index: number) {
  flowNodes.value.splice(index, 1);
}

function move(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= flowNodes.value.length) return;
  const [item] = flowNodes.value.splice(index, 1);
  flowNodes.value.splice(target, 0, item);
}

function buildNodes(): WorkflowNode[] {
  return [
    { id: "start", name: "发起", type: "start" },
    ...flowNodes.value.map((n) => ({ ...n })),
    { id: "end", name: "结束", type: "end", on_approve: { status: "已审批" }, on_reject: { status: "已驳回" } },
  ];
}

async function save() {
  if (!form.name.trim() || !form.code.trim()) {
    ElMessage.warning("请填写流程名称和编码");
    return;
  }
  if (!flowNodes.value.some((n) => n.type === "approval")) {
    ElMessage.warning("至少添加一个审批节点");
    return;
  }
  saving.value = true;
  try {
    const payload = { name: form.name, code: form.code, description: form.description, nodes: buildNodes() };
    let def: WorkflowDefinition;
    if (selected.value?.id) {
      def = await api.put<WorkflowDefinition>(`/workflows/definitions/${selected.value.id}/`, payload);
    } else {
      def = await api.post<WorkflowDefinition>(`/workflows/definitions/`, { app_id: appId, ...payload });
    }
    selected.value = def;
    await load();
    select(def);
    ElMessage.success("流程已保存");
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function publish() {
  if (!selected.value?.id) {
    ElMessage.warning("请先保存流程");
    return;
  }
  publishing.value = true;
  try {
    const def = await api.post<WorkflowDefinition>(`/workflows/definitions/${selected.value.id}/publish/`, {});
    selected.value = def;
    await load();
    select(def);
    ElMessage.success("流程已发布");
  } catch (e: any) {
    ElMessage.error(e?.message || "发布失败");
  } finally {
    publishing.value = false;
  }
}

function goBack() {
  router.push(`/admin/apps/${appId}`);
}

onMounted(load);
</script>

<style scoped>
.wp-wf-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  color: #1f2329;
}
.wp-wf-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  padding: 18px 24px;
  background: #fff;
  border-bottom: 1px solid #e5e6eb;
}
.wp-wf-top h1 {
  margin: 2px 0 4px;
  font-size: 22px;
}
.wp-wf-top p {
  margin: 0;
  color: #86909c;
  font-size: 12px;
}
.wp-wf-top-actions {
  display: flex;
  gap: 8px;
}
.wp-wf-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.wp-wf-list {
  width: 280px;
  background: #fff;
  border-right: 1px solid #e5e6eb;
  overflow: auto;
  padding: 14px;
}
.wp-wf-list-head {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  display: flex;
  justify-content: space-between;
}
.wp-wf-list-head span {
  color: #86909c;
  font-weight: 400;
}
.wp-wf-list-item {
  width: 100%;
  text-align: left;
  border: 1px solid #eef0f3;
  border-radius: 5px;
  background: #fff;
  padding: 9px 10px;
  margin-bottom: 6px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.wp-wf-list-item:hover,
.wp-wf-list-item.active {
  border-color: #2f6fed;
  background: #f4f8ff;
}
.wp-wf-list-item strong {
  font-size: 13px;
}
.wp-wf-list-item span {
  color: #86909c;
  font-size: 11px;
}
.wp-wf-editor {
  flex: 1;
  overflow: auto;
  padding: 24px;
}
.wp-wf-editor-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 760px;
}
.wp-wf-editor-head h2 {
  margin: 0 0 6px;
  font-size: 20px;
}
.wp-wf-status {
  font-size: 11px;
  color: #86909c;
  border: 1px solid #e5e6eb;
  padding: 1px 6px;
  border-radius: 3px;
}
.wp-wf-status.published {
  color: #00a870;
  border-color: #b7ebd4;
  background: #f0fff7;
}
.wp-wf-form {
  max-width: 760px;
  background: #fff;
  border: 1px solid #eef0f3;
  border-radius: 6px;
  padding: 18px;
  margin-top: 14px;
  display: grid;
  grid-template-columns: 100px 1fr;
  gap: 10px 12px;
  align-items: center;
}
.wp-wf-form label {
  font-size: 12px;
  color: #6b7280;
}
.wp-wf-steps-head {
  max-width: 760px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 20px 0 10px;
}
.wp-wf-steps-head h3 {
  margin: 0;
  font-size: 15px;
}
.wp-wf-steps {
  max-width: 760px;
  background: #fff;
  border: 1px solid #eef0f3;
  border-radius: 6px;
  padding: 18px;
}
.wp-wf-endpoint {
  font-size: 12px;
  color: #86909c;
  padding: 8px 10px;
  background: #f7f8fa;
  border-radius: 4px;
}
.wp-wf-step {
  display: flex;
  gap: 10px;
  margin: 8px 0 8px 10px;
  padding-left: 12px;
  border-left: 2px solid #2f6fed;
}
.wp-wf-step-index {
  flex: none;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #2f6fed;
  color: #fff;
  font-size: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.wp-wf-step-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wp-wf-step-title {
  display: flex;
  gap: 6px;
}
.wp-wf-step.type-condition {
  border-left-color: #d97706;
}
.wp-wf-step.type-condition .wp-wf-step-index {
  background: #d97706;
}
.wp-wf-add-actions {
  display: flex;
  gap: 6px;
}
.wp-wf-step-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}
.wp-wf-hint {
  color: #aab1bb;
  margin-left: 8px;
}
.wp-wf-approvers-row {
  align-items: flex-start;
}
.wp-wf-approvers {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}
.wp-wf-approver {
  display: flex;
  align-items: center;
  gap: 4px;
}
.wp-wf-step-actions {
  flex: none;
}
.wp-wf-tip {
  max-width: 760px;
  color: #86909c;
  font-size: 11px;
  margin-top: 12px;
}
.wp-wf-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
