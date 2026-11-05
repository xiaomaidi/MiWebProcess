<template>
  <div class="wp-comments">
    <div class="wp-comments-head">
      <strong>页面评论</strong>
      <div class="wp-comments-head-right">
        <span
          class="wp-comments-sync"
          :class="{ online: syncOnline }"
          :title="syncOnline ? '评论实时同步已连接' : '评论实时同步未连接'"
        >
          {{ syncOnline ? "实时同步" : "实时未连接" }}
        </span>
        <el-checkbox v-model="showResolved" size="small" @change="reload">显示已解决</el-checkbox>
      </div>
    </div>

    <div v-if="mentionNotice" class="wp-comments-notice">
      <button type="button" class="wp-comments-notice-body" @click="focusComment(mentionNotice.commentId)">
        {{ mentionNotice.text }}
      </button>
      <button type="button" class="wp-comments-notice-close" title="关闭" @click="mentionNotice = null">×</button>
    </div>

    <div class="wp-comments-compose">
      <div v-if="replyTo" class="wp-comments-reply-banner">
        <span>
          正在回复
          <strong>{{ replyTo.author || "成员" }}</strong>
          <em v-if="replyTo.deleted">（已删除）</em>
        </span>
        <button type="button" class="wp-comments-reply-cancel" @click="cancelReply">取消</button>
      </div>
      <div class="wp-comments-input-wrap">
        <el-input
          ref="composeRef"
          v-model="body"
          type="textarea"
          :rows="3"
          maxlength="4000"
          show-word-limit
          :placeholder="composePlaceholder"
          @input="onBodyInput"
          @keydown="onComposeKeydown"
          @click="onCaret"
          @keyup="onCaret"
          @blur="onComposeBlur"
        />
        <div v-if="mentionOpen" class="wp-mention-menu">
          <button
            v-for="(user, index) in filteredUsers"
            :key="user.id || user.username"
            type="button"
            class="wp-mention-item"
            :class="{ active: index === mentionIndex }"
            @mousedown.prevent="insertMention(user)"
          >
            <strong>{{ user.display_name }}</strong>
            <span>@{{ user.username }}</span>
          </button>
          <div v-if="!filteredUsers.length" class="wp-mention-empty">没有匹配的成员</div>
        </div>
      </div>
      <div class="wp-comments-compose-foot">
        <span>
          <template v-if="replyTo">回复 {{ replyTo.author || "成员" }} · 第 {{ replyTo.depth + 2 }} 层</template>
          <template v-else>{{ selectedId ? `关联组件 ${selectedId}` : "页面级评论" }}</template>
        </span>
        <div class="wp-comments-compose-actions">
          <el-button v-if="replyTo" size="small" text @click="cancelReply">取消回复</el-button>
          <el-button size="small" type="primary" :loading="saving" @click="submit">
            {{ replyTo ? "回复" : "发表" }}
          </el-button>
        </div>
      </div>
      <div v-if="pendingMentionUsers.length" class="wp-comments-mention-hint">
        将通知
        <span v-for="user in pendingMentionUsers" :key="user.username" class="wp-mention-chip">
          @{{ user.username }}
        </span>
      </div>
    </div>

    <div v-loading="loading" class="wp-comments-list">
      <template v-for="row in visibleRows" :key="row.item.id">
        <article
          :id="`wp-comment-${row.item.id}`"
          class="wp-comment"
          :class="{
            resolved: row.item.resolved,
            deleted: row.item.deleted,
            focused: focusedId === row.item.id,
            reply: row.level > 0,
          }"
          :style="indentStyle(row.level)"
        >
          <div class="wp-comment-head">
            <span class="wp-comment-author">
              <span v-if="row.level" class="wp-comment-arrow">↳</span>
              <strong>{{ row.item.author || "成员" }}</strong>
              <span v-if="row.item.deleted" class="wp-comment-deleted-badge">已删除</span>
              <span v-else-if="mentionsMe(row.item)" class="wp-comment-mention-badge">提到了你</span>
              <span v-if="row.item.parent_id" class="wp-comment-reply-to">
                回复 {{ replyTargetName(row.item) || "成员" }}
              </span>
            </span>
            <span>{{ format(row.item.created_at) }}</span>
          </div>
          <p class="wp-comment-body" :class="{ deleted: row.item.deleted }">
            <template v-if="row.item.deleted">{{ row.item.body || "[已删除]" }}</template>
            <template v-else>
              <span
                v-for="(segment, index) in segmentsFor(row.item)"
                :key="index"
                :class="{ 'wp-mention': segment.mention }"
              >{{ segment.text }}</span>
            </template>
          </p>
          <div v-if="!row.item.deleted && row.item.mentions && row.item.mentions.length" class="wp-comment-mentions">
            <span class="wp-comment-mention-label">提及</span>
            <span v-for="mention in row.item.mentions" :key="mention.username" class="wp-mention-chip">
              @{{ mention.username }}
            </span>
          </div>
          <div class="wp-comment-foot">
            <div class="wp-comment-foot-left">
              <button v-if="row.item.node_id" type="button" class="wp-comment-node" @click="focusNode(row.item.node_id)">
                {{ nodeLabel(row.item.node_id) }}
              </button>
              <span v-else class="wp-comment-node">页面</span>
              <span v-if="row.level" class="wp-comment-depth-tag">第 {{ row.level + 1 }} 层</span>
              <button
                v-if="row.totalReplies"
                type="button"
                class="wp-comment-thread-toggle"
                @click="toggleCollapse(row.item)"
              >
                {{ row.collapsed ? `展开 ${row.totalReplies} 条回复` : `收起 ${row.totalReplies} 条回复` }}
              </button>
            </div>
            <div class="wp-comment-actions">
              <el-button v-if="canReply(row.item)" size="small" text @click="startReply(row.item)">回复</el-button>
              <template v-if="!row.item.deleted">
                <el-button size="small" text @click="toggle(row.item)">{{ row.item.resolved ? "重新打开" : "解决" }}</el-button>
                <el-button size="small" text type="danger" @click="remove(row.item)">删除</el-button>
              </template>
            </div>
          </div>
        </article>
      </template>
      <el-empty v-if="!loading && !visibleRows.length" description="还没有评论" :image-size="48" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import { useAuthStore } from "@/store/auth";
