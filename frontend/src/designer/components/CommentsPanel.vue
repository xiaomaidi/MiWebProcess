<template>
  <div class="wp-comments">
    <div class="wp-comments-head">
      <strong>页面评论</strong>
      <el-checkbox v-model="showResolved" size="small" @change="load">显示已解决</el-checkbox>
    </div>
    <div class="wp-comments-compose">
      <el-input
        v-model="body"
        type="textarea"
        :rows="3"
        maxlength="4000"
        show-word-limit
        placeholder="评论当前选中组件，或输入页面级评论…"
        @keydown.ctrl.enter="submit"
      />
      <div class="wp-comments-compose-foot">
        <span>{{ selectedId ? `关联组件 ${selectedId}` : "页面级评论" }}</span>
        <el-button size="small" type="primary" :loading="saving" @click="submit">发表</el-button>
      </div>
    </div>
    <div v-loading="loading" class="wp-comments-list">
      <article v-for="item in comments" :key="item.id" class="wp-comment" :class="{ resolved: item.resolved }">
        <div class="wp-comment-head">
          <strong>{{ item.author || "成员" }}</strong>
          <span>{{ format(item.created_at) }}</span>
        </div>
        <p>{{ item.body }}</p>
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
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";

const props = defineProps<{ pageId: number }>();
const schema = useSchemaStore();
const comments = ref<any[]>([]);
const body = ref("");
const loading = ref(false);
const saving = ref(false);
const showResolved = ref(false);
const selectedId = computed(() => schema.selectedId || "");

async function load() {
  if (!props.pageId) return;
  loading.value = true;
  try {
    const query = showResolved.value ? "" : "?resolved=0";
    comments.value = (await api.get<any>(`/collab/pages/${props.pageId}/comments/${query}`)).results || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "评论加载失败");
  } finally { loading.value = false; }
}
async function submit() {
  const text = body.value.trim();
  if (!text) { ElMessage.warning("请输入评论"); return; }
  saving.value = true;
  try {
    await api.post(`/collab/pages/${props.pageId}/comments/`, { body: text, node_id: selectedId.value || "" });
    body.value = "";
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "评论失败");
  } finally { saving.value = false; }
}
async function toggle(item: any) {
  await api.patch(`/collab/comments/${item.id}/`, { resolved: !item.resolved });
  await load();
}
async function remove(item: any) {
  try { await ElMessageBox.confirm("删除这条评论？", "确认"); } catch { return; }
  await api.del(`/collab/comments/${item.id}/`);
  await load();
}
function focusNode(id: string) {
  if (schema.schema?.nodes[id]) schema.select(id);
}
function nodeLabel(id: string) {
  const node = schema.schema?.nodes[id];
  return node ? node.type : id;
}
function format(value: string) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
onMounted(load);
</script>

<style scoped>
.wp-comments { display: flex; flex-direction: column; gap: 10px; }
.wp-comments-head { display: flex; align-items: center; justify-content: space-between; }
.wp-comments-head strong { color: #0f172a; font-size: 12px; }
.wp-comments-compose { padding: 8px; border: 1px solid #e8edf5; border-radius: 9px; background: #fff; }
.wp-comments-compose-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 7px; color: #94a3b8; font-size: 9px; }
.wp-comments-list { display: flex; flex-direction: column; gap: 8px; max-height: 460px; overflow-y: auto; }
.wp-comment { padding: 9px; border: 1px solid #e8edf5; border-radius: 9px; background: #fff; }
.wp-comment.resolved { opacity: 0.6; }
.wp-comment-head { display: flex; justify-content: space-between; color: #94a3b8; font-size: 9px; }
.wp-comment-head strong { color: #475569; font-size: 11px; }
.wp-comment p { margin: 6px 0; color: #334155; font-size: 11px; line-height: 1.6; white-space: pre-wrap; word-break: break-word; }
.wp-comment-foot { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
.wp-comment-node { border: none; background: transparent; color: #2563eb; font-size: 9px; cursor: pointer; }
</style>
