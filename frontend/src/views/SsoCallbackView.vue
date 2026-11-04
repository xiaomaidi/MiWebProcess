<template>
  <div class="wp-sso-callback">
    <div class="wp-sso-card">
      <div class="wp-sso-logo">M</div>
      <h1>{{ error ? "登录未完成" : "正在完成企业登录" }}</h1>
      <p v-if="!error">正在验证身份并进入应用，请稍候…</p>
      <el-result v-else icon="warning" title="SSO 登录失败" :sub-title="error">
        <template #extra>
          <el-button type="primary" @click="backToLogin">返回登录</el-button>
        </template>
      </el-result>
      <el-progress v-if="!error" :percentage="100" :show-text="false" :indeterminate="true" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { setToken } from "@/api";
import { useAuthStore } from "@/store/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const error = ref("");

function readParams(): Record<string, string> {
  const out: Record<string, string> = {};
  const hash = typeof window !== "undefined" ? window.location.hash.replace(/^#/, "") : "";
  const sources = [route.query, Object.fromEntries(new URLSearchParams(hash))];
  for (const source of sources) {
    for (const [key, value] of Object.entries(source)) {
      if (value !== undefined && value !== null) out[key] = String(value);
    }
  }
  return out;
}

async function finish() {
  const params = readParams();
  if (params.error) {
    error.value = params.error_description || `SSO 登录失败：${params.error}`;
    return;
  }
  const access = params.access_token || params.access;
  if (!access) {
    error.value = "未收到登录令牌，请重新发起 SSO 登录";
    return;
  }
  setToken(access);
  auth.setTokenLocal(access);
  try {
    await auth.fetchUser();
  } catch {
    /* token can still be valid for the runtime */
  }
  const appCode = params.app_code || "";
  let target = params.redirect || (appCode ? `/run/${appCode}` : "/admin/apps");
  if (!target.startsWith("/") || target.startsWith("//")) target = appCode ? `/run/${appCode}` : "/admin/apps";
  router.replace(target);
}

function backToLogin() {
  const appCode = readParams().app_code;
  router.replace(appCode ? `/auth/${appCode}/login` : "/login");
}

onMounted(finish);
</script>

<style scoped>
.wp-sso-callback { display: flex; min-height: 100vh; align-items: center; justify-content: center; background: #f4f6fb; }
.wp-sso-card { width: 380px; padding: 34px; border: 1px solid #e8edf5; border-radius: 18px; background: #fff; text-align: center; box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08); }
.wp-sso-logo { display: flex; align-items: center; justify-content: center; width: 42px; height: 42px; margin: 0 auto 14px; border-radius: 12px; background: linear-gradient(135deg, #2563eb, #38bdf8); color: #fff; font-weight: 800; }
.wp-sso-card h1 { margin: 0 0 8px; color: #0f172a; font-size: 21px; }
.wp-sso-card p { margin: 0 0 18px; color: #64748b; font-size: 12px; }
</style>