import { CommentSync, type CommentEvent } from "../comment-sync";
import {
  extractMentionTokens,
  fetchMentionUsers,
  filterMentionUsers,
  mentionSegments,
  resolveMentionUser,
  type MentionSegment,
  type MentionUser,
  type MentionWarning,
} from "../comment-mentions";

interface CommentMention {
  id?: number | null;
  username: string;
  display_name?: string;
}

interface CommentItem {
  id: number;
  page_id: number;
  node_id: string;
  body: string;
  author: string;
  author_id: number | null;
  parent_id: number | null;
  root_id: number | null;
  depth: number;
  is_reply: boolean;
  deleted: boolean;
  resolved: boolean;
  resolved_by: string;
  resolved_reply_ids?: number[];
  created_at: string | null;
  updated_at: string | null;
  mentions?: CommentMention[];
  mention_usernames?: string[];
  warnings?: MentionWarning[];
  notified_count?: number;
}

interface CommentRow {
  item: CommentItem;
  level: number;
  totalReplies: number;
  collapsed: boolean;
}

/** 与后端 collab.models.MAX_COMMENT_DEPTH 对齐：根评论 + 最多两级回复。 */
const MAX_THREAD_LEVELS = 3;
const MAX_COMMENTS = 500;

const props = defineProps<{ pageId: number }>();
const schema = useSchemaStore();
const auth = useAuthStore();
const route = useRoute();
const comments = ref<CommentItem[]>([]);
const body = ref("");
const loading = ref(false);
const saving = ref(false);
const showResolved = ref(false);
const selectedId = computed(() => schema.selectedId || "");
const appId = computed(() => Number(schema.appId) || 0);
const me = computed(() => auth.user?.username || "");

const composeRef = ref<any>(null);
const mentionUsers = ref<MentionUser[]>([]);
const mentionOpen = ref(false);
const mentionQuery = ref("");
const mentionStart = ref(-1);
const mentionIndex = ref(0);
const mentionNotice = ref<{ text: string; commentId: number } | null>(null);
const syncOnline = ref(false);
const replyTo = ref<CommentItem | null>(null);
const collapsedIds = ref(new Set<number>());
const focusedId = ref(0);

