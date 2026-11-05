<template>
  <el-container class="wp-admin-shell">
    <div v-if="mobileOpen" class="wp-admin-mask" @click="mobileOpen = false" />
    <el-aside width="248px" class="wp-admin-aside" :class="{ 'is-open': mobileOpen }">
      <div class="wp-admin-brand">
        <div class="wp-brand-mark">M</div>
        <div class="wp-brand-copy">
          <strong>MiWebProcess</strong>
          <span>NO-CODE PLATFORM</span>
        </div>
      </div>

      <el-menu :default-active="activeMenu" router class="wp-admin-menu" :default-openeds="['g-ai', 'g-biz', 'g-res', 'g-sys']">
        <el-menu-item index="/admin/apps">
          <el-icon><Grid /></el-icon>
          <span>工作台 · 应用</span>
        </el-menu-item>
        <el-menu-item index="/admin/notifications">
          <el-icon><Bell /></el-icon>
          <span>通知中心</span>
        </el-menu-item>

        <el-sub-menu index="g-ai">
          <template #title>
            <el-icon><MagicStick /></el-icon>
            <span>AI 与自动化</span>
          </template>
          <el-menu-item index="/admin/agent">
            <el-icon><MagicStick /></el-icon>
            <span>高级 Agent</span>
          </el-menu-item>
          <el-menu-item v-if="auth.isAdmin" index="/admin/ai">
            <el-icon><Monitor /></el-icon>
            <span>AI 管理</span>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="g-biz">
          <template #title>
            <el-icon><Checked /></el-icon>
            <span>业务运营</span>
          </template>
          <el-menu-item index="/admin/reviews">
            <el-icon><Checked /></el-icon>
            <span>内容审核</span>
          </el-menu-item>
          <el-menu-item index="/admin/workflows">
            <el-icon><Finished /></el-icon>
            <span>工作流待办</span>
          </el-menu-item>
          <el-menu-item index="/admin/org">
            <el-icon><OfficeBuilding /></el-icon>
            <span>组织架构</span>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu index="g-res">
          <template #title>
            <el-icon><Files /></el-icon>
            <span>资源</span>
          </template>
          <el-menu-item index="/admin/templates">
            <el-icon><Files /></el-icon>
            <span>模板中心</span>
          </el-menu-item>
          <el-menu-item index="/admin/market">
            <el-icon><Shop /></el-icon>
            <span>组件市场</span>
          </el-menu-item>
          <el-menu-item index="/admin/template-market">
            <el-icon><Shop /></el-icon>
            <span>模板市场</span>
          </el-menu-item>
          <el-menu-item v-if="auth.isAdmin" index="/admin/components">
            <el-icon><SetUp /></el-icon>
            <span>组件工坊</span>
          </el-menu-item>
        </el-sub-menu>

        <el-sub-menu v-if="auth.isAdmin" index="g-sys">
          <template #title>
            <el-icon><User /></el-icon>
            <span>系统</span>
          </template>
          <el-menu-item index="/admin/users">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/login-logs">
            <el-icon><Key /></el-icon>
            <span>登录日志</span>
          </el-menu-item>
          <el-menu-item index="/admin/enterprise">
            <el-icon><Monitor /></el-icon>
            <span>企业运维</span>
          </el-menu-item>
          <el-menu-item index="/admin/audit">
            <el-icon><Document /></el-icon>
            <span>审计日志</span>
          </el-menu-item>
          <el-menu-item index="/admin/security">
            <el-icon><Lock /></el-icon>
            <span>安全设置</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="wp-admin-side-foot">v1.0 · Local</div>
    </el-aside>

    <el-container class="wp-admin-body">
      <el-header class="wp-admin-header">
        <div class="wp-admin-left">
          <button class="wp-admin-mobile-toggle" @click="mobileOpen = !mobileOpen">
            <el-icon><Menu /></el-icon>
          </button>
          <div class="wp-admin-breadcrumb">
            <span>管理后台</span>
            <i>/</i>
            <strong>{{ pageTitle }}</strong>
          </div>
        </div>
        <div class="wp-admin-right">
          <el-tag size="small" type="success" effect="plain">运行中</el-tag>
          <el-dropdown @command="onCommand">
            <span class="wp-admin-user">
              <span class="wp-admin-avatar">{{ avatarText }}</span>
              <span class="wp-admin-user-name">{{ auth.displayName }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>
      <el-main class="wp-admin-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  ArrowDown, Checked, Document, Files, Finished, Grid, Key, Lock, MagicStick, Menu, Monitor,
  Bell, OfficeBuilding, SetUp, Shop, User,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/store/auth";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const mobileOpen = ref(false);

const pageTitle = computed(() => {
  const path = route.path;
  if (path === "/admin/apps") return "应用管理";
  if (/^\/admin\/apps\/\d+/.test(path)) return "应用详情";
  if (path.startsWith("/admin/templates")) return "模板中心";
  if (path.startsWith("/admin/market")) return "组件市场";
  if (path.startsWith("/admin/template-market")) return "模板市场";
  if (path.startsWith("/admin/components")) return "组件工坊";
  if (path.startsWith("/admin/agent")) return "高级 Agent";
  if (path.startsWith("/admin/ai")) return "AI 管理";
  if (path.startsWith("/admin/workflows")) return "工作流待办";
  if (path.startsWith("/admin/reviews")) return "内容审核";
  if (path.startsWith("/admin/org")) return "组织架构";
  if (path.startsWith("/admin/notifications")) return "通知中心";
  if (path.startsWith("/admin/enterprise")) return "企业运维";
  if (path.startsWith("/admin/audit")) return "审计日志";
  if (path.startsWith("/admin/users")) return "用户管理";
  if (path.startsWith("/admin/login-logs")) return "登录日志";
  if (path.startsWith("/admin/security")) return "安全设置";
  return "管理工作台";
});

const activeMenu = computed(() => {
  const path = route.path;
  if (/^\/admin\/apps\/\d+/.test(path) || path.startsWith("/admin/models")) return "/admin/apps";
  if (path.startsWith("/admin/market")) return "/admin/market";
  if (path.startsWith("/admin/template-market")) return "/admin/template-market";
  if (path.startsWith("/admin/templates")) return "/admin/templates";
  if (path.startsWith("/admin/components")) return "/admin/components";
  if (path.startsWith("/admin/agent")) return "/admin/agent";
  if (path.startsWith("/admin/ai")) return "/admin/ai";
  if (path.startsWith("/admin/workflows")) return "/admin/workflows";
  if (path.startsWith("/admin/reviews")) return "/admin/reviews";
  if (path.startsWith("/admin/org")) return "/admin/org";
  if (path.startsWith("/admin/notifications")) return "/admin/notifications";
  if (path.startsWith("/admin/enterprise")) return "/admin/enterprise";
  if (path.startsWith("/admin/audit")) return "/admin/audit";
  if (path.startsWith("/admin/users")) return "/admin/users";
  if (path.startsWith("/admin/login-logs")) return "/admin/login-logs";
  if (path.startsWith("/admin/security")) return "/admin/security";
  return "/admin/apps";
});

const avatarText = computed(() => String(auth.displayName || "A").slice(0, 1).toUpperCase());

function onCommand(command: string) {
  if (command === "logout") {
    auth.logout();
    ElMessage.success("已退出登录");
    router.push("/login");
  }
}

watch(() => route.path, () => { mobileOpen.value = false; });

onMounted(() => {
  auth.fetchUser().catch(() => {});
});
</script>

<style scoped>
.wp-admin-shell { height: 100vh; background: #f4f6fb; }
.wp-admin-aside {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #0f172a;
  color: #cbd5e1;
  border-right: 1px solid rgba(148, 163, 184, 0.12);
}
.wp-admin-brand { display: flex; align-items: center; gap: 10px; height: 70px; padding: 0 18px; border-bottom: 1px solid rgba(148, 163, 184, 0.12); }
.wp-brand-mark { display: flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #38bdf8); color: #fff; font-size: 16px; font-weight: 800; box-shadow: 0 6px 18px rgba(37, 99, 235, 0.32); }
.wp-brand-copy { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.wp-brand-copy strong { color: #f8fafc; font-size: 14px; letter-spacing: -0.2px; }
.wp-brand-copy span { color: #64748b; font-size: 8px; letter-spacing: 1.4px; }
.wp-admin-menu { flex: 1; overflow-y: auto; padding: 10px 9px; border-right: none; background: transparent; --el-menu-bg-color: transparent; --el-menu-hover-bg-color: rgba(148, 163, 184, 0.1); --el-menu-text-color: #94a3b8; --el-menu-active-color: #fff; }
.wp-admin-menu :deep(.el-sub-menu .el-menu),
.wp-admin-menu :deep(.el-menu--inline) { background: transparent !important; }
.wp-admin-menu :deep(.el-sub-menu) { background: transparent !important; }
.wp-admin-menu :deep(.el-menu-item),
.wp-admin-menu :deep(.el-sub-menu__title) { height: 40px; margin: 2px 0; border-radius: 9px; color: #94a3b8; font-size: 13px; }
.wp-admin-menu :deep(.el-menu-item:hover),
.wp-admin-menu :deep(.el-sub-menu__title:hover) { background: rgba(148, 163, 184, 0.1); color: #e2e8f0; }
.wp-admin-menu :deep(.el-menu-item.is-active) { background: linear-gradient(90deg, #2563eb, #1d4ed8); color: #fff; box-shadow: 0 6px 16px rgba(37, 99, 235, 0.3); }
.wp-admin-menu :deep(.el-sub-menu .el-menu-item) { min-width: 0; height: 36px; padding-left: 44px !important; font-size: 12px; }
.wp-admin-menu :deep(.el-sub-menu.is-opened > .el-sub-menu__title) { color: #e2e8f0; }
.wp-admin-side-foot { padding: 12px 18px; border-top: 1px solid rgba(148, 163, 184, 0.1); color: #475569; font-size: 10px; }
.wp-admin-body { min-width: 0; }
.wp-admin-header { display: flex; align-items: center; justify-content: space-between; height: 62px; padding: 0 24px; background: rgba(255, 255, 255, 0.92); border-bottom: 1px solid #e8edf5; backdrop-filter: blur(12px); }
.wp-admin-left, .wp-admin-right { display: flex; align-items: center; gap: 12px; }
.wp-admin-breadcrumb { display: flex; align-items: center; gap: 8px; color: #94a3b8; font-size: 12px; }
.wp-admin-breadcrumb i { color: #cbd5e1; font-style: normal; }
.wp-admin-breadcrumb strong { color: #0f172a; font-size: 13px; font-weight: 600; }
.wp-admin-user { display: inline-flex; align-items: center; gap: 8px; color: #334155; cursor: pointer; }
.wp-admin-avatar { display: flex; align-items: center; justify-content: center; width: 28px; height: 28px; border-radius: 50%; background: #e2e8f0; color: #475569; font-size: 11px; font-weight: 700; }
.wp-admin-user-name { max-width: 140px; overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.wp-admin-main { overflow-y: auto; padding: 24px; background: #f4f6fb; }
.wp-admin-mobile-toggle { display: none; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; color: #475569; cursor: pointer; }
.wp-admin-mask { display: none; }

@media (max-width: 900px) {
  .wp-admin-aside { position: fixed; top: 0; bottom: 0; left: 0; z-index: 3001; transform: translateX(-100%); transition: transform 0.22s ease; box-shadow: 16px 0 40px rgba(15, 23, 42, 0.3); }
  .wp-admin-aside.is-open { transform: translateX(0); }
  .wp-admin-mask { position: fixed; inset: 0; z-index: 3000; display: block; background: rgba(15, 23, 42, 0.45); }
  .wp-admin-mobile-toggle { display: inline-flex; }
  .wp-admin-header { padding: 0 14px; }
  .wp-admin-main { padding: 16px; }
  .wp-admin-breadcrumb span, .wp-admin-breadcrumb i { display: none; }
  .wp-admin-user-name { display: none; }
}
</style>
