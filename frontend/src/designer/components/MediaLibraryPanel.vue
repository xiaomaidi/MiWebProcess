<template>
  <div class="wp-media-library">
    <div class="wp-media-toolbar">
      <el-input v-model="keyword" size="small" clearable placeholder="搜索素材" @keyup.enter="load" @clear="load" />
      <input ref="fileInput" type="file" multiple hidden accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.zip" @change="upload" />
      <el-button size="small" type="primary" :loading="uploading" @click="fileInput?.click()">上传</el-button>
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </div>
    <div v-if="uploading" class="wp-media-tip">正在上传 {{ uploadProgress }} / {{ uploadTotal }}…</div>
    <div v-loading="loading" class="wp-media-grid">
      <button v-for="asset in filtered" :key="asset.id" class="wp-media-card" @click="select(asset)">
        <img v-if="isImage(asset)" :src="asset.url" :alt="asset.name" loading="lazy" />
        <span v-else class="wp-media-file">{{ extension(asset.name) }}</span>
        <span class="wp-media-name">{{ asset.name }}</span>
      </button>
      <el-empty v-if="!loading && !filtered.length" description="暂无素材" :image-size="52" />
    </div>
    <div v-if="selected" class="wp-media-detail">
      <strong>{{ selected.name }}</strong>
      <code>{{ selected.url }}</code>
      <div class="wp-media-actions">
        <el-button size="small" @click="copy(selected.url)">复制地址</el-button>
        <el-button size="small" type="primary" @click="$emit('insert', selected)">插入到页面</el-button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const props = withDefaults(defineProps<{ appId: number | string }>(), { appId: 0 });
const emit = defineEmits<{ insert: [asset: any] }>();
const keyword = ref("");
const assets = ref<any[]>([]);
const loading = ref(false);
const uploading = ref(false);
const uploadProgress = ref(0);
const uploadTotal = ref(0);
const selected = ref<any>(null);
const fileInput = ref<HTMLInputElement | null>(null);

const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  if (!text) return assets.value;
  return assets.value.filter((item) => String(item.name || "").toLowerCase().includes(text));
});
function isImage(asset: any) {
  return String(asset.type || "").includes("image") || /\.(png|jpe?g|gif|webp|svg)$/i.test(String(asset.name || ""));
}
function extension(name: string) {
  const parts = String(name || "").split(".");
  return (parts.length > 1 ? parts.pop() : "FILE")?.toUpperCase();
}
async function load() {
  if (!props.appId) return;
  loading.value = true;
  try {
    const data = await api.get<any>(`/assets/?app_id=${props.appId}&size=100`);
    assets.value = data.results || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "素材加载失败");
  } finally { loading.value = false; }
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  input.value = "";
  if (!files.length) return;
  uploading.value = true;
  uploadProgress.value = 0;
  uploadTotal.value = files.length;
  try {
    for (const file of files) {
      await api.upload(`/assets/?app_id=${props.appId}`, file);
      uploadProgress.value += 1;
    }
    ElMessage.success(`已上传 ${files.length} 个素材`);
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "上传失败");
  } finally { uploading.value = false; }
}
function select(asset: any) { selected.value = asset; }
async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); ElMessage.success("已复制"); }
  catch { ElMessage.warning(text); }
}
onMounted(load);
</script>

<style scoped>
.wp-media-library { display: flex; flex-direction: column; gap: 10px; min-height: 280px; }
.wp-media-toolbar { display: flex; align-items: center; gap: 6px; }
.wp-media-toolbar :deep(.el-input) { flex: 1; }
.wp-media-tip { color: #2563eb; font-size: 11px; }
.wp-media-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; min-height: 160px; }
.wp-media-card { display: flex; flex-direction: column; gap: 4px; padding: 6px; border: 1px solid #e8edf5; border-radius: 8px; background: #fff; cursor: pointer; text-align: left; }
.wp-media-card:hover { border-color: #93c5fd; box-shadow: 0 6px 16px rgba(37, 99, 235, 0.08); }
.wp-media-card img { width: 100%; height: 72px; border-radius: 5px; object-fit: cover; background: #f1f5f9; }
.wp-media-file { display: flex; align-items: center; justify-content: center; height: 72px; border-radius: 5px; background: #f1f5f9; color: #64748b; font-size: 10px; font-weight: 700; }
.wp-media-name { overflow: hidden; color: #475569; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.wp-media-detail { padding: 8px; border-top: 1px solid #eef2f8; }
.wp-media-detail strong { display: block; margin-bottom: 4px; color: #0f172a; font-size: 11px; }
.wp-media-detail code { display: block; overflow: hidden; color: #94a3b8; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.wp-media-actions { display: flex; gap: 6px; margin-top: 7px; }
</style>
