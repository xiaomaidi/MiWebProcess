<template>
  <div v-loading="loading" class="wp-designer">
    <header class="wp-d-header">
      <el-button size="small" text @click="goBack">← 返回应用</el-button>
      <span class="wp-d-title">{{ page?.name || "页面设计器" }}</span>
      <span v-if="page" class="wp-d-meta">路径 /{{ page.path }}</span>
      <span v-if="page" class="wp-d-meta">草稿 v{{ page.version }}</span>
      <span v-if="schema.dirty" class="wp-d-dirty">● 未保存</span>
      <el-button size="small" class="wp-d-ai" @click="reviewOpen = true">🔎 AI 评审</el-button>
      <el-button size="small" @click="diffOpen = true">🧾 差异</el-button>
      <el-button size="small" @click="coordinationOpen = true">🧩 协同</el-button>
      <el-button size="small" :loading="regenerating" @click="regeneratePage">♻️ AI 重生成</el-button>
      <el-button size="small" @click="agentOpen = true">🤖 AI 助手</el-button>
      <el-button class="wp-d-mobile-btn" size="small" @click="mobilePanel = mobilePanel === 'left' ? '' : 'left'">面板</el-button>
      <el-button class="wp-d-mobile-btn" size="small" @click="mobilePanel = mobilePanel === 'right' ? '' : 'right'">属性</el-button>
      <el-button size="small" type="primary" plain @click="aiOpen = true">✨ AI 生成</el-button>
      <CollabPresence />
      <el-button size="small" @click="debugOpen = true">调试</el-button>
    </header>

    <DesignerToolbar
      ref="toolbarRef"
      :page="page"
      :app-id="appId"
      @preview="openPreview"
      @publish="publishOpen = true"
      @versions="versionsOpen = true"
      @saved="onDraftSaved"
    />

    <div class="wp-d-body">
      <div v-if="mobilePanel" class="wp-d-mobile-mask" @click="mobilePanel = ''" />
      <aside class="wp-d-left" :class="{ 'is-mobile-open': mobilePanel === 'left' }">
        <el-tabs v-model="leftTab" class="wp-d-left-tabs">
          <el-tab-pane label="组件" name="components">
            <ComponentLibrary />
          </el-tab-pane>
          <el-tab-pane label="大纲" name="outline">
            <OutlinePanel />
          </el-tab-pane>
          <el-tab-pane label="数据源" name="datasources">
            <DatasourcePanel :datasources="datasources" :app-id="appId" @refresh="reloadDatasources" />
          </el-tab-pane>
          <el-tab-pane label="区块" name="blocks">
            <BlockLibrary v-if="page" :app-id="appId" :page-id="page.id" @insert="onBlockInsert" />
          </el-tab-pane>
          <el-tab-pane label="素材" name="media">
            <MediaLibraryPanel :app-id="appId" @insert="insertAsset" />
          </el-tab-pane>
          <el-tab-pane label="变量" name="variables">
            <VariablePanel />
          </el-tab-pane>
          <el-tab-pane label="协同" name="coordination">
            <CoordinationPanel />
          </el-tab-pane>
        </el-tabs>
      </aside>

      <main class="wp-d-canvas" @pointermove="onCollabPointerMove">
        <CanvasArea />
        <CollabCursors />
      </main>

      <aside class="wp-d-right" :class="{ 'is-mobile-open': mobilePanel === 'right' }">
        <PropertyPanel
          :page="page"
          :app-id="appId"
          :datasources="datasources"
          :models="models"
          @page-updated="onPageUpdated"
        />
      </aside>
    </div>

    <AiGenerateDialog v-model="aiOpen" :app-id="appId" :schema="schema.schema" @generated="onAiGenerated" />
    <AiReviewDialog v-model="reviewOpen" :app-id="appId" :schema="schema.schema" :page-name="page?.name" />
    <AiAgentPanel
      v-model="agentOpen"
      :app-id="appId"
      :page-id="pageId"
      :page-name="page?.name"
      @applied="onAgentApplied"
    />
    <PublishDialog v-model="publishOpen" :page-id="pageId" @published="onPublished" />
    <VersionsDialog v-model="versionsOpen" :page-id="pageId" @rolled-back="onRolledBack" />
    <el-drawer v-model="debugOpen" title="交互调试" size="460px">
      <DesignerDebuggerPanel />
    </el-drawer>

    <el-dialog v-model="diffOpen" title="AI 变更差异" width="760px" @open="loadDiff">
      <div v-if="diffLoading" class="wp-diff-tip">正在计算差异…</div>
      <el-empty v-else-if="!diffData || diffData.same" description="当前草稿与最近快照没有差异" />
      <template v-else>
        <div class="wp-diff-summary">
          新增 {{ diffData.summary.added }} · 删除 {{ diffData.summary.removed }} ·
          修改 {{ diffData.summary.changed }} · meta {{ diffData.summary.meta }}
        </div>
        <div class="wp-diff-list">
          <div v-for="node in diffData.nodes" :key="node.id" class="wp-diff-node">
            <el-tag size="small" :type="node.status === 'added' ? 'success' : node.status === 'removed' ? 'danger' : 'warning'">
              {{ node.status }}
            </el-tag>
            <b>{{ node.id }}</b>
            <span class="wp-diff-type">{{ node.type }}</span>
            <div v-for="(change, index) in node.changes" :key="index" class="wp-diff-change">
              <code>{{ change.field }}</code>
              <span class="wp-diff-before">{{ change.before || "（空）" }}</span>
              <span>→</span>
              <span class="wp-diff-after">{{ change.after || "（空）" }}</span>
            </div>
          </div>
          <div v-for="change in diffData.meta" :key="`meta-${change.field}`" class="wp-diff-node">
            <el-tag size="small" type="info">meta</el-tag>
            <b>{{ change.field }}</b>
            <div class="wp-diff-change">
              <span class="wp-diff-before">{{ change.before || "（空）" }}</span>
              <span>→</span>
              <span class="wp-diff-after">{{ change.after || "（空）" }}</span>
            </div>
          </div>
        </div>
      </template>
    </el-dialog>

    <el-drawer v-model="coordinationOpen" title="页面协同中心" size="86%">
      <CoordinationPanel />
      <template #footer>
        <el-button @click="coordinationOpen = false">关闭</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, provide, reactive, ref, watch } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import { useHistoryStore } from "@/store/history";
