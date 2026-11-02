<template>
  <el-drawer
    :model-value="modelValue"
    title="AI 页面助手"
    size="460px"
    direction="rtl"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="wp-agent">
      <div class="wp-agent-toolbar">
        <span class="wp-agent-hint">
          多轮对话 · 工具调用 · 改前确认
          <el-tag v-if="conversationId" size="small" effect="plain">会话 #{{ conversationId }}</el-tag>
        </span>
        <el-button size="small" text @click="showTasks = !showTasks">{{ showTasks ? "收起高级任务" : "高级任务" }}</el-button>
        <el-button size="small" text @click="openAdvanced">高级 Agent</el-button>
        <el-button size="small" text @click="reset">新会话</el-button>
      </div>

      <AgentTaskMiniPanel v-if="showTasks" :app-id="appId" :page-id="pageId" @applied="onMiniApplied" />

      <div ref="listRef" class="wp-agent-list">
        <div v-if="!messages.length" class="wp-agent-empty">
          <p>试试：</p>
          <el-button size="small" @click="quick('评审这个页面')">评审这个页面</el-button>
          <el-button size="small" @click="quick('把首屏标题改成秋季新品')">改首屏标题</el-button>
          <el-button size="small" @click="quick('切换成深色主题')">切换深色主题</el-button>
          <el-button size="small" @click="quick('加一个按钮 立即购买')">新增按钮</el-button>
        </div>

        <div v-for="message in messages" :key="message.id" class="wp-agent-item" :class="`is-${message.role}`">
          <template v-if="message.role === 'user'">
            <div class="wp-agent-bubble">{{ message.content }}</div>
          </template>

          <template v-else-if="message.role === 'assistant'">
            <div class="wp-agent-bubble assistant">
              <div class="wp-agent-text markdown-body" v-html="renderMarkdown(message.content)"></div>
              <el-collapse v-if="toolTrace(message).length" class="wp-agent-tools">
                <el-collapse-item :title="`工具调用（${toolTrace(message).length}）`" name="tools">
                  <div v-for="(tool, index) in toolTrace(message)" :key="index" class="wp-agent-tool">
                    <code>{{ tool.tool }}</code>
                    <span class="wp-agent-tool-result">{{ JSON.stringify(tool.result).slice(0, 160) }}</span>
                  </div>
                </el-collapse-item>
              </el-collapse>
              <div v-if="message.proposal && message.proposal.kind" class="wp-agent-proposal">
                <div class="wp-agent-proposal-title">
                  <el-tag size="small" type="warning">待确认</el-tag>
                  {{ message.proposal.summary }}
                </div>
                <div class="wp-agent-ops">
                  <span v-for="(op, index) in message.proposal.ops || []" :key="index" class="wp-agent-op">
                    {{ opLabel(op) }}
                  </span>
                  <span v-if="message.proposal.kind === 'page_schema'" class="wp-agent-op">整页替换</span>
                </div>
                <el-button
                  v-if="message.proposal.status !== 'applied'"
                  type="primary"
                  size="small"
                  :loading="applyingId === message.id"
                  @click="apply(message)"
                >应用修改</el-button>
                <el-button
                  v-else-if="message.proposal.undo?.kind && message.proposal.undo_status !== 'undone'"
                  type="warning"
                  plain
                  size="small"
                  :loading="undoingId === message.id"
                  @click="undo(message)"
                >撤销本次应用</el-button>
                <el-tag v-if="message.proposal.status === 'applied' && message.proposal.undo_status === 'undone'" size="small" type="info">已撤销</el-tag>
                <el-tag v-else-if="message.proposal.status === 'applied' && !message.proposal.undo?.kind" size="small" type="success">已应用</el-tag>
              </div>
            </div>
          </template>

          <template v-else-if="message.role === 'tool'">
            <div class="wp-agent-tool-line">
              <code>{{ message.tool_name }}</code>
              <span>{{ JSON.stringify(message.tool_result).slice(0, 100) }}</span>
            </div>
          </template>
        </div>

        <div v-if="sending" class="wp-agent-thinking">{{ streamStatus || "AI 正在分析页面并调用工具…" }}</div>
      </div>

      <div class="wp-agent-input">
        <el-input
          v-model="draft"
          type="textarea"
          :rows="2"
          resize="none"
          placeholder="描述你想怎么改，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="send"
        />
        <el-button v-if="sending" type="danger" plain @click="stopAgent">停止</el-button>
        <el-button type="primary" :loading="sending" :disabled="!draft.trim()" @click="send">发送</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api, apiBase, getToken } from "@/api";
import { renderMarkdown } from "@/utils/markdown";
import AgentTaskMiniPanel from "./AgentTaskMiniPanel.vue";

interface AgentMessage {
  id: number;
  role: string;
  content: string;
  tool_name?: string;
  tool_result?: any;
  proposal?: any;
}

const props = defineProps<{ modelValue: boolean; appId: number; pageId: number; pageName?: string }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "applied", schema: any): void }>();

const conversationId = ref<number | null>(null);
const showTasks = ref(false);

function onMiniApplied(schema: any) {
  emit("applied", schema);
}

