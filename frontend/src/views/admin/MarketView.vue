<template>
  <div class="wp-admin-page market-page" v-loading="loading">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <span class="market-eyebrow">ENTERPRISE MARKET</span>
        <h2>组件与区块市场</h2>
        <p class="wp-page-desc">复用企业内沉淀的组件和页面区块，一键安装到目标应用。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="createOpen = true">发布到市场</el-button>
      </div>
    </div>

    <div class="market-toolbar">
      <el-radio-group v-model="kind" @change="load">
        <el-radio-button value="">全部</el-radio-button>
        <el-radio-button value="block">区块</el-radio-button>
        <el-radio-button value="component">组件</el-radio-button>
      </el-radio-group>
      <el-input v-model="query" clearable placeholder="搜索组件 / 区块" style="width: 260px" @keyup.enter="load" @clear="load" />
      <el-select v-model="category" clearable placeholder="全部分类" style="width: 160px" @change="load">
        <el-option v-for="item in categories" :key="`${item.kind}-${item.category}`" :label="item.category" :value="item.category" />
      </el-select>
      <el-select v-model="targetApp" placeholder="安装到应用" style="width: 220px">
        <el-option v-for="app in apps" :key="app.id" :label="app.name" :value="app.id" />
      </el-select>
    </div>

    <div class="market-grid">
      <article v-for="item in items" :key="item.id" class="market-card">
        <div class="market-card-head">
          <div>
            <div class="market-kind-row">
              <el-tag size="small" :type="item.kind === 'block' ? 'primary' : 'success'">{{ item.kind === "block" ? "区块" : "组件" }}</el-tag>
              <el-tag v-if="item.kind === 'component'" size="small" :type="item.sandboxed ? 'warning' : 'info'" effect="plain">
                {{ item.sandboxed ? "沙箱" : "非沙箱" }}
              </el-tag>
              <el-tag
                v-if="item.kind === 'component'"
                size="small"
                :type="item.signature_valid ? 'success' : 'danger'"
                effect="plain"
              >
                {{ item.signature_valid ? "已签名" : item.signature ? "签名失效" : "未签名" }}
              </el-tag>
            </div>
            <h3>{{ item.name }}</h3>
            <code>{{ item.slug }}</code>
          </div>
          <span class="market-installs">{{ item.installs }} 次安装</span>
        </div>
        <p>{{ item.description || "暂无描述" }}</p>
        <div v-if="item.kind === 'component'" class="market-sign-row">
          <template v-if="item.signature">
            <span class="market-sign-hash" :title="item.code_hash">#{{ shortHash(item.code_hash) }}</span>
            <span v-if="item.signer">· {{ item.signer }}</span>
            <span v-if="item.signed_at">· {{ formatDateTime(item.signed_at) }}</span>
          </template>
          <span v-else class="market-sign-missing">安装前需由创建者签名</span>
          <span v-if="item.signature && !item.signature_valid" class="market-sign-invalid">{{ item.signature_error }}</span>
        </div>
        <div class="market-card-tags">
          <el-tag v-for="tag in item.tags || []" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
        </div>
        <div class="market-card-foot">
          <span>{{ item.created_by || "平台" }} · {{ format(item.updated_at) }}</span>
          <div class="market-card-actions">
            <el-button v-if="item.kind === 'component'" size="small" text @click="openPreview(item)">预览</el-button>
            <el-button
              v-if="canSign(item)"
              size="small"
              text
              :loading="signingId === item.id"
              @click="signItem(item)"
            >{{ item.signature ? "重签" : "签名" }}</el-button>
            <el-button
              size="small"
              :type="item.kind === 'block' ? 'default' : 'primary'"
              plain
              :disabled="!targetApp || !canInstall(item)"
              @click="install(item)"
            >安装</el-button>
            <el-button v-if="item.created_by === auth.displayName || auth.isAdmin" size="small" text @click="publish(item)">发布</el-button>
          </div>
        </div>
      </article>
      <el-empty v-if="!loading && !items.length" description="市场暂无可安装内容" :image-size="60" />
    </div>

    <el-dialog
      v-model="previewOpen"
      :title="previewItem ? `沙箱预览 · ${previewItem.name}` : '沙箱预览'"
      width="880px"
      destroy-on-close
    >
      <div v-if="previewItem" class="market-preview">
        <div class="market-preview-meta">
          <el-tag size="small" type="warning" effect="plain">sandbox="allow-scripts"</el-tag>
          <code>{{ previewSource || "未配置 source_url" }}</code>
        </div>
        <SandboxedComponent
          v-if="previewSource"
          :source-url="previewSource"
          :element="previewElement"
          :component-props="previewProps"
          :events="previewEvents"
          :policy="previewPolicy"
          :min-height="320"
          @event="onPreviewComponentEvent"
        />
        <el-empty v-else description="该组件没有 source_url，无法预览" :image-size="60" />
        <p class="market-preview-hint">
          远端 ESM 仅在无 same-origin 的 iframe 中执行；父页面不会 import 或 eval 组件代码。
          组件通过 postMessage 接收 props，事件从沙箱回传。
        </p>
      </div>
    </el-dialog>

    <el-dialog v-model="createOpen" title="发布到市场" width="560px">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="名称"><el-input v-model="form.name" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="Slug"><el-input v-model="form.slug" placeholder="my-block" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="类型">
              <el-select v-model="form.kind" style="width:100%"><el-option label="区块" value="block" /><el-option label="组件" value="component" /></el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="分类"><el-input v-model="form.category" /></el-form-item></el-col>
        </el-row>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <template v-if="form.kind === 'component'">
          <el-alert
            title="组件将在 sandbox=&quot;allow-scripts&quot; 的 iframe 中运行；发布后需点击“签名”，只有签名且未被篡改的组件可以安装。"
            type="warning"
            :closable="false"
            show-icon
            class="market-form-alert"
          />
          <el-row :gutter="12">
            <el-col :span="14">
              <el-form-item label="source_url（已构建 ESM JS）">
                <el-input v-model="form.sourceUrl" placeholder="/media/custom-components/hello/1.0.0/index.js" />
              </el-form-item>
            </el-col>
            <el-col :span="10">
              <el-form-item label="custom element（可选）">
                <el-input v-model="form.element" placeholder="wp-widget-hello" />
              </el-form-item>
            </el-col>
          </el-row>
        </template>
        <el-form-item label="Payload JSON">
          <el-input v-model="form.payloadText" type="textarea" :rows="7" placeholder='区块：{"rootId":"root","nodes":{...}}；组件：{"label":"...","props_schema":{...}}' />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status"><el-radio value="draft">草稿</el-radio><el-radio value="published">直接发布</el-radio></el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createItem">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { useAuthStore } from "@/store/auth";
