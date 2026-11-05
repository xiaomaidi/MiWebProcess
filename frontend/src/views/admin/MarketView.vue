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
            <el-tag size="small" :type="item.kind === 'block' ? 'primary' : 'success'">{{ item.kind === "block" ? "区块" : "组件" }}</el-tag>
            <h3>{{ item.name }}</h3>
            <code>{{ item.slug }}</code>
          </div>
          <span class="market-installs">{{ item.installs }} 次安装</span>
        </div>
        <p>{{ item.description || "暂无描述" }}</p>
        <div class="market-card-tags">
          <el-tag v-for="tag in item.tags || []" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
        </div>
        <div class="market-card-foot">
          <span>{{ item.created_by || "平台" }} · {{ format(item.updated_at) }}</span>
          <div>
            <el-button size="small" :disabled="!targetApp" @click="install(item)">安装</el-button>
            <el-button v-if="item.created_by === auth.displayName || auth.isAdmin" size="small" text @click="publish(item)">发布</el-button>
          </div>
        </div>
      </article>
      <el-empty v-if="!loading && !items.length" description="市场暂无可安装内容" :image-size="60" />
    </div>

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
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { useAuthStore } from "@/store/auth";

const auth = useAuthStore();
const loading = ref(false);
const saving = ref(false);
const kind = ref("");
const category = ref("");
const query = ref("");
const createOpen = ref(false);
const items = ref<any[]>([]);
const categories = ref<any[]>([]);
const apps = ref<any[]>([]);
const targetApp = ref<number | null>(null);
const form = reactive({ name: "", slug: "", kind: "block", category: "", description: "", status: "published", payloadText: "{}" });

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
async function install(item: any) {
  if (!targetApp.value) { ElMessage.warning("请选择目标应用"); return; }
  try {
    const result = await api.post<any>(`/market/items/${item.id}/install/`, { app_id: targetApp.value });
    ElMessage.success(result.kind === "block" ? `区块已安装：${result.code}` : `组件已安装：${result.component}`);
    await load();
  } catch (e: any) { ElMessage.error(e?.detail || e?.message || "安装失败"); }
}
async function publish(item: any) {
  await api.patch(`/market/items/${item.id}/`, { status: "published", visibility: "public" });
  await load();
  ElMessage.success("已发布到市场");
}
async function createItem() {
  let payload: any;
  try { payload = JSON.parse(form.payloadText); } catch { ElMessage.error("Payload JSON 格式不正确"); return; }
  saving.value = true;
  try {
    await api.post("/market/items/", {
      name: form.name, slug: form.slug, kind: form.kind, category: form.category,
      description: form.description, payload, status: form.status, visibility: "public",
    });
    createOpen.value = false;
    await load();
    ElMessage.success("已保存到市场");
  } catch (e: any) { ElMessage.error(e?.detail || e?.message || "保存失败"); }
  finally { saving.value = false; }
}
function format(value: string) { return value ? new Date(value).toLocaleDateString() : ""; }
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
.market-installs { color:#94a3b8; font-size:10px; white-space:nowrap; }
.market-card p { flex:1; margin:10px 0; color:#64748b; font-size:11px; line-height:1.6; }
.market-card-tags { display:flex; flex-wrap:wrap; gap:4px; min-height:20px; }
.market-card-foot { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:12px; padding-top:10px; border-top:1px solid #f1f5f9; color:#94a3b8; font-size:9px; }
@media (max-width:1100px){ .market-grid{grid-template-columns:repeat(2,minmax(0,1fr));} }
@media (max-width:700px){ .market-grid{grid-template-columns:1fr;} }
</style>