let sync: CommentSync | null = null;
let blurTimer: number | undefined;
let reloadTimer: number | undefined;
let focusTimer: number | undefined;

const MENTION_TRIGGER_RE = /(^|[^A-Za-z0-9_@])@([\p{L}\p{N}_.@+\-]*)$/u;

const filteredUsers = computed(() => filterMentionUsers(mentionUsers.value, mentionQuery.value));

const pendingMentionUsers = computed<MentionUser[]>(() => {
  const rows: MentionUser[] = [];
  for (const token of extractMentionTokens(body.value)) {
    const user = resolveMentionUser(token, mentionUsers.value);
    if (user && !rows.some((row) => row.username === user.username)) rows.push(user);
  }
  return rows;
});

const composePlaceholder = computed(() =>
  replyTo.value
    ? `回复 @${replyTo.value.author || "成员"}，输入 @ 可提及成员…`
    : "评论当前选中组件，或输入页面级评论；输入 @ 提及成员…"
);

const commentsById = computed(() => {
  const map = new Map<number, CommentItem>();
  for (const item of comments.value) map.set(item.id, item);
  return map;
});

/** 按 parent_id 组装线程：根评论新→旧，同一父节点下的回复旧→新。 */
const threadIndex = computed(() => {
  const children = new Map<number, CommentItem[]>();
  const roots: CommentItem[] = [];
  for (const item of comments.value) {
    if (item.parent_id && commentsById.value.has(item.parent_id)) {
      const rows = children.get(item.parent_id) || [];
      rows.push(item);
      children.set(item.parent_id, rows);
    } else {
      // 父评论不在当前结果集时（被硬删除/超出上限），提升为根节点，避免丢评论。
      roots.push(item);
    }
  }
  const asc = (a: CommentItem, b: CommentItem) =>
    timestamp(a.created_at) - timestamp(b.created_at) || a.id - b.id;
  const desc = (a: CommentItem, b: CommentItem) =>
    timestamp(b.created_at) - timestamp(a.created_at) || b.id - a.id;
  for (const rows of children.values()) rows.sort(asc);
  roots.sort(desc);
  return { children, roots };
});

const visibleRows = computed<CommentRow[]>(() => {
  const { children, roots } = threadIndex.value;
  const counts = new Map<number, number>();
  const countReplies = (id: number): number => {
    if (counts.has(id)) return counts.get(id) || 0;
    let total = 0;
    for (const child of children.get(id) || []) total += 1 + countReplies(child.id);
    counts.set(id, total);
    return total;
  };
  const rows: CommentRow[] = [];
  const walk = (list: CommentItem[], level: number) => {
    for (const item of list) {
      const totalReplies = countReplies(item.id);
      const collapsed = collapsedIds.value.has(item.id);
      rows.push({ item, level, totalReplies, collapsed });
      if (totalReplies && !collapsed) walk(children.get(item.id) || [], level + 1);
    }
  };
  walk(roots, 0);
  return rows;
});

function textareaEl(): HTMLTextAreaElement | null {
  const input = composeRef.value;
  const node = input?.textarea || input?.$el?.querySelector?.("textarea");
  return node instanceof HTMLTextAreaElement ? node : null;
}

function closeMentions() {
  mentionOpen.value = false;
  mentionQuery.value = "";
  mentionStart.value = -1;
  mentionIndex.value = 0;
}

function detectMention() {
  const el = textareaEl();
  const text = body.value;
  const caret = el && typeof el.selectionStart === "number" ? el.selectionStart : text.length;
  const match = text.slice(0, caret).match(MENTION_TRIGGER_RE);
  if (!match) {
    closeMentions();
    return;
  }
  const query = match[2] || "";
  if (query.length > 64) {
    closeMentions();
    return;
  }
  mentionStart.value = caret - query.length - 1;
  mentionQuery.value = query;
  mentionOpen.value = true;
  mentionIndex.value = 0;
}

function onBodyInput() {
  detectMention();
}

function onCaret() {
  if (mentionOpen.value) detectMention();
}

function onComposeBlur() {
  window.clearTimeout(blurTimer);
  blurTimer = window.setTimeout(() => {
    mentionOpen.value = false;
  }, 150);
}

