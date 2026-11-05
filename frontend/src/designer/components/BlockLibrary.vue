<template>
  <div class="wp-block-lib">
    <div class="wp-block-lib-head">
      <el-input
        v-model="keyword"
        size="small"
        clearable
        placeholder="搜索区块名称 / 编码"
        class="wp-block-lib-search"
      >
        <template #prefix>⌕</template>
      </el-input>
      <el-button size="small" type="primary" plain :disabled="!canCreate" @click="openCreate">
        从选区创建
      </el-button>
    </div>

    <div v-if="!canCreate" class="wp-block-lib-hint">
      选中画布节点后可将当前选区保存为可复用区块。
    </div>

    <el-alert v-if="error" type="error" :closable="false" show-icon class="wp-block-lib-alert">
      <template #title>{{ error }}</template>
      <el-button link type="primary" size="small" @click="reload">重新加载</el-button>
    </el-alert>

    <div v-if="loading" class="wp-block-lib-loading">
      <el-skeleton :rows="3" animated />
    </div>

    <el-empty
      v-else-if="!filteredBlocks.length"
      :description="keyword ? '没有匹配的区块' : '应用还没有可复用区块'"
      :image-size="56"
    />

    <el-scrollbar v-else max-height="420px">
      <div class="wp-block-lib-list">
        <div v-for="block in filteredBlocks" :key="block.id" class="wp-block-lib-card">
          <div class="wp-block-lib-info">
            <div class="wp-block-lib-title">
              <span class="wp-block-lib-name">{{ block.name }}</span>
              <el-tag size="small" effect="plain">{{ block.code }}</el-tag>
            </div>
            <div class="wp-block-lib-meta">
              <span>{{ block.description || "无描述" }}</span>
              <span>v{{ block.version }}</span>
              <span>{{ formatTime(block.updated_at) }}</span>
            </div>
          </div>
          <div class="wp-block-lib-actions">
            <el-button size="small" type="primary" plain @click="insert(block)">插入引用</el-button>
            <el-button v-if="block.page_id" size="small" link @click="openEditor(block)">编辑</el-button>
          </div>
        </div>
      </div>
    </el-scrollbar>

    <el-dialog v-model="createOpen" title="从当前选区创建区块" width="460px" append-to-body>
      <el-form label-width="72px" @submit.prevent>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="200" show-word-limit placeholder="例如：产品卡片" />
        </el-form-item>
        <el-form-item label="编码">
          <el-input v-model="form.code" maxlength="80" placeholder="可选；字母/数字/下划线/连字符，留空自动生成" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="500" show-word-limit />
        </el-form-item>
        <el-form-item label="">
          <el-checkbox v-model="form.insertAfterCreate">创建后立即插入引用</el-checkbox>
        </el-form-item>
        <div class="wp-block-lib-dialog-tip">
          将复制 {{ selectionIds.length }} 个选中节点，并创建可编辑的 fragment 页面（路径
          <code>__blocks__/&lt;code&gt;</code>）。
        </div>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="creating" :disabled="!form.name.trim()" @click="submitCreate">
          创建区块
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import type { SchemaNode } from "@/types";
import { api } from "@/api";
import {
  buildBlockReferenceNode,
  createBlockFromCurrentPage,
  listBlocks,
  normalizeSelectedIds,
  type BlockCreateResult,
  type BlockSummary,
} from "@/designer/block-api";
import { useSchemaStore } from "@/store/schema";

const props = withDefaults(
  defineProps<{
    /** 应用 id（必填）。 */
    appId: number;
    /** 当前页面 id；用于“从选区创建”。 */
    pageId?: number;
    /** 当前选中节点 id；由集成方从 schema store 传入。 */
    selectedNodeIds?: string[];
    /** 可选的插入回调；未提供时通过 insert 事件交给外层处理。 */
    insertHandler?: (node: SchemaNode, block: BlockSummary) => void;
  }>(),
  {
    pageId: 0,
    selectedNodeIds: () => [],
    insertHandler: undefined,
  }
);

const emit = defineEmits<{
  (e: "insert", payload: { node: SchemaNode; block: BlockSummary }): void;
  (e: "created", payload: BlockCreateResult): void;
}>();

const schemaStore = useSchemaStore();

const keyword = ref("");
const loading = ref(true);
const error = ref("");
const blocks = ref<BlockSummary[]>([]);
const createOpen = ref(false);
const creating = ref(false);
const versionsOpen = ref(false);
const publishOpen = ref(false);
const versionSaving = ref(false);
const publishing = ref(false);
const versions = ref<any[]>([]);
const activeBlock = ref<BlockSummary | null>(null);
const publishForm = reactive({ name: "", slug: "", description: "", status: "published" });
const form = reactive({ name: "", code: "", description: "", insertAfterCreate: true });

const selectionIds = computed(() =>
  normalizeSelectedIds(schemaStore.schema, props.selectedNodeIds || [])
);
const canCreate = computed(() => !!props.appId && !!props.pageId && selectionIds.value.length > 0);

const filteredBlocks = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  if (!kw) return blocks.value;
  return blocks.value.filter((b) =>
    [b.name, b.code, b.description || ""].join(" ").toLowerCase().includes(kw)
  );
});

function formatTime(value: string): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString();
}

