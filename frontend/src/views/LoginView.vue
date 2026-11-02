<template>
  <div class="wp-login">
    <div class="wp-login-card">
      <h1 class="wp-login-title">MiWebProcess</h1>
      <p class="wp-login-subtitle">无代码页面构建平台 · 登录</p>
      <el-form :model="form" @submit.prevent="onSubmit">
        <el-form-item label="用户名">
          <el-input
            v-model="form.username"
            placeholder="请输入用户名"
            clearable
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            show-password
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" style="width: 100%" @click="onSubmit">
            登 录
          </el-button>
        </el-form-item>
      </el-form>
    </div>
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
    // 仅允许站内相对路径，防止开放重定向
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
.wp-login {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #e8f0fe 0%, #f5f7fa 100%);
}
.wp-login-card {
  width: 380px;
  padding: 32px 28px;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08);
}
.wp-login-title {
  margin: 0 0 4px;
  font-size: 24px;
  text-align: center;
}
.wp-login-subtitle {
  margin: 0 0 24px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
</style>
