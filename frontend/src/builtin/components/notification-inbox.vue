<template>
  <section class="inbox" v-loading="loading">
    <header class="inbox-head">
      <div>
        <h2>消息中心</h2>
        <p>审批提醒、系统通知和站内信，未读消息会保留红点。</p>
      </div>
      <div class="inbox-actions">
        <el-radio-group v-model="filter" size="small">
          <el-radio-button label="all">全部</el-radio-button>
          <el-radio-button label="unread">未读</el-radio-button>
        </el-radio-group>
        <el-button size="small" :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <el-empty v-if="!visible.length && !loading" description="暂无消息" :image-size="70" />

    <div v-for="item in visible" :key="item.id" class="inbox-item" :class="{ unread: !item.read_at }" @click="open(item)">
      <div class="inbox-dot" />
      <div class="inbox-body">
        <div class="inbox-title-row">
          <strong>{{ item.subject || "系统通知" }}</strong>
          <span>{{ formatTime(item.created_at) }}</span>
        </div>
        <p>{{ item.content || "—" }}</p>
        <div class="inbox-meta">
          <el-tag size="small" effect="plain">{{ channelText(item.channel) }}</el-tag>
          <el-tag v-if="!item.read_at" size="small" type="warning" effect="plain">未读</el-tag>
          <el-tag v-else size="small" type="info" effect="plain">已读</el-tag>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { RuntimeScope } from "@/types";

const scope = inject<RuntimeScope | null>("wp.scope", null);
const loading = ref(false);
const filter = ref("all");
const messages = ref<any[]>([]);

const visible = computed(() => (filter.value === "unread" ? messages.value.filter((x) => !x.read_at) : messages.value));

async function load() {
  const appId = Number((scope?.variables?.app as any)?.id);
  if (!appId) return;
  loading.value = true;
  try {
    messages.value = (await api.get<any>(`/apps/${appId}/messages/`)).results || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "加载消息失败");
  } finally {
    loading.value = false;
  }
}

async function open(item: any) {
  if (item.read_at) return;
  const appId = Number((scope?.variables?.app as any)?.id);
  try {
    await api.post(`/apps/${appId}/messages/${item.id}/read/`);
    item.read_at = new Date().toISOString();
  } catch {
    /* 忽略单条已读失败 */
  }
}

function channelText(channel: string) {
  return ({ inapp: "站内信", email: "邮件", webhook: "Webhook" } as Record<string, string>)[channel] || channel;
}

function formatTime(value?: string) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString("zh-CN", { hour12: false });
}

onMounted(load);
</script>

<style scoped>
.inbox {
  padding: 8px 0;
}
.inbox-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}
.inbox-head h2 {
  margin: 0;
  font-size: 18px;
}
.inbox-head p {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.inbox-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.inbox-item {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-bg-color);
  cursor: pointer;
  transition: box-shadow 0.15s ease;
}
.inbox-item:hover {
  box-shadow: var(--el-box-shadow-light);
}
.inbox-item.unread {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
}
.inbox-dot {
  width: 8px;
  height: 8px;
  margin-top: 6px;
  border-radius: 50%;
  background: var(--el-border-color);
}
.inbox-item.unread .inbox-dot {
  background: var(--el-color-primary);
}
.inbox-body {
  flex: 1;
  min-width: 0;
}
.inbox-title-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.inbox-title-row strong {
  color: var(--el-text-color-primary);
}
.inbox-title-row span {
  flex: none;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.inbox-body p {
  margin: 8px 0;
  color: var(--el-text-color-regular);
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}
.inbox-meta {
  display: flex;
  gap: 6px;
}
</style>
