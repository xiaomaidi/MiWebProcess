<template>
  <div class="wp-login-shell">
    <section class="wp-login-brand">
      <div class="wp-login-logo">
        <span>M</span>
        <strong>MiWebProcess</strong>
      </div>
      <div class="wp-login-copy">
        <span class="wp-login-eyebrow">NO-CODE PLATFORM</span>
        <h1>把业务想法<br />变成可运行的应用</h1>
        <p>页面、数据、权限、工作流和 AI，统一在一个平台里完成。</p>
      </div>
      <div class="wp-login-features">
        <div><i>01</i><span>可视化页面设计</span></div>
        <div><i>02</i><span>数据模型与工作流</span></div>
        <div><i>03</i><span>AI 辅助构建</span></div>
      </div>
      <div class="wp-login-brand-foot">MiWebProcess v1.0 · Local</div>
    </section>

    <section class="wp-login-panel">
      <div class="wp-login-card">
        <div class="wp-login-mobile-brand">
          <span>M</span>
          <strong>MiWebProcess</strong>
        </div>
        <span class="wp-login-eyebrow">SIGN IN</span>
        <h2>登录工作台</h2>
        <p class="wp-login-subtitle">使用平台统一账号继续</p>

        <el-form :model="form" class="wp-login-form" @submit.prevent="onSubmit">
          <el-form-item>
            <el-input v-model="form.username" size="large" placeholder="用户名" clearable @keyup.enter="onSubmit" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="form.password" size="large" type="password" placeholder="密码" show-password @keyup.enter="onSubmit" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" size="large" :loading="submitting" class="wp-login-submit" @click="onSubmit">
              登录
            </el-button>
          </el-form-item>
        </el-form>

        <div class="wp-login-foot">
          <span>平台统一账号登录</span>
          <span>v1.0</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { ApiError } from "@/api";
import { useAuthStore } from "@/store/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const submitting = ref(false);
const form = reactive({ username: "", password: "" });

async function onSubmit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning("请输入用户名和密码");
    return;
  }
  submitting.value = true;
  try {
    await auth.login(form.username.trim(), form.password);
    let redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/admin/apps";
    if (!redirect.startsWith("/") || redirect.startsWith("//")) redirect = "/admin/apps";
    router.push(redirect);
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : "登录失败，请稍后重试";
    ElMessage.error(msg);
  } finally {
    submitting.value = false;
  }
}
</script>

<style scoped>
.wp-login-shell { display: flex; min-height: 100vh; background: #f8fafc; }
.wp-login-brand {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  width: 46%;
  min-width: 420px;
  padding: 40px 54px;
  overflow: hidden;
  background: radial-gradient(circle at 80% 20%, rgba(56, 189, 248, 0.25), transparent 35%), #0f172a;
  color: #e2e8f0;
}
.wp-login-brand::after {
  position: absolute;
  right: -80px;
  bottom: -120px;
  width: 340px;
  height: 340px;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 50%;
  content: "";
}
.wp-login-logo { display: flex; align-items: center; gap: 10px; }
.wp-login-logo span,
.wp-login-mobile-brand span { display: flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #38bdf8); color: #fff; font-weight: 800; }
.wp-login-logo strong { color: #f8fafc; font-size: 15px; }
.wp-login-copy { position: relative; z-index: 1; max-width: 480px; }
.wp-login-eyebrow { display: inline-block; margin-bottom: 12px; color: #38bdf8; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
.wp-login-copy h1 { margin: 0 0 16px; color: #f8fafc; font-size: 42px; line-height: 1.22; letter-spacing: -1.5px; }
.wp-login-copy p { margin: 0; color: #94a3b8; font-size: 14px; line-height: 1.7; }
.wp-login-features { position: relative; z-index: 1; display: flex; gap: 12px; }
.wp-login-features div { display: flex; flex-direction: column; gap: 6px; min-width: 110px; padding: 12px; border: 1px solid rgba(148, 163, 184, 0.18); border-radius: 10px; background: rgba(15, 23, 42, 0.35); }
.wp-login-features i { color: #38bdf8; font-size: 10px; font-style: normal; font-weight: 700; }
.wp-login-features span { color: #cbd5e1; font-size: 11px; }
.wp-login-brand-foot { color: #475569; font-size: 10px; }
.wp-login-panel { display: flex; flex: 1; align-items: center; justify-content: center; padding: 32px; }
.wp-login-card { width: 100%; max-width: 400px; padding: 34px 32px; border: 1px solid #e8edf5; border-radius: 18px; background: #fff; box-shadow: 0 20px 60px rgba(15, 23, 42, 0.08); }
.wp-login-mobile-brand { display: none; align-items: center; gap: 9px; margin-bottom: 26px; color: #0f172a; font-size: 14px; }
.wp-login-card h2 { margin: 0 0 6px; color: #0f172a; font-size: 26px; letter-spacing: -0.5px; }
.wp-login-subtitle { margin: 0 0 24px; color: #94a3b8; font-size: 12px; }
.wp-login-form :deep(.el-form-item) { margin-bottom: 14px; }
.wp-login-form :deep(.el-input__wrapper) { border-radius: 8px; box-shadow: 0 0 0 1px #e2e8f0 inset; }
.wp-login-form :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 1px #2563eb inset; }
.wp-login-submit { width: 100%; margin-top: 4px; border-radius: 8px; font-weight: 600; }
.wp-login-foot { display: flex; justify-content: space-between; margin-top: 24px; padding-top: 14px; border-top: 1px solid #f1f5f9; color: #94a3b8; font-size: 10px; }

@media (max-width: 860px) {
  .wp-login-brand { display: none; }
  .wp-login-panel { padding: 20px; }
  .wp-login-card { padding: 26px 22px; }
  .wp-login-mobile-brand { display: flex; }
}
</style>