import SandboxedComponent from "@/components/market/SandboxedComponent.vue";

const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);
const signingId = ref<number | null>(null);
const kind = ref("");
const category = ref("");
const query = ref("");
const createOpen = ref(false);
const previewOpen = ref(false);
const previewItem = ref<any | null>(null);
const items = ref<any[]>([]);
const categories = ref<any[]>([]);
const apps = ref<any[]>([]);
const targetApp = ref<number | null>(null);
const form = reactive({
  name: "", slug: "", kind: "block", category: "", description: "", status: "published",
  sourceUrl: "", element: "", payloadText: "{}",
});

const previewSource = computed(() => String(previewItem.value?.payload?.source_url || ""));
const previewElement = computed(() => {
  const item = previewItem.value;
  if (!item) return "";
  const explicit = String(item.payload?.element || "").trim();
  if (explicit) return explicit;
  return `wp-market-${String(item.slug || "component")}`
    .toLowerCase()
    .replace(/[^a-z0-9-]/g, "-")
    .split("-")
    .filter(Boolean)
    .join("-");
});
const previewProps = computed(() => {
  const value = previewItem.value?.payload?.default_props;
  return value && typeof value === "object" ? value : {};
});
const previewEvents = computed(() => {
  const value = previewItem.value?.payload?.events;
  return Array.isArray(value) ? value.map(String) : [];
});
const previewPolicy = computed(() => {
  const value = previewItem.value?.policy;
  return value && typeof value === "object" ? value : {};
});

