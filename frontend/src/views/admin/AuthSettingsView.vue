<template>
  <div class="wp-admin-page" v-loading="loading">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>认证设置 <el-tag size="small" effect="plain">{{ config.app_code || "" }}</el-tag></h2>
        <p class="wp-page-desc">平台统一账号，应用决定品牌、注册策略与准入方式。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="router.push(`/admin/apps/${appId}`)">返回应用</el-button>
        <el-button @click="openLogin">预览登录页</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存设置</el-button>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :span="15">
        <el-card shadow="never">
          <template #header><strong>准入策略</strong></template>
          <el-form label-position="top">
            <el-row :gutter="16">
              <el-col :span="12">
                <el-form-item label="启用登录页">
                  <el-switch v-model="config.enabled" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="访问需要登录">
                  <el-switch v-model="config.require_login" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="允许注册">
                  <el-switch v-model="config.allow_register" />
                  <div class="hint">关闭后只允许已有账号登录。</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="无成员关系时自动加入">
                  <el-switch v-model="config.auto_join" />
                  <div class="hint">登录时自动创建应用成员关系。</div>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="注册默认角色">
                  <el-select v-model="config.default_role" style="width: 100%">
                    <el-option label="只读 viewer" value="viewer" />
                    <el-option label="编辑 editor" value="editor" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="注册需要邀请码">
                  <el-switch v-model="config.invite_required" />
                </el-form-item>
              </el-col>
              <el-col v-if="config.invite_required" :span="24">
                <el-form-item label="邀请码">
                  <el-input v-model="config.invite_code" placeholder="例如 MIADMIN-2026" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="登录后跳转路径">
                  <el-input v-model="config.redirect_path" placeholder="dashboard 或 /run/应用编码/页面" />
                  <div class="hint">留空时进入应用工作台。</div>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </el-card>
      </el-col>

      <el-col :span="9">
        <el-card shadow="never">
          <template #header><strong>品牌与文案</strong></template>
          <el-form label-position="top">
            <el-form-item label="登录页标题">
              <el-input v-model="config.login_title" placeholder="MiAdmin 企业管理后台" />
            </el-form-item>
            <el-form-item label="登录页副标题">
              <el-input v-model="config.login_subtitle" type="textarea" :rows="2" placeholder="登录 MiAdmin，继续管理企业数据" />
            </el-form-item>
            <el-form-item label="Logo 地址">
              <el-input v-model="config.logo_url" placeholder="https://.../logo.svg" />
            </el-form-item>
            <el-form-item label="品牌主色">
              <div class="color-row">
                <el-color-picker v-model="config.theme_color" />
                <el-input v-model="config.theme_color" style="flex: 1" />
              </div>
            </el-form-item>
          </el-form>
        </el-card>

        <el-card shadow="never" style="margin-top: 16px">
          <template #header><strong>通用登录地址</strong></template>
          <div class="url-row">
            <code>/auth/{{ config.app_code }}/login</code>
            <el-button size="small" @click="copy(`/auth/${config.app_code}/login`)">复制</el-button>
          </div>
          <div class="url-row">
            <code>/auth/{{ config.app_code }}/register</code>
            <el-button size="small" @click="copy(`/auth/${config.app_code}/register`)">复制</el-button>
          </div>
          <div class="hint">
            其他应用使用同一套页面，只需配置本页的品牌与策略，不需要另写登录页。
          </div>
        </el-card>
      </el-col>
    </el-row>
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
const loading = ref(true);
const saving = ref(false);
const config = reactive<Record<string, any>>({
  app_code: "",
  enabled: true,
  require_login: false,
  allow_register: false,
  auto_join: true,
  default_role: "viewer",
  invite_required: false,
  invite_code: "",
  login_title: "",
  login_subtitle: "",
  logo_url: "",
  theme_color: "#2563eb",
  redirect_path: "",
});

async function load() {
  loading.value = true;
  try {
    const data = await api.get<Record<string, any>>(`/apps/${appId}/auth-config/`);
    Object.assign(config, data);
  } catch (e: any) {
    ElMessage.error(e?.message || "加载认证设置失败");
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const data = await api.put<Record<string, any>>(`/apps/${appId}/auth-config/`, { ...config });
    Object.assign(config, data);
    ElMessage.success("认证设置已保存");
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

function openLogin() {
  window.open(`/auth/${config.app_code}/login`, "_blank");
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
.hint {
  margin-top: 5px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.color-row {
  display: flex;
  gap: 10px;
  width: 100%;
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
  color: var(--el-text-color-regular);
}
</style>
