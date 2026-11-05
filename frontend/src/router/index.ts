import { createRouter, createWebHistory, type RouterHistory } from "vue-router";
import { useAuthStore } from "@/store/auth";
import { api } from "@/api";

const appAuthCache = new Map<string, { at: number; config: any }>();

async function appAuthConfig(appCode: string): Promise<any | null> {
  if (!appCode) return null;
  const cached = appAuthCache.get(appCode);
  if (cached && Date.now() - cached.at < 30000) return cached.config;
  try {
    const config = await api.get<any>(`/runtime/${appCode}/auth-config/`, { silent: true });
    appAuthCache.set(appCode, { at: Date.now(), config });
    return config;
  } catch {
    return null;
  }
}

const routes = [
    { path: "/", redirect: "/admin/apps" },
    {
      path: "/portal",
      name: "portal",
      component: () => import("@/views/PortalView.vue"),
      meta: { public: true },
    },
    {
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
      meta: { public: true },
    },
    {
      path: "/sso/callback",
      name: "sso-callback",
      component: () => import("@/views/SsoCallbackView.vue"),
      meta: { public: true },
    },
    {
      path: "/auth/:appCode/login",
      name: "app-auth-login",
      component: () => import("@/views/AppAuthView.vue"),
      meta: { public: true },
    },
    {
      path: "/auth/:appCode/register",
      name: "app-auth-register",
      component: () => import("@/views/AppAuthView.vue"),
      meta: { public: true },
    },
    {
      path: "/miadmin/login",
      redirect: (to: any) => ({ path: "/auth/mi-admin/login", query: to.query }),
    },
    {
      path: "/miadmin/register",
      redirect: (to: any) => ({ path: "/auth/mi-admin/register", query: to.query }),
    },
    {
      path: "/admin",
      component: () => import("@/views/AdminLayout.vue"),
      children: [
        { path: "", redirect: "/admin/apps" },
        {
          path: "apps",
          name: "admin-apps",
          component: () => import("@/views/admin/AppsView.vue"),
        },
        {
          path: "market",
          name: "admin-market",
          component: () => import("@/views/admin/MarketView.vue"),
        },
        {
          path: "notifications",
          name: "admin-notifications",
          component: () => import("@/views/admin/NotificationCenterView.vue"),
        },
        {
          path: "enterprise",
          name: "admin-enterprise",
          component: () => import("@/views/admin/EnterpriseConsoleView.vue"),
        },
        {
          path: "agent",
          name: "admin-agent",
          component: () => import("@/views/admin/AgentCenterView.vue"),
        },
        {
          path: "agent/evals",
          name: "admin-agent-evals",
          component: () => import("@/views/admin/AgentEvalsView.vue"),
        },
        {
          path: "templates",
          name: "admin-templates",
          component: () => import("@/views/admin/TemplatesView.vue"),
        },
        {
          path: "template-market",
          name: "admin-template-market",
          component: () => import("@/views/admin/TemplateMarketView.vue"),
        },
        {
          path: "apps/:appId/design-tokens",
          name: "admin-app-design",
          component: () => import("@/views/admin/AppDesignView.vue"),
        },
        {
          path: "apps/:appId/services",
          name: "admin-app-services",
          component: () => import("@/views/admin/AppServicesView.vue"),
        },
        {
          path: "apps/:appId/settings",
          name: "admin-app-settings",
          component: () => import("@/views/admin/AppSettingsView.vue"),
        },
        {
          path: "apps/:appId/auth",
          name: "admin-app-auth",
          component: () => import("@/views/admin/AuthSettingsView.vue"),
        },
        {
          path: "apps/:appId",
          name: "admin-app-detail",
          component: () => import("@/views/admin/AppDetailView.vue"),
        },
        {
          path: "apps/:appId/ops",
          name: "admin-app-ops",
          component: () => import("@/views/admin/AppOpsView.vue"),
        },
        {
          path: "org",
          name: "admin-org",
          component: () => import("@/views/admin/OrgView.vue"),
        },
        {
          path: "components",
          name: "admin-components",
          component: () => import("@/views/admin/ComponentsView.vue"),
        },
        {
          path: "reviews",
          name: "admin-reviews",
          component: () => import("@/views/admin/ReviewCenterView.vue"),
        },
        {
          path: "models/:modelId",
          name: "admin-record-manager",
          component: () => import("@/views/RecordManagerView.vue"),
        },
        {
          path: "models/:modelId/report",
          name: "admin-report-builder",
          component: () => import("@/views/ReportBuilderView.vue"),
        },
        {
          path: "workflows",
          name: "admin-workflows",
          component: () => import("@/views/WorkflowTasksView.vue"),
        },
        {
          path: "audit",
          name: "admin-audit",
          component: () => import("@/views/admin/AuditView.vue"),
        },
        {
          path: "users",
          name: "admin-users",
          component: () => import("@/views/admin/UsersView.vue"),
        },
        {
          path: "login-logs",
          name: "admin-login-logs",
          component: () => import("@/views/admin/LoginLogsView.vue"),
        },
        {
          path: "security",
          name: "admin-security",
          component: () => import("@/views/admin/SecuritySettingsView.vue"),
        },
        {
          path: "ai",
          name: "admin-ai",
          component: () => import("@/views/admin/AiSettingsView.vue"),
        },
      ],
    },
    {
      path: "/design/:appId/:pageId",
      name: "designer",
      component: () => import("@/designer/DesignerView.vue"),
    },
    {
      path: "/workflow/design/:appId",
      name: "workflow-designer",
      component: () => import("@/views/WorkflowDesignerView.vue"),
    },
    {
      path: "/preview/:appId/:pageId",
      name: "preview",
      component: () => import("@/views/PreviewView.vue"),
      meta: { public: true },
    },
    {
      path: "/run/:appCode/record/:modelId/:recordId",
      name: "runtime-record-detail",
      component: () => import("@/views/RecordDetailView.vue"),
      meta: { public: true },
    },
    {
      path: "/run/:appCode",
      name: "runtime",
      component: () => import("@/views/RuntimeView.vue"),
      meta: { public: true },
    },
    {
      // Vue Router 4 兼容写法；参数名为 pathMatch，RuntimeView 会同时兼容 splat/pathMatch。
      path: "/run/:appCode/:pathMatch(.*)*",
      name: "runtime-deep",
      component: () => import("@/views/RuntimeView.vue"),
      meta: { public: true },
    },
    { path: "/:pathMatch(.*)*", redirect: "/admin/apps" },
];

