<template>
  <div class="mauth" :style="{ '--mauth-primary': config?.theme_color || '#2563eb' }">
    <div class="mauth-glow mauth-glow-a"></div>
    <div class="mauth-glow mauth-glow-b"></div>

    <section class="mauth-brand">
      <div class="mauth-brand-inner">
        <div class="mauth-logo">
          <img v-if="config?.logo_url" :src="config.logo_url" class="mauth-logo-img" alt="" />
          <span v-else class="mauth-logo-mark">{{ brandMark }}</span>
          <div>
            <div class="mauth-logo-name">{{ brandName }}</div>
            <div class="mauth-logo-sub">MiWebProcess 应用平台</div>
          </div>
        </div>

        <h1>让管理更简单<br />让协作更高效</h1>
        <p class="mauth-lead">
          {{ config?.login_subtitle || "统一管理企业数据、流程与协作，让每一个业务动作都清晰可追踪。" }}
        </p>

        <ul class="mauth-points">
          <li><span class="dot"></span><div><strong>统一账号</strong><small>平台身份，多应用通用</small></div></li>
          <li><span class="dot"></span><div><strong>应用级权限</strong><small>进入应用后按成员角色授权</small></div></li>
          <li><span class="dot"></span><div><strong>安全可控</strong><small>注册策略与访问范围由应用配置</small></div></li>
        </ul>

        <div class="mauth-copyright">© 2026 MiWebProcess · {{ brandName }}</div>
      </div>
    </section>

    <section class="mauth-panel">
      <div v-if="loadingConfig" class="mauth-card mauth-loading">
        <el-skeleton :rows="5" animated />
      </div>

      <div v-else-if="configError" class="mauth-card mauth-loading">
        <el-result icon="warning" title="无法加载登录配置" :sub-title="configError">
          <template #extra>
            <el-button type="primary" @click="loadConfig">重新加载</el-button>
          </template>
        </el-result>
      </div>

      <div v-else class="mauth-card">
        <div class="mauth-card-head">
          <div>
            <h2>{{ isRegister ? "创建账号" : "欢迎回来" }}</h2>
            <p>{{ isRegister ? `注册 ${brandName} 账号` : (config?.login_subtitle || `登录 ${brandName}`) }}</p>
          </div>
          <el-tag size="small" effect="plain" type="primary">{{ appCode }}</el-tag>
        </div>

        <el-alert
          v-if="config && !config.enabled"
          title="该应用已关闭登录"
          type="warning"
          :closable="false"
          show-icon
          class="mauth-error"
        />

        <el-form v-else :model="form" label-position="top" @submit.prevent="submit">
          <el-form-item label="账号">
            <el-input v-model="form.username" size="large" placeholder="请输入账号" autocomplete="username" clearable @keyup.enter="submit" />
          </el-form-item>

          <el-form-item v-if="isRegister" label="邮箱">
            <el-input v-model="form.email" size="large" placeholder="name@company.com" autocomplete="email" clearable @keyup.enter="submit" />
          </el-form-item>

          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" show-password placeholder="请输入密码" autocomplete="current-password" @keyup.enter="submit" />
          </el-form-item>

          <el-form-item v-if="isRegister" label="确认密码">
            <el-input v-model="form.confirm" size="large" type="password" show-password placeholder="请再次输入密码" autocomplete="new-password" @keyup.enter="submit" />
          </el-form-item>

          <el-form-item v-if="isRegister && config?.invite_required" label="邀请码">
            <el-input v-model="form.invite" size="large" placeholder="请输入邀请码" @keyup.enter="submit" />
          </el-form-item>

          <div v-if="!isRegister" class="mauth-row">
            <el-checkbox v-model="remember">记住账号</el-checkbox>
            <el-link type="primary" :underline="false" @click="forgot">忘记密码？</el-link>
          </div>

          <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mauth-error" />

          <el-button
            class="mauth-submit"
            type="primary"
            size="large"
            :loading="submitting"
            :style="{ background: config?.theme_color || '#2563eb', borderColor: config?.theme_color || '#2563eb' }"
            @click="submit"
          >
            {{ isRegister ? "注册并进入应用" : "登 录" }}
          </el-button>
        </el-form>

        <div v-if="config?.enabled" class="mauth-switch">
          <template v-if="isRegister">
            已有账号？
            <el-link type="primary" :underline="false" @click="switchMode(false)">返回登录</el-link>
          </template>
          <template v-else-if="config?.allow_register">
            还没有账号？
            <el-link type="primary" :underline="false" @click="switchMode(true)">立即注册</el-link>
          </template>
        </div>

        <div class="mauth-foot">
          <el-link :underline="false" @click="goPlatformLogin">平台登录</el-link>
          <span>·</span>
          <el-link :underline="false" @click="goHelp">帮助中心</el-link>
          <span>·</span>
          <span>MiWebProcess v2</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api, ApiError } from "@/api";