function openAdvanced() {
  const lastUser = [...messages.value].reverse().find((x) => x.role === "user")?.content || "";
  const query = new URLSearchParams({
    app_id: String(props.appId),
    page_id: String(props.pageId),
    page_name: props.pageName || "",
    goal: draft.value.trim() || lastUser,
  });
  window.open(`/admin/agent?${query.toString()}`, "_blank");
}
const messages = ref<AgentMessage[]>([]);
const draft = ref("");
const sending = ref(false);
const streamStatus = ref("");
const stopping = ref(false);
let streamController: AbortController | null = null;
const applyingId = ref<number | null>(null);
const undoingId = ref<number | null>(null);
const listRef = ref<HTMLElement | null>(null);

function toolTrace(message: AgentMessage) {
  // 工具消息由后端单独存储，这里从相邻 tool 消息无法直接关联；
  // 会话刷新后按时间顺序展示，已在模板中作为独立条目渲染。
  return Array.isArray((message as any).tools) ? (message as any).tools : [];
}

function opLabel(op: any) {
  const map: Record<string, string> = {
    update_node: `改节点 ${op.node_id || ""}`,
    add_node: "新增节点",
    remove_node: `删除节点 ${op.node_id || ""}`,
    set_meta: "更新页面 Meta",
    set_theme: op.dark ? "深色主题" : "浅色主题",
    set_var: "设置变量",
  };
  return map[op.op] || op.op;
}

async function scrollBottom() {
  await nextTick();
  if (listRef.value) listRef.value.scrollTop = listRef.value.scrollHeight;
}

async function ensureConversation(): Promise<number> {
  if (conversationId.value) return conversationId.value;
  const conversation = await api.post<{ id: number }>("/ai/agent/conversations/", {
    app_id: props.appId,
    page_id: props.pageId,
    title: props.pageName ? `${props.pageName} · AI 助手` : "AI 页面助手",
  });
  conversationId.value = conversation.id;
  return conversation.id;
}

async function refreshConversation() {
  if (!conversationId.value) return;
  const detail = await api.get<{ messages: AgentMessage[] }>(`/ai/agent/conversations/${conversationId.value}/`);
  messages.value = detail.messages || [];
  await scrollBottom();
}

function quick(text: string) {
  draft.value = text;
  send();
}

async function streamAgent(conversation: number, text: string, assistant: AgentMessage, signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${apiBase()}/api/ai/agent/conversations/${conversation}/messages/stream/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(getToken() ? { Authorization: `Bearer ${getToken()}` } : {}),
    },
    body: JSON.stringify({ message: text }),
    signal,
  });
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (!response.body) throw new Error("浏览器不支持流式响应");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let done = false;
  while (!done) {
    const { value, done: finished } = await reader.read();
    if (finished) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.split("\n").find((item) => item.startsWith("data:"));
      if (!line) continue;
      let payload: any;
      try {
        payload = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (payload.type === "status") {
        streamStatus.value = String(payload.text || "正在处理…");
      } else if (payload.type === "delta") {
        assistant.content += String(payload.text || "");
        await scrollBottom();
      } else if (payload.type === "done") {
        const final = payload.assistant || {};
        assistant.id = Number(final.id) || assistant.id;
        assistant.content = String(final.content || assistant.content);
        assistant.proposal = final.proposal || assistant.proposal;
        (assistant as any).tools = final.tools || (assistant as any).tools;
        streamStatus.value = "";
        done = true;
        break;
      } else if (payload.type === "error") {
        throw new Error(String(payload.message || "AI 助手请求失败"));
      }
    }
  }
  await reader.cancel().catch(() => undefined);
}

async function send() {
  const text = draft.value.trim();
  if (!text || sending.value) return;
  sending.value = true;
  stopping.value = false;
  streamController = new AbortController();
  streamStatus.value = "正在连接 AI 助手…";
  draft.value = "";
  messages.value.push({ id: Date.now(), role: "user", content: text });
  const assistant: AgentMessage = { id: Date.now() + 1, role: "assistant", content: "" };
  messages.value.push(assistant);
  await scrollBottom();
  try {
    const id = await ensureConversation();
    await streamAgent(id, text, assistant, streamController.signal);
    await refreshConversation();
  } catch (e: any) {
    if (stopping.value || e?.name === "AbortError") {
      if (!assistant.content) assistant.content = "已停止生成。";
    } else {
      assistant.content = `请求失败：${e?.message || "未知错误"}。可以稍后重试，或先配置 AI Provider。`;
      ElMessage.error(e?.message || "AI 助手请求失败");
    }
  } finally {
    sending.value = false;
    stopping.value = false;
    streamController = null;
    streamStatus.value = "";
    await scrollBottom();
  }
}

async function stopAgent() {
  if (!sending.value || stopping.value) return;
  stopping.value = true;
  try {
    if (conversationId.value) {
      await api.post(`/ai/agent/conversations/${conversationId.value}/stop/`, {});
    }
  } catch {
    /* 即使停止接口失败，也中断前端流 */
  }
  streamController?.abort();
}