/** 路由工厂：浏览器用 WebHistory，SSR 用 MemoryHistory，两者共享同一份路由表。 */
export function createAppRouter(history?: RouterHistory) {
  const router = createRouter({
    history: history ?? createWebHistory(),
    routes,
  });

  router.beforeEach(async (to) => {
    if (typeof window === "undefined") return true;
    const auth = useAuthStore();
    // 阻止 /admin/apps/NaN、/design/undefined/... 这类坏链接继续发请求。
    const rawAppId = to.params.appId;
    if (rawAppId !== undefined) {
      const value = String(rawAppId);
      if (!/^\d+$/.test(value) || Number(value) <= 0) {
        return { path: "/admin/apps", query: { invalid_app: value } };
      }
    }
    const rawPageId = to.params.pageId;
    if (rawPageId !== undefined) {
      const value = String(rawPageId);
      if (!/^\d+$/.test(value) || Number(value) <= 0) {
        return { path: "/admin/apps", query: { invalid_page: value } };
      }
    }
    const appCode = String(to.params.appCode || "");
    // 运行时页面按应用配置决定是否需要登录。
    if (to.path.startsWith("/run/") && appCode && !auth.isLoggedIn) {
      const config = await appAuthConfig(appCode);
      if (config?.require_login) {
        return { path: `/auth/${appCode}/login`, query: { redirect: to.fullPath } };
      }
    }
    if (!to.meta.public && !auth.isLoggedIn) {
      return { path: "/login", query: { redirect: to.fullPath } };
    }
    if (to.path === "/login" && auth.isLoggedIn) return { path: "/admin/apps" };
    return true;
  });

  return router;
}

// 默认路由实例只用于浏览器入口；SSR 侧通过 createAppRouter(createMemoryHistory()) 创建，
// 避免在 Node 中执行 createWebHistory 访问 window。
const router = typeof window === "undefined" ? (null as unknown as ReturnType<typeof createAppRouter>) : createAppRouter();

export default router;