async function load() {
  loading.value = true;
  try {
    const params = new URLSearchParams();
    if (kind.value) params.set("kind", kind.value);
    if (category.value) params.set("category", category.value);
    if (query.value.trim()) params.set("q", query.value.trim());
    const [list, cats] = await Promise.all([
      api.get<any>(`/market/items/?${params.toString()}`),
      api.get<any>("/market/categories/"),
    ]);
    items.value = list.results || [];
    categories.value = cats.results || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "市场加载失败");
  } finally { loading.value = false; }
}
async function loadApps() {
  try {
    const data = await api.get<any>("/apps/?size=100");
    apps.value = data.results || data || [];
    if (!targetApp.value && apps.value[0]) targetApp.value = apps.value[0].id;
  } catch { apps.value = []; }
}
function errorText(e: any, fallback: string): string {
  const data = e?.data;
  if (data && typeof data === "object") {
    const signature = data.signature;
    if (Array.isArray(signature) && signature.length) return String(signature[0]);
    if (typeof signature === "string") return signature;
    if (typeof data.detail === "string") return data.detail;
    for (const value of Object.values(data)) {
      if (Array.isArray(value) && value.length) return String(value[0]);
      if (typeof value === "string") return value;
    }
  }
  return e?.message || fallback;
}
function canSign(item: any): boolean {
  return item.kind === "component" && (item.created_by === auth.displayName || auth.isAdmin);
}
function canInstall(item: any): boolean {
  return item.kind !== "component" || item.signature_valid === true;
}
async function signItem(item: any) {
  signingId.value = item.id;
  try {
    const result = await api.post<any>(`/market/items/${item.id}/sign/`, {}, { silent: true });
    ElMessage.success(`已签名：${shortHash(result.code_hash)}`);
    await load();
  } catch (e: any) {
    ElMessage.error(errorText(e, "签名失败"));
  } finally { signingId.value = null; }
}
async function install(item: any) {
  if (!targetApp.value) { ElMessage.warning("请选择目标应用"); return; }
  if (!canInstall(item)) { ElMessage.warning("组件必须签名且未篡改后才能安装"); return; }
  try {
    const result = await api.post<any>(`/market/items/${item.id}/install/`, { app_id: targetApp.value }, { silent: true });
    ElMessage.success(result.kind === "block" ? `区块已安装：${result.code}` : `组件已安装：${result.component}`);
    await load();
  } catch (e: any) { ElMessage.error(errorText(e, "安装失败")); }
}
async function publish(item: any) {
  await api.patch(`/market/items/${item.id}/`, { status: "published", visibility: "public" });
  await load();
  ElMessage.success(item.kind === "component" ? "已发布到市场，请补签名后安装" : "已发布到市场");
}
async function createItem() {
  let payload: any;
  try { payload = JSON.parse(form.payloadText); } catch { ElMessage.error("Payload JSON 格式不正确"); return; }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    ElMessage.error("Payload 必须是 JSON 对象");
    return;
  }
  if (form.kind === "component") {
    const sourceUrl = form.sourceUrl.trim() || String(payload.source_url || "").trim();
    if (!sourceUrl) { ElMessage.warning("组件必须填写 source_url（已构建的 ESM JS 地址）"); return; }
    payload.source_url = sourceUrl;
    const element = form.element.trim() || String(payload.element || "").trim();
    if (element) payload.element = element;
  }
  saving.value = true;
  try {
    await api.post("/market/items/", {
      name: form.name, slug: form.slug, kind: form.kind, category: form.category,
      description: form.description, payload, status: form.status, visibility: "public",
    });
    createOpen.value = false;
    await load();
    ElMessage.success(form.kind === "component" ? "组件已保存，请点击“签名”后安装" : "已保存到市场");
  } catch (e: any) { ElMessage.error(errorText(e, "保存失败")); }
  finally { saving.value = false; }
}
function openPreview(item: any) {
  previewItem.value = item;
  previewOpen.value = true;
}
function onPreviewComponentEvent() {
  // 预览仅用于视觉确认；真实页面的事件应通过动作流接收，不在管理页消费。
}
function shortHash(hash: string): string {
  return (hash || "").slice(0, 12);
}
function format(value: string) { return value ? new Date(value).toLocaleDateString() : ""; }
function formatDateTime(value: string) { return value ? new Date(value).toLocaleString() : ""; }
onMounted(async () => { await Promise.all([load(), loadApps()]); });
</script>

<style scoped>
.market-eyebrow { display:inline-block; margin-bottom:7px; color:#2563eb; font-size:10px; font-weight:700; letter-spacing:1.8px; }
.market-toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:16px; }
.market-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.market-card { display:flex; flex-direction:column; min-height:190px; padding:16px; border:1px solid #e8edf5; border-radius:13px; background:#fff; }
.market-card-head { display:flex; justify-content:space-between; gap:8px; }
.market-card-head h3 { margin:8px 0 2px; color:#0f172a; font-size:14px; }
.market-card-head code { color:#94a3b8; font-size:9px; }
.market-kind-row { display:flex; flex-wrap:wrap; gap:4px; align-items:center; }
.market-installs { color:#94a3b8; font-size:10px; white-space:nowrap; }
.market-sign-row { display:flex; flex-wrap:wrap; gap:4px; align-items:center; margin:-2px 0 8px; color:#64748b; font-size:9px; }
.market-sign-hash { padding:1px 5px; border-radius:5px; background:#f1f5f9; color:#475569; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
.market-sign-missing { color:#b45309; }
.market-sign-invalid { width:100%; color:#dc2626; }
.market-card-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:2px; }
.market-form-alert { margin-bottom:12px; }
.market-preview-meta { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:10px; color:#64748b; font-size:11px; }
.market-preview-meta code { word-break:break-all; }
.market-preview-hint { margin:10px 0 0; color:#94a3b8; font-size:10px; line-height:1.6; }
.market-card p { flex:1; margin:10px 0; color:#64748b; font-size:11px; line-height:1.6; }
.market-card-tags { display:flex; flex-wrap:wrap; gap:4px; min-height:20px; }
.market-card-foot { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:12px; padding-top:10px; border-top:1px solid #f1f5f9; color:#94a3b8; font-size:9px; }
@media (max-width:1100px){ .market-grid{grid-template-columns:repeat(2,minmax(0,1fr));} }
@media (max-width:700px){ .market-grid{grid-template-columns:1fr;} }
</style>
