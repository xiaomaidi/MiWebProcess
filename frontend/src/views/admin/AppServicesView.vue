<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>应用服务</h2>
        <p class="wp-page-desc">文件、通知模板、API Token、Webhook 与定时任务，全部按应用隔离。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="router.push(`/admin/apps/${appId}/settings`)">应用设置</el-button>
      </div>
    </div>

    <el-tabs v-model="tab" @tab-change="loadTab">
      <el-tab-pane label="文件" name="files">
        <div class="toolbar">
          <input ref="fileInput" type="file" hidden @change="uploadFile" />
          <el-button type="primary" :loading="uploading" @click="fileInput?.click()">上传文件</el-button>
          <el-button @click="loadFiles">刷新</el-button>
        </div>
        <el-table :data="files" v-loading="loading" border stripe>
          <el-table-column prop="name" label="文件名" min-width="220" show-overflow-tooltip />
          <el-table-column prop="type" label="类型" width="90" />
          <el-table-column label="地址" min-width="220">
            <template #default="{ row }"><el-link :href="row.url" target="_blank" type="primary">{{ row.url }}</el-link></template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }"><el-button size="small" type="danger" link @click="deleteFile(row)">删除</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="通知模板" name="notifications">
        <div class="toolbar">
          <el-button type="primary" @click="openTemplate">新建模板</el-button>
          <el-button @click="loadNotifications">刷新</el-button>
        </div>
        <el-table :data="templates" v-loading="loading" border stripe>
          <el-table-column prop="name" label="模板" min-width="180" />
          <el-table-column prop="key" label="编码" width="140" />
          <el-table-column prop="channel" label="渠道" width="100" />
          <el-table-column prop="subject" label="标题" min-width="180" show-overflow-tooltip />
          <el-table-column label="操作" width="170">
            <template #default="{ row }">
              <el-button size="small" @click="sendTemplate(row)">发送</el-button>
              <el-button size="small" type="danger" link @click="deleteTemplate(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="API Token" name="tokens">
        <div class="toolbar">
          <el-button type="primary" @click="openToken">创建 Token</el-button>
          <el-button @click="loadTokens">刷新</el-button>
        </div>
        <el-alert v-if="newToken" :title="`新 Token（只显示一次）：${newToken}`" type="success" :closable="false" show-icon class="token-alert" />
        <el-table :data="tokens" v-loading="loading" border stripe>
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column prop="prefix" label="前缀" width="100" />
          <el-table-column label="权限" min-width="180">
            <template #default="{ row }"><el-tag v-for="s in row.scopes" :key="s" size="small" style="margin-right:4px">{{ s }}</el-tag></template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? "启用" : "停用" }}</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="110">
            <template #default="{ row }"><el-button size="small" type="danger" link @click="deleteToken(row)">撤销</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="Webhook" name="webhooks">
        <div class="toolbar">
          <el-button type="primary" @click="openWebhook">新建 Webhook</el-button>
          <el-button @click="loadWebhooks">刷新</el-button>
        </div>
        <el-table :data="webhooks" v-loading="loading" border stripe>
          <el-table-column prop="name" label="名称" min-width="150" />
          <el-table-column prop="url" label="地址" min-width="260" show-overflow-tooltip />
          <el-table-column prop="last_status" label="最近状态" width="110" />
          <el-table-column label="操作" width="170">
            <template #default="{ row }">
              <el-button size="small" @click="testWebhook(row)">测试</el-button>
              <el-button size="small" type="danger" link @click="deleteWebhook(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="定时任务" name="jobs">
        <div class="toolbar">
          <el-button type="primary" @click="openJob">新建任务</el-button>
          <el-button @click="loadJobs">刷新</el-button>
        </div>
        <el-table :data="jobs" v-loading="loading" border stripe>
          <el-table-column prop="name" label="任务" min-width="160" />
          <el-table-column prop="code" label="编码" width="140" />
          <el-table-column prop="handler" label="处理器" width="150" />
          <el-table-column prop="cron" label="Cron" width="140" />
          <el-table-column prop="last_status" label="最近状态" width="110" />
          <el-table-column label="操作" width="150">
            <template #default="{ row }">
              <el-button size="small" @click="runJob(row)">运行</el-button>
              <el-button size="small" type="danger" link @click="deleteJob(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dialogOpen" :title="dialogTitle" width="520px">
      <el-form v-if="dialog === 'template'" label-position="top">
        <el-form-item label="模板名称"><el-input v-model="templateForm.name" /></el-form-item>
        <el-form-item label="模板编码"><el-input v-model="templateForm.key" placeholder="approval_pending" /></el-form-item>
        <el-form-item label="渠道">
          <el-select v-model="templateForm.channel" style="width:100%">
            <el-option label="站内信" value="inapp" /><el-option label="邮件" value="email" /><el-option label="Webhook" value="webhook" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="templateForm.subject" /></el-form-item>
        <el-form-item label="内容"><el-input v-model="templateForm.content" type="textarea" :rows="4" /></el-form-item>
      </el-form>
      <el-form v-else-if="dialog === 'token'" label-position="top">
        <el-form-item label="Token 名称"><el-input v-model="tokenForm.name" /></el-form-item>
        <el-form-item label="权限">
          <el-select v-model="tokenForm.scopes" multiple style="width:100%">
            <el-option label="读取记录" value="records:read" /><el-option label="写入记录" value="records:write" />
          </el-select>
        </el-form-item>
        <el-form-item label="有效期（天，0 为永久）"><el-input-number v-model="tokenForm.expires_days" :min="0" /></el-form-item>
      </el-form>
      <el-form v-else-if="dialog === 'webhook'" label-position="top">
        <el-form-item label="名称"><el-input v-model="webhookForm.name" /></el-form-item>
        <el-form-item label="地址 URL"><el-input v-model="webhookForm.url" placeholder="https://example.com/hook" /></el-form-item>
        <el-form-item label="事件（逗号分隔）"><el-input v-model="webhookForm.events" placeholder="record.created,workflow.approved" /></el-form-item>
        <el-form-item label="签名密钥（可选）"><el-input v-model="webhookForm.secret" type="password" show-password /></el-form-item>
      </el-form>
      <el-form v-else-if="dialog === 'job'" label-position="top">
        <el-form-item label="任务名称"><el-input v-model="jobForm.name" /></el-form-item>
        <el-form-item label="任务编码"><el-input v-model="jobForm.code" /></el-form-item>
        <el-form-item label="处理器">
          <el-select v-model="jobForm.handler" style="width:100%">
            <el-option label="空任务" value="noop" /><el-option label="Webhook 测试" value="webhook.test" /><el-option label="通知测试" value="notification.test" />
          </el-select>
        </el-form-item>
        <el-form-item label="Cron"><el-input v-model="jobForm.cron" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveDialog">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, getToken } from "@/api";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId);
