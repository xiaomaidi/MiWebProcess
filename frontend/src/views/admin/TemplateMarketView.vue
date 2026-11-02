<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>模板市场</h2>
        <p class="wp-page-desc">服务端模板库：发布、共享、版本化和权限控制。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="load">刷新</el-button>
        <el-button @click="openFromApp">从应用创建模板</el-button>
      </div>
    </div>

    <el-card>
      <div class="wp-filter-bar">
        <el-input v-model="keyword" placeholder="搜索模板" clearable style="width: 220px" @keyup.enter="load" @clear="load" />
        <el-select v-model="scope" style="width: 140px" @change="load">
          <el-option label="全部可见" value="" />
          <el-option label="模板市场" value="market" />
          <el-option label="我的模板" value="mine" />
        </el-select>
        <el-button @click="load">查询</el-button>
      </div>

      <div v-if="!templates.length" class="wp-empty">
        <el-empty description="还没有模板，先从应用创建一个" :image-size="60" />
      </div>
      <div v-else class="wp-market-grid">
        <el-card v-for="item in templates" :key="item.id" shadow="hover" class="wp-market-card">
          <div class="wp-market-head">
            <div class="wp-market-icon" :style="{ background: item.accent }">{{ item.icon }}</div>
            <div class="wp-market-title">
              <strong>{{ item.name }}</strong>
              <span>{{ item.owner_username }} · v{{ item.current_version }} · {{ item.downloads }} 次使用</span>
            </div>
            <el-tag size="small" :type="item.status === 'published' ? 'success' : 'info'" effect="plain">
              {{ item.status === "published" ? "已发布" : "草稿" }}
            </el-tag>
          </div>
          <p class="wp-market-desc">{{ item.description || "暂无描述" }}</p>
          <div class="wp-market-tags">
            <el-tag v-if="item.category" size="small" effect="plain">{{ item.category }}</el-tag>
            <el-tag v-for="tag in item.tags || []" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
            <el-tag size="small" type="warning" effect="plain">{{ visibilityText(item.visibility) }}</el-tag>
          </div>
          <div class="wp-market-actions">
            <el-button size="small" type="primary" plain @click="openUse(item)">使用</el-button>
            <el-button v-if="canManage(item)" size="small" @click="openEdit(item)">编辑</el-button>
            <el-button size="small" @click="openVersions(item)">版本</el-button>
            <el-button v-if="canManage(item)" size="small" @click="openShare(item)">共享</el-button>
            <el-button v-if="canManage(item) && item.status !== 'published'" size="small" type="success" plain @click="publish(item)">发布</el-button>
          </div>
        </el-card>
      </div>
    </el-card>

    <el-dialog v-model="fromAppVisible" title="从应用创建模板" width="520px">
      <el-form label-width="90px">
        <el-form-item label="应用">
          <el-select v-model="fromAppId" filterable placeholder="选择应用" style="width: 100%">
            <el-option v-for="app in apps" :key="app.id" :label="`${app.name} (${app.code})`" :value="app.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="模板名称">
          <el-input v-model="fromAppName" placeholder="默认使用应用名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fromAppVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createFromApp">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="useVisible" title="使用服务端模板" width="520px">
      <el-form label-width="90px">
        <el-form-item label="应用名称"><el-input v-model="useName" /></el-form-item>
        <el-form-item label="应用标识"><el-input v-model="useCode" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="useVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="applyTemplate">创建应用</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑模板 JSON" width="820px">
      <el-input v-model="editJson" type="textarea" :rows="22" class="wp-mono" />
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存并新版本</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="versionsVisible" title="模板版本" width="580px">
      <el-table :data="versions" size="small" border>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="changelog" label="说明" min-width="200" />
        <el-table-column prop="created_by" label="操作人" width="100" />
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" @click="rollback(row)">回滚</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <el-dialog v-model="shareVisible" title="模板共享" width="560px">
      <div class="wp-access-add">
        <el-select v-model="shareUserId" filterable placeholder="选择用户" style="width: 220px">
          <el-option v-for="u in users" :key="u.id" :label="u.username" :value="u.id" />
        </el-select>
        <el-select v-model="shareRole" style="width: 110px">
          <el-option label="只读" value="viewer" />
          <el-option label="可编辑" value="editor" />
        </el-select>
        <el-button size="small" type="primary" :disabled="!shareUserId" @click="addShare">添加</el-button>
      </div>
      <el-table :data="accessRows" size="small" border style="margin-top: 12px">
        <el-table-column prop="username" label="用户" />
        <el-table-column prop="role" label="角色" width="100" />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button size="small" type="danger" plain @click="removeShare(row)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useAuthStore } from "@/store/auth";

const auth = useAuthStore();
const router = useRouter();
const templates = ref<any[]>([]);
const apps = ref<any[]>([]);
const users = ref<any[]>([]);
const keyword = ref("");
const scope = ref("");
const saving = ref(false);

const fromAppVisible = ref(false);
const fromAppId = ref<number | null>(null);
const fromAppName = ref("");
const useVisible = ref(false);
const useTemplate = ref<any>(null);
const useName = ref("");
const useCode = ref("");
const editVisible = ref(false);
const editTemplate = ref<any>(null);
const editJson = ref("");
const versionsVisible = ref(false);
const versions = ref<any[]>([]);
const versionTemplate = ref<any>(null);
const shareVisible = ref(false);
const shareTemplate = ref<any>(null);
const shareUserId = ref<number | null>(null);
const shareRole = ref("viewer");
const accessRows = ref<any[]>([]);

