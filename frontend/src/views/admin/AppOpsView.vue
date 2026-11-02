<template>
  <div class="wp-admin-page" v-loading="loading">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>{{ app?.name || "应用" }} · 扩展能力</h2>
        <p class="wp-page-desc">组织可见性、搜索索引、MQTT/WebSocket 通道、内容审核策略与 SSR 快照。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="router.push(`/admin/apps/${appId}`)">返回应用</el-button>
        <el-button type="primary" @click="loadAll">刷新</el-button>
      </div>
    </div>

    <el-tabs v-model="tab">
      <!-- 组织可见性 -->
      <el-tab-pane label="组织可见性" name="org">
        <el-card shadow="never">
          <el-form label-width="130px" style="max-width: 620px">
            <el-form-item label="归属部门">
              <el-select v-model="orgForm.department_id" clearable filterable placeholder="不限制" style="width: 100%">
                <el-option v-for="node in departments" :key="node.id" :label="node.display_path" :value="node.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="部门成员只读访问">
              <el-switch v-model="orgForm.department_visible" />
              <span class="wp-hint">开启后，归属部门及其子部门成员可只读访问本应用（含页面与数据）。</span>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveOrg">保存</el-button>
              <el-button @click="router.push('/admin/org')">管理组织架构</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 搜索索引 -->
      <el-tab-pane label="搜索索引" name="search">
        <el-row :gutter="12">
          <el-col :span="6"><el-card shadow="never" class="wp-metric"><div class="wp-metric-value">{{ searchStats.documents || 0 }}</div><div class="wp-metric-label">文档数</div></el-card></el-col>
          <el-col :span="6"><el-card shadow="never" class="wp-metric"><div class="wp-metric-value">{{ searchStats.published || 0 }}</div><div class="wp-metric-label">公开已发布</div></el-card></el-col>
          <el-col :span="12">
            <el-card shadow="never" class="wp-metric">
              <div class="wp-metric-value">{{ searchStats.last_indexed_at ? formatTime(searchStats.last_indexed_at) : "—" }}</div>
              <div class="wp-metric-label">最近索引时间</div>
            </el-card>
          </el-col>
        </el-row>

        <el-card shadow="never" style="margin-top: 12px">
          <div class="wp-tab-toolbar">
            <el-input v-model="searchQuery" placeholder="输入关键词测试搜索" style="width: 280px" @keyup.enter="runSearch" />
            <el-button type="primary" @click="runSearch">测试搜索</el-button>
            <el-button :loading="rebuilding" @click="rebuildSearch">重建索引</el-button>
          </div>
          <el-table :data="searchResults" border size="small">
            <el-table-column prop="title" label="标题" min-width="220" />
            <el-table-column prop="model_name" label="模型" width="120" />
            <el-table-column prop="score" label="相关度" width="90" />
            <el-table-column prop="snippet" label="摘要" min-width="260" show-overflow-tooltip />
            <el-table-column label="链接" width="110">
              <template #default="{ row }"><el-link :href="row.url" target="_blank" type="primary">打开</el-link></template>
            </el-table-column>
            <template #empty><el-empty description="暂无搜索结果" :image-size="50" /></template>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 实时通道 -->
      <el-tab-pane label="实时通道" name="realtime">
        <el-card shadow="never">
          <div class="wp-tab-toolbar">
            <el-button type="primary" size="small" @click="openChannelCreate">新建通道</el-button>
            <el-tag :type="mqtt.connected ? 'success' : 'info'" size="small">
              MQTT：{{ mqtt.connected ? "已连接" : mqtt.enabled ? "未连接" : "未启用" }}
            </el-tag>
            <span class="wp-hint">Broker：{{ mqtt.broker || "未配置" }}；WebSocket：/ws/{{ appId }}/?token=JWT</span>
          </div>
          <el-table :data="channels" border stripe size="small">
            <el-table-column prop="name" label="名称" min-width="140" />
            <el-table-column prop="slug" label="标识" width="130" />
            <el-table-column prop="kind" label="类型" width="110" />
            <el-table-column prop="topic" label="主题" min-width="200" />
            <el-table-column prop="message_count" label="消息数" width="90" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? "启用" : "停用" }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="280" fixed="right">
              <template #default="{ row }">
                <el-button size="small" type="primary" plain @click="openPublish(row)">发送</el-button>
                <el-button size="small" @click="loadMessages(row)">消息</el-button>
                <el-button size="small" @click="openChannelEdit(row)">编辑</el-button>
                <el-button size="small" type="danger" plain @click="deleteChannel(row)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="还没有实时通道" :image-size="60" /></template>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- 内容审核 -->
      <el-tab-pane label="内容审核" name="review">
        <el-card shadow="never">
          <el-table :data="policies" border stripe size="small">
            <el-table-column prop="model_name" label="数据模型" min-width="160" />
            <el-table-column label="开启审核" width="120">
              <template #default="{ row }">
                <el-switch v-model="row.review_required" @change="savePolicy(row)" />
              </template>
            </el-table-column>
            <el-table-column label="审核角色" min-width="220">
              <template #default="{ row }">
                <el-select v-model="row.review_roles" multiple size="small" style="width: 100%" @change="savePolicy(row)">
                  <el-option label="所有者 owner" value="owner" />
                  <el-option label="编辑 editor" value="editor" />
                  <el-option label="查看者 viewer" value="viewer" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column prop="pending" label="待审" width="80" />
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button size="small" @click="router.push(`/admin/reviews?app=${appId}`)">审核队列</el-button>
              </template>
            </el-table-column>
            <template #empty><el-empty description="还没有数据模型" :image-size="60" /></template>
          </el-table>
          <p class="wp-hint" style="margin-top: 10px">开启后，编辑保存内容自动进入待审；审核角色可直接发布。</p>
        </el-card>
      </el-tab-pane>

      <!-- SSR -->
      <el-tab-pane label="SSR 快照" name="ssr">
        <el-card shadow="never">
          <p class="wp-hint">
            使用前端 Vue SSR 产物渲染完整页面 HTML（含 <code>window.__WP_SSR__</code> 水合状态），
            可直接交给 Nginx/CDN 托管；未构建 SSR 产物时该功能自动跳过。
          </p>
          <div class="wp-tab-toolbar">
            <el-button type="primary" :loading="ssrBuilding" @click="rebuildSsr">生成快照</el-button>
            <el-link :href="`/api/runtime/${app?.code}/prerender/home/`" target="_blank" type="primary">查看示例快照</el-link>
          </div>
          <el-table :data="ssrResults" border size="small">
            <el-table-column prop="path" label="页面" min-width="160" />
            <el-table-column prop="file" label="输出文件" min-width="300" show-overflow-tooltip />
            <el-table-column prop="bytes" label="大小（字节）" width="120" />
            <template #empty><el-empty description="尚未生成" :image-size="50" /></template>
          </el-table>
          <el-alert
            v-if="ssrErrors.length"
            type="warning"
            :closable="false"
            show-icon
            title="部分页面未生成"
            style="margin-top: 10px"
          >
            <div v-for="err in ssrErrors" :key="err.path">{{ err.path }}：{{ err.error }}</div>
          </el-alert>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="dlg.channel" :title="channelEditing ? '编辑通道' : '新建通道'" width="520px">
      <el-form :model="channelForm" label-width="90px">
        <el-form-item label="名称" required><el-input v-model="channelForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="channelForm.kind" style="width: 100%">
            <el-option label="MQTT + WebSocket" value="both" />
            <el-option label="仅 MQTT" value="mqtt" />
            <el-option label="仅 WebSocket" value="ws" />
          </el-select>
        </el-form-item>
        <el-form-item label="主题" required>
          <el-input v-model="channelForm.topic" placeholder="devices/+/telemetry" />
        </el-form-item>
        <el-form-item label="QoS"><el-input-number v-model="channelForm.qos" :min="0" :max="2" /></el-form-item>
        <el-form-item label="保留消息"><el-switch v-model="channelForm.retain" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="channelForm.description" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="channelForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlg.channel = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveChannel">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dlg.publish" :title="`发送消息 · ${publishChannel?.topic || ''}`" width="520px">
      <el-input v-model="publishPayload" type="textarea" :rows="8" placeholder='JSON，如 {"temp": 23.5}' />
      <template #footer>
        <el-button @click="dlg.publish = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="publish">发送</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="dlg.messages" :title="`最近消息 · ${messageChannel?.name || ''}`" size="520px">
      <el-timeline>
        <el-timeline-item v-for="msg in messages" :key="msg.id" :timestamp="formatTime(msg.created_at)" :type="msg.direction === 'in' ? 'success' : 'primary'">
          <div class="wp-msg-topic">{{ msg.topic }}</div>
          <pre class="wp-msg-payload">{{ JSON.stringify(msg.payload, null, 2) }}</pre>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!messages.length" description="暂无消息" :image-size="60" />
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId || 0);
const app = ref<any>(null);
const tab = ref("org");
const loading = ref(false);
const saving = ref(false);

