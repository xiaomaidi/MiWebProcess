<template>
  <el-container class="wp-admin">
    <el-aside width="200px" class="wp-admin-aside">
      <div class="wp-admin-brand">MiWebProcess</div>
      <el-menu :default-active="activeMenu" router class="wp-admin-menu">
        <el-menu-item index="/admin/apps">
          <el-icon><Grid /></el-icon>
          <span>应用</span>
        </el-menu-item>
        <el-menu-item index="/admin/templates">
          <el-icon><Files /></el-icon>
          <span>模板中心</span>
        </el-menu-item>
        <el-menu-item index="/admin/template-market">
          <el-icon><Shop /></el-icon>
          <span>模板市场</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/components">
          <el-icon><SetUp /></el-icon>
          <span>组件工坊</span>
        </el-menu-item>
        <el-menu-item index="/admin/reviews">
          <el-icon><Checked /></el-icon>
          <span>内容审核</span>
        </el-menu-item>
        <el-menu-item index="/admin/org">
          <el-icon><OfficeBuilding /></el-icon>
          <span>组织架构</span>
        </el-menu-item>
        <el-menu-item index="/admin/agent">
          <el-icon><MagicStick /></el-icon>
          <span>高级 Agent</span>
        </el-menu-item>
        <el-menu-item index="/admin/workflows">
          <el-icon><Finished /></el-icon>
          <span>工作流待办</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/ai">
          <el-icon><MagicStick /></el-icon>
          <span>AI 管理</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/audit">
          <el-icon><Document /></el-icon>
          <span>审计日志</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/users">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/login-logs">
          <el-icon><Key /></el-icon>
          <span>登录日志</span>
        </el-menu-item>
        <el-menu-item v-if="auth.isAdmin" index="/admin/security">
          <el-icon><Lock /></el-icon>
          <span>安全设置</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="wp-admin-header">
        <span class="wp-admin-title">管理后台</span>
        <el-dropdown @command="onCommand">
          <span class="wp-admin-user">
            <el-icon><UserFilled /></el-icon>
            {{ auth.displayName }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="wp-admin-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { Grid, Document, User, UserFilled, ArrowDown, Finished, MagicStick, Checked, OfficeBuilding, SetUp, Key, Files, Shop, Lock } from "@element-plus/icons-vue";
import { useAuthStore } from "@/store/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const activeMenu = computed(() => {
  const path = route.path;
  if (path.startsWith("/admin/agent")) return "/admin/agent";
  if (path.startsWith("/admin/workflows")) return "/admin/workflows";
  if (path.startsWith("/admin/components")) return "/admin/components";
  if (path.startsWith("/admin/reviews")) return "/admin/reviews";
  if (path.startsWith("/admin/org")) return "/admin/org";
  if (path.startsWith("/admin/ai")) return "/admin/ai";
  if (path.startsWith("/admin/models")) return "/admin/apps";
  if (path.startsWith("/admin/audit")) return "/admin/audit";
  if (path.startsWith("/admin/users")) return "/admin/users";
  return "/admin/apps";
});

function onCommand(command: string) {
  if (command === "logout") {
    auth.logout();
    ElMessage.success("已退出登录");
    router.push("/login");
  }
}

onMounted(() => {
  auth.fetchUser().catch(() => {});
});
</script>

<style scoped>
.wp-admin {
  height: 100vh;
}
.wp-admin-aside {
  background: #fff;
  border-right: 1px solid var(--el-border-color-light);
}
.wp-admin-brand {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.wp-admin-menu {
  border-right: none;
}
.wp-admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid var(--el-border-color-light);
}
.wp-admin-title {
  font-weight: 600;
}
.wp-admin-user {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: var(--el-text-color-regular);
}
.wp-admin-main {
  background: #f5f7fa;
}
</style>