function moveMention(delta: number) {
  const count = filteredUsers.value.length;
  if (!count) return;
  mentionIndex.value = (mentionIndex.value + delta + count) % count;
}

function insertMention(user: MentionUser) {
  const el = textareaEl();
  const caret = el && typeof el.selectionStart === "number" ? el.selectionStart : body.value.length;
  const start = mentionStart.value >= 0 ? Math.min(mentionStart.value, caret) : caret;
  const insert = `@${user.username} `;
  body.value = body.value.slice(0, start) + insert + body.value.slice(caret);
  closeMentions();
  void nextTick(() => {
    const node = textareaEl();
    if (!node) return;
    node.focus();
    const pos = start + insert.length;
    node.setSelectionRange(pos, pos);
  });
}

function onComposeKeydown(event: KeyboardEvent) {
  if (event.isComposing) return;
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    void submit();
    return;
  }
  if (!mentionOpen.value) return;
  if (event.key === "ArrowDown") {
    event.preventDefault();
    moveMention(1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    moveMention(-1);
  } else if (event.key === "Enter" || event.key === "Tab") {
    const user = filteredUsers.value[mentionIndex.value];
    if (user) {
      event.preventDefault();
      insertMention(user);
    } else {
      closeMentions();
    }
  } else if (event.key === "Escape") {
    event.preventDefault();
    closeMentions();
  }
}

async function load(silent = false) {
  if (!props.pageId) return;
  if (!silent) loading.value = true;
  try {
    const query = showResolved.value ? "" : "?resolved=0";
    const data = await api.get<{ results?: CommentItem[] }>(`/collab/pages/${props.pageId}/comments/${query}`);
    comments.value = data?.results || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "评论加载失败");
  } finally {
    if (!silent) loading.value = false;
  }
}

function reload() {
  void load();
}

/** 实时事件里的“解决/重开”可能影响整条线程，静默重载最稳妥（避免残留隐藏节点）。 */
function scheduleReload() {
  window.clearTimeout(reloadTimer);
  reloadTimer = window.setTimeout(() => {
    void load(true);
  }, 300);
}

async function loadMentionUsers() {
  try {
    mentionUsers.value = await fetchMentionUsers(appId.value);
  } catch {
    mentionUsers.value = [];
  }
}

function timestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? 0 : time;
}

function upsert(item: CommentItem) {
  const index = comments.value.findIndex((row) => row.id === item.id);
  if (index >= 0) comments.value[index] = { ...comments.value[index], ...item };
  else comments.value.push(item);
  if (comments.value.length > MAX_COMMENTS) comments.value.splice(0, comments.value.length - MAX_COMMENTS);
}

function collectThreadIds(id: number): Set<number> {
  const ids = new Set<number>([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const item of comments.value) {
      if (item.parent_id && ids.has(item.parent_id) && !ids.has(item.id)) {
        ids.add(item.id);
        changed = true;
      }
    }
  }
  return ids;
}

function dropComment(id: number) {
  const ids = collectThreadIds(id);
  comments.value = comments.value.filter((row) => !ids.has(row.id));
  for (const value of ids) collapsedIds.value.delete(value);
  if (replyTo.value && ids.has(replyTo.value.id)) replyTo.value = null;
}

function applyRealtime(event: CommentEvent) {
  if (event.type === "comment_deleted") {
    dropComment(event.commentId);
    return;
  }
  const item = event.comment as CommentItem | null;
  if (!item || !item.id) return;

  const mentioned = (item.mentions || []).some((mention) => mention.username === me.value);
  if (me.value && event.from && event.from !== me.value && mentioned) {
    const where = item.is_reply ? "在回复中" : "在评论中";
    mentionNotice.value = {
      text: `@${event.from} ${where}提到了你`,
      commentId: item.id,
    };
    ElMessage.info(`@${event.from} ${where}提到了你`);
  }

  const resolvedIds = Array.isArray(item.resolved_reply_ids)
    ? item.resolved_reply_ids.map((value) => Number(value)).filter((value) => value > 0)
    : [];
  if (!showResolved.value && (item.resolved || resolvedIds.length)) {
    // 未显示已解决时，解决/重开会改变整条线程的可见性，直接重载。
    scheduleReload();
    return;
  }
  for (const id of resolvedIds) {
    const target = commentsById.value.get(id);
    if (target) target.resolved = Boolean(item.resolved);
  }
  const existing = commentsById.value.get(item.id);
  const incoming: CommentItem = { ...(existing || {}), ...item };
  delete incoming.resolved_reply_ids;
  upsert(incoming);
  if (incoming.parent_id) expandAncestors(incoming.id);
}

