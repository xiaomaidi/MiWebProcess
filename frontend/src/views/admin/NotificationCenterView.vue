<template>
  <div class="wp-admin-page wp-notify-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>
          通知中心
          <el-tag v-if="unreadCount" type="danger" effect="plain" size="small">
            {{ unreadCount }} 条未读
          </el-tag>
        </h2>
        <p class="wp-page-desc">
          汇总你在各应用中被 @ 提及的评论与站内信；点击卡片可跳回页面并定位评论。
        </p>
      </div>
      <div class="wp-page-actions">
        <el-radio-group v-model="filterMode" size="small" @change="onFilterChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="unread">未读</el-radio-button>
        </el-radio-group>
        <el-button :disabled="!unreadCount" :loading="markingAll" @click="readAll">全部标为已读</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <el-card shadow="never">
      <div class="wp-notify-summary">
        <span>共 {{ total }} 条{{ filterMode === "unread" ? "未读" : "" }}通知</span>
        <span v-if="lastLoadedAt" class="wp-muted">更新于 {{ lastLoadedAt }}</span>
      </div>

      <div v-loading="loading" class="wp-notify-list">
        <article
          v-for="row in notifications"
          :key="row.id"
          class="wp-notify-card"
          :class="{ unread: !row.is_read }"
          role="button"
          tabindex="0"
          @click="openNotification(row)"
          @keydown.enter.prevent="openNotification(row)"
        >
          <span class="wp-notify-dot" aria-hidden="true" />
          <div class="wp-notify-main">
            <div class="wp-notify-title-row">
              <el-tag
                v-if="row.kind"
                size="small"
                effect="plain"
                :type="row.kind === 'comment_mention' ? 'warning' : 'info'"
              >{{ kindLabel(row.kind) }}</el-tag>
              <strong>{{ row.subject || "系统通知" }}</strong>
              <span class="wp-notify-time">{{ formatTime(row.created_at) }}</span>
            </div>
            <p class="wp-notify-content">{{ row.content || "—" }}</p>
            <div class="wp-notify-meta">
              <span v-if="row.app_name">应用：{{ row.app_name }}</span>
              <span v-if="row.page_name">页面：{{ row.page_name }}</span>
              <span v-if="row.comment_id">
                评论 #{{ row.comment_id }}<template v-if="row.is_reply">（回复）</template>
              </span>
              <span v-if="row.author">来自 {{ row.author }}</span>
              <span v-if="row.mention_username">提及 @{{ row.mention_username }}</span>
            </div>
          </div>
          <div class="wp-notify-actions" @click.stop>
            <el-button v-if="!row.is_read" size="small" :loading="readingId === row.id" @click="markRead(row)">
              标为已读
            </el-button>
            <el-tag v-else size="small" type="info" effect="plain">已读</el-tag>
            <el-button size="small" type="primary" text @click="openNotification(row)">查看</el-button>
          </div>
        </article>
        <el-empty
          v-if="!loading && !notifications.length"
          :description="filterMode === 'unread' ? '没有未读通知' : '暂无通知'"
          :image-size="70"
        />
      </div>

      <div class="wp-pager">
        <el-pagination
          small
          background
          layout="prev, pager, next, total"
          :total="total"
          :page-size="size"
          :current-page="page"
          @current-change="onPageChange"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";

import { api } from "@/api";

interface NotificationItem {
  id: number;
  channel: string;
  kind: string;
  subject: string;
  content: string;
  status: string;
  app_id: number | null;
  app_name: string;
  page_id: number | null;
  page_name: string;
  comment_id: number | null;
  parent_id: number | null;
  root_id: number | null;
  is_reply: boolean;
  node_id: string;
  author: string;
  body: string;
  mention_username: string;
  is_read: boolean;
  read_at: string | null;
  created_at: string | null;
}

interface NotificationFeed {
  count: number;
  results: NotificationItem[];
  page: number;
  size: number;
  unread_count: number;
}

/**
 * 正式路径是 `/api/notifications/`；`config/urls.py` 尚未挂载时回退到
 * `/api/collab/notifications/`（collab/urls.py 已注册同一组视图），
 * 这样无需改 config 也能在本仓库直接使用。
 */
const NOTIFICATION_BASES = ["/notifications/", "/collab/notifications/"] as const;
let notificationBase: string = NOTIFICATION_BASES[0];

async function notificationRequest<T>(
  method: "get" | "post",
  path: string,
  body?: unknown
): Promise<T> {
  let lastError: unknown = null;
  const order = [notificationBase, ...NOTIFICATION_BASES.filter((base) => base !== notificationBase)];
  for (const base of order) {
    try {
      const url = `${base}${path}`;
      const result =
        method === "get"
          ? await api.get<T>(url, { silent: true })
          : await api.post<T>(url, body, { silent: true });
      notificationBase = base;
      return result;
    } catch (error: any) {
      lastError = error;
      // 只有“路径未挂载”的 404 才回退；业务 404 直接抛出。
      if (error?.status !== 404) break;
    }
  }
  throw lastError;
}

const router = useRouter();
const notifications = ref<NotificationItem[]>([]);
const loading = ref(false);
const markingAll = ref(false);
const readingId = ref(0);
const filterMode = ref<"all" | "unread">("all");
const page = ref(1);
const size = ref(20);
const total = ref(0);
const unreadCount = ref(0);
const lastLoadedAt = ref("");

