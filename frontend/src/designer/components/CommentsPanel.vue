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
        <el-checkbox v-model="showResolved" size="small" @change="load">显示已解决</el-checkbox>
      </div>
    </div>

    <div v-if="mentionNotice" class="wp-comments-notice">
      <button type="button" class="wp-comments-notice-body" @click="focusComment(mentionNotice.commentId)">
        {{ mentionNotice.text }}
      </button>
      <button type="button" class="wp-comments-notice-close" title="关闭" @click="mentionNotice = null">×</button>
    </div>

    <div class="wp-comments-compose">
      <div class="wp-comments-input-wrap">
        <el-input
          ref="composeRef"
          v-model="body"
          type="textarea"
          :rows="3"
          maxlength="4000"
          show-word-limit
          placeholder="评论当前选中组件，或输入页面级评论；输入 @ 提及成员…"
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
        <span>{{ selectedId ? `关联组件 ${selectedId}` : "页面级评论" }}</span>
        <el-button size="small" type="primary" :loading="saving" @click="submit">发表</el-button>
      </div>
      <div v-if="pendingMentionUsers.length" class="wp-comments-mention-hint">
        将通知
        <span v-for="user in pendingMentionUsers" :key="user.username" class="wp-mention-chip">
          @{{ user.username }}
        </span>
      </div>
    </div>

    <div v-loading="loading" class="wp-comments-list">
      <article
        v-for="item in comments"
        :id="`wp-comment-${item.id}`"
        :key="item.id"
        class="wp-comment"
        :class="{ resolved: item.resolved }"
      >
        <div class="wp-comment-head">
          <strong>{{ item.author || "成员" }}</strong>
          <span>{{ format(item.created_at) }}</span>
        </div>
        <p class="wp-comment-body">
          <span
            v-for="(segment, index) in segmentsFor(item)"
            :key="index"
            :class="{ 'wp-mention': segment.mention }"
          >{{ segment.text }}</span>
        </p>
        <div v-if="item.mentions && item.mentions.length" class="wp-comment-mentions">
          <span v-if="mentionsMe(item)" class="wp-comment-mention-badge">提到了你</span>
          <span v-else class="wp-comment-mention-label">提及</span>
          <span v-for="mention in item.mentions" :key="mention.username" class="wp-mention-chip">
            @{{ mention.username }}
          </span>
        </div>
        <div class="wp-comment-foot">
          <button v-if="item.node_id" type="button" class="wp-comment-node" @click="focusNode(item.node_id)">
            {{ nodeLabel(item.node_id) }}
          </button>
          <span v-else class="wp-comment-node">页面</span>
          <div>
            <el-button size="small" text @click="toggle(item)">{{ item.resolved ? "重新打开" : "解决" }}</el-button>
            <el-button size="small" text type="danger" @click="remove(item)">删除</el-button>
          </div>
        </div>
      </article>
      <el-empty v-if="!loading && !comments.length" description="还没有评论" :image-size="48" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
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
  resolved: boolean;
  resolved_by: string;
  created_at: string | null;
  updated_at: string | null;
  mentions?: CommentMention[];
  mention_usernames?: string[];
  warnings?: MentionWarning[];
  notified_count?: number;
}

const props = defineProps<{ pageId: number }>();
const schema = useSchemaStore();
const auth = useAuthStore();
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

let sync: CommentSync | null = null;
let blurTimer: number | undefined;

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

async function load() {
  if (!props.pageId) return;
  loading.value = true;
  try {
    const query = showResolved.value ? "" : "?resolved=0";
    const data = await api.get<{ results?: CommentItem[] }>(`/collab/pages/${props.pageId}/comments/${query}`);
    comments.value = data?.results || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "评论加载失败");
  } finally {
    loading.value = false;
  }
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
  else comments.value.unshift(item);
  comments.value.sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at));
  if (comments.value.length > 200) comments.value.splice(200);
}

function applyRealtime(event: CommentEvent) {
  if (event.type === "comment_deleted") {
    comments.value = comments.value.filter((row) => row.id !== event.commentId);
    return;
  }
  const item = event.comment as CommentItem | null;
  if (!item || !item.id) return;
  const mentioned = (item.mentions || []).some((mention) => mention.username === me.value);
  if (me.value && event.from && event.from !== me.value && mentioned) {
    mentionNotice.value = {
      text: `@${event.from} 在评论中提到了你`,
      commentId: item.id,
    };
    ElMessage.info(`@${event.from} 在评论中提到了你`);
  }
  if (item.resolved && !showResolved.value) {
    comments.value = comments.value.filter((row) => row.id !== item.id);
    return;
  }
  upsert(item);
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
  saving.value = true;
  try {
    const created = await api.post<CommentItem>(`/collab/pages/${props.pageId}/comments/`, {
      body: text,
      node_id: selectedId.value || "",
    });
    body.value = "";
    closeMentions();
    if (created?.id) {
      if (!(created.resolved && !showResolved.value)) upsert(created);
      sync?.publish("comment_created", created);
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
      comments.value = comments.value.filter((row) => row.id !== updated.id);
    } else {
      upsert(updated);
    }
    sync?.publish(updated.resolved ? "comment_resolved" : "comment_updated", updated);
  } catch (e: any) {
    ElMessage.error(e?.message || "操作失败");
  }
}

async function remove(item: CommentItem) {
  try {
    await ElMessageBox.confirm("删除这条评论？", "确认");
  } catch {
    return;
  }
  try {
    await api.del(`/collab/comments/${item.id}/`);
    comments.value = comments.value.filter((row) => row.id !== item.id);
    sync?.publish("comment_deleted", { id: item.id, page_id: props.pageId });
  } catch (e: any) {
    ElMessage.error(e?.message || "删除失败");
  }
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

function focusComment(commentId: number) {
  mentionNotice.value = null;
  const el = document.getElementById(`wp-comment-${commentId}`);
  el?.scrollIntoView({ block: "center", behavior: "smooth" });
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
  startSync();
});

onBeforeUnmount(() => {
  window.clearTimeout(blurTimer);
  sync?.disconnect();
  sync = null;
});

watch(
  () => props.pageId,
  async (next, previous) => {
    if (!next || next === previous) return;
    mentionNotice.value = null;
    // 先断开旧页面连接，避免加载新页面期间把旧页面事件合并进来。
    sync?.disconnect();
    sync = null;
    syncOnline.value = false;
    await load();
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
.wp-comments-input-wrap { position: relative; }
.wp-comments-compose-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 7px; color: #94a3b8; font-size: 9px; }
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
.wp-comment { padding: 9px; border: 1px solid #e8edf5; border-radius: 9px; background: #fff; }
.wp-comment.resolved { opacity: 0.6; }
.wp-comment-head { display: flex; justify-content: space-between; color: #94a3b8; font-size: 9px; }
.wp-comment-head strong { color: #475569; font-size: 11px; }
.wp-comment-body { margin: 6px 0; color: #334155; font-size: 11px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.wp-comment-mentions { display: flex; flex-wrap: wrap; align-items: center; gap: 3px; margin-bottom: 5px; font-size: 9px; }
.wp-comment-mention-label { color: #94a3b8; }
.wp-comment-mention-badge { padding: 0 5px; border-radius: 999px; background: #fef3c7; color: #b45309; font-size: 9px; }
.wp-comment-foot { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.wp-comment-node { border: none; background: transparent; color: #2563eb; font-size: 9px; cursor: pointer; }
</style>