import { useAuthStore } from "@/store/auth";

interface AppAuthConfig {
  app_code: string;
  app_name: string;
  enabled: boolean;
  require_login: boolean;
  allow_register: boolean;
  invite_required: boolean;
  login_title: string;
  login_subtitle: string;
  logo_url: string;
  theme_color: string;
  redirect_path: string;
}

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const appCode = computed(() => String(route.params.appCode || ""));
const isRegister = computed(() => route.path.endsWith("/register"));
const loadingConfig = ref(true);
const configError = ref("");
const config = ref<AppAuthConfig | null>(null);
const submitting = ref(false);
const error = ref("");
const remember = ref(true);
const form = reactive({ username: "", email: "", password: "", confirm: "", invite: "" });

const brandName = computed(() => config.value?.login_title || config.value?.app_name || appCode.value || "MiWebProcess");
const brandMark = computed(() => (config.value?.app_name || appCode.value || "M").slice(0, 1).toUpperCase());

function targetPath(): string {
  const raw = typeof route.query.redirect === "string" ? route.query.redirect : "";
  if (raw.startsWith("/") && !raw.startsWith("//")) return raw;
  const configured = config.value?.redirect_path || "";
  if (configured.startsWith("/")) return configured;
  return `/run/${appCode.value}/${configured || "dashboard"}`;
}

async function loadConfig() {
  loadingConfig.value = true;
  configError.value = "";
  try {
    config.value = await api.get<AppAuthConfig>(`/runtime/${appCode.value}/auth-config/`, { silent: true });
    if (typeof document !== "undefined") document.title = `${isRegister.value ? "注册" : "登录"} · ${brandName.value}`;
  } catch (e: any) {
    configError.value = e?.message || "应用不存在或未配置登录";
  } finally {
    loadingConfig.value = false;
  }
}

function setSession(result: any) {
  auth.setTokenLocal(String(result.access || ""));
  auth.user = result.user;
}

async function submit() {
  if (submitting.value || !config.value) return;
  error.value = "";
  if (!form.username.trim()) { error.value = "请输入账号"; return; }
  if (!form.password) { error.value = "请输入密码"; return; }
  if (isRegister.value) {
    if (!form.email.trim() || !form.email.includes("@")) { error.value = "请输入有效邮箱"; return; }
    if (form.password.length < 8) { error.value = "密码至少 8 位"; return; }
    if (form.password !== form.confirm) { error.value = "两次输入的密码不一致"; return; }
    if (config.value.invite_required && !form.invite.trim()) { error.value = "请输入邀请码"; return; }
  }
  submitting.value = true;
  try {
    if (isRegister.value) {
      const result = await api.post<any>(`/runtime/${appCode.value}/auth/register/`, {
        username: form.username.trim(),
        email: form.email.trim(),
        password: form.password,
        invite_code: form.invite.trim(),
      });
      setSession(result);
      ElMessage.success("账号已创建");
    } else {
      const result = await api.post<any>(`/runtime/${appCode.value}/auth/login/`, {
        username: form.username.trim(),
        password: form.password,
      });
      setSession(result);
      ElMessage.success("登录成功");
    }
    router.push(targetPath());
  } catch (e) {
    if (e instanceof ApiError) {
      const data = e.data as any;
      error.value = String(data?.detail || data?.username?.[0] || data?.email?.[0] || data?.password?.[0] || data?.invite_code?.[0] || e.message || "操作失败");
    } else {
      error.value = "网络异常，请稍后重试";
    }
  } finally {
    submitting.value = false;
  }
}

function switchMode(register: boolean) {
  router.push({
    path: register ? `/auth/${appCode.value}/register` : `/auth/${appCode.value}/login`,
    query: route.query,
  });
}

function forgot() { ElMessage.info("请联系应用管理员重置密码"); }
function goPlatformLogin() { router.push("/login"); }
function goHelp() { router.push(`/run/${appCode.value}/help`); }