async function load() {
  if (!props.appId) {
    loading.value = false;
    error.value = "缺少 appId，无法加载区块库";
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const page = await listBlocks(props.appId, { search: keyword.value.trim(), size: 100 });
    blocks.value = page.results || [];
  } catch (e: any) {
    error.value = e?.message || "区块列表加载失败";
    blocks.value = [];
  } finally {
    loading.value = false;
  }
}

function reload() {
  void load();
}

let searchTimer: ReturnType<typeof setTimeout> | null = null;
watch(keyword, () => {
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => void load(), 250);
});

function insert(block: BlockSummary) {
  const node = buildBlockReferenceNode(block);
  if (props.insertHandler) props.insertHandler(node, block);
  emit("insert", { node, block });
  ElMessage.success(`已插入区块引用：${block.name}`);
}

function openEditor(block: BlockSummary) {
  if (!block.page_id) return;
  window.open(`/design/${props.appId}/${block.page_id}`, "_blank");
}

function openCreate() {
  if (!canCreate.value) return;
  form.name = "";
  form.code = "";
  form.description = "";
  form.insertAfterCreate = true;
  createOpen.value = true;
}

async function submitCreate() {
  const name = form.name.trim();
  if (!name || !props.pageId) return;
  creating.value = true;
  try {
    const result = await createBlockFromCurrentPage(
      props.appId,
      props.pageId,
      selectionIds.value,
      name,
      { code: form.code.trim() || undefined, description: form.description.trim() || undefined }
    );
    createOpen.value = false;
    emit("created", result);
    await load();
    if (form.insertAfterCreate) insert(result.block);
    if (result.warnings?.length) ElMessage.warning(result.warnings.join("；"));
    ElMessage.success(`区块「${result.block.name}」已创建`);
  } catch (e: any) {
    // api 客户端已提示错误，这里只保留弹窗便于重试
    if (e?.message) ElMessage.error(e.message);
  } finally {
    creating.value = false;
  }
}

async function openVersions(block: BlockSummary) {
  activeBlock.value = block;
  versionsOpen.value = true;
  versions.value = [];
  try {
    const data = await api.get<any>(`/blocks/${block.id}/versions/?size=100`);
    versions.value = data.results || data || [];
  } catch (e: any) { ElMessage.error(e?.message || "鍔犺浇鐗堟湰澶辫触"); }
}
async function loadVersions() {
  if (!activeBlock.value) return;
  const data = await api.get<any>(`/blocks/${activeBlock.value.id}/versions/?size=100`);
  versions.value = data.results || data || [];
}
async function createVersion() {
  if (!activeBlock.value) return;
  versionSaving.value = true;
  try {
    await api.post(`/blocks/${activeBlock.value.id}/versions/`, { changelog: "manual snapshot" });
    await loadVersions();
    ElMessage.success("Version saved");
  } catch (e: any) { ElMessage.error(e?.message || "Save version failed"); }
  finally { versionSaving.value = false; }
}
async function rollbackVersion(row: any) {
  if (!activeBlock.value) return;
  try {
    await api.post(`/blocks/${activeBlock.value.id}/versions/${row.version}/rollback/`, {});
    await Promise.all([loadVersions(), load()]);
    ElMessage.success(`Rolled back to v${row.version}`);
  } catch (e: any) { ElMessage.error(e?.message || "Rollback failed"); }
}

function openPublish(block: BlockSummary) {
  activeBlock.value = block;
  publishForm.name = block.name;
  publishForm.slug = block.code;
  publishForm.description = block.description || "";
  publishForm.status = "published";
  publishOpen.value = true;
}
async function publishToMarket() {
  if (!activeBlock.value) return;
  publishing.value = true;
  try {
    await api.post(`/blocks/${activeBlock.value.id}/publish-market/`, {
      name: publishForm.name, slug: publishForm.slug, description: publishForm.description, status: publishForm.status,
    });
    publishOpen.value = false;
    ElMessage.success("宸插彂甯冨埌甯傚満");
  } catch (e: any) { ElMessage.error(e?.message || "鍙戝竷澶辫触"); }
  finally { publishing.value = false; }
}

onMounted(() => {
  void load();
});

watch(() => props.appId, () => void load());
</script>

<style scoped>
.wp-block-lib {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wp-block-lib-head {
  display: flex;
  gap: 8px;
  align-items: center;
}
.wp-block-lib-search {
  flex: 1;
}
.wp-block-lib-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  line-height: 1.5;
}
.wp-block-lib-alert {
  margin: 0;
}
.wp-block-lib-loading {
  padding: 4px;
}
.wp-block-lib-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-right: 4px;
}
.wp-block-lib-card {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 6px;
  padding: 8px;
  transition: border-color 0.15s ease;
}
.wp-block-lib-card:hover {
  border-color: var(--el-color-primary, #409eff);
}
.wp-block-lib-info {
  flex: 1;
  min-width: 0;
}
.wp-block-lib-title {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.wp-block-lib-name {
  font-size: 13px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-block-lib-meta {
  display: flex;
  gap: 8px;
  font-size: 11px;
  color: var(--el-text-color-secondary, #909399);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.wp-block-lib-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
.wp-block-lib-dialog-tip {
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
  line-height: 1.6;
  padding-left: 72px;
}
</style>
