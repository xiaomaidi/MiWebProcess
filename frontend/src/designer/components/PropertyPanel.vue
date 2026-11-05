<template>
  <div class="wp-props-panel">
    <div v-if="!schema.schema" class="wp-pp-empty">尚未加载页面</div>
    <div v-else-if="!selected" class="wp-pp-empty">点击画布中的节点以编辑属性</div>

    <!-- 选中根画布：页面级设置 -->
    <template v-else-if="isRoot">
      <div class="wp-pp-title">页面设置</div>
      <el-form v-if="page" label-position="top" size="small">
        <el-form-item label="名称 name">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="路径 path（单段 slug）">
          <el-input v-model="form.path" />
        </el-form-item>
        <el-form-item label="类型 type">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="页面 page" value="page" />
            <el-option label="布局 layout" value="layout" />
            <el-option label="弹窗 popup" value="popup" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button size="small" type="primary" :loading="saving" @click="savePage">保存页面信息</el-button>
        </el-form-item>
      </el-form>

      <div class="wp-pp-subtitle">画布布局</div>
      <el-form label-position="top" size="small">
        <el-form-item label="布局模式 layout_mode">
          <el-radio-group :model-value="layoutMode" @change="(v: string | number | boolean) => setLayoutMode(v as 'flow' | 'free')">
            <el-radio value="flow">流式 flow</el-radio>
            <el-radio value="free">自由 free</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="画布背景（根节点 backgroundColor）">
          <el-input v-model="canvasBg" placeholder="如 #ffffff" @change="setCanvasBg" />
        </el-form-item>
        <el-form-item label="画布尺寸">
          <div class="wp-pp-size">
            <el-input v-model="canvasW" size="small" style="width: 90px" @change="setCanvasSize" />
            <span class="wp-pp-x">×</span>
            <el-input v-model="canvasH" size="small" style="width: 90px" @change="setCanvasSize" />
          </div>
        </el-form-item>
      </el-form>

      <el-collapse v-model="pageOpen" class="wp-pp-meta">
        <el-collapse-item title="页面 Meta / SEO / 全局样式" name="meta">
          <el-form label-position="top" size="small">
            <el-form-item label="浏览器标题 title">
              <el-input v-model="metaForm.title" placeholder="页面标题" />
            </el-form-item>
            <el-form-item label="语言 lang">
              <el-input v-model="metaForm.lang" placeholder="zh-CN" />
            </el-form-item>
            <el-form-item label="favicon">
              <el-input v-model="metaForm.favicon" placeholder="https://... 或 /media/..." />
            </el-form-item>
            <el-form-item label="SEO 描述">
              <el-input v-model="metaForm.description" type="textarea" :rows="2" />
            </el-form-item>
            <el-form-item label="SEO 关键词">
              <el-input v-model="metaForm.keywords" placeholder="逗号分隔" />
            </el-form-item>
            <el-form-item label="分享图 og:image">
              <el-input v-model="metaForm.ogImage" />
            </el-form-item>
            <el-form-item label="公开提交后转发（REST 数据源）">
              <el-select v-model="metaForm.forwardDatasourceId" clearable placeholder="不转发" style="width: 100%">
                <el-option
                  v-for="ds in restDatasources"
                  :key="ds.id"
                  :label="`${ds.name} (#${ds.id})`"
                  :value="ds.id"
                />
              </el-select>
              <div class="wp-pp-tip">仅 REST 数据源；公开表单提交后由服务端转发，失败不影响入库。</div>
            </el-form-item>
            <el-form-item label="主题预设">
              <el-select v-model="themePreset" size="small" style="width: 100%" @change="applyThemePreset">
                <el-option label="默认蓝色" value="default" />
                <el-option label="资讯红" value="news" />
                <el-option label="ERP 企业蓝" value="erp" />
                <el-option label="暗色" value="dark" />
                <el-option label="暖色" value="warm" />
              </el-select>
            </el-form-item>
            <el-form-item label="全局 CSS 变量（JSON）">
              <el-input v-model="metaForm.cssVars" type="textarea" :rows="3" class="wp-mono" placeholder='{"--wp-accent":"#409eff"}' />
            </el-form-item>
            <div class="wp-token-head">设计 Token</div>
            <el-form-item label="Token 预设">
              <el-select v-model="tokenPreset" size="small" style="width: 100%" @change="applyTokenPreset">
                <el-option label="深色游戏" value="dark-game" />
                <el-option label="浅色后台" value="light-admin" />
                <el-option label="企业蓝" value="corporate-blue" />
                <el-option label="数据大屏" value="dashboard-dark" />
                <el-option label="暖色内容" value="warm" />
              </el-select>
            </el-form-item>
            <el-form-item label="页面继承应用 Token">
              <el-switch v-model="useAppTokens" />
              <el-button size="small" text @click="applyTokensToApp">保存到整个应用</el-button>
            </el-form-item>
            <div class="wp-token-actions">
              <el-button size="small" @click="exportTokens">导出 JSON</el-button>
              <el-button size="small" @click="tokenFile?.click()">导入 JSON</el-button>
              <input ref="tokenFile" type="file" accept=".json,application/json" hidden @change="importTokens" />
            </div>
            <div v-for="group in tokenGroups" :key="group.title" class="wp-token-group">
              <div class="wp-token-group-title">{{ group.title }}</div>
              <div class="wp-token-grid">
                <label v-for="field in group.fields" :key="field.path" class="wp-token-field">
                  <span>{{ field.label }}</span>
                  <el-color-picker
                    v-if="field.color"
                    :model-value="tokenValue(field.path)"
                    size="small"
                    @change="(value: string | null) => setToken(field.path, value || '')"
                  />
                  <el-input
                    v-else
                    :model-value="tokenValue(field.path)"
                    size="small"
                    @input="(value: string) => setToken(field.path, value)"
                  />
                </label>
              </div>
            </div>
            <el-form-item>
              <el-button size="small" type="primary" @click="saveMeta">保存 Meta</el-button>
            </el-form-item>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </template>

    <!-- 多选：批量操作 -->
    <div v-else-if="selectedIds.length > 1" class="wp-pp-multi">
      <div class="wp-pp-title">已选择 {{ selectedIds.length }} 个节点</div>
      <div class="wp-pp-multi-list">
        <el-tag v-for="n in selectedNodes.slice(0, 8)" :key="n.id" size="small" type="info">
          {{ components.meta(n.type)?.label || n.type }}
        </el-tag>
        <el-tag v-if="selectedNodes.length > 8" size="small" type="info">+{{ selectedNodes.length - 8 }}</el-tag>
      </div>
      <div class="wp-pp-multi-section">对齐</div>
      <div class="wp-pp-btn-row">
        <el-button size="small" :disabled="!canAlign" @click="align('left')">左对齐</el-button>
        <el-button size="small" :disabled="!canAlign" @click="align('hcenter')">水平居中</el-button>
        <el-button size="small" :disabled="!canAlign" @click="align('right')">右对齐</el-button>
      </div>
      <div class="wp-pp-btn-row">
        <el-button size="small" :disabled="!canAlign" @click="align('top')">顶对齐</el-button>
        <el-button size="small" :disabled="!canAlign" @click="align('vcenter')">垂直居中</el-button>
        <el-button size="small" :disabled="!canAlign" @click="align('bottom')">底对齐</el-button>
      </div>
      <div class="wp-pp-btn-row">
        <el-button size="small" :disabled="!canDistribute" @click="distribute('x')">水平分布</el-button>
        <el-button size="small" :disabled="!canDistribute" @click="distribute('y')">垂直分布</el-button>
      </div>
      <div class="wp-pp-multi-section">编辑</div>
      <div class="wp-pp-btn-row">
        <el-button size="small" @click="copySelected">复制</el-button>
        <el-button size="small" :disabled="!schema.clipboard" @click="pasteCopied">粘贴</el-button>
        <el-button size="small" type="danger" plain @click="deleteMultiple">删除</el-button>
      </div>
      <p class="wp-pp-multi-tip">对齐/分布仅对自由布局（free）下带坐标的节点生效。</p>
    </div>

    <!-- 选中普通节点：属性/样式/事件/数据绑定/高级 -->
    <div v-else class="wp-pp-node">
      <div class="wp-pp-node-bar">
        <span class="wp-pp-node-type">{{ selected.type }}</span>
        <span class="wp-pp-node-source">{{ meta?.label }} · {{ meta?.source || "legacy" }}</span>
        <el-button size="small" type="danger" plain @click="deleteSelected">删除</el-button>
      </div>
      <div class="wp-pp-ai">
        <el-input
          v-model="aiPrompt"
          size="small"
          placeholder="用一句话描述想怎么改，例如：改成红色、圆角、字号 18"
          @keyup.enter="aiGenerateNode"
        />
        <el-button size="small" type="primary" plain :loading="aiLoading" @click="aiGenerateNode">✨ AI</el-button>
      </div>
      <el-alert
        v-if="aiMessage"
        :title="aiMessage"
        :type="aiWarnings.length ? 'warning' : 'success'"
        :closable="false"
        show-icon
        class="wp-pp-ai-msg"
      />
      <el-tabs v-model="rightTab" class="wp-pp-tabs">
        <el-tab-pane label="属性" name="props">
          <PropsTab :node-id="selected.id" :datasources="datasources" :models="models" />
        </el-tab-pane>
        <el-tab-pane label="样式" name="style">
          <StyleTab :node-id="selected.id" />
        </el-tab-pane>
        <el-tab-pane label="状态" name="states">
          <StatesVariantsTab :node-id="selected.id" />
        </el-tab-pane>
        <el-tab-pane label="事件" name="events">
          <EventsTab :node-id="selected.id" :datasources="datasources" :models="models" />
        </el-tab-pane>
        <el-tab-pane label="绑定" name="binding">
          <BindingTab :node-id="selected.id" :datasources="datasources" :models="models" />
        </el-tab-pane>
        <el-tab-pane label="质检" name="audit">
          <QualityPanel />
        </el-tab-pane>
        <el-tab-pane label="评论" name="comments">
          <CommentsPanel v-if="page" :page-id="page.id" />
        </el-tab-pane>
        <el-tab-pane label="高级" name="advanced">
          <el-collapse v-model="advancedOpen" class="wp-pp-advanced">
            <el-collapse-item title="条件渲染" name="condition">
              <ConditionTab :node-id="selected.id" />
            </el-collapse-item>
            <el-collapse-item title="自由布局 / 对齐" name="layout">
              <LayoutTab :node-id="selected.id" />
            </el-collapse-item>
            <el-collapse-item title="设备布局覆盖" name="device-layout">
              <DeviceLayoutPanel :node-id="selected.id" />
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import { TOKEN_PRESETS, clone, normalizeTokens, type DesignTokens } from "@/design/tokens";
import type { DataModelInfo, DataSourceDef, PageInfo } from "@/types";
import { commit } from "../util";
import PropsTab from "./PropsTab.vue";
import StyleTab from "./StyleTab.vue";
import StatesVariantsTab from "./StatesVariantsTab.vue";
import EventsTab from "./EventsTab.vue";
import BindingTab from "./BindingTab.vue";
import ConditionTab from "./ConditionTab.vue";
import LayoutTab from "./LayoutTab.vue";
import CommentsPanel from "./CommentsPanel.vue";
import DeviceLayoutPanel from "./DeviceLayoutPanel.vue";
import QualityPanel from "./QualityPanel.vue";

