<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>组件工坊</h2>
        <p class="wp-page-desc">导入预构建的 Vue Web Component；导入后设计器即可使用，不需要重新构建平台。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="load">刷新</el-button>
        <el-button @click="openEditor">在线编写</el-button>
        <el-button type="primary" @click="openImport">导入组件</el-button>
      </div>
    </div>

    <el-card>
      <div class="wp-comp-toolbar">
        <el-radio-group v-model="origin" size="small" @change="onFilterChange">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button value="builtin">平台自带</el-radio-button>
          <el-radio-button value="custom">我的组件</el-radio-button>
        </el-radio-group>
        <el-select v-model="category" size="small" clearable placeholder="全部分类" style="width: 150px" @change="onFilterChange">
          <el-option v-for="item in categories" :key="item.key" :label="item.label" :value="item.key" />
        </el-select>
        <el-input v-model="keyword" size="small" clearable placeholder="搜索组件名/显示名" style="width: 220px" @keyup.enter="onFilterChange" @clear="onFilterChange" />
        <el-button size="small" @click="onFilterChange">查询</el-button>
      </div>
      <el-table :data="components" v-loading="loading" border stripe>
        <el-table-column prop="name" label="组件名" min-width="150" />
        <el-table-column prop="label" label="显示名" min-width="150" />
        <el-table-column prop="element" label="标签" min-width="170" />
        <el-table-column label="分类" width="110">
          <template #default="{ row }">{{ categoryLabel(row.category) }}</template>
        </el-table-column>
        <el-table-column label="来源" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_builtin ? 'info' : 'success'" effect="plain">
              {{ row.is_builtin ? "平台自带" : "我的组件" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.is_enabled ? 'success' : 'info'">
              {{ row.is_enabled ? "启用" : "停用" }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <template v-if="row.is_builtin">
              <el-button size="small" type="danger" plain @click="toggle(row)">
                {{ row.is_enabled ? "禁用" : "启用" }}
              </el-button>
            </template>
            <template v-else>
              <el-button size="small" @click="openPreview(row)">预览</el-button>
              <el-button size="small" @click="openVersions(row)">版本</el-button>
              <el-button size="small" @click="openImport(row)">新版本</el-button>
              <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
            </template>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="origin === 'custom' ? '还没有自定义组件' : '没有匹配的组件'" :image-size="60" />
        </template>
      </el-table>
      <div class="wp-comp-pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[10, 20, 50]"
          :total="total"
          layout="total, sizes, prev, pager, next"
          @current-change="load"
          @size-change="onSizeChange"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" title="导入 Web Component" width="680px" :close-on-click-modal="false">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="上传构建后的 ESM JS。组件需要自己调用 customElements.define('wp-widget-xxx', ...)。"
        style="margin-bottom: 14px"
      />
      <el-form :model="form" label-width="110px">
        <el-form-item label="组件名">
          <el-input v-model="form.name" :disabled="!!editing" placeholder="stock-editor" />
        </el-form-item>
        <el-form-item label="显示名">
          <el-input v-model="form.label" placeholder="库存编辑器" />
        </el-form-item>
        <el-form-item label="自定义标签">
          <el-input v-model="form.tag" placeholder="wp-widget-stock-editor" />
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="form.version" placeholder="1.0.0" />
        </el-form-item>
        <el-form-item label="JS 文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".js"
            :on-change="onFileChange"
            :on-remove="() => (file = null)"
          >
            <el-button>选择 .js 文件</el-button>
          </el-upload>
        </el-form-item>
        <el-form-item label="属性 Schema">
          <el-input v-model="form.propsSchema" type="textarea" :rows="5" class="wp-mono" />
        </el-form-item>
        <el-form-item label="事件">
          <el-input v-model="form.events" placeholder='["saved","change"]' />
        </el-form-item>
        <el-form-item label="默认属性">
          <el-input v-model="form.defaultProps" type="textarea" :rows="3" class="wp-mono" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editorVisible" title="在线编写组件" width="900px" :close-on-click-modal="false">
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="在线编译会在服务端执行 Vite 构建，仅适合管理员自用；不支持沙箱。"
        style="margin-bottom: 12px"
      />
      <div class="wp-ai-draft">
        <el-input
          v-model="aiPrompt"
          type="textarea"
          :rows="2"
          placeholder="描述你想要的组件，例如：库存表格，支持按仓库筛选，显示物料、库存、预警状态。"
          @keyup.ctrl.enter="aiDraft"
        />
        <el-button type="primary" plain :loading="aiDrafting" @click="aiDraft">✨ AI 生成/修改</el-button>
      </div>
      <el-alert
        v-if="aiWarnings.length"
        type="warning"
        :closable="false"
        show-icon
        :title="aiWarnings.join('；')"
        style="margin-bottom: 12px"
      />
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="样式规范：使用 --wp-accent / --wp-bg / --wp-text 等 CSS 变量；类名加 wp- 前缀；避免全局选择器。"
        style="margin-bottom: 12px"
      />
      <el-form :model="editorForm" label-width="110px">
        <el-row :gutter="10">
          <el-col :span="12"><el-form-item label="组件名"><el-input v-model="editorForm.name" placeholder="stock-editor" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="显示名"><el-input v-model="editorForm.label" placeholder="库存编辑器" /></el-form-item></el-col>
        </el-row>
        <el-row :gutter="10">
          <el-col :span="12"><el-form-item label="标签"><el-input v-model="editorForm.tag" placeholder="wp-widget-stock-editor" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="版本"><el-input v-model="editorForm.version" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="Vue SFC">
          <MonacoCodeEditor
            v-model="editorForm.source"
            language="html"
            height="460px"
            :error-line="compileErrorLine"
            :error-message="compileErrorMessage"
          />
          <el-alert
            v-if="compileError"
            type="error"
            :closable="false"
            show-icon
            :title="compileError"
            style="margin-top: 8px"
          />
        </el-form-item>
        <el-form-item label="属性 Schema">
          <el-input v-model="editorForm.propsSchema" type="textarea" :rows="4" class="wp-mono" />
        </el-form-item>
        <el-form-item label="事件">
          <el-input v-model="editorForm.events" placeholder='["saved"]' />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editorVisible = false">取消</el-button>
        <el-button type="primary" :loading="compiling" @click="compile">编译并导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewVisible" title="组件预览" width="820px" append-to-body>
      <div class="wp-comp-preview">
        <component v-if="previewComponent" :is="previewComponent" v-bind="previewProps" />
        <el-empty v-else description="该组件没有可加载的构建文件" :image-size="50" />
      </div>
    </el-dialog>

    <el-dialog v-model="versionsVisible" title="组件版本" width="720px" append-to-body>
      <el-table :data="versions" size="small" border>
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column prop="changelog" label="说明" min-width="200" />
        <el-table-column label="时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button size="small" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, type Component } from "vue";
import { ElMessage, ElMessageBox, type UploadFile } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";
import { remoteComponentFor } from "@/engine/remote-component";
import type { ComponentMeta } from "@/types";
import MonacoCodeEditor from "@/components/MonacoCodeEditor.vue";

const loading = ref(false);
const saving = ref(false);
const compiling = ref(false);
const compileError = ref("");
const compileErrorLine = ref(0);
const compileErrorMessage = ref("");
const aiPrompt = ref("");
const aiDrafting = ref(false);
const aiWarnings = ref<string[]>([]);
const previewVisible = ref(false);
const previewComponent = ref<Component | null>(null);
const previewProps = ref<Record<string, any>>({});
const versionsVisible = ref(false);
const versions = ref<any[]>([]);
const versionTarget = ref<ComponentMeta | null>(null);
const dialogVisible = ref(false);
const editorVisible = ref(false);
const components = ref<ComponentMeta[]>([]);
const editing = ref<ComponentMeta | null>(null);
const file = ref<File | null>(null);
const origin = ref<"all" | "builtin" | "custom">("all");
const category = ref("");
const keyword = ref("");
const categories = ref<{ key: string; label: string }[]>([]);
const page = ref(1);
const size = ref(10);
const total = ref(0);

const defaultSource = `<template>
  <div class="demo-widget">
    <h3>{{ title }}</h3>
    <p>这是一个通过平台在线编译的 Vue Web Component。</p>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ title?: string }>(), { title: "我的组件" });
<\/script>

<style scoped>
.demo-widget {
  border: 1px solid var(--wp-border, #dcdfe6);
  border-radius: 8px;
  padding: 16px;
  color: var(--wp-text, #303133);
  background: var(--wp-bg, #fff);
}
.demo-widget h3 {
  margin: 0 0 8px;
  color: var(--wp-heading, inherit);
}
</style>`;

const editorForm = reactive({
  name: "",
  label: "",
  tag: "",
  version: "1.0.0",
  source: defaultSource,
  propsSchema: '{\n  "type": "object",\n  "properties": {\n    "title": { "type": "string", "title": "标题" }\n  }\n}',
  events: "[]",
});

const form = reactive({
  name: "",
  label: "",
  tag: "",
  version: "1.0.0",
  propsSchema: '{\n  "type": "object",\n  "properties": {}\n}',
  events: "[]",
  defaultProps: "{}",
});

async function load() {
  loading.value = true;
  try {
    const params = new URLSearchParams({
      enabled: "0",
      page: String(page.value),
      size: String(size.value),
    });
    if (origin.value !== "all") params.set("origin", origin.value);
    if (category.value) params.set("category", category.value);
    if (keyword.value.trim()) params.set("q", keyword.value.trim());
    const result = await api.get<any>(`/components/?${params.toString()}`);
    components.value = result.results || [];
    total.value = Number(result.count) || 0;
  } finally {
    loading.value = false;
  }
}

async function loadCategories() {
  try {
    const result = await api.get<any>("/components/registry/");
    categories.value = result.categories || [];
  } catch {
    categories.value = [];
  }
}

function categoryLabel(key: string): string {
  return categories.value.find((item) => item.key === key)?.label || key || "-";
}

function onFilterChange() {
  page.value = 1;
  load();
}

function onSizeChange() {
  page.value = 1;
  load();
}

async function toggle(row: ComponentMeta) {
  try {
    await api.post(`/components/${row.id}/${row.is_enabled ? "disable" : "enable"}/`, {});
    ElMessage.success(row.is_enabled ? "已禁用" : "已启用");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "操作失败");
  }
}

function openImport(row?: ComponentMeta) {
  editing.value = row || null;
  file.value = null;
  form.name = row?.name || "";
  form.label = row?.label || "";
  form.tag = row?.element || "";
  form.version = row?.version || "1.0.0";
  form.propsSchema = JSON.stringify(row?.props_schema || { type: "object", properties: {} }, null, 2);
  form.events = JSON.stringify(row?.events || [], null, 2);
  form.defaultProps = JSON.stringify(row?.default_props || {}, null, 2);
  dialogVisible.value = true;
}

function onFileChange(uploadFile: UploadFile) {
  file.value = uploadFile.raw || null;
}

async function submit() {
  if (!file.value) {
    ElMessage.warning("请选择组件 JS 文件");
    return;
  }
  if (!form.name.trim() || !form.tag.trim() || !form.label.trim()) {
    ElMessage.warning("请填写组件名、显示名和标签");
    return;
  }
  saving.value = true;
  try {
    const extra: Record<string, string> = {
      name: form.name.trim(),
      label: form.label.trim(),
      tag: form.tag.trim(),
      version: form.version.trim() || "1.0.0",
      props_schema: form.propsSchema,
      events: form.events,
      default_props: form.defaultProps,
    };
    await api.upload("/components/import/", file.value, "file", extra);
    ElMessage.success("组件已导入");
    dialogVisible.value = false;
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "导入失败");
  } finally {
    saving.value = false;
  }
}

function openPreview(row: ComponentMeta) {
  if (!row.source_url || !row.element) {
    ElMessage.warning("该组件没有构建文件");
    return;
  }
  const values: Record<string, any> = { ...(row.default_props || {}) };
  for (const [key, schema] of Object.entries(row.props_schema?.properties || {})) {
    if (values[key] !== undefined) continue;
    const prop = schema as any;
    values[key] = prop.default ?? (prop.type === "number" ? 0 : prop.type === "boolean" ? false : prop.title || key);
  }
  previewProps.value = values;
  previewComponent.value = remoteComponentFor(row.source_url, row.element);
  previewVisible.value = true;
}

async function openVersions(row: ComponentMeta) {
  versionTarget.value = row;
  const result = await api.get<any>(`/components/${row.id}/versions/?size=100`);
  versions.value = result.results || [];
  versionsVisible.value = true;
}

async function rollback(row: any) {
  if (!versionTarget.value) return;
  try {
    await ElMessageBox.confirm(`回滚到版本 ${row.version}？该操作会切换组件当前版本。`, "回滚组件", {
      type: "warning",
    });
    await api.post(`/components/${versionTarget.value.id}/versions/${row.version}/rollback/`, {});
    ElMessage.success("已回滚");
    versionsVisible.value = false;
    await load();
  } catch {
    /* 用户取消或接口已提示 */
  }
}

async function remove(row: ComponentMeta) {
  try {
    await ElMessageBox.confirm(`删除组件「${row.label || row.name}」及其入口文件？`, "删除组件", {
      type: "warning",
    });
    await api.del(`/components/${row.id}/`);
    ElMessage.success("组件已删除");
    await load();
  } catch {
    /* 用户取消或接口已提示 */
  }
}

function openEditor() {
  editorForm.name = "";
  editorForm.label = "";
  editorForm.tag = "";
  editorForm.version = "1.0.0";
  editorForm.source = defaultSource;
  editorForm.propsSchema = '{\n  "type": "object",\n  "properties": {\n    "title": { "type": "string", "title": "标题" }\n  }\n}';
  editorForm.events = "[]";
  aiPrompt.value = "";
  aiWarnings.value = [];
  editorVisible.value = true;
}

async function aiDraft() {
  if (!aiPrompt.value.trim()) {
    ElMessage.warning("请先描述想要的组件");
    return;
  }
  aiDrafting.value = true;
  aiWarnings.value = [];
  try {
    const result = await api.post<any>("/components/ai-draft/", {
      prompt: aiPrompt.value.trim(),
      name: editorForm.name.trim(),
      tag: editorForm.tag.trim(),
      current_source: editorForm.source,
    });
    const draft = result.draft || {};
    if (draft.name) editorForm.name = draft.name;
    if (draft.label) editorForm.label = draft.label;
    if (draft.tag) editorForm.tag = draft.tag;
    if (draft.source) editorForm.source = draft.source;
    if (draft.props_schema) editorForm.propsSchema = JSON.stringify(draft.props_schema, null, 2);
    if (Array.isArray(draft.events)) editorForm.events = JSON.stringify(draft.events);
    aiWarnings.value = result.warnings || [];
    ElMessage.success(`AI 已写入组件（${result.provider || "local"}）`);
  } catch (error: any) {
    ElMessage.error(error?.message || "AI 生成失败");
  } finally {
    aiDrafting.value = false;
  }
}

async function compile() {
  if (!editorForm.name.trim() || !editorForm.tag.trim() || !editorForm.label.trim()) {
    ElMessage.warning("请填写组件名、显示名和标签");
    return;
  }
  compiling.value = true;
  compileError.value = "";
  compileErrorLine.value = 0;
  compileErrorMessage.value = "";
  try {
    await api.post("/components/compile/", {
      name: editorForm.name.trim(),
      label: editorForm.label.trim(),
      tag: editorForm.tag.trim(),
      version: editorForm.version.trim() || "1.0.0",
      source: editorForm.source,
      props_schema: editorForm.propsSchema,
      events: editorForm.events,
      default_props: {},
    });
    ElMessage.success("编译成功，组件已导入");
    editorVisible.value = false;
    await load();
  } catch (error: any) {
    compileError.value = error?.message || "编译失败";
    compileErrorLine.value = Number(error?.data?.line) || 0;
    compileErrorMessage.value = compileError.value;
    ElMessage.error(compileError.value);
  } finally {
    compiling.value = false;
  }
}

onMounted(() => {
  loadCategories();
  load();
});
</script>

<style scoped>
.wp-comp-source {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  word-break: break-all;
}
.wp-comp-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.wp-comp-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.wp-code-editor :deep(textarea) {
  font-family: Consolas, "Courier New", monospace;
  font-size: 13px;
  line-height: 1.55;
}
.wp-comp-preview {
  min-height: 180px;
  padding: 16px;
  border: 1px dashed #dcdfe6;
  border-radius: 8px;
  background: #f7f8fa;
}
.wp-ai-draft {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 14px;
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fafafa;
}
.wp-ai-draft .el-textarea {
  flex: 1;
}
.wp-ai-draft .el-button {
  flex: none;
  margin-top: 1px;
}
</style>
