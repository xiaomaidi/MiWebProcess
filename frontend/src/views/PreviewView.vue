<template>
  <div class="wp-preview">
    <div class="wp-preview-toolbar">
      <span class="wp-preview-title">
        预览：{{ pageTitle || `页面 #${pageId}` }}
        <el-tag v-if="app" size="small" type="info">{{ app.name }}</el-tag>
      </span>
      <el-radio-group v-model="device" size="small">
        <el-radio-button value="375">手机</el-radio-button>
        <el-radio-button value="768">平板</el-radio-button>
        <el-radio-button value="1280">桌面</el-radio-button>
        <el-radio-button value="auto">自适应</el-radio-button>
      </el-radio-group>
    </div>
    <div class="wp-preview-stage" :style="stageStyle">
      <div v-if="loading" class="wp-runtime-status">草稿加载中…</div>
      <div v-else-if="error" class="wp-runtime-status wp-runtime-error">{{ error }}</div>
      <div class="wp-runtime wp-preview-canvas">
        <NodeRenderer
          v-if="rootNode"
          :node="rootNode"
          :nodes="nodes"
          mode="runtime"
          :layout-mode="layoutMode"
        />
        <div v-else class="wp-runtime-status">空页面</div>
      </div>
    </div>
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
import { computed, nextTick, onBeforeUnmount, provide, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "@/api";
import { createRuntimeScope } from "@/engine/scope";
import { installRuntimeBridge } from "@/engine/runtime-bridge";
import { runSteps } from "@/engine/actions";
import { tokensToCssVars } from "@/design/tokens";
import NodeRenderer from "@/engine/NodeRenderer.vue";
import type { AppInfo, PageSchema, RuntimeScope, SchemaNode } from "@/types";

const route = useRoute();
const router = useRouter();

const appId = () => Number(route.params.appId);
const pageId = () => Number(route.params.pageId);

const loading = ref(true);
const error = ref("");
const app = ref<AppInfo | null>(null);
const pageTitle = ref("");
const schema = ref<PageSchema | null>(null);
const device = ref<"375" | "768" | "1280" | "auto">("1280");

const rootNode = computed(() =>
  schema.value ? (schema.value.nodes[schema.value.rootId] ?? null) : null
);
const nodes = computed<Record<string, SchemaNode>>(() => schema.value?.nodes ?? {});
const layoutMode = computed<"flow" | "free" | undefined>(() => schema.value?.layout?.mode);

const stageStyle = computed(() =>
  device.value === "auto" ? {} : { width: `${device.value}px` }
);

onBeforeUnmount(() => {
  if (schema.value?.lifecycle?.onUnload?.length) {
    void runSteps(schema.value.lifecycle.onUnload, scope, {});
  }
  disposeBridge();
});

// 同步创建 scope 并 provide（provide 只能在 setup 同步阶段调用）；
// 页面数据到达后把 app/page/页面变量 写入 scope 的 reactive variables。
const scope: RuntimeScope = createRuntimeScope({
  app: {
    id: appId(),
    name: "",
    code: "",
    owner_id: 0,
    status: "draft",
    version: 0,
    created_at: "",
    updated_at: "",
  },
  pageId: pageId(),
  pageVersion: 0,
  datasources: [],
  models: [],
  variables: {},
  routeParams: {},
  routePath: "",
  navigate: (path: string) => {
    const seg = String(path ?? "").replace(/^\/+/, "");
    const code = (scope.variables.app as { code?: string } | undefined)?.code;
    if (code) router.push(`/run/${code}/${seg}`);
  },
  setNodeStyle(nodeId: string, style: Record<string, any>) {
    const n = schema.value?.nodes?.[nodeId];
    if (n) n.style = { ...(n.style || {}), ...style };
  },
});
provide("wp.scope", scope);
const disposeBridge = installRuntimeBridge(scope);

function initialVariables(pageSchema: PageSchema): Record<string, any> {
  const vars: Record<string, any> = {};
  for (const [name, def] of Object.entries(pageSchema.state || {})) {
    vars[name] = def?.default ?? null;
  }
  const defs = (pageSchema.variables ?? {}) as Record<string, { value?: any }>;
  for (const [name, def] of Object.entries(defs)) vars[name] = def?.value;
  return vars;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [appInfo, schemaRes, dsRes] = await Promise.all([
      api.get<AppInfo>(`/apps/${appId()}/`),
      api.get<{ schema: PageSchema }>(`/pages/${pageId()}/schema/`),
      api.get<any>(`/apps/${appId()}/datasources/`),
    ]);
    app.value = appInfo;
    pageTitle.value = appInfo.name;
    scope.variables.app = { id: appInfo.id, name: appInfo.name, code: appInfo.code };
    scope.variables.page = { id: pageId(), name: pageTitle.value };
    scope.datasources = Array.isArray(dsRes) ? dsRes : dsRes?.results || [];
    for (const [name, value] of Object.entries(initialVariables(schemaRes.schema))) {
      scope.setVariable(name, value);
    }
    schema.value = schemaRes.schema;
    scope.stateDefs = schemaRes.schema?.state as any;
    scope.eventSchemas = schemaRes.schema?.events as any;
    if (schema.value?.lifecycle?.onLoad?.length) {
      void runSteps(schema.value.lifecycle.onLoad, scope, {});
    }
    if (schema.value?.lifecycle?.onReady?.length) {
      void nextTick(() => runSteps(schema.value!.lifecycle!.onReady!, scope, {}));
    }
    const meta = schemaRes.schema?.meta;
    if (meta) {
      const tokens = (meta as any).useAppTokens && appInfo.design_tokens ? appInfo.design_tokens : (meta.designTokens || appInfo.design_tokens);
      for (const [key, value] of Object.entries({
        ...(tokens ? tokensToCssVars(tokens as any) : {}),
        ...(meta.globalStyle?.cssVars || {}),
      })) {
        if (key.startsWith("--")) document.documentElement.style.setProperty(key, String(value));
      }
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : "草稿加载失败";
  } finally {
    loading.value = false;
  }
}

load();
</script>

<style scoped>
.wp-preview {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.wp-preview-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--el-border-color);
  background: var(--el-bg-color);
}
.wp-preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.wp-preview-stage {
  flex: 1;
  overflow: auto;
  background: #f5f7fa;
  display: flex;
  justify-content: center;
}
.wp-preview-canvas {
  min-height: 100%;
  background: #fff;
  box-shadow: 0 0 0 1px var(--el-border-color-lighter);
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
}
.wp-coordination-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}
.wp-coordination-head button {
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  cursor: pointer;
}
.wp-coordination-panel ul {
  margin: 0;
  padding-left: 16px;
}
.wp-coordination-panel li {
  margin: 3px 0;
}
</style>
