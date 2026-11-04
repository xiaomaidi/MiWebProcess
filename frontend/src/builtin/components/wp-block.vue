<template>
  <!-- 设计态：带标签的容器；内部节点不可交互，点击只会选中外层 wp-block 节点 -->
  <div
    v-if="effectiveMode === 'design'"
    class="wp-block-design"
    :class="{ 'is-error': !!error, 'is-empty': !loading && !error && !hasContent }"
    @click.capture.stop="onDesignClick"
    @dblclick.capture.stop
    @dragstart.capture.stop.prevent
  >
    <div class="wp-block-design-head">
      <span class="wp-block-design-icon">◫</span>
      <span class="wp-block-design-label">{{ designLabel }}</span>
      <span v-if="blockCode" class="wp-block-design-code">{{ blockCode }}</span>
      <span v-if="blockId && !blockCode" class="wp-block-design-code">#{{ blockId }}</span>
      <span v-if="!loading && !error" class="wp-block-design-count">{{ nodeCount }} 节点</span>
      <span class="wp-block-design-spacer" />
      <button
        v-if="error"
        type="button"
        class="wp-block-design-retry"
        title="重新加载"
        @click.stop.prevent="reload"
      >
        重试
      </button>
    </div>
    <div class="wp-block-design-body">
      <div v-if="loading" class="wp-block-state">区块加载中…</div>
      <div v-else-if="error" class="wp-block-state is-error">{{ error }}</div>
      <div v-else-if="!hasContent" class="wp-block-state">空区块（{{ blockCode || `#${blockId}` }}）</div>
      <NodeRenderer v-else-if="renderRoot" :node="renderRoot" :nodes="renderNodes" mode="design" />
    </div>
  </div>

  <!-- 运行态：直接渲染区块子树，不额外包裹布局层（避免破坏父级 flex/grid 关系） -->
  <template v-else>
    <div v-if="loading" class="wp-block-state is-runtime">区块加载中…</div>
    <div v-else-if="error" class="wp-block-state is-runtime is-error">{{ error }}</div>
    <div v-else-if="!hasContent" class="wp-block-state is-runtime">空区块</div>
    <NodeRenderer v-else-if="renderRoot" :node="renderRoot" :nodes="renderNodes" mode="runtime" />
  </template>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, provide, ref, watch } from "vue";
import type { SchemaNode } from "@/types";
import NodeRenderer from "@/engine/NodeRenderer.vue";
import { useSchemaStore } from "@/store/schema";
import {
  fetchRuntimeBlock,
  findBlockByCode,
  getBlock,
  prefixBlockSchema,
  type BlockSchema,
} from "@/designer/block-api";

defineOptions({ name: "WpBlock", inheritAttrs: false });

/** 递归/循环引用保护：超过该层数不再渲染。 */
const MAX_BLOCK_DEPTH = 8;

const props = withDefaults(
  defineProps<{
    /** 区块编码（推荐，跨环境稳定）。 */
    blockCode?: string;
    /** 区块 id（设计态可直接按 id 取 schema）。 */
    blockId?: number;
    /** 展示用区块名称（通常由插入引用时写入，离线也能显示标签）。 */
    blockName?: string;
    /** 运行态应用编码；缺省时依次取 scope.variables.app.code / 全局变量 / /run/<code>/ 路径。 */
    appCode?: string;
    /** 模式；缺省时处于设计器上下文则 design，否则 runtime。 */
    mode?: "design" | "runtime";
    /** 预加载的区块 schema（SSR/集成方可跳过请求）。 */
    schema?: BlockSchema | null;
    /** 嵌套深度（一般由父级 provide 注入，无需手写）。 */
    depth?: number;
    /** NodeRenderer 注入的当前渲染模式（比注入 design 上下文更可靠）。 */
    wpMode?: "design" | "runtime";
    /** NodeRenderer 注入的页面节点 id，用于设计态选中外层引用节点。 */
    wpNodeId?: string;
  }>(),
  {
    blockCode: "",
    blockId: 0,
    blockName: "",
    appCode: "",
    mode: undefined,
    schema: null,
    depth: undefined,
    wpMode: undefined,
    wpNodeId: "",
  }
);

interface DesignCtx {
  selectedId: string | null;
  selectedIds: string[];
  onSelect: (id: string | null, additive?: boolean) => void;
  onDelete?: (id: string) => void;
}

const designCtx = inject<DesignCtx | null>("wp.design", null);
const runtimeScope = inject<{ variables?: Record<string, any> } | null>("wp.scope", null);
const injectedDepth = inject<number>("wp.block.depth", 0);
// 让嵌套的 wp-block 引用继续累加深度（即使组件之间隔了若干层 NodeRenderer）。
provide("wp.block.depth", (props.depth ?? injectedDepth) + 1);

const schemaStore = useSchemaStore();

const blockSchema = ref<BlockSchema | null>(null);
const fetchedName = ref("");
const loading = ref(false);
const error = ref("");

const effectiveMode = computed<"design" | "runtime">(() => {
  if (props.mode === "design" || props.mode === "runtime") return props.mode;
  if (props.wpMode === "design" || props.wpMode === "runtime") return props.wpMode;
  return designCtx ? "design" : "runtime";
});
const effectiveDepth = computed(() => props.depth ?? injectedDepth);

