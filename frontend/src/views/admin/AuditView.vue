<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <h2>审计日志</h2>
    </div>

    <el-card>
      <el-form :model="filter" inline class="wp-audit-filter">
        <el-form-item label="动作">
          <el-select v-model="filter.action" clearable placeholder="全部" style="width: 140px">
            <el-option v-for="a in actions" :key="a" :label="a" :value="a" />
          </el-select>
        </el-form-item>
        <el-form-item label="用户 ID">
          <el-input-number v-model="filter.user_id" :min="1" controls-position="right" placeholder="可选" />
        </el-form-item>
        <el-form-item label="应用 ID">
          <el-input-number v-model="filter.app_id" :min="1" controls-position="right" placeholder="可选" />
        </el-form-item>
        <el-form-item label="开始">
          <el-date-picker v-model="filter.start" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" />
        </el-form-item>
        <el-form-item label="结束">
          <el-date-picker v-model="filter.end" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="reload">查询</el-button>
          <el-button @click="resetFilter">重置</el-button>
        </el-form-item>
      </el-form>

      <el-table :data="logs" v-loading="loading" border stripe>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="用户" width="130" />
        <el-table-column label="应用" width="90">
          <template #default="{ row }">{{ row.app_id ?? "—" }}</template>
        </el-table-column>
        <el-table-column prop="object_type" label="对象类型" width="120" />
        <el-table-column label="对象 ID" width="100">
          <template #default="{ row }">{{ row.object_id ?? "—" }}</template>
        </el-table-column>
        <el-table-column label="动作" width="100">
          <template #default="{ row }">
            <el-tag :type="actionType(row.action)" size="small">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="130" />
        <el-table-column label="变更内容" min-width="200">
          <template #default="{ row }">
            <el-popover placement="left" :width="480" trigger="click" v-if="row.before || row.after">
              <template #reference>
                <el-link type="primary" :underline="false">查看 before/after</el-link>
              </template>
              <div class="wp-diff">
                <h4>before</h4>
                <pre>{{ JSON.stringify(row.before, null, 2) }}</pre>
                <h4>after</h4>
                <pre>{{ JSON.stringify(row.after, null, 2) }}</pre>
              </div>
            </el-popover>
            <span v-else class="wp-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="暂无审计记录" :image-size="60" /></template>
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

    <el-drawer v-model="detailVisible" title="审计详情" size="680px">
      <template v-if="selectedLog">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="时间">{{ formatTime(selectedLog.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ selectedLog.username }}</el-descriptions-item>
          <el-descriptions-item label="动作">{{ selectedLog.action }}</el-descriptions-item>
          <el-descriptions-item label="应用">{{ selectedLog.app_id ?? "—" }}</el-descriptions-item>
          <el-descriptions-item label="对象类型">{{ selectedLog.object_type }}</el-descriptions-item>
          <el-descriptions-item label="对象 ID">{{ selectedLog.object_id ?? "—" }}</el-descriptions-item>
          <el-descriptions-item label="IP">{{ selectedLog.ip || "—" }}</el-descriptions-item>
          <el-descriptions-item label="用户 ID">{{ selectedLog.user_id ?? "—" }}</el-descriptions-item>
        </el-descriptions>
        <div class="wp-audit-json">
          <h4>before</h4>
          <pre>{{ JSON.stringify(selectedLog.before, null, 2) }}</pre>
          <h4>after</h4>
          <pre>{{ JSON.stringify(selectedLog.after, null, 2) }}</pre>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";
import type { AuditLogInfo } from "@/types";

const actions = [
  "user.create",
  "user.update",
  "user.delete",
  "component.create",
  "component.create_custom",
  "component.update",
  "component.delete",
  "component.upgrade",
  "release.create",
  "release.activate",
  "release.rollback",
  "release.traffic",
];

const loading = ref(false);
const logs = ref<AuditLogInfo[]>([]);
const total = ref(0);
const page = ref(1);
const size = ref(20);
const detailVisible = ref(false);
const selectedLog = ref<AuditLogInfo | null>(null);

function openDetail(row: AuditLogInfo) {
  selectedLog.value = row;
  detailVisible.value = true;
}

const filter = reactive({
  action: "" as string,
  user_id: undefined as number | undefined,
  app_id: undefined as number | undefined,
  start: "" as string,
  end: "" as string,
});

function actionType(action: string): "success" | "warning" | "danger" | "info" {
  const suffix = action.split(".").pop() || action;
  if (suffix === "create" || suffix === "activate" || suffix === "upgrade") return "success";
  if (suffix === "delete") return "danger";
  if (suffix === "update" || suffix === "rollback" || suffix === "traffic") return "warning";
  return "info";
}

async function load() {
  loading.value = true;
  try {
    const qs = new URLSearchParams({ page: String(page.value), size: String(size.value) });
    if (filter.action) qs.set("action", filter.action);
    if (filter.user_id) qs.set("user_id", String(filter.user_id));
    if (filter.app_id) qs.set("app_id", String(filter.app_id));
    if (filter.start) qs.set("start", filter.start);
    if (filter.end) qs.set("end", filter.end);
    const data = await api.get<unknown>(`/audit-logs/?${qs.toString()}`);
    if (Array.isArray(data)) {
      logs.value = data as AuditLogInfo[];
      total.value = data.length;
    } else {
      const p = data as { count: number; results: AuditLogInfo[] } | null;
      logs.value = p?.results ?? [];
      total.value = p?.count ?? 0;
    }
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "加载审计日志失败");
  } finally {
    loading.value = false;
  }
}

function reload() {
  page.value = 1;
  load();
}

function resetFilter() {
  filter.action = "";
  filter.user_id = undefined;
  filter.app_id = undefined;
  filter.start = "";
  filter.end = "";
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
.wp-audit-filter {
  margin-bottom: 12px;
  flex-wrap: wrap;
  row-gap: 8px;
}
.wp-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}
.wp-diff {
  display: flex;
  flex-direction: column;  gap: 4px;
}
.wp-diff h4 {
  margin: 4px 0;
  font-size: 12px;
}
.wp-diff pre {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  font-size: 12px;
  background: var(--el-fill-color-light);
  padding: 8px;
  border-radius: 4px;
}
.wp-muted {
  color: var(--el-text-color-placeholder);
}
.wp-audit-json {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 16px;
}
.wp-audit-json h4 {
  margin: 6px 0 2px;
  font-size: 12px;
}
.wp-audit-json pre {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  padding: 10px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
  font-size: 12px;
}
</style>
