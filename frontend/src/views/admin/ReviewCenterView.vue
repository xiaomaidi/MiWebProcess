<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>内容审核</h2>
        <p class="wp-page-desc">编辑保存内容后自动进入待审；审核通过后自动发布并写入搜索索引。驳回需填写原因。</p>
      </div>
      <div class="wp-page-actions">
        <el-select v-model="appId" placeholder="选择应用" style="width: 220px" @change="loadAll">
          <el-option v-for="app in apps" :key="app.id" :label="app.name" :value="app.id" />
        </el-select>
        <el-button @click="loadAll">刷新</el-button>
      </div>
    </div>

    <el-row :gutter="12" class="wp-review-stats">
      <el-col :span="6" v-for="card in statCards" :key="card.key">
        <el-card shadow="never" class="wp-stat" :class="`is-${card.key}`">
          <div class="wp-stat-value">{{ counts[card.key] || 0 }}</div>
          <div class="wp-stat-label">{{ card.label }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <div class="wp-tab-toolbar">
        <el-radio-group v-model="statusFilter" @change="loadReviews">
          <el-radio-button value="pending">待审核</el-radio-button>
          <el-radio-button value="approved">已通过</el-radio-button>
          <el-radio-button value="rejected">已驳回</el-radio-button>
          <el-radio-button value="">全部</el-radio-button>
        </el-radio-group>
        <el-input v-model="keyword" placeholder="搜索标题 / 模型" clearable style="width: 220px" @change="loadReviews" />
        <el-checkbox v-model="onlyMine" @change="loadReviews">只看我提交的</el-checkbox>
        <el-button v-if="selected.length" type="success" plain size="small" @click="batchApprove">批量通过（{{ selected.length }}）</el-button>
      </div>

      <el-table :data="reviews" v-loading="loading" border stripe @selection-change="onSelectionChange">
        <el-table-column type="selection" width="44" :selectable="(row: any) => row.status === 'pending' && row.can_approve" />
        <el-table-column label="标题" min-width="220">
          <template #default="{ row }">
            <a class="wp-review-title" @click="openDetail(row)">{{ row.title || `记录 #${row.record_id}` }}</a>
            <el-tag size="small" effect="plain" style="margin-left: 6px">v{{ row.revision }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="model_name" label="模型" width="120" />
        <el-table-column label="提交人" width="120">
          <template #default="{ row }">{{ row.submitted_by_name || "—" }}</template>
        </el-table-column>
        <el-table-column label="提交时间" width="160">
          <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openDetail(row)">查看</el-button>
            <el-button v-if="row.can_approve" size="small" type="success" @click="approve(row)">通过</el-button>
            <el-button v-if="row.can_approve" size="small" type="danger" plain @click="reject(row)">驳回</el-button>
            <el-button v-if="row.can_withdraw" size="small" plain @click="withdraw(row)">撤回</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="appId ? '当前筛选下没有审核单' : '请选择应用'" :image-size="70" />
        </template>
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" size="640px" :title="detail?.title || '审核详情'">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="模型">{{ detail.model_name }}</el-descriptions-item>
          <el-descriptions-item label="记录">#{{ detail.record_id }}</el-descriptions-item>
          <el-descriptions-item label="提交人">{{ detail.submitted_by_name || "—" }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">{{ formatTime(detail.submitted_at) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag size="small" :type="statusType(detail.status)">{{ detail.status_label }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="审核人">{{ detail.reviewed_by_name || "—" }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="wp-review-section">内容预览</h4>
        <el-table :data="dataRows" size="small" border>
          <el-table-column prop="key" label="字段" width="140" />
          <el-table-column prop="value" label="值" />
        </el-table>

        <h4 class="wp-review-section">审核意见</h4>
        <el-input v-model="comment" type="textarea" :rows="3" placeholder="通过可选填；驳回必须填写原因" />
        <div class="wp-review-actions" v-if="detail.status === 'pending' && detail.can_approve">
          <el-button type="success" :loading="acting" @click="approve(detail)">通过并发布</el-button>
          <el-button type="danger" :loading="acting" @click="reject(detail)">驳回</el-button>
        </div>

        <h4 class="wp-review-section">流转记录</h4>
        <el-timeline>
          <el-timeline-item
            v-for="event in detail.events || []"
            :key="event.id"
            :timestamp="formatTime(event.created_at)"
            :type="event.to_status === 'approved' ? 'success' : event.to_status === 'rejected' ? 'danger' : 'primary'"
          >
            <strong>{{ actionText(event.action) }}</strong>
            <span class="wp-muted"> · {{ event.actor || "system" }}</span>
            <div v-if="event.comment" class="wp-review-comment">{{ event.comment }}</div>
          </el-timeline-item>
        </el-timeline>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";

const route = useRoute();

interface ReviewRow {
  id: number;
  app_id: number;
  model_id: number;
  model_name: string;
  record_id: number;
  title: string;
  status: string;
  status_label: string;
  revision: number;
  submitted_by_name: string;
  submitted_at: string;
  reviewed_by_name: string;
  reviewed_at: string;
  comment: string;
  can_approve: boolean;
  can_withdraw: boolean;
  record_data: Record<string, any>;
  events?: any[];
}

const apps = ref<any[]>([]);
const appId = ref<number | null>(null);
const statusFilter = ref("pending");
const keyword = ref("");
const onlyMine = ref(false);
const reviews = ref<ReviewRow[]>([]);
const counts = ref<Record<string, number>>({ pending: 0, approved: 0, rejected: 0, cancelled: 0 });
const loading = ref(false);
const acting = ref(false);
const selected = ref<ReviewRow[]>([]);
const drawer = ref(false);
const detail = ref<ReviewRow | null>(null);
const comment = ref("");

const statCards = [
  { key: "pending", label: "待审核" },
  { key: "approved", label: "已通过" },
  { key: "rejected", label: "已驳回" },
  { key: "total", label: "可见总量" },
];

const dataRows = computed(() => {
  const data = detail.value?.record_data || {};
  return Object.entries(data).map(([key, value]) => ({
    key,
    value: typeof value === "object" ? JSON.stringify(value) : String(value ?? ""),
  }));
});

function statusType(status: string): "warning" | "success" | "danger" | "info" {
  return status === "pending" ? "warning" : status === "approved" ? "success" : status === "rejected" ? "danger" : "info";
}

function actionText(action: string) {
  const map: Record<string, string> = {
    submit: "提交审核",
    resubmit: "重新送审",
    approve: "审核通过",
    reject: "驳回",
    withdraw: "撤回",
  };
  return map[action] || action;
}

async function loadApps() {
  const scope = "member";
  const res = await api.get<{ results: any[] }>(`/apps/?scope=${scope}&size=100`);
  apps.value = res.results || [];
  if (!appId.value && apps.value.length) appId.value = apps.value[0].id;
}

async function loadAll() {
  await Promise.all([loadSummary(), loadReviews()]);
}

async function loadSummary() {
  if (!appId.value) return;
  const res = await api.get<{ counts: Record<string, number>; total: number }>(`/moderation/summary/?app_id=${appId.value}`);
  counts.value = { ...(res.counts || {}), total: res.total || 0 };
}

async function loadReviews() {
  if (!appId.value) return;
  loading.value = true;
  try {
    const params = new URLSearchParams({
      app_id: String(appId.value),
      status: statusFilter.value || "",
      size: "100",
    });
    if (keyword.value) params.set("q", keyword.value);
    if (onlyMine.value) params.set("mine", "1");
    const res = await api.get<{ results: ReviewRow[] }>(`/moderation/reviews/?${params.toString()}`);
    reviews.value = res.results || [];
  } finally {
    loading.value = false;
  }
}

function onSelectionChange(rows: ReviewRow[]) {
  selected.value = rows;
}

async function openDetail(row: ReviewRow) {
  detail.value = await api.get<ReviewRow>(`/moderation/reviews/${row.id}/`);
  comment.value = "";
  drawer.value = true;
}

async function approve(row: ReviewRow) {
  acting.value = true;
  try {
    await api.post(`/moderation/reviews/${row.id}/approve/`, { comment: comment.value });
    ElMessage.success("已通过并发布");
    drawer.value = false;
    await loadAll();
  } finally {
    acting.value = false;
  }
}

async function reject(row: ReviewRow) {
  let reason = comment.value;
  if (!reason.trim()) {
    try {
      const result = await ElMessageBox.prompt("请填写驳回原因", "驳回内容", {
        inputType: "textarea",
        inputValidator: (value) => (!!value && value.trim().length > 0) || "驳回原因不能为空",
      });
      reason = result.value;
    } catch {
      return;
    }
  }
  acting.value = true;
  try {
    await api.post(`/moderation/reviews/${row.id}/reject/`, { comment: reason });
    ElMessage.success("已驳回");
    drawer.value = false;
    await loadAll();
  } finally {
    acting.value = false;
  }
}

async function withdraw(row: ReviewRow) {
  await api.post(`/moderation/reviews/${row.id}/withdraw/`, {});
  ElMessage.success("已撤回");
  await loadAll();
}

async function batchApprove() {
  const ids = selected.value.filter((r) => r.status === "pending").map((r) => r.id);
  if (!ids.length) return;
  const res = await api.post<{ processed: number[]; errors: any[] }>("/moderation/reviews/batch/", {
    ids,
    action: "approve",
    comment: "批量通过",
  });
  ElMessage.success(`已通过 ${res.processed?.length || 0} 条`);
  await loadAll();
}

onMounted(async () => {
  await loadApps();
  const fromQuery = Number(route.query.app || 0);
  if (fromQuery && apps.value.some((item) => item.id === fromQuery)) appId.value = fromQuery;
  await loadAll();
});
</script>

<style scoped>
.wp-review-stats {
  margin-bottom: 12px;
}
.wp-stat {
  text-align: center;
}
.wp-stat-value {
  font-size: 26px;
  font-weight: 700;
}
.wp-stat-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-stat.is-pending .wp-stat-value {
  color: var(--el-color-warning);
}
.wp-stat.is-approved .wp-stat-value {
  color: var(--el-color-success);
}
.wp-stat.is-rejected .wp-stat-value {
  color: var(--el-color-danger);
}
.wp-review-title {
  color: var(--el-color-primary);
  cursor: pointer;
}
.wp-review-section {
  margin: 18px 0 8px;
}
.wp-review-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
}
.wp-review-comment {
  margin-top: 4px;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
  padding: 6px 8px;
  border-radius: 4px;
}
.wp-muted {
  color: var(--el-text-color-secondary);
}
</style>