const departments = ref<any[]>([]);
const orgForm = reactive<{ department_id: number | null; department_visible: boolean }>({
  department_id: null,
  department_visible: false,
});

const searchStats = ref<Record<string, any>>({});
const searchQuery = ref("");
const searchResults = ref<any[]>([]);
const rebuilding = ref(false);

const channels = ref<any[]>([]);
const mqtt = ref<Record<string, any>>({});
const messages = ref<any[]>([]);
const messageChannel = ref<any>(null);
const publishChannel = ref<any>(null);
const publishPayload = ref('{\n  "value": 1\n}');
const policies = ref<any[]>([]);

const ssrBuilding = ref(false);
const ssrResults = ref<any[]>([]);
const ssrErrors = ref<any[]>([]);

const dlg = reactive({ channel: false, publish: false, messages: false });
const channelEditing = ref(false);
const channelForm = reactive<Record<string, any>>({
  name: "",
  kind: "both",
  topic: "",
  qos: 0,
  retain: false,
  description: "",
  enabled: true,
});

async function loadAll() {
  loading.value = true;
  try {
    app.value = await api.get(`/apps/${appId}/`);
    orgForm.department_id = app.value.department_id || null;
    orgForm.department_visible = !!app.value.department_visible;
    const [tree, stats, channelList, status, policyRes] = await Promise.all([
      api.get<{ nodes: any[] }>("/org/tree/"),
      api.get(`/search/stats/?app_id=${appId}`),
      api.get<{ results: any[] }>(`/realtime/channels/?app_id=${appId}`),
      api.get(`/realtime/status/?app_id=${appId}`).catch(() => ({})),
      api.get<{ policies: any[] }>(`/moderation/policies/?app_id=${appId}`),
    ]);
    departments.value = tree.nodes || [];
    searchStats.value = stats;
    channels.value = channelList.results || [];
    mqtt.value = status || {};
    policies.value = policyRes.policies || [];
  } finally {
    loading.value = false;
  }
}