function formatTime(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function kindLabel(kind: string): string {
  const labels: Record<string, string> = {
    comment_mention: "评论提及",
    workflow_todo: "工作流待办",
    audit: "审计提醒",
  };
  return labels[kind] || "通知";
}

async function load() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (filterMode.value === "unread") params.set("unread", "1");
    params.set("page", String(page.value));
    params.set("size", String(size.value));
    const data = await notificationRequest<NotificationFeed>("get", `?${params.toString()}`);
    const rows = data?.results || [];
    const count = Number(data?.count || 0);
    // 删除/已读后当前页可能越界：回退到最后一页重新拉取。
    const lastPage = Math.max(1, Math.ceil(count / size.value));
    if (!rows.length && count > 0 && page.value > lastPage) {
      page.value = lastPage;
      await load();
      return;
    }
    notifications.value = rows;
    total.value = count;
    unreadCount.value = Number(data?.unread_count || 0);
    const currentPage = Number(data?.page || 1);
    if (currentPage !== page.value) page.value = currentPage;
    lastLoadedAt.value = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  } catch (error: any) {
    ElMessage.error(error?.message || "通知加载失败");
  } finally {
    loading.value = false;
  }
}

function onFilterChange() {
  page.value = 1;
  void load();
}

function onPageChange(value: number) {
  page.value = Math.max(1, Number(value) || 1);
  void load();
}

async function markRead(row: NotificationItem): Promise<void> {
  if (row.is_read) return;
  readingId.value = row.id;
  try {
    const updated = await notificationRequest<NotificationItem>("post", `${row.id}/read/`);
    applyRead(row, updated);
  } catch (error: any) {
    ElMessage.error(error?.message || "标记已读失败");
  } finally {
    if (readingId.value === row.id) readingId.value = 0;
  }
}

function applyRead(row: NotificationItem, updated?: Partial<NotificationItem>) {
  row.is_read = true;
  row.read_at = updated?.read_at || new Date().toISOString();
  unreadCount.value = Math.max(0, unreadCount.value - 1);
  if (filterMode.value === "unread") {
    notifications.value = notifications.value.filter((item) => item.id !== row.id);
    total.value = Math.max(0, total.value - 1);
  }
}

async function readAll() {
  if (!unreadCount.value) return;
  markingAll.value = true;
  try {
    const data = await notificationRequest<{ updated: number; unread_count: number }>(
      "post",
      "read-all/"
    );
    unreadCount.value = Number(data?.unread_count || 0);
    ElMessage.success(`已将 ${Number(data?.updated || 0)} 条通知标为已读`);
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "操作失败");
  } finally {
    markingAll.value = false;
  }
}

async function openNotification(row: NotificationItem) {
  // 先标记已读，但不阻塞跳转（失败会提示，仍允许打开）。
  if (!row.is_read) await markRead(row);
  const appId = Number(row.app_id || 0);
  const pageId = Number(row.page_id || 0);
  if (appId > 0 && pageId > 0) {
    await router.push({
      name: "designer",
      params: { appId, pageId },
      query: row.comment_id ? { comment: String(row.comment_id) } : {},
    });
    return;
  }
  if (appId > 0) {
    await router.push(`/admin/apps/${appId}`);
    return;
  }
  ElMessage.info("该通知没有关联页面，可在应用「通知记录」中查看详情");
}

onMounted(load);
</script>

<style scoped>
.wp-notify-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  color: var(--wp-text-muted, #64748b);
  font-size: 12px;
}
.wp-notify-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 160px;
}
.wp-notify-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid #eef2f8;
  border-radius: 12px;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
}
.wp-notify-card:hover,
.wp-notify-card:focus-visible {
  border-color: #bfdbfe;
  background: #f8fbff;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
  outline: none;
}
.wp-notify-card.unread {
  border-color: #bfdbfe;
  background: #f5f9ff;
}
.wp-notify-dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 50%;
  background: #cbd5e1;
}
.wp-notify-card.unread .wp-notify-dot {
  background: var(--wp-primary, #2563eb);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.14);
}
.wp-notify-main {
  flex: 1;
  min-width: 0;
}
.wp-notify-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.wp-notify-title-row strong {
  flex: 1;
  min-width: 0;
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
  word-break: break-word;
}
.wp-notify-card.unread .wp-notify-title-row strong {
  font-weight: 700;
}
.wp-notify-time {
  flex: none;
  color: #94a3b8;
  font-size: 11px;
}
.wp-notify-content {
  margin: 7px 0;
  color: #475569;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.wp-notify-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  color: #94a3b8;
  font-size: 11px;
}
.wp-notify-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 6px;
}
.wp-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

@media (max-width: 720px) {
  .wp-page-actions {
    width: 100%;
    justify-content: flex-start;
  }
  .wp-notify-card {
    flex-wrap: wrap;
    padding: 12px;
  }
  .wp-notify-actions {
    width: 100%;
    justify-content: flex-end;
    border-top: 1px dashed #eef2f8;
    padding-top: 8px;
  }
  .wp-pager {
    justify-content: center;
  }
}
</style>