const canManage = (item: any) => auth.isAdmin || item.owner_id === auth.user?.id;

function visibilityText(value: string) {
  return value === "market" ? "公开市场" : value === "shared" ? "已共享" : "私有";
}

async function load() {
  try {
    const qs = new URLSearchParams();
    if (keyword.value.trim()) qs.set("q", keyword.value.trim());
    if (scope.value) qs.set("scope", scope.value);
    const data = await api.get<any>(`/templates/library/?${qs.toString()}`);
    templates.value = data?.results || [];
    if (!apps.value.length) {
      const appData = await api.get<any>("/apps/?size=100");
      apps.value = appData?.results || [];
    }
  } catch (error: any) {
    ElMessage.error(error?.message || "加载模板库失败");
  }
}

function openFromApp() {
  fromAppId.value = apps.value[0]?.id || null;
  fromAppName.value = "";
  fromAppVisible.value = true;
}

async function createFromApp() {
  if (!fromAppId.value) return ElMessage.warning("请选择应用");
  saving.value = true;
  try {
    const template = await api.post<any>(`/templates/library/from-app/${fromAppId.value}/`, {
      name: fromAppName.value.trim() || undefined,
    });
    fromAppVisible.value = false;
    ElMessage.success("模板已创建");
    await load();
    openEdit(template);
  } catch (error: any) {
    ElMessage.error(error?.message || "创建模板失败");
  } finally {
    saving.value = false;
  }
}

function openUse(item: any) {
  useTemplate.value = item;
  useName.value = item.name;
  useCode.value = `${item.key}-${Date.now().toString(36)}`;
  useVisible.value = true;
}

async function applyTemplate() {
  if (!useTemplate.value) return;
  saving.value = true;
  try {
    const result = await api.post<any>(`/templates/library/${useTemplate.value.id}/apply/`, {
      name: useName.value.trim(),
      code: useCode.value.trim(),
    });
    useVisible.value = false;
    ElMessage.success("应用已创建");
    router.push(`/admin/apps/${result.app.id}`);
  } catch (error: any) {
    ElMessage.error(error?.message || "使用模板失败");
  } finally {
    saving.value = false;
  }
}

function openEdit(item: any) {
  editTemplate.value = item;
  editJson.value = JSON.stringify(item.bundle || {}, null, 2);
  editVisible.value = true;
}

async function saveEdit() {
  if (!editTemplate.value) return;
  let bundle: any;
  try {
    bundle = JSON.parse(editJson.value);
  } catch {
    return ElMessage.error("JSON 格式不正确");
  }
  saving.value = true;
  try {
    await api.put(`/templates/library/${editTemplate.value.id}/`, {
      bundle,
      changelog: "编辑模板",
    });
    editVisible.value = false;
    ElMessage.success("已保存并生成新版本");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function openVersions(item: any) {
  versionTemplate.value = item;
  versions.value = await api.get<any[]>(`/templates/library/${item.id}/versions/`);
  versionsVisible.value = true;
}

async function rollback(row: any) {
  if (!versionTemplate.value) return;
  try {
    await ElMessageBox.confirm(`回滚到版本 v${row.version}？`, "确认", { type: "warning" });
    await api.post(`/templates/library/${versionTemplate.value.id}/versions/${row.version}/rollback/`, {});
    ElMessage.success("已回滚");
    versionsVisible.value = false;
    await load();
  } catch {
    /* ignore */
  }
}

async function publish(item: any) {
  try {
    await ElMessageBox.confirm("发布到模板市场后，其他用户可以看到并使用。", "发布模板", { type: "warning" });
    await api.post(`/templates/library/${item.id}/publish/`, { visibility: "market" });
    ElMessage.success("已发布到模板市场");
    await load();
  } catch (error: any) {
    if (error?.message) ElMessage.error(error.message);
  }
}

async function openShare(item: any) {
  shareTemplate.value = item;
  accessRows.value = await api.get<any[]>(`/templates/library/${item.id}/access/`);
  if (!users.value.length) {
    const data = await api.get<any>("/auth/users/?size=100").catch(() => null);
    users.value = data?.results || [];
  }
  shareUserId.value = null;
  shareRole.value = "viewer";
  shareVisible.value = true;
}

async function addShare() {
  if (!shareTemplate.value || !shareUserId.value) return;
  await api.post(`/templates/library/${shareTemplate.value.id}/access/`, {
    user_id: shareUserId.value,
    role: shareRole.value,
  });
  accessRows.value = await api.get<any[]>(`/templates/library/${shareTemplate.value.id}/access/`);
  ElMessage.success("已共享");
}

async function removeShare(row: any) {
  if (!shareTemplate.value) return;
  await api.del(`/templates/library/${shareTemplate.value.id}/access/${row.user_id}/`);
  accessRows.value = accessRows.value.filter((item) => item.user_id !== row.user_id);
}

onMounted(load);
</script>

<style scoped>
.wp-market-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}
.wp-market-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.wp-market-head {
  display: flex;
  gap: 10px;
  align-items: center;
}
.wp-market-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 20px;
  flex: none;
}
.wp-market-title {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.wp-market-title strong {
  font-size: 15px;
}
.wp-market-title span {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-market-desc {
  margin: 4px 0;
  min-height: 38px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}
.wp-market-tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
}
.wp-market-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.wp-access-add {
  display: flex;
  gap: 8px;
  align-items: center;
}
.wp-empty {
  padding: 30px;
}
@media (max-width: 1100px) {
  .wp-market-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .wp-market-grid { grid-template-columns: 1fr; }
}
</style>