function startSync() {
  sync?.disconnect();
  sync = null;
  syncOnline.value = false;
  if (!appId.value || !props.pageId) return;
  sync = new CommentSync({
    onEvent: applyRealtime,
    onStatus: (connected) => {
      syncOnline.value = connected;
    },
  });
  sync.connect(appId.value, props.pageId);
}

async function submit() {
  const text = body.value.trim();
  if (!text) {
    ElMessage.warning("请输入评论");
    return;
  }
  const target = replyTo.value;
  if (target && target.deleted) {
    ElMessage.warning("该评论已删除，无法回复");
    cancelReply();
    return;
  }
  saving.value = true;
  try {
    const payload: Record<string, unknown> = { body: text };
    if (target) payload.parent_id = target.id;
    else payload.node_id = selectedId.value || "";
    const created = await api.post<CommentItem>(`/collab/pages/${props.pageId}/comments/`, payload);
    body.value = "";
    closeMentions();
    replyTo.value = null;
    if (created?.id) {
      expandAncestors(created.id);
      if (!(created.resolved && !showResolved.value)) upsert(created);
      sync?.publish("comment_created", created);
      void nextTick(() => focusComment(created.id, false));
    }
    const warnings = created?.warnings || [];
    if (warnings.length) {
      ElMessage.warning(warnings.map((warning) => warning.message).join("；"));
    } else if (created?.notified_count) {
      ElMessage.success(`已通知 ${created.notified_count} 位成员`);
    }
  } catch (e: any) {
    ElMessage.error(e?.message || "评论失败");
  } finally {
    saving.value = false;
  }
}