const tab = ref("files");
const loading = ref(false);
const uploading = ref(false);
const saving = ref(false);
const dialog = ref("");
const dialogOpen = ref(false);
const dialogTitle = ref("");
const fileInput = ref<HTMLInputElement | null>(null);
const files = ref<any[]>([]);
const templates = ref<any[]>([]);
const tokens = ref<any[]>([]);
const webhooks = ref<any[]>([]);
const jobs = ref<any[]>([]);
const newToken = ref("");

const templateForm = reactive({ key: "", name: "", channel: "inapp", subject: "", content: "" });
const tokenForm = reactive({ name: "", scopes: ["records:read"], expires_days: 0 });
const webhookForm = reactive({ name: "", url: "", events: "record.created", secret: "" });
const jobForm = reactive({ name: "", code: "", handler: "noop", cron: "0 2 * * *" });

async function loadFiles() {
  loading.value = true;
  try { files.value = (await api.get<any>(`/assets/?app_id=${appId}`)).results || []; } finally { loading.value = false; }
}
async function loadNotifications() {
  loading.value = true;
  try { templates.value = (await api.get<any>(`/apps/${appId}/notification-templates/`)).results || []; } finally { loading.value = false; }
}
async function loadTokens() {
  loading.value = true;
  try { tokens.value = (await api.get<any>(`/apps/${appId}/api-tokens/`)).results || []; } finally { loading.value = false; }
}
async function loadWebhooks() {
  loading.value = true;
  try { webhooks.value = (await api.get<any>(`/apps/${appId}/webhooks/`)).results || []; } finally { loading.value = false; }
}
async function loadJobs() {
  loading.value = true;
  try { jobs.value = (await api.get<any>(`/apps/${appId}/jobs/`)).results || []; } finally { loading.value = false; }
}
function loadTab() {
  if (tab.value === "files") loadFiles();
  else if (tab.value === "notifications") loadNotifications();
  else if (tab.value === "tokens") loadTokens();
  else if (tab.value === "webhooks") loadWebhooks();
  else loadJobs();
}