const props = defineProps<{
  page: PageInfo | null;
  appId: number;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();
const emit = defineEmits<{ (e: "page-updated", meta: PageInfo): void }>();

const schema = useSchemaStore();
const components = useComponentStore();
const rightTab = ref("props");
const themePreset = ref("default");
const THEME_PRESETS: Record<string, Record<string, string>> = {
  default: { "--el-color-primary": "#409eff", "--wp-page-bg": "#ffffff" },
  news: { "--el-color-primary": "#e4393c", "--wp-page-bg": "#ffffff", "--wp-accent": "#e4393c" },
  erp: { "--el-color-primary": "#2f6fed", "--wp-page-bg": "#f5f7fa", "--wp-accent": "#2f6fed" },
  dark: {
    "--el-color-primary": "#7aa2ff",
    "--el-bg-color": "#17181c",
    "--el-fill-color-blank": "#17181c",
    "--el-text-color-primary": "#f2f3f5",
    "--el-border-color": "#34363d",
    "--wp-page-bg": "#17181c",
  },
  warm: { "--el-color-primary": "#d97706", "--wp-page-bg": "#fffaf3", "--wp-accent": "#d97706" },
};

function applyThemePreset() {
  const preset = THEME_PRESETS[themePreset.value] || THEME_PRESETS.default;
  metaForm.cssVars = JSON.stringify(preset, null, 2);
}
const selected = computed(() => (schema.selectedId ? schema.node(schema.selectedId) : null));
const selectedIds = computed(() => schema.selectedIds);
const selectedNodes = computed(() => schema.selectedNodes);
const isRoot = computed(() => selected.value?.type === "wp-canvas");
const meta = computed(() => (selected.value ? components.meta(selected.value.type) : undefined));
const canAlign = computed(() => selectedNodes.value.some((n) => !!n.layout));
const canDistribute = computed(() => selectedNodes.value.filter((n) => !!n.layout).length >= 3);
const advancedOpen = ref(["condition", "layout"]);
const tokenPreset = ref("light-admin");
const useAppTokens = ref(false);
const tokenFile = ref<HTMLInputElement | null>(null);
const tokenForm = reactive<DesignTokens>(normalizeTokens({ preset: "light-admin" }));
const tokenGroups = [
  {
    title: "颜色",
    fields: [
      { path: "color.bg", label: "背景", color: true },
      { path: "color.surface", label: "卡片", color: true },
      { path: "color.text", label: "正文", color: true },
      { path: "color.muted", label: "次要文字", color: true },
      { path: "color.accent", label: "强调色", color: true },
      { path: "color.border", label: "边框", color: true },
      { path: "color.success", label: "成功", color: true },
      { path: "color.warning", label: "警告", color: true },
      { path: "color.danger", label: "危险", color: true },
    ],
  },
  {
    title: "间距",
    fields: [
      { path: "space.xs", label: "XS", color: false },
      { path: "space.sm", label: "SM", color: false },
      { path: "space.md", label: "MD", color: false },
      { path: "space.lg", label: "LG", color: false },
      { path: "space.xl", label: "XL", color: false },
    ],
  },
  {
    title: "字体",
    fields: [
      { path: "font.family", label: "字体", color: false },
      { path: "font.body", label: "正文", color: false },
      { path: "font.title", label: "标题", color: false },
      { path: "font.mono", label: "等宽", color: false },
    ],
  },
  {
    title: "圆角 / 阴影",
    fields: [
      { path: "radius.sm", label: "圆角 SM", color: false },
      { path: "radius.md", label: "圆角 MD", color: false },
      { path: "radius.lg", label: "圆角 LG", color: false },
      { path: "shadow.sm", label: "阴影 SM", color: false },
      { path: "shadow.md", label: "阴影 MD", color: false },
      { path: "shadow.lg", label: "阴影 LG", color: false },
    ],
  },
  {
    title: "响应式断点",
    fields: [
      { path: "breakpoint.sm", label: "SM", color: false },
      { path: "breakpoint.md", label: "MD", color: false },
      { path: "breakpoint.lg", label: "LG", color: false },
      { path: "breakpoint.xl", label: "XL", color: false },
    ],
  },
] as const;

function tokenValue(path: string): string {
  const [group, key] = path.split(".");
  return String((tokenForm as any)[group]?.[key] ?? "");
}

function setToken(path: string, value: string) {
  const [group, key] = path.split(".");
  (tokenForm as any)[group][key] = value;
}

function applyTokenPreset() {
  const preset = TOKEN_PRESETS[tokenPreset.value] || TOKEN_PRESETS["light-admin"];
  Object.assign(tokenForm, clone(preset));
}

async function applyTokensToApp() {
  try {
    await api.patch(`/apps/${props.appId}/`, { design_tokens: clone(tokenForm) });
    useAppTokens.value = true;
    ElMessage.success("已保存为应用级 Token，保存页面 Meta 后生效");
  } catch (error: any) {
    ElMessage.error(error?.message || "保存应用 Token 失败");
  }
}

function exportTokens() {
  const blob = new Blob([JSON.stringify(tokenForm, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "design-tokens.json";
  link.click();
  URL.revokeObjectURL(url);
}

function importTokens(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const parsed = JSON.parse(String(reader.result || "{}"));
      const tokens = normalizeTokens(parsed);
      Object.assign(tokenForm, tokens);
      tokenPreset.value = tokens.preset || "custom";
      ElMessage.success("Token JSON 已导入");
    } catch {
      ElMessage.error("Token JSON 格式不正确");
    }
  };
  reader.readAsText(file);
  input.value = "";
}
const aiPrompt = ref("");
const aiLoading = ref(false);
const aiMessage = ref("");
const aiWarnings = ref<string[]>([]);
const pageOpen = ref<string[]>([]);

function deleteSelected() {
  const id = selected.value?.id;
  if (!id || isRoot.value) return;
  commit("删除组件", () => schema.removeNodeReparent(id));
}

function align(mode: "left" | "hcenter" | "right" | "top" | "vcenter" | "bottom") {
  if (!canAlign.value) {
    ElMessage.warning("请切换到自由布局，并选择带坐标的节点");
    return;
  }
  commit("多选对齐", () => schema.alignSelection(mode));
}

function distribute(axis: "x" | "y") {
  if (!canDistribute.value) {
    ElMessage.warning("等间距分布至少需要 3 个带坐标的节点");
    return;
  }
  commit("多选分布", () => schema.distributeSelection(axis));
}

function pasteTarget(): string {
  const s = schema.schema;
  if (!s) return "";
  const n = selected.value;
  if (n) {
    const m = components.meta(n.type);
    const accepts = m?.accept_children || m?.accepts || [];
    if (m?.is_container || accepts.length > 0) return n.id;
    return schema.parentOf(n.id) || s.rootId;
  }
  return s.rootId;
}

function copySelected() {
  if (schema.copySelection()) ElMessage.success(`已复制 ${schema.selectedIds.length} 个节点`);
}

function pasteCopied() {
  if (!schema.clipboard) return;
  commit("粘贴组件", () => schema.pasteClipboard(pasteTarget()));
}

function deleteMultiple() {
  const s = schema.schema;
  if (!s) return;
  const count = schema.selectedIds.filter((id) => id !== s.rootId).length;
  if (!count) return;
  commit(`删除 ${count} 个组件`, () => schema.removeSelected());
}

// ---- 页面信息表单 ----
const form = reactive({ name: "", path: "", type: "page" as PageInfo["type"] });
const saving = ref(false);

function syncForm() {
  if (!props.page) return;
  form.name = props.page.name;
  form.path = props.page.path;
  form.type = props.page.type;
}
watch(() => props.page, syncForm, { immediate: true });

async function savePage() {
  const p = props.page;
  if (!p) return;
  saving.value = true;
  try {
    const info = await api.put<PageInfo>(`/pages/${p.id}/`, {
      name: form.name.trim(),
      path: form.path.trim(),
      type: form.type,
    });
    emit("page-updated", info);
    ElMessage.success("页面信息已保存");
  } catch {
    /* api 层已提示 */
  } finally {
    saving.value = false;
  }
}

// ---- 画布级设置 ----
const layoutMode = computed<"flow" | "free">(() => schema.schema?.layout?.mode ?? "flow");
function setLayoutMode(v: "flow" | "free") {
  commit("布局模式", () => schema.setLayoutMode(v));
}

const rootNode = computed(() => (isRoot.value ? selected.value! : null));
const canvasBg = ref("");
watch(
  rootNode,
  (n) => {
    canvasBg.value = (n?.style?.backgroundColor as string) ?? "";
  },
  { immediate: true }
);
function setCanvasBg(v: string) {
  commit("画布背景", () => rootNode.value && schema.setNodeStyle(rootNode.value.id, { backgroundColor: v.trim() || undefined }));
}

const canvasW = ref("");
const canvasH = ref("");
watch(
  () => schema.schema?.layout,
  (l) => {
    if (!l) return;
    canvasW.value = String(l.width);
    canvasH.value = String(l.height);
  },
  { immediate: true }
);
function setCanvasSize() {
  const w = Number(canvasW.value) || 1200;
  const h = Number(canvasH.value) || 800;
  commit("画布尺寸", () => {
    if (!schema.schema) return;
    schema.schema.layout = { ...schema.schema.layout!, width: w, height: h };
  });
}

async function aiGenerateNode() {
  if (!selected.value || !aiPrompt.value.trim()) {
    ElMessage.warning("请先描述想怎么改");
    return;
  }
  const node = selected.value;
  aiLoading.value = true;
  aiMessage.value = "";
  aiWarnings.value = [];
  try {
    const result = await api.post<any>("/ai/design/node-draft/", {
      app_id: props.appId,
      node_type: node.type,
      node_label: meta.value?.label || node.type,
      props_schema: meta.value?.props_schema || {},
      style_schema: meta.value?.style_schema || {},
      allowed_events: meta.value?.events || [],
      current_props: node.props || {},
      current_style: node.style || {},
      current_events: node.events || {},
      prompt: aiPrompt.value.trim(),
    });
    const hasChanges = Object.keys(result.props || {}).length || Object.keys(result.style || {}).length || Object.keys(result.events || {}).length;
    if (!hasChanges) {
      aiWarnings.value = result.warnings || ["AI 没有返回可应用的修改"];
      aiMessage.value = "没有可应用的修改";
      return;
    }
    commit("AI 生成节点属性", () => {
      schema.patchNode(node.id, {
        props: result.props || {},
        style: result.style || {},
        events: result.events || {},
      });
    });
    rightTab.value = "props";
    aiWarnings.value = result.warnings || [];
    aiMessage.value = result.explanation || `已应用：${Object.keys(result.props || {}).join("、") || "样式"}`;
    ElMessage.success("AI 已应用修改");
  } catch (error: any) {
    ElMessage.error(error?.message || "AI 生成失败");
  } finally {
    aiLoading.value = false;
  }
}

// ---- 页面 Meta ----
const metaForm = reactive({
  title: "",
  lang: "zh-CN",
  favicon: "",
  description: "",
  keywords: "",
  ogImage: "",
  forwardDatasourceId: null as number | null,
  cssVars: "{}",
});

const restDatasources = computed(() => (props.datasources || []).filter((ds) => String(ds.type) === "rest"));
function syncMeta() {
  const m = schema.schema?.meta || {};
  metaForm.title = m.title || "";
  metaForm.lang = m.lang || "zh-CN";
  metaForm.favicon = m.favicon || "";
  metaForm.description = m.seo?.description || m.description || "";
  metaForm.keywords = m.seo?.keywords || m.keywords || "";
  metaForm.ogImage = m.seo?.ogImage || m.ogImage || "";
  metaForm.forwardDatasourceId = Number(m.forwardDatasourceId) || null;
  try {
    metaForm.cssVars = JSON.stringify(m.globalStyle?.cssVars || {}, null, 2);
  } catch {
    metaForm.cssVars = "{}";
  }
  const tokens = normalizeTokens(m.designTokens || { preset: "light-admin" });
  Object.assign(tokenForm, tokens);
  tokenPreset.value = tokens.preset || "light-admin";
  useAppTokens.value = !!(m as any).useAppTokens;
}
watch(isRoot, syncMeta, { immediate: true });

function saveMeta() {
  let cssVars: Record<string, string> = {};
  try {
    const parsed = JSON.parse(metaForm.cssVars || "{}");
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) cssVars = parsed;
  } catch {
    ElMessage.error("全局 CSS 变量必须是 JSON 对象");
    return;
  }
  commit("页面 Meta", () =>
    schema.setPageMeta({
      title: metaForm.title,
      lang: metaForm.lang,
      favicon: metaForm.favicon,
      seo: { description: metaForm.description, keywords: metaForm.keywords, ogImage: metaForm.ogImage },
      forwardDatasourceId: metaForm.forwardDatasourceId || 0,
      designTokens: clone(tokenForm),
      useAppTokens: useAppTokens.value,
      globalStyle: { ...(schema.schema?.meta?.globalStyle || {}), cssVars },
    })
  );
  ElMessage.success("页面 Meta 已保存");
}
</script>

<style scoped>
.wp-props-panel {
  font-size: 13px;
  padding: 8px 10px;
  overflow: auto;
  height: 100%;
}
.wp-pp-empty {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  padding: 20px 0;
  text-align: center;
}
.wp-pp-title {
  font-weight: 600;
  margin-bottom: 10px;
}
.wp-pp-tip {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
}
.wp-pp-ai {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 8px 0;
}
.wp-pp-ai .el-input {
  flex: 1;
}
.wp-pp-ai-msg {
  margin-bottom: 8px;
}
.wp-token-head {
  margin: 14px 0 8px;
  padding-top: 10px;
  border-top: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
  font-weight: 600;
}
.wp-token-group {
  margin-bottom: 10px;
}
.wp-token-actions {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.wp-token-group-title {
  margin-bottom: 6px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-token-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
}
.wp-token-field {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.wp-token-field > span {
  flex: none;
  max-width: 48px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-token-field :deep(.el-input) {
  min-width: 0;
}
.wp-token-field :deep(.el-color-picker) {
  flex: none;
}
.wp-pp-subtitle {
  font-weight: 600;
  margin: 16px 0 8px;
}
.wp-pp-size {
  display: flex;
  align-items: center;
  gap: 6px;
}
.wp-pp-x {
  color: var(--el-text-color-secondary);
}
.wp-pp-tabs :deep(.el-tabs__header) {
  margin-bottom: 8px;
}
.wp-pp-tabs :deep(.el-tabs__item) {
  padding: 0 8px;
  font-size: 12px;
}
.wp-pp-multi {
  padding: 2px;
}
.wp-pp-multi-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 10px;
}
.wp-pp-multi-section {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  margin: 12px 0 6px;
}
.wp-pp-btn-row {
  display: flex;
  gap: 4px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.wp-pp-multi-tip {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.wp-pp-node-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.wp-pp-node-type {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.wp-pp-node-source {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-pp-meta {
  margin-top: 12px;
}
.wp-mono :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
</style>
