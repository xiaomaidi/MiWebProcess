<template>
  <div class="wp-admin-page enterprise-page" v-loading="loading">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <span class="ent-eyebrow">ENTERPRISE OPERATIONS</span>
        <h2>企业运维控制台</h2>
        <p class="wp-page-desc">平台健康、数据规模、任务与 Webhook 失败、审计动态与数据库备份。</p>
      </div>
      <div class="wp-page-actions">
        <el-tag v-if="overview" :type="overallType" effect="plain">{{ overallText }}</el-tag>
        <el-button :loading="loading" @click="loadAll">刷新</el-button>
        <el-button type="primary" :loading="backingUp" @click="createBackup">创建备份</el-button>
      </div>
    </div>

    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />

    <div v-if="overview" class="ent-health-grid">
      <div v-for="item in healthItems" :key="item.key" class="ent-health-card" :class="`is-${item.status}`">
        <div class="ent-health-top">
          <span>{{ item.label }}</span>
          <i class="ent-dot" />
        </div>
        <strong>{{ item.statusText }}</strong>
        <small>{{ item.detail }}</small>
      </div>
    </div>

    <div v-if="overview" class="ent-kpi-grid">
      <div class="ent-kpi"><span>应用</span><strong>{{ overview.apps.total }}</strong><small>已发布 {{ overview.apps.by_status?.published || 0 }}</small></div>
      <div class="ent-kpi"><span>用户</span><strong>{{ overview.users.total }}</strong><small>活跃 {{ overview.users.active }}</small></div>
      <div class="ent-kpi"><span>数据记录</span><strong>{{ overview.data.records }}</strong><small>{{ overview.data.models }} 个模型</small></div>
      <div class="ent-kpi"><span>存储</span><strong>{{ bytesText(overview.storage.total_bytes) }}</strong><small>数据库 {{ overview.storage.database_human || "—" }}</small></div>
      <div class="ent-kpi"><span>24h 审计</span><strong>{{ overview.audit.last_24h }}</strong><small>累计 {{ overview.audit.total }}</small></div>
      <div class="ent-kpi"><span>失败任务</span><strong>{{ overview.jobs.failed + overview.webhooks.failed_deliveries }}</strong><small>定时任务 / Webhook</small></div>
    </div>

    <div v-if="overview" class="ent-columns">
      <el-card shadow="never" class="ent-card">
        <template #header><div class="ent-card-head"><strong>最近审计</strong><span>最新 10 条</span></div></template>
        <el-table :data="overview.audit.recent || []" size="small" border>
          <el-table-column prop="created_at" label="时间" width="155" />
          <el-table-column prop="action" label="动作" width="150" />
          <el-table-column prop="username" label="用户" width="100" />
          <el-table-column prop="object_type" label="对象" min-width="120" />
        </el-table>
        <el-empty v-if="!(overview.audit.recent || []).length" description="暂无审计记录" :image-size="48" />
      </el-card>

      <el-card shadow="never" class="ent-card">
        <template #header><div class="ent-card-head"><strong>运行风险</strong><span>任务 / Webhook</span></div></template>
        <div class="ent-risk-row"><span>定时任务失败</span><el-tag :type="overview.jobs.failed ? 'danger' : 'success'" size="small">{{ overview.jobs.failed }}</el-tag></div>
        <div class="ent-risk-row"><span>Webhook 失败投递</span><el-tag :type="overview.webhooks.failed_deliveries ? 'danger' : 'success'" size="small">{{ overview.webhooks.failed_deliveries }}</el-tag></div>
        <div class="ent-risk-row"><span>失败通知</span><el-tag :type="overview.notifications.failed ? 'warning' : 'success'" size="small">{{ overview.notifications.failed }}</el-tag></div>
        <div class="ent-risk-row"><span>发布失败</span><el-tag :type="overview.releases.failed ? 'danger' : 'success'" size="small">{{ overview.releases.failed }}</el-tag></div>
        <el-divider />
        <div class="ent-backup-line">
          <div><strong>数据库备份</strong><small>{{ overview.backups.count }} 个 · {{ overview.backups.total_human || "—" }}</small></div>
          <el-switch v-model="includeMedia" active-text="含媒体" />
        </div>
      </el-card>
    </div>

    <el-card v-if="overview" shadow="never" class="ent-card ent-backups">
      <template #header><div class="ent-card-head"><strong>备份记录</strong><span>{{ backups.directory?.name || "backup" }}</span></div></template>
      <el-table :data="backups.items || []" size="small" border>
        <el-table-column prop="name" label="文件" min-width="260" show-overflow-tooltip />
        <el-table-column prop="size_human" label="大小" width="100" />
        <el-table-column prop="created_at" label="时间" width="170" />
      </el-table>
      <el-empty v-if="!(backups.items || []).length" description="暂无备份" :image-size="48" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const loading = ref(false);