const instancePrefix = `wpblk${Math.random().toString(36).slice(2, 8)}-`;
const renderSchema = computed(() => prefixBlockSchema(props.schema || blockSchema.value, instancePrefix));
const renderNodes = computed<Record<string, SchemaNode>>(() => renderSchema.value.nodes);
const renderRoot = computed<SchemaNode | null>(
  () => renderSchema.value.nodes[renderSchema.value.rootId] || null
);
const hasContent = computed(() => !!renderRoot.value);
const nodeCount = computed(() => Object.keys(blockSchema.value?.nodes || {}).length);
const designLabel = computed(
  () =>
    fetchedName.value ||
    props.blockName ||
    props.blockCode ||
    (props.blockId ? `#${props.blockId}` : "未配置区块")
);

function runtimeAppCode(): string {
  if (props.appCode) return props.appCode;
  const fromScope = runtimeScope?.variables?.app as { code?: string } | undefined;
  if (fromScope?.code) return String(fromScope.code);
  const globalCode = (globalThis as any).__WP_APP_CODE__;
  if (globalCode) return String(globalCode);
  if (typeof location !== "undefined") {
    const m = location.pathname.match(/^\/run\/([^/]+)/);
    if (m) return m[1];
  }
  return "";
}

async function load() {
  error.value = "";
  if (effectiveDepth.value > MAX_BLOCK_DEPTH) {
    error.value = "区块嵌套层级过深，已停止渲染";
    return;
  }
  if (props.schema) {
    blockSchema.value = props.schema;
    fetchedName.value = "";
    return;
  }
  if (!props.blockCode && !props.blockId) {
    error.value = "wp-block 缺少 blockCode / blockId";
    return;
  }
  loading.value = true;
  try {
    if (effectiveMode.value === "design") {
      const appId = Number(schemaStore.appId || 0);
      if (props.blockId) {
        const detail = await getBlock(Number(props.blockId));
        blockSchema.value = detail.schema;
        fetchedName.value = detail.name;
      } else if (appId) {
        const detail = await findBlockByCode(appId, props.blockCode);
        if (!detail) throw new Error(`区块 ${props.blockCode} 不存在`);
        blockSchema.value = detail.schema;
        fetchedName.value = detail.name;
      } else {
        throw new Error("无法确定应用，无法加载区块");
      }
    } else {
      const appCode = runtimeAppCode();
      if (!appCode) throw new Error("无法确定应用编码（可传入 appCode）");
      const data = await fetchRuntimeBlock(appCode, props.blockCode, { silent: true });
      blockSchema.value = { rootId: data.rootId, nodes: data.nodes };
      fetchedName.value = data.name;
    }
  } catch (e: any) {
    error.value = e?.message || "区块加载失败";
    blockSchema.value = null;
  } finally {
    loading.value = false;
  }
}

function reload() {
  void load();
}

function onDesignClick(e: MouseEvent) {
  if (!designCtx) return;
  const id = props.wpNodeId || "";
  if (!id) return;
  designCtx.onSelect(id, e.ctrlKey || e.metaKey || e.shiftKey);
}

onMounted(() => {
  void load();
});

watch(
  () => [props.blockCode, props.blockId, props.appCode, props.schema, props.wpMode],
  () => {
    if (props.schema) blockSchema.value = props.schema;
    void load();
  }
);
</script>

<style scoped>
.wp-block-design {
  position: relative;
  border: 1px dashed var(--el-color-primary, #409eff);
  border-radius: 6px;
  padding: 4px;
  margin: 2px 0;
  background: color-mix(in srgb, var(--el-color-primary, #409eff) 3%, transparent);
}
.wp-block-design.is-error {
  border-color: var(--el-color-danger, #f56c6c);
}
.wp-block-design.is-empty {
  border-style: dotted;
}
.wp-block-design-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 4px;
  font-size: 12px;
  color: var(--el-color-primary, #409eff);
  user-select: none;
  cursor: default;
}
.wp-block-design-icon {
  font-size: 12px;
}
.wp-block-design-label {
  font-weight: 600;
}
.wp-block-design-code {
  color: var(--el-text-color-secondary, #909399);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.wp-block-design-count {
  color: var(--el-text-color-secondary, #909399);
}
.wp-block-design-spacer {
  flex: 1;
}
.wp-block-design-retry {
  border: 1px solid currentColor;
  border-radius: 4px;
  background: transparent;
  color: inherit;
  font-size: 11px;
  padding: 0 6px;
  line-height: 18px;
  cursor: pointer;
}
.wp-block-design-body {
  /* 内部节点由区块 schema 渲染，设计器里只允许选中外层引用节点 */
  pointer-events: none;
  user-select: none;
}
.wp-block-state {
  padding: 8px 10px;
  font-size: 12px;
  color: var(--el-text-color-secondary, #909399);
}
.wp-block-state.is-runtime {
  color: inherit;
}
.wp-block-state.is-error {
  color: var(--el-color-danger, #f56c6c);
}
</style>