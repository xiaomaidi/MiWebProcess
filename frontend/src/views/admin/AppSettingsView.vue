<template>
  <div class="wp-admin-page" v-loading="loading">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>应用设置 <el-tag size="small" effect="plain">{{ app?.code || "" }}</el-tag></h2>
        <p class="wp-page-desc">{{ app?.name || "" }} · 模块、认证、主题与应用蓝图统一配置</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="router.push(`/admin/apps/${appId}`)">返回应用</el-button>
        <el-button @click="router.push(`/admin/apps/${appId}/auth`)">认证设置</el-button>
        <el-button @click="router.push(`/admin/apps/${appId}/services`)">应用服务</el-button>
        <el-button @click="router.push(`/admin/apps/${appId}/design-tokens`)">设计 Token</el-button>
        <el-button type="primary" :loading="savingModules" @click="saveModules">保存模块</el-button>
      </div>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="应用模块" name="modules">
        <el-alert
          title="模块开关决定该应用启用哪些平台能力。已有页面不会自动删除，但可以在应用菜单和权限中按模块收敛。"
          type="info"
          :closable="false"
          show-icon
          class="settings-note"
        />
        <div class="module-grid">
          <el-card v-for="item in modules" :key="item.key" shadow="never" class="module-card">
            <div class="module-head">
              <div>
                <strong>{{ item.label }}</strong>
                <code>{{ item.key }}</code>
              </div>
              <el-switch v-model="item.enabled" />
            </div>
            <p>{{ item.description }}</p>
            <el-tag size="small" :type="item.enabled ? 'success' : 'info'" effect="plain">
              {{ item.enabled ? "已启用" : "未启用" }}
            </el-tag>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="认证入口" name="auth">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never">
              <template #header><strong>登录与注册</strong></template>
              <p class="settings-text">配置应用标题、注册开关、邀请码、默认角色和登录后跳转。</p>
              <el-button type="primary" @click="router.push(`/admin/apps/${appId}/auth`)">打开认证设置</el-button>
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never">
              <template #header><strong>通用地址</strong></template>
              <div class="url-row"><code>/auth/{{ app?.code }}/login</code><el-button size="small" @click="copy(`/auth/${app?.code}/login`)">复制</el-button></div>
              <div class="url-row"><code>/auth/{{ app?.code }}/register</code><el-button size="small" @click="copy(`/auth/${app?.code}/register`)">复制</el-button></div>
            </el-card>
          </el-col>
        </el-row>
      </el-tab-pane>

      <el-tab-pane label="应用蓝图" name="blueprint">
        <el-card shadow="never">
          <template #header><strong>完整应用蓝图</strong></template>
          <p class="settings-text">
            导出内容包含页面、数据模型、示例数据、工作流、数据模型流程绑定、认证配置、模块开关、设计 Token 和成员。
            可用于克隆或导入新应用。
          </p>
          <div class="blueprint-actions">
            <el-button type="primary" :loading="exporting" @click="exportBlueprint">导出应用蓝图 JSON</el-button>
            <el-button @click="router.push(`/admin/apps/${appId}`)">从应用详情克隆</el-button>
            <el-button @click="router.push('/admin/templates')">模板库</el-button>
          </div>
          <el-divider />
          <div class="blueprint-list">
            <div><span>页面</span><strong>{{ blueprint.pages ?? "—" }}</strong></div>
            <div><span>数据模型</span><strong>{{ blueprint.models ?? "—" }}</strong></div>
            <div><span>工作流</span><strong>{{ blueprint.workflows ?? "—" }}</strong></div>
            <div><span>成员</span><strong>{{ blueprint.members ?? "—" }}</strong></div>
          </div>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId);
const tab = ref("modules");
const loading = ref(true);
const savingModules = ref(false);
const exporting = ref(false);
const app = ref<any>(null);
const modules = ref<any[]>([]);
const blueprint = reactive<Record<string, any>>({});

async function load() {
  loading.value = true;
  try {
    const [appData, moduleData] = await Promise.all([
      api.get<any>(`/apps/${appId}/`),
      api.get<any>(`/apps/${appId}/modules/`),
    ]);
    app.value = appData;
    modules.value = moduleData.modules || [];
  } catch (e: any) {
    ElMessage.error(e?.message || "加载应用设置失败");
  } finally {
    loading.value = false;
  }
}

async function saveModules() {
  savingModules.value = true;
  try {
    const data = await api.put<any>(`/apps/${appId}/modules/`, {
      modules: modules.value.map((item) => ({ key: item.key, enabled: item.enabled })),
    });
    modules.value = data.modules || modules.value;
    ElMessage.success("模块设置已保存");
  } catch (e: any) {
    ElMessage.error(e?.message || "保存模块失败");
  } finally {
    savingModules.value = false;
  }
}

async function exportBlueprint() {
  exporting.value = true;
  try {
    const data = await api.get<any>(`/templates/export/${appId}/`);
    blueprint.pages = Array.isArray(data.pages) ? data.pages.length : 0;
    blueprint.models = Array.isArray(data.models) ? data.models.length : 0;
    blueprint.workflows = Array.isArray(data.workflows) ? data.workflows.length : 0;
    blueprint.members = Array.isArray(data.members) ? data.members.length : 0;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${app.value?.code || "app"}-blueprint.json`;
    a.click();
    URL.revokeObjectURL(url);
    ElMessage.success("应用蓝图已导出");
  } catch (e: any) {
    ElMessage.error(e?.message || "导出失败");
  } finally {
    exporting.value = false;
  }
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    ElMessage.success("已复制");
  } catch {
    ElMessage.warning(text);
  }
}

onMounted(load);
</script>

<style scoped>
.settings-note {
  margin-bottom: 16px;
}
.module-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.module-card {
  border-radius: 10px;
}
.module-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.module-head strong {
  display: block;
  color: var(--el-text-color-primary);
}
.module-head code {
  display: block;
  margin-top: 3px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.module-card p {
  min-height: 38px;
  margin: 10px 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.settings-text {
  max-width: 760px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.8;
}
.url-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 10px;
  padding: 8px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}
.url-row code {
  font-size: 12px;
}
.blueprint-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 16px;
}
.blueprint-list {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}
.blueprint-list div {
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  text-align: center;
}
.blueprint-list span {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.blueprint-list strong {
  display: block;
  margin-top: 6px;
  font-size: 20px;
  color: var(--el-text-color-primary);
}
</style>
