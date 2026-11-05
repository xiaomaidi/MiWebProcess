<template>
  <div class="wp-admin-page app-page">
    <div class="wp-page-header app-page-head">
      <div class="wp-page-title-block">
        <span class="app-eyebrow">WORKSPACE</span>
        <h2>应用管理</h2>
        <p class="wp-page-desc">创建、发布和运营你的业务应用。所有应用共享平台账号、数据和服务能力。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="autoBuildOpen = true">✨ 全自动建站</el-button>
        <el-button type="primary" @click="openCreate">新建应用</el-button>
      </div>
    </div>

    <div class="app-stats">
      <div class="app-stat">
        <span>应用总数</span>
        <strong>{{ total }}</strong>
        <small>当前账号可见</small>
      </div>
      <div class="app-stat">
        <span>已发布</span>
        <strong>{{ publishedCount }}</strong>
        <small>本页统计</small>
      </div>
      <div class="app-stat">
        <span>草稿</span>
        <strong>{{ draftCount }}</strong>
        <small>本页统计</small>
      </div>
      <div class="app-stat app-stat-accent">
        <span>平台状态</span>
        <strong>运行中</strong>
        <small>v1.0 · Local</small>
      </div>
    </div>

    <el-card shadow="never" class="app-list-card">
      <div class="app-toolbar">
        <div>
          <strong>我的应用</strong>
          <span class="app-toolbar-count">{{ total }} 个</span>
        </div>
        <div class="app-toolbar-actions">
          <el-input
            v-model="query"
            placeholder="按名称或标识搜索"
            clearable
            style="width: 260px"
            @keyup.enter="reload"
            @clear="reload"
          />
          <el-button @click="reload">查询</el-button>
        </div>
      </div>

      <div v-loading="loading" class="app-grid">
        <el-empty v-if="!loading && !apps.length" description="还没有应用，创建一个开始吧" :image-size="70" />
        <article v-for="(row, index) in apps" :key="row.id" class="app-card" @click="goDetail(row)">
          <div class="app-card-top">
            <div class="app-avatar" :style="{ background: appGradient(row, index) }">{{ appInitial(row) }}</div>
            <el-tag :type="statusType(row.status)" size="small" effect="light">{{ statusText(row.status) }}</el-tag>
          </div>
          <h3>{{ row.name }}</h3>
          <code>{{ row.code }}</code>
          <p>{{ row.description || "暂无描述" }}</p>
          <div class="app-card-meta">
            <span>创建于 {{ formatTime(row.created_at) }}</span>
            <span class="app-card-open">打开 →</span>
          </div>
          <div class="app-card-actions" @click.stop>
            <el-button size="small" type="primary" plain @click="goDetail(row)">进入应用</el-button>
            <el-button size="small" text @click="archive(row)">归档</el-button>
            <el-button size="small" text type="danger" @click="remove(row)">删除</el-button>
          </div>
        </article>
      </div>

      <div class="wp-pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="size"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="load"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="480px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" placeholder="应用名称" />
        </el-form-item>
        <el-form-item label="标识">
          <el-input v-model="form.code" :disabled="editingId !== null" placeholder="唯一标识，如 demo" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="应用描述（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <AutoBuildDialog v-model="autoBuildOpen" @created="onAutoBuilt" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";
import type { AppInfo } from "@/types";
import AutoBuildDialog from "./AutoBuildDialog.vue";

const router = useRouter();
const route = useRoute();

const loading = ref(false);
const saving = ref(false);
const autoBuildOpen = ref(false);
const apps = ref<AppInfo[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(10);
const query = ref("");

const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const form = reactive({ name: "", code: "", description: "" });
const dialogTitle = computed(() => (editingId.value === null ? "新建应用" : "编辑应用"));

function statusText(status: string) {
  const map: Record<string, string> = { published: "已发布", archived: "已归档", draft: "草稿" };
  return map[status] || status;
}
function statusType(status: string): "success" | "warning" | "info" {
  const map: Record<string, "success" | "warning" | "info"> = { published: "success", archived: "info", draft: "warning" };
  return map[status] || "info";
}

const publishedCount = computed(() => apps.value.filter((item) => item.status === "published").length);
const draftCount = computed(() => apps.value.filter((item) => item.status === "draft").length);

function appInitial(row: AppInfo) {
  return String(row.name || row.code || "A").slice(0, 1).toUpperCase();
}
function appGradient(row: AppInfo, index: number) {
  const palettes = [
    "linear-gradient(135deg, #2563eb, #38bdf8)",
    "linear-gradient(135deg, #7c3aed, #a78bfa)",
    "linear-gradient(135deg, #0d9488, #2dd4bf)",
    "linear-gradient(135deg, #ea580c, #fbbf24)",
  ];
  return palettes[(Number(row.id) || index) % palettes.length];
}

async function load() {
  loading.value = true;
  try {
    const qs = new URLSearchParams({ page: String(page.value), size: String(size.value), scope: "member" });
    if (query.value.trim()) qs.set("search", query.value.trim());
    const data = await api.get<PagedResponse<AppInfo>>(`/apps/?${qs.toString()}`);
    apps.value = data.results;
    total.value = data.count;
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载应用列表失败");
  } finally {
    loading.value = false;
  }
}

function reload() {
  page.value = 1;
  load();
}

function goDetail(row: AppInfo) {
  router.push(`/admin/apps/${row.id}`);
}

async function remove(row: AppInfo) {
  try {
    await ElMessageBox.prompt(
      `此操作会永久删除应用「${row.name}」及其页面、模型、数据和发布记录，且不可恢复。\n请输入应用编码 ${row.code} 确认：`,
      "删除应用",
      {
        type: "error",
        confirmButtonText: "永久删除",
        cancelButtonText: "取消",
        inputPlaceholder: row.code,
        inputValidator: (value: string) => value === row.code || "应用编码不匹配，未执行删除",
      }
    );
  } catch {
    return;
  }
  try {
    await api.del(`/apps/${row.id}/`);
    ElMessage.success("应用已删除");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.detail || error?.message || "删除失败");
  }
}