async function uploadFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  try {
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch(`/api/assets/?app_id=${appId}`, {
      method: "POST",
      headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
      body: form,
    });
    if (!resp.ok) throw new Error(`上传失败 (${resp.status})`);
    ElMessage.success("上传成功");
    await loadFiles();
  } catch (e: any) {
    ElMessage.error(e?.message || "上传失败");
  } finally {
    uploading.value = false;
    input.value = "";
  }
}
async function deleteFile(row: any) {
  await ElMessageBox.confirm(`删除文件 ${row.name}？`, "确认");
  await api.del(`/assets/${row.id}/`);
  await loadFiles();
}

function openTemplate() {
  Object.assign(templateForm, { key: "", name: "", channel: "inapp", subject: "", content: "" });
  dialog.value = "template"; dialogTitle.value = "新建通知模板"; dialogOpen.value = true;
}
async function sendTemplate(row: any) {
  let recipient = "";
  if (row.channel === "email") {
    const res = await ElMessageBox.prompt("收件邮箱", "发送通知");
    recipient = res.value;
  }
  await api.post(`/apps/${appId}/notification-templates/${row.id}/send/`, { recipient, payload: {} });
  ElMessage.success("已发送并记录");
}
async function deleteTemplate(row: any) {
  await ElMessageBox.confirm(`删除模板 ${row.name}？`, "确认");
  await api.del(`/apps/${appId}/notification-templates/${row.id}/`);
  await loadNotifications();
}

function openToken() {
  Object.assign(tokenForm, { name: "", scopes: ["records:read"], expires_days: 0 });
  dialog.value = "token"; dialogTitle.value = "创建 API Token"; dialogOpen.value = true;
}
async function deleteToken(row: any) {
  await ElMessageBox.confirm(`撤销 Token ${row.name}？`, "确认");
  await api.del(`/apps/${appId}/api-tokens/${row.id}/`);
  await loadTokens();
}

function openWebhook() {
  Object.assign(webhookForm, { name: "", url: "", events: "record.created", secret: "" });
  dialog.value = "webhook"; dialogTitle.value = "新建 Webhook"; dialogOpen.value = true;
}
async function testWebhook(row: any) {
  const result = await api.post<any>(`/apps/${appId}/webhooks/${row.id}/test/`);
  ElMessage[result.ok ? "success" : "warning"](result.ok ? "投递成功" : `失败：${result.error || result.status_code}`);
  await loadWebhooks();
}
async function deleteWebhook(row: any) {
  await ElMessageBox.confirm(`删除 Webhook ${row.name}？`, "确认");
  await api.del(`/apps/${appId}/webhooks/${row.id}/`);
  await loadWebhooks();
}

function openJob() {
  Object.assign(jobForm, { name: "", code: "", handler: "noop", cron: "0 2 * * *" });
  dialog.value = "job"; dialogTitle.value = "新建定时任务"; dialogOpen.value = true;
}
async function runJob(row: any) {
  const result = await api.post<any>(`/apps/${appId}/jobs/${row.id}/run/`);
  ElMessage[result.ok ? "success" : "error"](result.ok ? "任务已执行" : result.error || "执行失败");
  await loadJobs();
}
async function deleteJob(row: any) {
  await ElMessageBox.confirm(`删除任务 ${row.name}？`, "确认");
  await api.del(`/apps/${appId}/jobs/${row.id}/`);
  await loadJobs();
}

async function saveDialog() {
  saving.value = true;
  try {
    if (dialog.value === "template") {
      await api.post(`/apps/${appId}/notification-templates/`, { ...templateForm });
      await loadNotifications();
    } else if (dialog.value === "token") {
      const res = await api.post<any>(`/apps/${appId}/api-tokens/`, { ...tokenForm });
      newToken.value = res.token;
      await loadTokens();
    } else if (dialog.value === "webhook") {
      await api.post(`/apps/${appId}/webhooks/`, {
        ...webhookForm,
        events: webhookForm.events.split(",").map((x) => x.trim()).filter(Boolean),
      });
      await loadWebhooks();
    } else if (dialog.value === "job") {
      await api.post(`/apps/${appId}/jobs/`, { ...jobForm });
      await loadJobs();
    }
    ElMessage.success("保存成功");
    dialogOpen.value = false;
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

onMounted(loadFiles);
</script>

<style scoped>
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.token-alert {
  margin-bottom: 12px;
  word-break: break-all;
}
</style>