import { useEditorStore } from "@/store/editor";
import type { ComponentMeta, DataModelInfo, DataSourceDef, PageSchema, PageInfo } from "@/types";
import { asList, commit, withHistory } from "./util";
import DesignerToolbar from "./components/DesignerToolbar.vue";
import ComponentLibrary from "./components/ComponentLibrary.vue";
import MediaLibraryPanel from "./components/MediaLibraryPanel.vue";
import CollabPresence from "./components/CollabPresence.vue";
import CollabCursors from "./components/CollabCursors.vue";
import DesignerDebuggerPanel from "./components/DesignerDebuggerPanel.vue";
import { connectDesignerCollab, disconnectDesignerCollab, sendCollabCursor, sendCollabSelection } from "./collab";
import BlockLibrary from "./components/BlockLibrary.vue";
import OutlinePanel from "./components/OutlinePanel.vue";
import DatasourcePanel from "./components/DatasourcePanel.vue";
import VariablePanel from "./components/VariablePanel.vue";
import CoordinationPanel from "./components/CoordinationPanel.vue";
import CanvasArea from "./components/CanvasArea.vue";
import PropertyPanel from "./components/PropertyPanel.vue";
import PublishDialog from "./components/PublishDialog.vue";
import VersionsDialog from "./components/VersionsDialog.vue";
import AiGenerateDialog from "./components/AiGenerateDialog.vue";
import AiReviewDialog from "./components/AiReviewDialog.vue";
import AiAgentPanel from "./components/AiAgentPanel.vue";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId);
const pageId = Number(route.params.pageId);

const loading = ref(true);
const regenerating = ref(false);
const diffOpen = ref(false);
const coordinationOpen = ref(false);
const diffLoading = ref(false);
const diffData = ref<any>(null);
const page = ref<PageInfo | null>(null);
const datasources = ref<DataSourceDef[]>([]);
const models = ref<DataModelInfo[]>([]);
const leftTab = ref("components");
const mobilePanel = ref<"" | "left" | "right">("");
const debugOpen = ref(false);
const publishOpen = ref(false);
const versionsOpen = ref(false);
const aiOpen = ref(false);
const reviewOpen = ref(false);
const agentOpen = ref(false);