async function apply(message: AgentMessage) {
  if (!conversationId.value) return;
  applyingId.value = message.id;
  try {
    const result = await api.post(`/ai/agent/conversations/${conversationId.value}/apply/`, {
      message_id: message.id,
    });
    message.proposal = { ...(message.proposal || {}), status: "applied" };
    if (result.schema) {
      ElMessage.success("修改已写入页面草稿");
      emit("applied", result.schema);
    } else if (result.tool === "create_page") {
      ElMessage.success(`页面已创建：${result.name || ""} /${result.path || ""}`);
    } else if (result.model_id) {
      ElMessage.success(`数据模型已创建：${result.name || result.model_id}`);
    } else if (result.workflow_id) {
      ElMessage.success(`工作流已创建：${result.name || result.workflow_id}`);
    } else if (result.release_id) {
      ElMessage.success("发布操作已完成");
    } else {
      ElMessage.success(result.summary || "操作已完成");
    }
    await refreshConversation();
  } catch (e: any) {
    ElMessage.error(e?.message || "应用失败");
  } finally {
    applyingId.value = null;
  }
}

async function undo(message: AgentMessage) {
  if (!conversationId.value) return;
  undoingId.value = message.id;
  try {
    const result = await api.post(`/ai/agent/conversations/${conversationId.value}/undo/`, {
      message_id: message.id,
    });
    message.proposal = { ...(message.proposal || {}), undo_status: "undone" };
    if (result.schema) {
      emit("applied", result.schema);
      ElMessage.success("已撤销本次页面修改");
    } else if (result.deleted) {
      ElMessage.success("已撤销本次创建操作");
    } else {
      ElMessage.success("已撤销本次应用");
    }
    await refreshConversation();
  } catch (e: any) {
    ElMessage.error(e?.message || "撤销失败");
  } finally {
    undoingId.value = null;
  }
}

function reset() {
  conversationId.value = null;
  messages.value = [];
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) scrollBottom();
  }
);
</script>

<style scoped>
.wp-agent {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.wp-agent-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.wp-agent-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.wp-agent-list {
  flex: 1;
  overflow-y: auto;
  padding: 12px 2px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.wp-agent-empty {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.wp-agent-item {
  display: flex;
  flex-direction: column;
}
.wp-agent-item.is-user {
  align-items: flex-end;
}
.wp-agent-bubble {
  max-width: 92%;
  padding: 8px 11px;
  border-radius: 8px;
  background: var(--el-color-primary);
  color: #fff;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
}
.wp-agent-bubble.assistant {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  white-space: normal;
}
.wp-agent-text {
  white-space: pre-wrap;
}
.wp-agent-text.markdown-body {
  white-space: normal;
  line-height: 1.7;
  word-break: break-word;
}
:deep(.markdown-body p) {
  margin: 0 0 8px;
}
:deep(.markdown-body p:last-child) {
  margin-bottom: 0;
}
:deep(.markdown-body h1),
:deep(.markdown-body h2),
:deep(.markdown-body h3),
:deep(.markdown-body h4) {
  margin: 10px 0 6px;
  line-height: 1.35;
  color: var(--el-text-color-primary);
}
:deep(.markdown-body h1) { font-size: 17px; }
:deep(.markdown-body h2) { font-size: 15px; }
:deep(.markdown-body h3),
:deep(.markdown-body h4) { font-size: 13px; }
:deep(.markdown-body ul),
:deep(.markdown-body ol) {
  margin: 4px 0 8px;
  padding-left: 20px;
}
:deep(.markdown-body li) {
  margin: 2px 0;
}
:deep(.markdown-body code) {
  padding: 1px 4px;
  border-radius: 3px;
  background: var(--el-fill-color);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
:deep(.markdown-body pre) {
  margin: 8px 0;
  padding: 10px;
  overflow-x: auto;
  border-radius: 6px;
  background: var(--el-fill-color-dark);
  color: var(--el-text-color-primary);
}
:deep(.markdown-body pre code) {
  padding: 0;
  background: transparent;
}
:deep(.markdown-body blockquote) {
  margin: 8px 0;
  padding-left: 10px;
  border-left: 3px solid var(--el-color-primary-light-5);
  color: var(--el-text-color-secondary);
}
.wp-agent-tools {
  margin-top: 6px;
}
.wp-agent-tool {
  display: flex;
  gap: 6px;
  font-size: 12px;
  padding: 2px 0;
}
.wp-agent-tool-result {
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-agent-proposal {
  margin-top: 10px;
  border: 1px dashed var(--el-color-warning);
  border-radius: 6px;
  padding: 8px 10px;
  background: var(--el-color-warning-light-9);
}
.wp-agent-proposal-title {
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.wp-agent-ops {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 8px;
}
.wp-agent-op {
  font-size: 11px;
  background: #fff;
  border: 1px solid var(--el-border-color-light);
  border-radius: 4px;
  padding: 1px 6px;
}
.wp-agent-tool-line {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  display: flex;
  gap: 6px;
  padding-left: 8px;
  border-left: 2px solid var(--el-border-color);
}
.wp-agent-thinking {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-agent-input {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
}
</style>