const backingUp = ref(false);
const includeMedia = ref(false);
const error = ref("");
const overview = ref<any>(null);
const backups = ref<any>({ items: [] });

const healthItems = computed(() => {
  const health = overview.value?.health || {};
  return [
    { key: "database", label: "数据库", ...health.database, statusText: statusText(health.database?.status) },
    { key: "cache", label: "缓存", ...health.cache, statusText: statusText(health.cache?.status) },
    { key: "celery", label: "Celery / Broker", ...health.celery_broker, statusText: statusText(health.celery_broker?.status) },
  ];
});
const overallType = computed(() => {
  const value = overview.value?.health?.overall?.status;
  return value === "ok" ? "success" : value === "degraded" ? "warning" : "danger";
});
const overallText = computed(() => (overallType.value === "success" ? "运行正常" : overallType.value === "warning" ? "部分降级" : "存在异常"));

function statusText(value?: string) {
  return ({ ok: "正常", degraded: "降级", error: "异常", unknown: "未知", not_configured: "未配置" } as Record<string, string>)[String(value || "")] || "未知";
}
function bytesText(value: number) {
  const n = Number(value || 0);
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let index = 0;
  let size = n;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
}

async function loadOverview() {
  overview.value = await api.get<any>("/enterprise/overview/");
}
async function loadBackups() {
  backups.value = await api.get<any>("/enterprise/backups/");
}
async function loadAll() {
  loading.value = true;
  error.value = "";
  try {
    await Promise.all([loadOverview(), loadBackups()]);
  } catch (e: any) {
    error.value = e?.detail || e?.message || "企业运维数据加载失败";
  } finally {
    loading.value = false;
  }
}
async function createBackup() {
  backingUp.value = true;
  try {
    const result = await api.post<any>("/enterprise/backups/", { include_media: includeMedia.value });
    ElMessage.success(result.message || "备份创建成功");
    await loadAll();
  } catch (e: any) {
    ElMessage.error(e?.detail || e?.message || "备份失败");
  } finally {
    backingUp.value = false;
  }
}

onMounted(loadAll);
</script>

<style scoped>
.ent-eyebrow { display: inline-block; margin-bottom: 7px; color: #2563eb; font-size: 10px; font-weight: 700; letter-spacing: 1.8px; }
.ent-health-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.ent-health-card { padding: 14px 16px; border: 1px solid #e8edf5; border-radius: 12px; background: #fff; }
.ent-health-top { display: flex; justify-content: space-between; align-items: center; color: #64748b; font-size: 11px; }
.ent-health-card strong { display: block; margin: 6px 0 2px; color: #0f172a; font-size: 17px; }
.ent-health-card small { color: #94a3b8; font-size: 10px; }
.ent-dot { width: 8px; height: 8px; border-radius: 50%; background: #22c55e; }
.ent-health-card.is-degraded .ent-dot { background: #f59e0b; }
.ent-health-card.is-error .ent-dot { background: #ef4444; }
.ent-health-card.is-not_configured .ent-dot { background: #94a3b8; }
.ent-kpi-grid { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.ent-kpi { padding: 13px 14px; border: 1px solid #e8edf5; border-radius: 12px; background: #fff; }
.ent-kpi span { color: #64748b; font-size: 10px; }
.ent-kpi strong { display: block; margin: 4px 0 2px; color: #0f172a; font-size: 20px; }
.ent-kpi small { color: #94a3b8; font-size: 9px; }
.ent-columns { display: grid; grid-template-columns: 1.35fr 1fr; gap: 14px; margin-bottom: 14px; }
.ent-card { border-radius: 14px; border-color: #e8edf5; }
.ent-card-head { display: flex; justify-content: space-between; align-items: center; }
.ent-card-head strong { color: #0f172a; font-size: 13px; }
.ent-card-head span { color: #94a3b8; font-size: 10px; }
.ent-risk-row { display: flex; align-items: center; justify-content: space-between; padding: 8px 0; color: #475569; font-size: 12px; border-bottom: 1px solid #f1f5f9; }
.ent-backup-line { display: flex; align-items: center; justify-content: space-between; }
.ent-backup-line div { display: flex; flex-direction: column; gap: 2px; }
.ent-backup-line strong { font-size: 12px; }
.ent-backup-line small { color: #94a3b8; font-size: 10px; }
@media (max-width: 1100px) { .ent-kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .ent-columns { grid-template-columns: 1fr; } }
@media (max-width: 700px) { .ent-health-grid, .ent-kpi-grid { grid-template-columns: 1fr; } }
</style>