const schema = useSchemaStore();
const components = useComponentStore();
const history = useHistoryStore();
const editor = useEditorStore();
const toolbarRef = ref<InstanceType<typeof DesignerToolbar> | null>(null);

// NodeRenderer 设计态上下文（点击选中 / 高亮 / 节点右上角 × 删除）
const designCtx = reactive<{
  selectedId: string | null;
  selectedIds: string[];
  onSelect: (id: string | null, additive?: boolean) => void;
  onDelete: (id: string) => void;
}>({
  selectedId: schema.selectedId,
  selectedIds: [...schema.selectedIds],
  onSelect: (id: string | null, additive = false) => schema.select(id, additive),
  onDelete: (id: string) => {
    const s = schema.schema;
    if (!s || !id || id === s.rootId) return;
    withHistory("删除组件", () => schema.removeNodeReparent(id));
  },
});
watch(
  () => [schema.selectedId, schema.selectedIds.join(",")],
  () => {
    designCtx.selectedId = schema.selectedId;
    designCtx.selectedIds = [...schema.selectedIds];
  },
  { immediate: true }
);
provide("wp.design", designCtx);

function isTypingTarget(target: EventTarget | null): boolean {
  const t = target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

function deleteSelection() {
  const s = schema.schema;
  if (!s) return;
  const ids = schema.selectedIds.filter((id) => id !== s.rootId);
  if (!ids.length) return;
  withHistory(ids.length > 1 ? `删除 ${ids.length} 个组件` : "删除组件", () => schema.removeSelected());
}

function pasteTarget(): string {
  const s = schema.schema;
  if (!s) return "";
  const selected = schema.selectedId ? s.nodes[schema.selectedId] : null;
  if (selected) {
    const meta = components.meta(selected.type);
    const accepts = meta?.accept_children || meta?.accepts || [];
    if (meta?.is_container || accepts.length > 0) return selected.id;
    return schema.parentOf(selected.id) || s.rootId;
  }
  return s.rootId;
}

function onBlockInsert(payload: any) {
  const blockNode = payload?.node;
  if (!blockNode) return;
  const rootId = schema.schema?.rootId;
  if (!rootId) return;
  withHistory("插入复用区块", () => {
    const parentId = schema.selectedId && schema.selectedId !== rootId ? schema.selectedId : rootId;
    const id = schema.insertComponent("wp-block", parentId, -1);
    const current = schema.node(id);
    if (current) {
      current.props = { ...(blockNode.props || {}) };
      current.style = { ...(blockNode.style || {}) };
    }
  });
}

function insertAsset(asset: any) {
  const rootId = schema.schema?.rootId;
  if (!rootId || !asset?.url) return;
  withHistory("插入素材", () => {
    const id = schema.insertComponent("wp-image", rootId, -1);
    const node = schema.node(id);
    if (node) node.props = { ...(node.props || {}), src: asset.url, alt: asset.name || "" };
  });
}

// 快捷键：Ctrl+S 保存、Ctrl+Z 撤销、Ctrl+Shift+Z / Ctrl+Y 重做、Delete、复制粘贴。
function onKeydown(e: KeyboardEvent) {
  const mod = e.ctrlKey || e.metaKey;
  const key = e.key.toLowerCase();
  if (mod && key === "s") {
    e.preventDefault();
    void toolbarRef.value?.save();
    return;
  }
  if (isTypingTarget(e.target)) return;
  if (mod && key === "z") {
    e.preventDefault();
    if (e.shiftKey) history.redo();
    else history.undo();
    if (schema.schema && (!schema.selectedId || !schema.schema.nodes[schema.selectedId])) {
      schema.select(schema.schema.rootId);
    }
    return;
  }
  if (mod && key === "y") {
    e.preventDefault();
    history.redo();
    if (schema.schema && (!schema.selectedId || !schema.schema.nodes[schema.selectedId])) {
      schema.select(schema.schema.rootId);
    }
    return;
  }
  if (e.key === "Delete" || e.key === "Backspace") {
    e.preventDefault();
    deleteSelection();
    return;
  }
  if (e.key === "Escape") {
    schema.select(null);
    return;
  }
  if (!mod) return;
  if (key === "a") {
    e.preventDefault();
    schema.selectAll();
  } else if (key === "c") {
    e.preventDefault();
    if (schema.copySelection()) ElMessage.success(`已复制 ${schema.selectedIds.length} 个节点`);
  } else if (key === "v") {
    e.preventDefault();
    if (!schema.clipboard) return;
    const parent = pasteTarget();
    withHistory("粘贴组件", () => schema.pasteClipboard(parent));
  } else if (key === "d") {
    e.preventDefault();
    if (schema.copySelection()) {
      const parent = pasteTarget();
      withHistory("复制组件", () => schema.pasteClipboard(parent));
    }
  }
}
onMounted(() => window.addEventListener("keydown", onKeydown));
onBeforeUnmount(() => window.removeEventListener("keydown", onKeydown));

async function reloadDatasources() {
  try {
    datasources.value = asList<DataSourceDef>(await api.get(`/apps/${appId}/datasources/`));
  } catch {
    /* api 客户端已提示 */
  }
}

async function loadAll() {
  loading.value = true;
  try {
    const [pageRes, schemaRes, dsRes, modelRes, compRes] = await Promise.all([
      api.get<PageInfo>(`/pages/${pageId}/`),
      api.get<{ schema: PageSchema }>(`/pages/${pageId}/schema/`),
      api.get(`/apps/${appId}/datasources/`),
      api.get(`/apps/${appId}/models/`),
      api.get<{ components?: ComponentMeta[] }>(`/components/registry/`),
    ]);
    page.value = pageRes;
    schema.setSchema(schemaRes?.schema || schema.createEmpty(), pageId, appId);
    history.clear();
    editor.saveStatus = "saved";
    editor.lastSavedAt = new Date().toISOString();
    datasources.value = asList<DataSourceDef>(dsRes);
    models.value = asList<DataModelInfo>(modelRes);
    components.applyApi(Array.isArray(compRes?.components) ? compRes.components : []);
  } catch (e: any) {
    ElMessage.error(e?.message || "页面加载失败");
  } finally {
    loading.value = false;
  }
}

function goBack() {
  router.push(`/admin/apps/${appId}`);
}

function openPreview() {
  window.open(`/preview/${appId}/${pageId}`, "_blank");
}

function onAiGenerated(generated: PageSchema) {
  commit("AI 生成页面", () => schema.setSchema(generated, pageId, appId));
  ElMessage.success("AI 草稿已应用到画布，请检查后保存或发布");
}

/** AI 助手已在服务端落库草稿，这里同步画布并刷新页面版本号。 */
function onAgentApplied(updated: PageSchema) {
  schema.setSchema(updated, pageId, appId);
  api.get<PageInfo>(`/pages/${pageId}/`).then((p) => (page.value = p)).catch(() => undefined);
  ElMessage.success("AI 修改已应用，可继续对话或撤销前先保存");
}

function onPageUpdated(meta: PageInfo) {
  page.value = meta;
}

function onPublished() {
  // 重新拉取页面元信息（版本字段刷新）
  api.get<PageInfo>(`/pages/${pageId}/`).then((p) => (page.value = p)).catch(() => undefined);
}

async function regeneratePage() {
  if (!page.value) return;
  regenerating.value = true;
  try {
    await api.post(`/ai/pages/${pageId}/regenerate/`, { publish: false });
    const [pageRes, schemaRes] = await Promise.all([
      api.get<PageInfo>(`/pages/${pageId}/`),
      api.get<{ schema: PageSchema }>(`/pages/${pageId}/schema/`),
    ]);
    page.value = pageRes;
    schema.setSchema(schemaRes?.schema || schema.createEmpty(), pageId, appId);
    history.clear();
    ElMessage.success("AI 已重新生成当前页，请检查后保存或发布");
  } catch (error: any) {
    ElMessage.error(error?.message || "AI 重新生成失败");
  } finally {
    regenerating.value = false;
  }
}

async function loadDiff() {
  diffLoading.value = true;
  try {
    diffData.value = await api.get<any>(`/ai/pages/${pageId}/diff/`);
  } catch (error: any) {
    ElMessage.error(error?.message || "差异加载失败");
    diffData.value = null;
  } finally {
    diffLoading.value = false;
  }
}

async function onRolledBack() {
  // 回滚已将快照载入草稿：重新加载 schema
  try {
    const res = await api.get<{ schema: PageSchema }>(`/pages/${pageId}/schema/`);
    schema.setSchema(res?.schema || schema.createEmpty(), pageId, appId);
    history.clear();
    ElMessage.success("草稿已更新为回滚版本，请检查后保存/发布");
  } catch {
    /* api 客户端已提示 */
  }
}

// ---------- 自动保存 / 本地草稿恢复 ----------
const DRAFT_PREFIX = "wp-designer-draft-v1:";
let localTimer: ReturnType<typeof setInterval> | null = null;
let serverTimer: ReturnType<typeof setInterval> | null = null;

function draftKey(): string {
  return `${DRAFT_PREFIX}${schema.pageId || pageId}`;
}

function saveLocalDraft(force = false) {
  if (!schema.schema || (!force && !schema.dirty)) return;
  try {
    localStorage.setItem(
      draftKey(),
      JSON.stringify({
        schema: schema.schema,
        at: Date.now(),
        baseVersion: page.value?.version || 0,
        pageId: schema.pageId || pageId,
      })
    );
  } catch {
    /* 浏览器存储已满或被禁用时不影响编辑 */
  }
}

function clearLocalDraft() {
  try {
    localStorage.removeItem(draftKey());
  } catch {
    /* ignore */
  }
}

async function checkLocalDraft() {
  let draft: any = null;
  try {
    const raw = localStorage.getItem(draftKey());
    if (!raw) return;
    draft = JSON.parse(raw);
  } catch {
    clearLocalDraft();
    return;
  }
  if (!draft?.schema || typeof draft.schema !== "object") {
    clearLocalDraft();
    return;
  }
  if (JSON.stringify(draft.schema) === JSON.stringify(schema.schema)) {
    clearLocalDraft();
    return;
  }
  const stale = !!(draft.baseVersion && page.value?.version && draft.baseVersion !== page.value.version);
  try {
    await ElMessageBox.confirm(
      stale
        ? "发现本地草稿，但它基于旧页面版本。恢复可能覆盖其他人的修改，是否继续？"
        : "发现上次未保存的本地草稿，是否恢复？",
      "恢复本地草稿",
      {
        type: "warning",
        confirmButtonText: "恢复",
        cancelButtonText: "放弃",
        distinguishCancelAndClose: true,
      }
    );
    schema.setSchema(draft.schema, pageId, appId);
    schema.dirty = true;
    editor.saveStatus = "dirty";
    history.clear();
    ElMessage.success("本地草稿已恢复，请检查后保存");
  } catch {
    clearLocalDraft();
  }
}

function stopAutosave() {
  if (localTimer) window.clearInterval(localTimer);
  if (serverTimer) window.clearInterval(serverTimer);
  localTimer = null;
  serverTimer = null;
}

function startAutosave() {
  stopAutosave();
  localTimer = window.setInterval(() => saveLocalDraft(), 10_000);
  serverTimer = window.setInterval(() => {
    if (!schema.dirty || editor.saveStatus === "conflict") return;
    void toolbarRef.value?.save(true);
  }, 30_000);
}

function onDraftSaved(payload: any) {
  clearLocalDraft();
  if (payload?.page) page.value = payload.page;
}

// 路由参数变化（同一设计器组件内切换页面）时重新加载
watch(
  () => [route.params.appId, route.params.pageId],
  async () => {
    stopAutosave();
    await loadAll();
    await checkLocalDraft();
    startAutosave();
  }
);

function onCollabPointerMove(event: PointerEvent) {
  const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect();
  if (!rect) return;
  sendCollabCursor(event.clientX - rect.left, event.clientY - rect.top);
}

watch(
  () => [...schema.selectedIds],
  (ids) => sendCollabSelection(ids),
  { deep: true }
);

onMounted(async () => {
  connectDesignerCollab(appId, pageId);
  await loadAll();
  await checkLocalDraft();
  startAutosave();
});

// 离开前若有未保存改动，提醒一次
function onBeforeUnload(e: BeforeUnloadEvent) {
  saveLocalDraft(true);
  if (schema.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
}
window.addEventListener("beforeunload", onBeforeUnload);
onBeforeUnmount(() => {
  disconnectDesignerCollab();
  stopAutosave();
  saveLocalDraft(true);
  window.removeEventListener("beforeunload", onBeforeUnload);
});

onBeforeRouteLeave(async () => {
  if (!schema.dirty) return true;
  saveLocalDraft(true);
  try {
    await ElMessageBox.confirm("当前页面有未保存的修改，确定离开设计器？", "离开确认", {
      type: "warning",
      confirmButtonText: "离开",
      cancelButtonText: "继续编辑",
      distinguishCancelAndClose: true,
    });
    return true;
  } catch {
    return false;
  }
});
</script>

<style scoped>
.wp-designer {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--el-bg-color);
}
.wp-d-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.wp-d-title {
  font-size: 15px;
  font-weight: 600;
}
.wp-d-meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-d-dirty {
  font-size: 12px;
  color: var(--el-color-warning);
}
.wp-d-ai {
  margin-left: auto;
}
.wp-diff-summary {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
}
.wp-diff-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 55vh;
  overflow: auto;
}
.wp-diff-node {
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
}
.wp-diff-type {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-diff-change {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
  word-break: break-all;
}
.wp-diff-before {
  color: var(--el-color-danger);
  text-decoration: line-through;
  margin: 0 4px;
}
.wp-diff-after {
  color: var(--el-color-success);
  margin-left: 4px;
}
.wp-diff-tip {
  padding: 20px;
  text-align: center;
  color: var(--el-text-color-secondary);
}
.wp-d-body {
  flex: 1;
  display: flex;
  min-height: 0;
}
.wp-d-left {
  width: 264px;
  border-right: 1px solid var(--el-border-color-light);
  overflow: auto;
  flex-shrink: 0;
}
.wp-d-left-tabs {
  height: 100%;
}
.wp-d-left-tabs :deep(.el-tabs__content) {
  height: calc(100% - 40px);
  overflow: auto;
}
.wp-d-canvas {
  position: relative;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.wp-d-right {
  width: 300px;
  border-left: 1px solid var(--el-border-color-light);
  overflow: auto;
  flex-shrink: 0;
}
/* 左侧面板功能增多后允许标签换行，避免“区块/素材/变量/协同”被箭头藏住 */
.wp-d-left-tabs :deep(.el-tabs__nav-wrap),
.wp-d-left-tabs :deep(.el-tabs__nav-scroll) { overflow: visible; }
.wp-d-left-tabs :deep(.el-tabs__nav) { display: flex; flex-wrap: wrap; }
.wp-d-left-tabs :deep(.el-tabs__item) { height: 30px; line-height: 30px; padding: 0 8px; font-size: 11px; }
.wp-d-mobile-btn { display: none; }
.wp-d-mobile-mask { display: none; }
@media (max-width: 900px) {
  .wp-d-mobile-btn { display: inline-flex; }
  .wp-d-left, .wp-d-right { position: fixed; top: 0; bottom: 0; z-index: 3001; width: min(82vw, 320px); background: #fff; box-shadow: 0 0 40px rgba(15, 23, 42, 0.25); transition: transform 0.2s ease; }
  .wp-d-left { left: 0; transform: translateX(-105%); }
  .wp-d-right { right: 0; transform: translateX(105%); }
  .wp-d-left.is-mobile-open, .wp-d-right.is-mobile-open { transform: translateX(0); }
  .wp-d-mobile-mask { display: block; position: fixed; inset: 0; z-index: 3000; background: rgba(15, 23, 42, 0.4); }
  .wp-d-header { flex-wrap: wrap; gap: 4px; }
  .wp-d-title { font-size: 14px; }
  .wp-d-meta { display: none; }
}
</style>
