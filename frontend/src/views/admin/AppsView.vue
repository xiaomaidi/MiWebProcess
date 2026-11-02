<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <h2>应用管理</h2>
      <div class="wp-page-actions">
        <el-button @click="autoBuildOpen = true">✨ 全自动建站</el-button>
        <el-button type="primary" @click="openCreate">新建应用</el-button>
      </div>
    </div>

    <el-card>
      <div class="wp-filter-bar">
        <el-input
          v-model="query"
          placeholder="按名称/标识搜索"
          clearable
          style="width: 240px"
          @keyup.enter="reload"
          @clear="reload"
        />
        <el-button @click="reload">查询</el-button>
      </div>

      <el-table :data="apps" v-loading="loading" border stripe>
        <el-table-column label="名称" min-width="160">
          <template #default="{ row }">
            <el-link type="primary" @click="goDetail(row)">{{ row.name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="code" label="标识" min-width="120" />
        <el-table-column prop="description" label="描述" min-width="220" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="goDetail(row)">详情</el-button>
            <el-button size="small" type="danger" plain @click="archive(row)">归档</el-button>
            <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无应用" :image-size="60" />
        </template>
      </el-table>

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
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";
import type { AppInfo } from "@/types";
import AutoBuildDialog from "./AutoBuildDialog.vue";

const router = useRouter();

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

onMounted(load);
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
</style>