watch(() => route.fullPath, () => {
  if (config.value && typeof document !== "undefined") {
    document.title = `${isRegister.value ? "注册" : "登录"} · ${brandName.value}`;
  }
});

onMounted(loadConfig);
</script>

<style scoped>
.mauth {
  position: relative;
  display: flex;
  min-height: 100vh;
  overflow: hidden;
  background: #07101f;
  color: #0f172a;
}
.mauth-glow { position: absolute; width: 520px; height: 520px; border-radius: 50%; filter: blur(100px); opacity: .45; pointer-events: none; }
.mauth-glow-a { top: -180px; left: -120px; background: var(--mauth-primary); }
.mauth-glow-b { right: 20%; bottom: -260px; background: #0f766e; }
.mauth-brand { position: relative; z-index: 1; flex: 1; display: flex; align-items: center; padding: 64px; color: #e2e8f0; }
.mauth-brand-inner { width: min(520px, 100%); }
.mauth-logo { display: flex; align-items: center; gap: 12px; margin-bottom: 56px; }
.mauth-logo-mark { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 12px; background: linear-gradient(135deg, var(--mauth-primary), #1d4ed8); color: #fff; font-size: 22px; font-weight: 800; box-shadow: 0 8px 24px rgba(37,99,235,.45); }
.mauth-logo-img { width: 42px; height: 42px; border-radius: 12px; object-fit: cover; background: #fff; }
.mauth-logo-name { font-size: 20px; font-weight: 750; letter-spacing: .2px; color: #f8fafc; }
.mauth-logo-sub { margin-top: 2px; font-size: 11px; color: #93c5fd; letter-spacing: .5px; }
.mauth-brand h1 { margin: 0 0 18px; font-size: 38px; line-height: 1.35; font-weight: 750; color: #f8fafc; }
.mauth-lead { margin: 0 0 32px; max-width: 430px; font-size: 14px; line-height: 1.9; color: #bfdbfe; }
.mauth-points { display: grid; gap: 18px; margin: 0; padding: 0; list-style: none; }
.mauth-points li { display: flex; gap: 12px; align-items: flex-start; }
.mauth-points .dot { width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; background: #60a5fa; box-shadow: 0 0 0 5px rgba(96,165,250,.12); flex: none; }
.mauth-points strong { display: block; color: #f1f5f9; font-size: 14px; font-weight: 650; }
.mauth-points small { display: block; margin-top: 3px; color: #93a9c8; font-size: 12px; }
.mauth-copyright { margin-top: 56px; font-size: 11px; color: #64748b; }
.mauth-panel { position: relative; z-index: 2; display: flex; align-items: center; justify-content: center; width: 540px; flex: none; padding: 32px; background: #f6f8fc; }
.mauth-card { width: 100%; max-width: 420px; padding: 34px 32px 26px; border: 1px solid #e6edf7; border-radius: 18px; background: #fff; box-shadow: 0 24px 70px rgba(15,23,42,.16); }
.mauth-loading { min-height: 340px; display: flex; align-items: center; }
.mauth-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 22px; }
.mauth-card-head h2 { margin: 0; font-size: 26px; color: #0f172a; }
.mauth-card-head p { margin: 7px 0 0; font-size: 12px; color: #64748b; }
.mauth-row { display: flex; align-items: center; justify-content: space-between; margin: -4px 0 16px; }
.mauth-error { margin-bottom: 14px; }
.mauth-submit { width: 100%; height: 44px; margin-top: 4px; border-radius: 10px; font-size: 14px; letter-spacing: 1px; box-shadow: 0 8px 20px rgba(37,99,235,.25); }
.mauth-switch { margin-top: 18px; text-align: center; font-size: 12px; color: #64748b; }
.mauth-foot { display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 26px; padding-top: 16px; border-top: 1px solid #eef2f7; color: #94a3b8; font-size: 11px; }
.mauth-foot :deep(.el-link) { font-size: 11px; color: #64748b; }
@media (max-width: 960px) {
  .mauth-brand { display: none; }
  .mauth-panel { width: 100%; background: linear-gradient(135deg, #07101f 0%, #12244a 100%); }
  .mauth-card { max-width: 440px; }
}
@media (max-width: 520px) {
  .mauth-panel { padding: 18px; }
  .mauth-card { padding: 26px 20px 20px; border-radius: 14px; }
}
</style>