async function toggle(item: CommentItem) {
  try {
    const updated = await api.patch<CommentItem>(`/collab/comments/${item.id}/`, {
      resolved: !item.resolved,
    });
    if (!updated) return;
    if (updated.resolved && !showResolved.value) {
      dropComment(updated.id);
    } else {
      for (const id of updated.resolved_reply_ids || []) {
        const target = commentsById.value.get(Number(id));
        if (target) target.resolved = updated.resolved;
      }
      const incoming: CommentItem = { ...(commentsById.value.get(updated.id) || {}), ...updated };
      delete incoming.resolved_reply_ids;
      upsert(incoming);
    }
    sync?.publish(updated.resolved ? "comment_resolved" : "comment_updated", updated);
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

async function remove(item: CommentItem) {
  try {
    await ElMessageBox.confirm(
      "删除后回复会保留，评论正文将显示为「[已删除]」。确定删除？",
      "确认删除",
      { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" }
    );
  } catch {
    return;
  }
  try {
    await api.del(`/collab/comments/${item.id}/`);
    markLocallyDeleted(item);
    sync?.publish("comment_updated", item);
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
}

function markLocallyDeleted(item: CommentItem) {
  item.deleted = true;
  item.body = "[已删除]";
  item.mentions = [];
  item.mention_usernames = [];
  item.updated_at = new Date().toISOString();
  if (replyTo.value?.id === item.id) replyTo.value = null;
}

function segmentsFor(item: CommentItem): MentionSegment[] {
  return mentionSegments(
    item.body || "",
    (item.mentions || []).map((mention) => mention.username)
  );
}

function mentionsMe(item: CommentItem): boolean {
  if (!me.value || item.author === me.value) return false;
  return (item.mentions || []).some((mention) => mention.username === me.value);
}

function replyTargetName(item: CommentItem): string {
  if (!item.parent_id) return "";
  return commentsById.value.get(item.parent_id)?.author || "";
}

function canReply(item: CommentItem): boolean {
  return !item.deleted && item.depth + 1 < MAX_THREAD_LEVELS;
}

/** 回复层级缩进（最多两级缩进，避免窄侧栏被挤压）。 */
function indentStyle(level: number): Record<string, string> | undefined {
  if (!level) return undefined;
  return { marginLeft: `${Math.min(level, 2) * 16}px` };
}

function expandAncestors(commentId: number) {
  let current = commentsById.value.get(commentId);
  const seen = new Set<number>();
  while (current?.parent_id && !seen.has(current.parent_id)) {
    seen.add(current.parent_id);
    collapsedIds.value.delete(current.parent_id);
    current = commentsById.value.get(current.parent_id);
  }
}

function toggleCollapse(item: CommentItem) {
  const next = new Set(collapsedIds.value);
  if (next.has(item.id)) next.delete(item.id);
  else next.add(item.id);
  collapsedIds.value = next;
}

function startReply(item: CommentItem) {
  if (!canReply(item)) {
    ElMessage.info(`回复最多 ${MAX_THREAD_LEVELS} 层，该评论已到最深层`);
    return;
  }
  replyTo.value = item;
  expandAncestors(item.id);
  void nextTick(() => {
    textareaEl()?.focus();
    document.querySelector(".wp-comments-compose")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

function cancelReply() {
  replyTo.value = null;
}

function focusComment(commentId: number, flash = true) {
  mentionNotice.value = null;
  expandAncestors(commentId);
  void nextTick(() => {
    const el = document.getElementById(`wp-comment-${commentId}`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    if (!flash) return;
    focusedId.value = commentId;
    window.clearTimeout(focusTimer);
    focusTimer = window.setTimeout(() => {
      if (focusedId.value === commentId) focusedId.value = 0;
    }, 2600);
  });
}

/** 支持从通知中心跳转：/design/{appId}/{pageId}?comment={id}。 */
function applyRouteFocus() {
  const id = Number(route.query.comment || 0);
  if (!id || !comments.value.some((item) => item.id === id)) return;
  focusComment(id);
}

function focusNode(id: string) {
  if (schema.schema?.nodes[id]) schema.select(id);
}

function nodeLabel(id: string) {
  const node = schema.schema?.nodes[id];
  return node ? node.type : id;
}

function format(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

onMounted(async () => {
  await Promise.all([load(), loadMentionUsers()]);
  applyRouteFocus();
  startSync();
});

onBeforeUnmount(() => {
  window.clearTimeout(blurTimer);
  window.clearTimeout(reloadTimer);
  window.clearTimeout(focusTimer);
  sync?.disconnect();
  sync = null;
});

watch(
  () => props.pageId,
  async (next, previous) => {
    if (!next || next === previous) return;
    mentionNotice.value = null;
    replyTo.value = null;
    collapsedIds.value = new Set();
    // 先断开旧页面连接，避免加载新页面期间把旧页面事件合并进来。
    sync?.disconnect();
    sync = null;
    syncOnline.value = false;
    await load();
    applyRouteFocus();
    startSync();
  }
);

watch(appId, async (next, previous) => {
  if (!next || next === previous) return;
  sync?.disconnect();
  sync = null;
  syncOnline.value = false;
  await loadMentionUsers();
  startSync();
});

watch(
  () => route.query.comment,
  () => applyRouteFocus()
);
</script>

<style scoped>
.wp-comments { display: flex; flex-direction: column; gap: 10px; }
.wp-comments-head { display: flex; align-items: center; justify-content: space-between; }
.wp-comments-head strong { color: #0f172a; font-size: 12px; }
.wp-comments-head-right { display: flex; align-items: center; gap: 8px; }
.wp-comments-sync { color: #94a3b8; font-size: 9px; white-space: nowrap; }
.wp-comments-sync.online { color: #16a34a; }
.wp-comments-sync.online::before { content: "● "; }
.wp-comments-notice { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 5px 8px; border: 1px solid #bfdbfe; border-radius: 8px; background: #eff6ff; color: #1d4ed8; font-size: 10px; }
.wp-comments-notice-body { flex: 1; border: none; padding: 0; background: transparent; color: inherit; font-size: inherit; text-align: left; cursor: pointer; }
.wp-comments-notice-close { border: none; background: transparent; color: #60a5fa; font-size: 14px; line-height: 1; cursor: pointer; }
.wp-comments-compose { padding: 8px; border: 1px solid #e8edf5; border-radius: 9px; background: #fff; }
.wp-comments-reply-banner { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; padding: 4px 7px; border-radius: 6px; background: #eff6ff; color: #1d4ed8; font-size: 10px; }
.wp-comments-reply-banner em { color: #94a3b8; font-style: normal; }
.wp-comments-reply-cancel { border: none; background: transparent; color: #2563eb; font-size: 10px; cursor: pointer; }
.wp-comments-input-wrap { position: relative; }
.wp-comments-compose-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 7px; color: #94a3b8; font-size: 9px; }
.wp-comments-compose-actions { display: flex; align-items: center; gap: 4px; }
.wp-comments-mention-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 5px; color: #64748b; font-size: 9px; }
.wp-mention-menu { position: absolute; z-index: 30; top: calc(100% + 4px); left: 0; right: 0; max-height: 168px; overflow-y: auto; padding: 4px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.12); }
.wp-mention-item { display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; padding: 5px 7px; border: none; border-radius: 6px; background: transparent; color: #334155; font-size: 10px; text-align: left; cursor: pointer; }
.wp-mention-item strong { color: #0f172a; font-size: 10px; font-weight: 600; }
.wp-mention-item span { color: #94a3b8; font-size: 9px; }
.wp-mention-item.active, .wp-mention-item:hover { background: #eff6ff; }
.wp-mention-empty { padding: 7px; color: #94a3b8; font-size: 10px; text-align: center; }
.wp-mention { border-radius: 4px; color: #1d4ed8; background: #dbeafe; padding: 0 2px; }
.wp-mention-chip { display: inline-block; margin-left: 3px; padding: 0 4px; border-radius: 999px; background: #eff6ff; color: #2563eb; font-size: 9px; }
.wp-comments-list { display: flex; flex-direction: column; gap: 8px; max-height: 460px; overflow-y: auto; }
.wp-comment { padding: 9px; border: 1px solid #e8edf5; border-radius: 9px; background: #fff; transition: box-shadow 0.18s ease, border-color 0.18s ease; }
.wp-comment.reply { border-left: 2px solid #dbeafe; background: #fcfdff; }
.wp-comment.resolved { opacity: 0.6; }
.wp-comment.deleted { background: #f8fafc; }
.wp-comment.focused { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18); }
.wp-comment-head { display: flex; justify-content: space-between; gap: 6px; color: #94a3b8; font-size: 9px; }
.wp-comment-head strong { color: #475569; font-size: 11px; }
.wp-comment-author { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; min-width: 0; }
.wp-comment-arrow { color: #94a3b8; }
.wp-comment-reply-to { color: #94a3b8; font-size: 9px; }
.wp-comment-body { margin: 6px 0; color: #334155; font-size: 11px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.wp-comment-body.deleted { color: #94a3b8; font-style: italic; }
.wp-comment-mentions { display: flex; flex-wrap: wrap; align-items: center; gap: 3px; margin-bottom: 5px; font-size: 9px; }
.wp-comment-mention-label { color: #94a3b8; }
.wp-comment-mention-badge { padding: 0 5px; border-radius: 999px; background: #fef3c7; color: #b45309; font-size: 9px; }
.wp-comment-deleted-badge { padding: 0 5px; border-radius: 999px; background: #f1f5f9; color: #64748b; font-size: 9px; }
.wp-comment-foot { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.wp-comment-foot-left { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.wp-comment-actions { display: flex; align-items: center; gap: 2px; flex: none; }
.wp-comment-node { border: none; background: transparent; color: #2563eb; font-size: 9px; cursor: pointer; }
.wp-comment-depth-tag { color: #b0bccd; font-size: 9px; }
.wp-comment-thread-toggle { border: none; padding: 0; background: transparent; color: #2563eb; font-size: 9px; cursor: pointer; }
.wp-comment-thread-toggle:hover { text-decoration: underline; }

@media (max-width: 640px) {
  .wp-comment { padding: 8px; }
  .wp-comment-head { flex-direction: column; align-items: flex-start; gap: 2px; }
  .wp-comment-foot { flex-direction: column; align-items: flex-start; }
  .wp-comments-compose-foot { flex-wrap: wrap; }
}
</style>
