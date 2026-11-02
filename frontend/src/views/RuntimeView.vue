<template>
  <div class="wp-runtime" :style="pageStyle">
    <div v-if="loading && !rootNode" class="wp-runtime-tip">加载中…</div>
    <div v-else-if="error && !rootNode" class="wp-runtime-tip wp-runtime-error">{{ error }}</div>
    <NodeRenderer v-else-if="rootNode" :node="rootNode" :nodes="nodes" :mode="'runtime'" :layout-mode="layoutMode" />
    <div v-else class="wp-runtime-tip">空页面</div>
    <div v-if="loading && rootNode" class="wp-route-progress" aria-label="页面加载中"><i /></div>
    <div v-if="scope.coordinationErrors?.length" class="wp-coordination-panel">
      <div class="wp-coordination-head">
        <strong>协同错误</strong>
        <button type="button" @click="scope.coordinationErrors?.splice(0)">清除</button>
      </div>
      <ul>
        <li v-for="(item, index) in scope.coordinationErrors" :key="index">{{ item }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "@/api";
import { createRuntimeScope } from "@/engine/scope";
import { installRuntimeBridge } from "@/engine/runtime-bridge";
import { runSteps } from "@/engine/actions";
import { tokensToCssVars } from "@/design/tokens";
import NodeRenderer from "@/engine/NodeRenderer.vue";
import { consumeSsrState } from "@/ssr/state";
import type { AppInfo, DataSourceDef, PageSchema, RuntimeScope, SchemaNode } from "@/types";

export interface RuntimePayload {
  app: { code: string; name: string; design_tokens?: Record<string, any> };
  page: { id: number; name: string; path: string; resolved_path?: string; params?: Record<string, string> };
  route_params?: Record<string, string>;
  page_version: { version: number; schema: PageSchema; published_at: string };
  config: {
    components: unknown[];
    datasources: { id: number; name: string; type: string; public_config?: Record<string, any> }[];
    modules?: Record<string, boolean>;
  };
}

function routePath(): string {
  const splat = route.params.splat ?? route.params.pathMatch;
  return (Array.isArray(splat) ? splat.join("/") : String(splat ?? "")).replace(/^\//, "").trim();
}

const route = useRoute();
const router = useRouter();

const appCode = String(route.params.appCode ?? "");

// SSR：服务端已渲染并注入 __WP_SSR__，首屏直接复用，避免重复请求与闪屏。
const ssrState = consumeSsrState();
const initialPayload: RuntimePayload | null =
  ssrState && ssrState.url.replace(/\/$/, "") === route.fullPath.replace(/\/$/, "")
    ? (ssrState.payload as RuntimePayload)
    : null;

const loading = ref(!initialPayload);
const error = ref("");
const schema = ref<PageSchema | null>(initialPayload?.page_version?.schema ?? null);
const modules = ref<Record<string, boolean>>((initialPayload as any)?.config?.modules || {});
const pageCache = new Map<string, RuntimePayload>();
const scrollPositions = new Map<string, number>();
let lastPath = initialPayload ? routePath() : "";
if (initialPayload) pageCache.set(routePath(), initialPayload);

function restoreScroll(path: string): void {
  if (typeof window === "undefined") return;
  void nextTick(() => {
    window.scrollTo({ top: scrollPositions.get(path) || 0, behavior: "auto" });
  });
}

const rootNode = computed(() => (schema.value ? (schema.value.nodes[schema.value.rootId] ?? null) : null));
const layoutMode = computed<"flow" | "free" | undefined>(() => schema.value?.layout?.mode);
const nodes = computed<Record<string, SchemaNode>>(() => filterModuleNodes(schema.value?.nodes ?? {}, modules.value));

function moduleForPath(path: string): string {
  const value = String(path || "").replace(/^\/+/, "");
  if (value.startsWith("cms/")) return "cms";
  if (value.startsWith("crm/")) return "crm";
  if (value.startsWith("members/")) return "members";
  if (value.startsWith("workflow/")) return "workflow";
  if (value.startsWith("reports/")) return "reports";
  if (value.startsWith("account/") || value.startsWith("auth/") || value.startsWith("system/")) return "auth";
  return "core";
}

function filterModuleNodes(raw: Record<string, SchemaNode>, enabled: Record<string, boolean>): Record<string, SchemaNode> {
  if (!enabled || !Object.keys(enabled).length) return raw;
  const out: Record<string, SchemaNode> = {};
  for (const [id, node] of Object.entries(raw)) out[id] = { ...node, children: [...(node.children || [])] };
  for (const node of Object.values(out)) {
    if (node.type !== "ElMenuItem") continue;
    const path = String((node.props as any)?.index || "");
    if (!path || path.startsWith("group-")) continue;
    const key = moduleForPath(path);
    if (enabled[key] === false) {
      for (const parent of Object.values(out)) {
        parent.children = (parent.children || []).filter((childId) => childId !== node.id);
      }
    }
  }
  return out;
}
const pageStyle = computed<Record<string, any>>(() => {
  const m = schema.value?.meta;
  return { ...(m?.background || {}), minHeight: "100vh" };
});

function navigateByPagePath(path: string) {
  const seg = String(path ?? "").replace(/^\//, "").trim();
  router.push(seg ? `/run/${appCode}/${seg}` : `/run/${appCode}`);
}

const scope: RuntimeScope = createRuntimeScope({
  app: {
    id: 0,
    name: "",
    code: appCode,
    owner_id: 0,
    status: "published",
    version: 0,
    created_at: "",
    updated_at: "",
  } as AppInfo,
  pageId: 0,
  pageVersion: 0,
  datasources: [] as DataSourceDef[],
  models: [],
  variables: {},
  routeParams: {},
  routePath: "",
  navigate: navigateByPagePath,
  setNodeStyle(nodeId: string, style: Record<string, any>) {
    const n = schema.value?.nodes?.[nodeId];
    if (n) n.style = { ...(n.style || {}), ...style };
  },
});
provide("wp.scope", scope);
const disposeBridge = installRuntimeBridge(scope);

let pageCssEl: HTMLStyleElement | null = null;

function setMetaTag(attr: "name" | "property", key: string, content: string) {
  if (!content) return;
  let el = document.head.querySelector(`meta[${attr}="${key}"]`) as HTMLMetaElement | null;
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

function applyPageMeta(s: PageSchema, fallbackTitle: string, appTokens?: Record<string, any>) {
  if (typeof document === "undefined") return;
  const m = s.meta || {};
  const tokens = (m as any).useAppTokens && appTokens ? appTokens : (m.designTokens || appTokens);
  document.title = m.title || fallbackTitle;
  document.documentElement.lang = m.lang || "zh-CN";
  if (m.favicon && /^(https?:\/\/|\/|\.\/|\.\.\/)/i.test(m.favicon)) {
    let link = document.head.querySelector('link[rel="icon"]') as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.rel = "icon";
      document.head.appendChild(link);
    }
    link.href = m.favicon;
  }
  setMetaTag("name", "description", m.seo?.description || m.description || "");
  setMetaTag("name", "keywords", m.seo?.keywords || m.keywords || "");
  setMetaTag("property", "og:image", m.seo?.ogImage || m.ogImage || "");
  setMetaTag("property", "og:title", m.title || fallbackTitle);
  setMetaTag("property", "og:url", window.location.href);
  let canonical = document.head.querySelector('link[rel="canonical"]') as HTMLLinkElement | null;
  if (!canonical) {
    canonical = document.createElement("link");
    canonical.rel = "canonical";
    document.head.appendChild(canonical);
  }
  canonical.href = window.location.href;
  for (const [key, value] of Object.entries({
    ...(tokens ? tokensToCssVars(tokens as any) : {}),
    ...(m.globalStyle?.cssVars || {}),
  })) {
    if (key.startsWith("--")) document.documentElement.style.setProperty(key, String(value));
  }
  pageCssEl?.remove();
  pageCssEl = null;
  if (s.customCss) {
    pageCssEl = document.createElement("style");
    pageCssEl.id = "wp-page-css";
    pageCssEl.textContent = s.customCss;
    document.head.appendChild(pageCssEl);
  }
}

function applyPageState(pageSchema: PageSchema | null) {
  if (!pageSchema) return;
  for (const [name, def] of Object.entries(pageSchema.state || {})) {
    const value = def?.default;
    scope.setVariable(name, value === undefined ? null : JSON.parse(JSON.stringify(value)));
  }
  for (const [name, def] of Object.entries(pageSchema.variables ?? {})) {
    scope.setVariable(name, (def as { value?: any })?.value);
  }
}

function runLifecycle(pageSchema: PageSchema | null, phase: "onLoad" | "onReady" | "onUnload") {
  const steps = pageSchema?.lifecycle?.[phase];
  if (Array.isArray(steps) && steps.length) {
    void runSteps(steps, scope as any, {});
  }
}

function applyPayload(payload: RuntimePayload, path: string) {
  const pageSchema = payload.page_version?.schema ?? null;
  schema.value = pageSchema;
  scope.stateDefs = pageSchema?.state as any;
  scope.eventSchemas = pageSchema?.events as any;
  scope.variables.app = payload.app;
  scope.variables.page = payload.page;
  modules.value = (payload.config as any)?.modules || {};
  scope.modules = modules.value;
  scope.datasources = (payload.config?.datasources || []).map((item: any) => ({
    id: item.id,
    name: item.name,
    type: item.type,
    public_config: item.public_config || {},
  }));
  scope.routeParams = { ...(payload.route_params || payload.page?.params || {}) };
  scope.routePath = path;
  scope.setPageMeta = (meta) => {
    if (typeof document === "undefined") return;
    if (meta.title) document.title = meta.title;
    setMetaTag("name", "description", meta.description || "");
    setMetaTag("property", "og:title", meta.title || "");
    setMetaTag("property", "og:description", meta.description || "");
    setMetaTag("property", "og:image", meta.image || "");
    setMetaTag("property", "og:type", meta.type || "website");
    setMetaTag("property", "og:url", window.location.href);
    let link = document.head.querySelector('link[rel="canonical"]') as HTMLLinkElement | null;
    if (!link) {
      link = document.createElement("link");
      link.rel = "canonical";
      document.head.appendChild(link);
    }
    link.href = window.location.href;
  };
  for (const [name, def] of Object.entries(pageSchema?.variables ?? {})) {
    scope.setVariable(name, (def as { value?: any })?.value);
  }
  if (pageSchema) {
    applyPageState(pageSchema);
    applyPageMeta(pageSchema, payload.page?.name || appCode, payload.app?.design_tokens);
    runLifecycle(pageSchema, "onLoad");
    void nextTick(() => runLifecycle(pageSchema, "onReady"));
  }
}

async function load() {
  const path = routePath();
  if (lastPath && lastPath !== path && typeof window !== "undefined") {
    scrollPositions.set(lastPath, window.scrollY);
  }
  lastPath = path;
  const cached = pageCache.get(path);
  if (cached) {
    applyPayload(cached, path);
    loading.value = false;
    restoreScroll(path);
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const payload = await api.get<RuntimePayload>(path ? `/runtime/${appCode}/${path}` : `/runtime/${appCode}`);
    pageCache.set(path, payload);
    applyPayload(payload, path);
    restoreScroll(path);
  } catch (e) {
    error.value = e instanceof Error ? e.message : "页面加载失败";
  } finally {
    loading.value = false;
  }
}

onBeforeUnmount(() => {
  runLifecycle(schema.value, "onUnload");
  disposeBridge();
  pageCssEl?.remove();
  pageCssEl = null;
});

watch(
  () => route.fullPath,
  () => load()
);

if (initialPayload) {
  applyPayload(initialPayload, routePath());
  loading.value = false;
} else {
  load();
}
</script>

<style scoped>
.wp-runtime {
  min-height: 100vh;
  background: var(--el-bg-color);
}
.wp-route-progress {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 5000;
  height: 2px;
  overflow: hidden;
  background: rgba(37, 99, 235, .12);
  pointer-events: none;
}
.wp-route-progress i {
  display: block;
  width: 38%;
  height: 100%;
  background: var(--el-color-primary, #2563eb);
  animation: wp-route-progress 0.9s ease-in-out infinite;
}
@keyframes wp-route-progress {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(360%); }
}
.wp-runtime-tip {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  color: var(--el-text-color-secondary);
}
.wp-runtime-error {
  color: var(--el-color-danger);
}
.wp-coordination-panel {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 3000;
  width: min(420px, calc(100vw - 36px));
  max-height: 220px;
  overflow: auto;
  padding: 10px 12px;
  border: 1px solid var(--el-color-warning-light-5);
  border-radius: 8px;
  background: var(--el-color-warning-light-9);
  box-shadow: var(--el-box-shadow-light);
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.wp-coordination-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.wp-coordination-head button {
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  cursor: pointer;
  font-size: 12px;
}
.wp-coordination-panel ul {
  margin: 0;
  padding-left: 16px;
}
.wp-coordination-panel li {
  margin: 3px 0;
}
</style>