async function saveOrg() {
  saving.value = true;
  try {
    await api.patch(`/apps/${appId}/`, {
      department_id: orgForm.department_id,
      department_visible: orgForm.department_visible,
    });
    ElMessage.success("已保存");
  } finally {
    saving.value = false;
  }
}

async function runSearch() {
  if (!searchQuery.value.trim()) return;
  const res = await api.get(`/search/?app_id=${appId}&q=${encodeURIComponent(searchQuery.value)}`);
  searchResults.value = res.results || [];
}

async function rebuildSearch() {
  rebuilding.value = true;
  try {
    const res = await api.post(`/search/rebuild/`, { app_id: appId });
    searchStats.value = res.stats || {};
    ElMessage.success(`索引已重建：${res.created} 条`);
  } finally {
    rebuilding.value = false;
  }
}

function openChannelCreate() {
  channelEditing.value = false;
  Object.assign(channelForm, { name: "", kind: "both", topic: "", qos: 0, retain: false, description: "", enabled: true });
  dlg.channel = true;
}

function openChannelEdit(row: any) {
  channelEditing.value = true;
  Object.assign(channelForm, { ...row, id: row.id });
  dlg.channel = true;
}

async function saveChannel() {
  if (!channelForm.name || !channelForm.topic) {
    ElMessage.warning("名称与主题必填");
    return;
  }
  saving.value = true;
  try {
    const payload = {
      name: channelForm.name,
      kind: channelForm.kind,
      topic: channelForm.topic,
      qos: channelForm.qos,
      retain: channelForm.retain,
      description: channelForm.description,
      enabled: channelForm.enabled,
    };
    if (channelEditing.value) await api.patch(`/realtime/channels/${channelForm.id}/`, payload);
    else await api.post(`/realtime/channels/?app_id=${appId}`, { ...payload, app_id: appId });
    dlg.channel = false;
    await loadAll();
  } finally {
    saving.value = false;
  }
}

async function deleteChannel(row: any) {
  await ElMessageBox.confirm(`删除通道「${row.name}」？`, "确认", { type: "warning" });
  await api.del(`/realtime/channels/${row.id}/`);
  await loadAll();
}

function openPublish(row: any) {
  publishChannel.value = row;
  publishPayload.value = '{\n  "value": 1\n}';
  dlg.publish = true;
}

async function publish() {
  let payload: any;
  try {
    payload = JSON.parse(publishPayload.value);
  } catch {
    ElMessage.error("payload 必须是合法 JSON");
    return;
  }
  saving.value = true;
  try {
    const res = await api.post(`/realtime/channels/${publishChannel.value.id}/publish/`, { payload });
    ElMessage.success(`已发送（${res.transport}）`);
    dlg.publish = false;
    await loadAll();
  } finally {
    saving.value = false;
  }
}

async function loadMessages(row: any) {
  messageChannel.value = row;
  const res = await api.get<{ results: any[] }>(`/realtime/channels/${row.id}/messages/?limit=50`);
  messages.value = res.results || [];
  dlg.messages = true;
}

async function savePolicy(row: any) {
  await api.patch(`/models/${row.model_id}/`, {
    review_required: row.review_required,
    review_roles: row.review_roles,
  });
  ElMessage.success("审核策略已更新");
}

async function rebuildSsr() {
  ssrBuilding.value = true;
  try {
    const res = await api.post(`/runtime/${app.value.code}/ssr/rebuild/`, {});
    ssrResults.value = res.generated || [];
    ssrErrors.value = res.errors || [];
    if (res.generated?.length) ElMessage.success(`已生成 ${res.generated.length} 个快照`);
    else ElMessage.warning("未生成快照，请先构建前端 SSR 产物");
  } finally {
    ssrBuilding.value = false;
  }
}

onMounted(loadAll);
</script>

<style scoped>
.wp-metric {
  text-align: center;
}
.wp-metric-value {
  font-size: 22px;
  font-weight: 700;
}
.wp-metric-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-left: 8px;
}
.wp-msg-topic {
  font-weight: 600;
  font-size: 12px;
}
.wp-msg-payload {
  background: var(--el-fill-color-light);
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