async function archive(row: AppInfo) {  if (row.status === "archived") return;
  try {
    await ElMessageBox.confirm(`确定归档应用「${row.name}」吗？`, "提示", { type: "warning" });
  } catch {
    return;
  }
  try {
    await api.post(`/apps/${row.id}/archive/`);
    ElMessage.success("已归档");
    load();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "归档失败");
  }
}

function openCreate() {
  editingId.value = null;
  form.name = "";
  form.code = "";
  form.description = "";
  dialogVisible.value = true;
}

async function save() {
  if (!form.name.trim() || !form.code.trim()) {
    ElMessage.warning("请填写名称和标识");
    return;
  }
  saving.value = true;
  try {
    const body = {
      name: form.name.trim(),
      code: form.code.trim(),
      description: form.description.trim() || null,
    };
    if (editingId.value === null) {
      const created = await api.post<AppInfo>("/apps/", body);
      ElMessage.success("应用已创建");
      dialogVisible.value = false;
      if (created && created.id) {
        router.push(`/admin/apps/${created.id}`);
        return;
      }
      load();
    } else {
      await api.put(`/apps/${editingId.value}/`, body);
      ElMessage.success("已保存");
      dialogVisible.value = false;
      load();
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "保存失败");
  } finally {
    saving.value = false;
  }
}

interface PagedResponse<T> {
  count: number;
  results: T[];
  page: number;
  size: number;
}

function onAutoBuilt() {
  reload();
}

onMounted(() => {
  if (route.query.invalid_app || route.query.invalid_page || route.query.invalid_id) {
    ElMessage.warning("链接中的应用或页面 ID 无效，已返回应用列表");
    router.replace({ path: "/admin/apps" });
  }
  load();
});
</script>

<style scoped>
.wp-page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.wp-page-header h2 {
  margin: 0;
  font-size: 18px;
}
.wp-filter-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.wp-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.app-page-head { align-items: flex-start; }
.app-eyebrow { display: inline-block; margin-bottom: 7px; color: #2563eb; font-size: 10px; font-weight: 700; letter-spacing: 1.8px; }
.app-page-head h2 { margin: 0 0 6px; font-size: 28px; letter-spacing: -0.5px; }
.app-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 16px; }
.app-stat { display: flex; flex-direction: column; gap: 3px; padding: 16px 18px; border: 1px solid #e8edf5; border-radius: 12px; background: #fff; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03); }
.app-stat span { color: #64748b; font-size: 11px; }
.app-stat strong { color: #0f172a; font-size: 24px; line-height: 1.2; }
.app-stat small { color: #94a3b8; font-size: 10px; }
.app-stat-accent { background: linear-gradient(135deg, #eff6ff, #f8fafc); border-color: #dbeafe; }
.app-stat-accent strong { color: #2563eb; font-size: 18px; }
.app-list-card { border-radius: 14px; }
.app-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.app-toolbar strong { color: #0f172a; font-size: 14px; }
.app-toolbar-count { margin-left: 7px; color: #94a3b8; font-size: 11px; }
.app-toolbar-actions { display: flex; gap: 8px; }
.app-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; min-height: 180px; }
.app-card { display: flex; flex-direction: column; min-height: 210px; padding: 17px; border: 1px solid #e8edf5; border-radius: 13px; background: #fff; cursor: pointer; transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease; }
.app-card:hover { transform: translateY(-2px); border-color: #bfdbfe; box-shadow: 0 12px 28px rgba(37, 99, 235, 0.1); }
.app-card-top { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 13px; }
.app-avatar { display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; border-radius: 12px; color: #fff; font-size: 17px; font-weight: 800; }
.app-card h3 { margin: 0 0 4px; color: #0f172a; font-size: 15px; }
.app-card code { width: fit-content; padding: 1px 6px; border-radius: 4px; background: #f1f5f9; color: #64748b; font-size: 10px; }
.app-card p { flex: 1; margin: 10px 0 12px; color: #64748b; font-size: 12px; line-height: 1.6; display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.app-card-meta { display: flex; align-items: center; justify-content: space-between; color: #94a3b8; font-size: 10px; }
.app-card-open { color: #2563eb; font-weight: 600; }
.app-card-actions { display: flex; gap: 2px; margin-top: 12px; padding-top: 10px; border-top: 1px solid #f1f5f9; }
.app-card-actions :deep(.el-button) { margin-left: 0; }
@media (max-width: 1200px) { .app-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .app-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 700px) { .app-grid { grid-template-columns: 1fr; } .app-stats { grid-template-columns: 1fr; } .app-toolbar { align-items: flex-start; flex-direction: column; } .app-toolbar-actions { width: 100%; } .app-toolbar-actions :deep(.el-input) { flex: 1; width: auto !important; } }
</style>
