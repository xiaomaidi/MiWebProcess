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

    <el-card shadow="never" class="sso-card">
      <template #header>
        <div class="sso-head">
          <div>
            <strong>企业 SSO（OpenID Connect）</strong>
            <p>配置企业的 OIDC 身份提供方，登录页会显示对应按钮。</p>
          </div>
          <el-button type="primary" @click="openProvider()">新建身份提供方</el-button>
        </div>
      </template>
      <el-table :data="providers" border stripe>
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="slug" label="标识" width="130" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? "启用" : "停用" }}</el-tag></template>
        </el-table-column>
        <el-table-column label="凭据" width="110">
          <template #default="{ row }"><el-tag :type="row.has_client_secret ? 'success' : 'warning'" size="small">{{ row.has_client_secret ? "已配置" : "未配置" }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="issuer" label="Issuer" min-width="220" show-overflow-tooltip />
        <el-table-column label="操作" width="150">
          <template #default="{ row }">
            <el-button size="small" @click="openProvider(row)">编辑</el-button>
            <el-button size="small" type="danger" link @click="deleteProvider(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="尚未配置企业 SSO" :image-size="50" /></template>
      </el-table>
    </el-card>

    <el-dialog v-model="ssoVisible" :title="ssoForm.id ? '编辑身份提供方' : '新建身份提供方'" width="640px">
      <el-form label-position="top">
        <el-row :gutter="12">
          <el-col :span="12"><el-form-item label="名称"><el-input v-model="ssoForm.name" placeholder="企业统一登录" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="标识 slug"><el-input v-model="ssoForm.slug" placeholder="corp-oidc" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="启用"><el-switch v-model="ssoForm.enabled" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="自动创建用户"><el-switch v-model="ssoForm.auto_create_user" /></el-form-item></el-col>
          <el-col :span="12">
            <el-form-item label="默认角色">
              <el-select v-model="ssoForm.default_role" style="width:100%"><el-option label="只读 viewer" value="viewer" /><el-option label="编辑 editor" value="editor" /></el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12"><el-form-item label="允许邮箱域名"><el-input v-model="ssoForm.domains" placeholder="company.com,group.com" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="Issuer"><el-input v-model="ssoForm.issuer" placeholder="https://id.example.com" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="Client ID"><el-input v-model="ssoForm.client_id" /></el-form-item></el-col>
          <el-col :span="12"><el-form-item label="Client Secret"><el-input v-model="ssoForm.client_secret" type="password" show-password :placeholder="ssoForm.has_client_secret ? '已配置，留空不修改' : '输入密钥'" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="Authorization Endpoint"><el-input v-model="ssoForm.authorization_endpoint" placeholder="https://id.example.com/oauth2/authorize" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="Token Endpoint"><el-input v-model="ssoForm.token_endpoint" placeholder="https://id.example.com/oauth2/token" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="UserInfo Endpoint"><el-input v-model="ssoForm.userinfo_endpoint" placeholder="https://id.example.com/oauth2/userinfo" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="Scopes"><el-input v-model="ssoForm.scopes" placeholder="openid profile email" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="ssoVisible = false">取消</el-button>
        <el-button type="primary" :loading="ssoSaving" @click="saveProvider">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId);
const loading = ref(true);
const saving = ref(false);
const providers = ref<any[]>([]);
const ssoVisible = ref(false);
const ssoSaving = ref(false);
const ssoForm = reactive<any>({ id: 0, name: "", slug: "", enabled: true, issuer: "", client_id: "", client_secret: "", has_client_secret: false, authorization_endpoint: "", token_endpoint: "", userinfo_endpoint: "", scopes: "openid profile email", auto_create_user: true, default_role: "viewer", domains: "" });
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
    await loadProviders();
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

async function loadProviders() {
  try {
    const data = await api.get<any>(`/apps/${appId}/sso/providers/`);
    providers.value = data.results || [];
  } catch {
    providers.value = [];
  }
}
function openProvider(row?: any) {
  Object.assign(ssoForm, {
    id: row?.id || 0, name: row?.name || "", slug: row?.slug || "", enabled: row?.enabled ?? true,
    issuer: row?.issuer || "", client_id: row?.client_id || "", client_secret: "", has_client_secret: !!row?.has_client_secret,
    authorization_endpoint: row?.authorization_endpoint || "", token_endpoint: row?.token_endpoint || "",
    userinfo_endpoint: row?.userinfo_endpoint || "", scopes: Array.isArray(row?.scopes) ? row.scopes.join(" ") : (row?.scopes || "openid profile email"),
    auto_create_user: row?.auto_create_user ?? true, default_role: row?.default_role || "viewer",
    domains: (row?.allowed_email_domains || []).join(","),
  });
  ssoVisible.value = true;
}
async function saveProvider() {
  ssoSaving.value = true;
  try {
    const payload: any = {
      name: ssoForm.name, slug: ssoForm.slug, enabled: ssoForm.enabled, issuer: ssoForm.issuer,
      client_id: ssoForm.client_id, authorization_endpoint: ssoForm.authorization_endpoint,
      token_endpoint: ssoForm.token_endpoint, userinfo_endpoint: ssoForm.userinfo_endpoint,
      scopes: ssoForm.scopes, auto_create_user: ssoForm.auto_create_user,
      default_role: ssoForm.default_role,
      allowed_email_domains: ssoForm.domains.split(",").map((x: string) => x.trim()).filter(Boolean),
    };
    if (ssoForm.client_secret) payload.client_secret = ssoForm.client_secret;
    if (ssoForm.id) await api.patch(`/apps/${appId}/sso/providers/${ssoForm.id}/`, payload);
    else await api.post(`/apps/${appId}/sso/providers/`, payload);
    ssoVisible.value = false;
    await loadProviders();
    ElMessage.success("SSO 配置已保存");
  } catch (e: any) {
    ElMessage.error(e?.detail || e?.message || "SSO 配置保存失败");
  } finally {
    ssoSaving.value = false;
  }
}
async function deleteProvider(row: any) {
  try { await ElMessageBox.confirm(`删除身份提供方「${row.name}」？`, "确认"); }
  catch { return; }
  await api.del(`/apps/${appId}/sso/providers/${row.id}/`);
  await loadProviders();
  ElMessage.success("已删除");
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
.sso-card { margin-top: 16px; }
.sso-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.sso-head p { margin: 4px 0 0; color: #94a3b8; font-size: 11px; }
</style>
