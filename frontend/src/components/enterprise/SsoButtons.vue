<template>
  <div v-if="providers.length" class="wp-sso">
    <div class="wp-sso-divider"><span>或使用企业账号登录</span></div>
    <div class="wp-sso-list">
      <el-button
        v-for="provider in providers"
        :key="provider.slug"
        class="wp-sso-button"
        :loading="starting === provider.slug"
        @click="start(provider)"
      >
        <span class="wp-sso-mark">SSO</span>
        {{ provider.name }}
      </el-button>
    </div>
    <p v-if="error" class="wp-sso-error">{{ error }}</p>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "@/api";

const props = withDefaults(defineProps<{ appCode: string; redirect?: string }>(), { redirect: "" });
const providers = ref<{ name: string; slug: string }[]>([]);
const starting = ref("");
const error = ref("");

async function load() {
  if (!props.appCode) return;
  try {
    const data = await api.get<any>(`/auth/sso/${encodeURIComponent(props.appCode)}/providers/`, { silent: true });
    providers.value = Array.isArray(data?.results) ? data.results : [];
  } catch {
    providers.value = [];
  }
}

async function start(provider: { name: string; slug: string }) {
  starting.value = provider.slug;
  error.value = "";
  try {
    const redirect = props.redirect || (typeof window !== "undefined" ? window.location.pathname + window.location.search : "");
    const data = await api.get<any>(
      `/auth/sso/${encodeURIComponent(props.appCode)}/${encodeURIComponent(provider.slug)}/start/?mode=redirect&redirect=${encodeURIComponent(redirect)}`
    );
    if (data?.authorize_url) window.location.assign(data.authorize_url);
    else error.value = "身份提供方未返回授权地址";
  } catch (e: any) {
    error.value = e?.detail || e?.error_description || e?.message || "SSO 登录启动失败";
  } finally {
    starting.value = "";
  }
}

onMounted(load);
</script>

<style scoped>
.wp-sso { margin-top: 18px; }
.wp-sso-divider { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; color: #94a3b8; font-size: 11px; }
.wp-sso-divider::before, .wp-sso-divider::after { flex: 1; height: 1px; background: #eef2f7; content: ""; }
.wp-sso-list { display: flex; flex-direction: column; gap: 8px; }
.wp-sso-button { width: 100%; height: 40px; border-radius: 9px; }
.wp-sso-mark { margin-right: 6px; padding: 1px 4px; border-radius: 4px; background: #eff6ff; color: #2563eb; font-size: 9px; font-weight: 700; }
.wp-sso-error { margin: 8px 0 0; color: #dc2626; font-size: 11px; }
</style>
