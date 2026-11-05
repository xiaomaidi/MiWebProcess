<template>
  <template v-if="!isHidden">
    <!-- 画布根 -->
    <div v-if="isCanvas" class="wp-canvas" :class="{ 'wp-canvas-free': layoutMode === 'free' }" :style="canvasStyle" :data-wp-node="node.id">
      <template v-for="child in childrenList" :key="child.id">
        <NodeRenderer :node="child" :nodes="nodes" :mode="mode" :loop-item="loopItem" :loop-name="loopName" :loop-index="loopIndex" />
      </template>
      <!-- 设计态：他人实时锁定的节点徽章/描边（只读覆盖层，不参与交互） -->
      <NodeLockOverlay v-if="mode === 'design'" />
    </div>

    <!-- 通用循环（dataBinding） -->
    <div v-else-if="isLoop" class="wp-loop">
      <div v-for="(item, i) in loopItems" :key="i" class="wp-loop-item">
        <template v-for="child in childrenList" :key="child.id">
          <NodeRenderer :node="child" :nodes="nodes" :mode="mode" :loop-item="item" :loop-name="loopVarName" :loop-index="i" />
        </template>
      </div>
    </div>

    <!-- 高级：循环容器 -->
    <div v-else-if="isRepeater" class="wp-repeater" :style="nodeStyle" :data-wp-node="node.id">
      <div v-for="(item, i) in repeaterItems" :key="i" class="wp-repeater-item">
        <template v-for="child in childrenList" :key="child.id">
          <NodeRenderer :node="child" :nodes="nodes" :mode="mode" :loop-item="item" :loop-name="repeaterItemVar" :loop-index="i" />
        </template>
      </div>
    </div>

    <!-- 高级：条件容器 -->
    <template v-else-if="isConditional">
      <template v-if="conditionPass">
        <template v-for="child in childrenList" :key="child.id">
          <NodeRenderer :node="child" :nodes="nodes" :mode="mode" :loop-item="loopItem" :loop-name="loopName" :loop-index="loopIndex" />
        </template>
      </template>
      <div v-else-if="mode === 'design'" class="wp-conditional-placeholder">条件未满足：{{ node.props.when }}</div>
    </template>

    <!-- 结构化组件：运行态不包 div，避免破坏 Element 插槽协议 -->
    <template v-else-if="isWrapperless">
      <component :is="comp" v-if="comp" ref="compRef" v-bind="elementProps" v-on="eventHandlers" :wp-node-id="node.id" :data-wp-node="node.id" :data-motion="node.motion || undefined" :wp-mode="mode">
        <template v-for="(children, slotName) in namedSlotNodes" :key="slotName" #[slotName]>
          <NodeRenderer
            v-for="child in children"
            :key="child.id"
            :node="child"
            :nodes="nodes"
            :mode="mode"
            :loop-item="loopItem"
            :loop-name="loopName"
            :loop-index="loopIndex"
          />
        </template>
        <template #default>
          <template v-if="hasChildren">
            <NodeRenderer
              v-for="child in childrenList"
              :key="child.id"
              :node="child"
              :nodes="nodes"
              :mode="mode"
              :loop-item="loopItem"
              :loop-name="loopName"
              :loop-index="loopIndex"
            />
          </template>
          <template v-else-if="isIcon && iconChild">
            <component :is="iconChild" />
          </template>
          <template v-else-if="textSlot">{{ textSlot }}</template>
        </template>
      </component>
    </template>

    <!-- 普通组件节点 -->
    <div
      v-else
      class="wp-node"
      :data-motion="node.motion || undefined"
      :class="{ 'wp-node-selected': isSelected, 'wp-node-free': hasLayout, 'wp-node-inline': isInlineWrapper }"
      :style="nodeStyle"
      :data-wp-node="node.id"
      :data-state-preview="previewStateName || undefined"
      :draggable="canDrag"
      @dragstart.stop="onNodeDragStart"
      @click="onNodeClick"
    >
      <SandboxedComponent
        v-if="isSandboxed"
        :source-url="meta?.source_url || ''"
        :element="meta?.element || ''"
        :component-props="elementProps"
        :title="meta?.label || node.type"
        @event="onSandboxEvent"
      />
      <component v-else-if="comp" :is="comp" ref="compRef" v-bind="elementProps" :wp-node-id="node.id" :data-motion="node.motion || undefined" :wp-mode="mode" v-on="eventHandlers">
        <template v-for="(children, slotName) in namedSlotNodes" :key="slotName" #[slotName]>
          <NodeRenderer
            v-for="child in children"
            :key="child.id"
            :node="child"
            :nodes="nodes"
            :mode="mode"
            :loop-item="loopItem"
            :loop-name="loopName"
            :loop-index="loopIndex"
          />
        </template>
        <template v-if="hasSlot" #default>
          <template v-if="hasChildren">
            <NodeRenderer
              v-for="child in childrenList"
              :key="child.id"
              :node="child"
              :nodes="nodes"
              :mode="mode"
              :loop-item="loopItem"
              :loop-name="loopName"
              :loop-index="loopIndex"
            />
          </template>
          <template v-else-if="isIcon && iconChild">
            <component :is="iconChild" />
          </template>
          <template v-else-if="textSlot">{{ textSlot }}</template>
        </template>
      </component>
      <div v-else class="wp-unknown">未知组件：{{ node.type }}</div>
      <!-- 设计态：右上角删除按钮 -->
      <button v-if="mode === 'design' && design?.onDelete" class="wp-node-close" title="删除组件" @click.stop="closeNode">×</button>
      <!-- 设计态 + free 布局：右下角缩放手柄 -->
      <div v-if="mode === 'design' && hasLayout" class="wp-resize-handle" />
    </div>
  </template>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, inject, onMounted, onUnmounted, provide, reactive, ref, toRefs, watch } from "vue";
import type { Component } from "vue";
import type { ComponentMeta, ComponentStateName, RuntimeScope, SchemaNode } from "@/types";
import { builtinComponents } from "@/builtin";
import { useComponentStore } from "@/store/component";
import { useSchemaStore } from "@/store/schema";
import { COMPOSITE_CHILDREN, getElementComponent, getElementIcon, TEXT_SLOT_ELEMENTS } from "./element-components";
import { remoteComponentFor } from "./remote-component";
import NodeLockOverlay from "@/designer/components/NodeLockOverlay.vue";
import SandboxedComponent from "@/components/market/SandboxedComponent.vue";
import { resolveProps, resolveLoopItems, buildScope } from "./binding";
import {
  COMPONENT_STATES,
  buildStateCss,
  hasStateOverride,
  mergeVariantProps,
  mergeVariantStyle,
  resolveDesignProps,
  resolveInteractionState,
  splitVariantStyleBindings,
  statePropsFor,
  stateStyleFor,
} from "./state-variants";
import { previewedStateOf } from "./state-preview";
import { evaluateExpression, interpolate } from "./expr";
import { runSteps } from "./actions";
import type { WpFormContext } from "@/builtin/components/form-context";
import { wpFormContextKey } from "@/builtin/components/form-context";

const props = defineProps<{
  node: SchemaNode;
  nodes: Record<string, SchemaNode>;
  mode: "design" | "runtime";
  /** 祖先循环注入的当前元素 */
  loopItem?: any;
  loopName?: string;
  /** 祖先循环注入的当前索引 */
  loopIndex?: number;
  canvasStyle?: Record<string, string>;
  layoutMode?: "flow" | "free";
}>();
const { node, mode, loopItem, loopName, loopIndex } = toRefs(props);

const components = useComponentStore();
const schemaStore = useSchemaStore();
const compRef = ref<any>(null);

/** 未知组件的兜底容器（渲染函数，无运行时模板编译器依赖）。 */
const Passthrough = defineComponent({
  name: "WpPassthrough",
  setup(_, { slots }) {
    return () => h("div", { class: "wp-passthrough" }, slots.default ? slots.default() : []);
  },
});

// 设计态上下文（DesignerView provide）
interface DesignCtx {
  selectedId: string | null;
  selectedIds: string[];
  onSelect: (id: string | null, additive?: boolean) => void;
  onDelete?: (id: string) => void;
}
const design = inject<DesignCtx | null>("wp.design", null);
// 运行态作用域（RuntimeView/Preview provide）
const scope = inject<RuntimeScope | null>("wp.scope", null);

const meta = computed<ComponentMeta | undefined>(() => components.meta(node.value.type));
const isSandboxed = computed(() => !!meta.value && meta.value.source === "custom-sandbox" && !!meta.value.source_url && !!meta.value.element);
function onSandboxEvent(payload: { name: string; detail: unknown }) {
  if (mode.value !== "runtime") return;
  const handler = eventHandlers.value?.[payload?.name];
  if (typeof handler === "function") handler(payload.detail);
}

const isCanvas = computed(() => node.value.type === "wp-canvas");
const hasLayout = computed(() => node.value.layout != null);
const isSelected = computed(() => mode.value === "design" && !!design?.selectedIds?.includes(node.value.id));

// ---------- 组件状态 / 变体 ----------
// 变体：激活变体的 props/style 覆盖基础节点（设计态与运行态一致）。
// 绑定对象在合并时保持原结构，随后统一交给 resolveProps 解析（变体绑定优先生效）。
const variantProps = computed(() => mergeVariantProps(node.value));
const variantStyleSplit = computed(() => splitVariantStyleBindings(mergeVariantStyle(node.value)));
// 变体 style 暂不支持数据绑定：过滤掉绑定值，避免输出 [object Object] 等无效 CSS。
const variantStyle = computed(() => variantStyleSplit.value.style);
/** style 绑定不支持：每个节点+键只提示一次（设计器属性面板另有常驻提示）。 */
const warnedStyleBindingKeys = new Set<string>();
watch(
  variantStyleSplit,
  (split) => {
    if (!split.bindingKeys.length) return;
    const signature = `${node.value.id}:${split.bindingKeys.join(",")}`;
    if (warnedStyleBindingKeys.has(signature)) return;
    warnedStyleBindingKeys.add(signature);
    console.warn(`[wp] 变体 style 暂不支持数据绑定，已忽略：${node.value.id} → ${split.bindingKeys.join(", ")}`);
  },
  { immediate: true }
);
// 设计态状态预览（由属性面板写入，不持久化）；运行态不使用。
const previewStateName = computed<ComponentStateName | null>(() =>
  mode.value === "design" ? previewedStateOf(node.value.id) : null
);
const previewStateStyle = computed(() => stateStyleFor(node.value, previewStateName.value));

// 运行态真实交互：hover / active / focus 由组件根元素事件驱动，disabled 取解析后的 props。
const hovered = ref(false);
const pressed = ref(false);
const focused = ref(false);
/** 未叠加状态覆盖的 props（用于 disabled 判定，避免与状态 props 形成环）。 */
const resolvedBaseProps = computed<Record<string, any>>(() => {
  if (isCanvas.value || !scope) return variantProps.value;
  return resolveProps(variantProps.value, scope as any, loopExtra());
});
const runtimeStateName = computed<ComponentStateName | null>(() => {
  if (mode.value !== "runtime") return null;
  return resolveInteractionState(node.value, {
    disabled: !!resolvedBaseProps.value.disabled,
    hovered: hovered.value,
    pressed: pressed.value,
    focused: focused.value,
  });
});
const activeStateName = computed<ComponentStateName | null>(() => previewStateName.value || runtimeStateName.value);
// 运行态：激活状态的样式也内联应用（覆盖基础 inline style），CSS 规则作为兜底。
const runtimeStateStyle = computed(() =>
  mode.value === "runtime" ? stateStyleFor(node.value, runtimeStateName.value) : {}
);
const activeStateProps = computed<Record<string, any>>(() => statePropsFor(node.value, activeStateName.value));
const resolvedStateProps = computed<Record<string, any>>(() => {
  const raw = activeStateProps.value;
  if (!raw || !Object.keys(raw).length) return {};
  if (!scope) return raw;
  return resolveProps(raw, scope as any, loopExtra());
});
const mergedProps = computed<Record<string, any>>(() => {
  const base = variantProps.value;
  const extra = activeStateProps.value;
  return extra && Object.keys(extra).length ? { ...base, ...extra } : base;
});
/** 是否存在需要监听交互事件的状态覆盖（hover/active/focus 的 style 或 props）。 */
const hasInteractiveStates = computed(() =>
  COMPONENT_STATES.some(({ key }) => key !== "disabled" && hasStateOverride(node.value, key))
);

const canDrag = computed(
  () =>
    mode.value === "design" &&
    schemaStore.layoutMode !== "free" &&
    node.value.id !== schemaStore.schema?.rootId
);

function onNodeDragStart(e: DragEvent) {
  if (!canDrag.value) {
    e.preventDefault();
    return;
  }
  const dt = e.dataTransfer;
  if (!dt) return;
  dt.setData("text/wp-node-move", node.value.id);
  dt.effectAllowed = "move";
}

// 设计态：无自定义样式/定位的节点使用 display:contents 包装，避免破坏
// ElRow/ElCol、ElSpace 等布局容器的直接子节点关系；选中态用子组件根节点描边。
const isInlineWrapper = computed(
  () =>
    mode.value === "design" &&
    !node.value.layout &&
    !(node.value.style && Object.keys(node.value.style).length) &&
    !(variantStyle.value && Object.keys(variantStyle.value).length) &&
    !previewStateName.value &&
    !node.value.customCss &&
    !(node.value.responsive && Object.keys(node.value.responsive).length)
);

const isRepeater = computed(() => node.value.type === "repeater");
const isConditional = computed(() => node.value.type === "conditional");
const isIcon = computed(() => node.value.type === "ElIcon");

function onNodeClick(e: MouseEvent) {
  if (mode.value !== "design") return;
  e.stopPropagation();
  design?.onSelect(node.value.id, e.ctrlKey || e.metaKey || e.shiftKey);
}

/** 右上角 ×：删除该节点（子节点上移给父节点；根画布不可删）。 */
function closeNode() {
  if (mode.value !== "design") return;
  design?.onDelete?.(node.value.id);
}

// ---------- 条件渲染 ----------
function loopExtra(): Record<string, any> | undefined {
  const extra: Record<string, any> = {};
  if (loopItem.value !== undefined && loopItem.value !== null) extra[loopName.value || "item"] = loopItem.value;
  if (loopIndex.value !== undefined) {
    const indexName = isRepeater.value ? String(variantProps.value.indexVar || "index") : "index";
    extra[indexName] = loopIndex.value;
    if (indexName !== "index") extra.index = loopIndex.value;
  }
  return Object.keys(extra).length ? extra : undefined;
}

const conditionPass = computed(() => {
  if (!isConditional.value) return true;
  const when = mergedProps.value?.when;
  if (!when) return true;
  if (mode.value !== "runtime" || !scope) return true;
  return !!evaluateExpression(String(when), buildScope(scope, loopExtra()));
});

const isHidden = computed(() => {
  if (mode.value !== "runtime") return false;
  const expr = node.value.condition?.expr;
  if (!expr) return false;
  const s = scope ? buildScope(scope as any, loopExtra()) : {};
  return !evaluateExpression(expr, s);
});

// ---------- 循环渲染 ----------
const loopVarName = computed(() => (node.value.dataBinding as any)?.loopVar || "item");
const isLoop = computed(() => mode.value === "runtime" && !!node.value.dataBinding && !!scope && !isRepeater.value);
const loopItems = computed(() => {
  if (!isLoop.value || !scope) return [];
  return resolveLoopItems(node.value.dataBinding, scope as any, loopExtra());
});

const repeaterItemVar = computed(() => String(variantProps.value.itemVar || "item"));
const repeaterItems = computed<any[]>(() => {
  if (!isRepeater.value) return [];
  if (mode.value !== "runtime" || !scope) return [{}];
  const list = resolvedProps.value.list;
  if (Array.isArray(list)) return list;
  if (list && typeof list === "object" && Array.isArray((list as any).results)) return (list as any).results;
  return [];
});

// ---------- 表单上下文 ----------
const injectedForm = inject<WpFormContext | null>(wpFormContextKey, null);
const ownFormValues = reactive<Record<string, any>>({});
const ownFormInitial = reactive<Record<string, any>>({});
const ownForm: WpFormContext = {
  values: ownFormValues,
  setField(field: string, value: any) {
    ownFormValues[field] = value;
  },
  register(field: string, value: any) {
    if (!(field in ownFormInitial)) {
      ownFormInitial[field] = value;
      if (!(field in ownFormValues)) ownFormValues[field] = value;
    }
  },
  reset() {
    for (const key of Object.keys(ownFormValues)) delete ownFormValues[key];
    for (const [key, value] of Object.entries(ownFormInitial)) ownFormValues[key] = value;
  },
  async validate() {
    const inst = compRef.value;
    if (inst && typeof inst.validate === "function") {
      return await new Promise<boolean>((resolve) => {
        try {
          const r = inst.validate((ok: boolean) => resolve(!!ok));
          if (r && typeof r.then === "function") r.then((ok: boolean) => resolve(!!ok)).catch(() => resolve(false));
        } catch {
          resolve(false);
        }
      });
    }
    return true;
  },
  get disabled() {
    return !!resolvedProps.value.disabled;
  },
  get inline() {
    return !!resolvedProps.value.inline;
  },
  get labelWidth() {
    const v = Number(resolvedProps.value.labelWidth);
    return Number.isFinite(v) && v > 0 ? v : 100;
  },
  get labelPosition() {
    return resolvedProps.value.labelPosition === "top" ? "top" : "right";
  },
};
const isFormRoot = computed(() => node.value.type === "ElForm");
if (props.node.type === "ElForm") provide(wpFormContextKey, ownForm);
const form = computed<WpFormContext | null>(() => (isFormRoot.value ? ownForm : injectedForm));

watch(
  () => ({ ...ownFormValues }),
  (values) => {
    if (scope && node.value.id) scope.formValues[node.value.id] = values;
    if (isFormRoot.value) for (const [k, v] of Object.entries(values)) form.value?.register(k, v);
  },
  { immediate: true, deep: true }
);

// ---------- props / 事件 ----------
const comp = computed<Component | string | null>(() => {
  if (isCanvas.value) return null;
  const t = node.value.type;
  // 需要适配层的组件（Element 原生 props 无法直接表达 options/columns）
  if (t === "ElTable") return builtinComponents.DataTable;
  if (t === "ElCard") return builtinComponents.CardRenderer;
  if (COMPOSITE_CHILDREN[t]) return builtinComponents.CompositeRenderer;
  if (t === "ElSelect") return builtinComponents.SelectField;
  if (t === "ElRadioGroup" || t === "ElCheckboxGroup") return builtinComponents.ChoiceGroup;
  if (t === "ElIcon") return getElementComponent("ElIcon") || builtinComponents.HtmlBlock;

  const source = meta.value?.source || (t.startsWith("wp-") ? "legacy" : "element-plus");
  if (source === "legacy") return builtinComponents[t] || Passthrough;
  if (source === "native") return meta.value?.element || t;
  if (source === "element-plus") {
    const el = meta.value?.element || t;
    return getElementComponent(el) || builtinComponents[el] || Passthrough;
  }
  if (source === "custom" || source === "chart" || source === "rich" || source === "advanced") {
    const el = meta.value?.element || t;
    if (source === "custom" && meta.value?.source_url && el) {
      return remoteComponentFor(meta.value.source_url, el);
    }
    return builtinComponents[el] || builtinComponents[t] || getElementComponent(el) || Passthrough;
  }
  return builtinComponents[t] || getElementComponent(t) || Passthrough;
});

/** 设计态绑定占位：按组件声明的 prop 类型给出对应空值，避免 Vue prop 类型检查警告。 */
function designPlaceholder(c: any, key: string): any {
  const decl = c?.props;
  if (!decl) return "";
  const def = Array.isArray(decl) ? (decl.includes(key) ? ({} as any) : undefined) : decl[key];
  if (!def) return "";
  const t = typeof def === "object" ? def.type : def;
  const types = Array.isArray(t) ? t : [t];
  if (types.includes(Boolean)) return false;
  if (types.includes(Number)) return 0;
  if (types.includes(Array)) return [];
  if (types.includes(Object)) return {};
  if (types.includes(Function)) return () => {};
  return "";
}

/**
 * 设计态预览作用域：用页面变量当前值构造（只读）。
 * 存在预览数据时，active 变体中的绑定在画布上显示真实值；否则回退占位值。
 */
const designPreviewScope = computed<RuntimeScope | null>(() => {
  if (mode.value !== "design") return null;
  const variables: Record<string, any> = {};
  for (const [key, def] of Object.entries(schemaStore.schema?.variables || {})) {
    const value = (def as { value?: unknown } | undefined)?.value;
    if (value !== undefined) variables[key] = value;
  }
  if (!Object.keys(variables).length) return null;
  const noop = () => {};
  const scope: RuntimeScope = {
    variables,
    routeParams: {},
    routePath: "",
    setVariable: noop,
    datasourceResults: {},
    modelResults: {},
    formValues: {},
    formValidators: {},
    loopVars: {},
    async callDatasource() {
      return undefined;
    },
    navigate: noop,
    openModal: noop,
    closeModal: noop,
    modalNodeIds: new Set<string>(),
    message: noop,
    record: {
      async list() {
        return undefined;
      },
      async get() {
        return undefined;
      },
      async create() {
        return undefined;
      },
      async update() {
        return undefined;
      },
      async remove() {
        return undefined;
      },
    },
  };
  return scope;
});

/** 设计态 props：变体绑定 / 表达式优先用预览作用域解析，未命中再用占位值。 */
const designResolvedProps = computed(() =>
  resolveDesignProps(
    mergedProps.value,
    designPreviewScope.value,
    (key) => designPlaceholder(comp.value, key),
    resolveProps
  )
);

const resolvedProps = computed(() => {
  if (isCanvas.value || !scope) {
    if (mode.value === "design") {
      // 设计态：有页面变量预览值时解析 active 变体绑定；否则输出类型安全的占位值。
      return designResolvedProps.value.props;
    }
    return mergedProps.value;
  }
  const base = resolvedBaseProps.value;
  const extra = resolvedStateProps.value;
  return extra && Object.keys(extra).length ? { ...base, ...extra } : base;
});

const localModel = ref<any>(undefined);
watch(
  () => resolvedProps.value.modelValue ?? resolvedProps.value.value ?? resolvedProps.value.content,
  (v) => {
    if (localModel.value === undefined && v !== undefined) localModel.value = v;
  },
  { immediate: true }
);
if (props.node.type === "ElCollapse" && localModel.value === undefined) localModel.value = [];

const fieldName = computed(() => String(resolvedProps.value.field || ""));
const isFormField = computed(() => !!meta.value?.is_form_field);
const modelValue = computed(() => {
  if (isFormField.value && fieldName.value && form.value) return form.value.values[fieldName.value];
  if (resolvedProps.value.modelValue !== undefined) return resolvedProps.value.modelValue;
  return localModel.value;
});

// 表单字段首次挂载时把 modelValue/default 写入表单上下文，避免初始值为 undefined。
watch(
  [fieldName, () => resolvedProps.value.modelValue, () => resolvedProps.value.value],
  () => {
    const f = form.value;
    if (!isFormField.value || !fieldName.value || !f) return;
    if (f.values[fieldName.value] === undefined) {
      const init = resolvedProps.value.modelValue ?? resolvedProps.value.value ?? "";
      f.register(fieldName.value, init);
      if (f.values[fieldName.value] === undefined) f.setField(fieldName.value, init);
    }
  },
  { immediate: true }
);

function updateModel(v: any) {
  if (isFormField.value && fieldName.value && form.value) form.value.setField(fieldName.value, v);
  else localModel.value = v;
  const handler = node.value.events?.["update:modelValue"];
  if (Array.isArray(handler) && handler.length && scope) void runSteps(handler, scope as any, { event: v, value: v });
}

const dialogVisible = computed(() => {
  if (!scope) return !!resolvedProps.value.visible;
  return !!resolvedProps.value.visible || scope.modalNodeIds.has(node.value.id) || !!scope.drawerNodeIds?.has(node.value.id);
});

const elementProps = computed<Record<string, any>>(() => {
  const out: Record<string, any> = { ...resolvedProps.value };
  const t = node.value.type;
  const source = meta.value?.source;
  delete out.field;
  delete out.when;
  delete out.keepPlaceholder;
  delete out.list;
  delete out.itemVar;
  delete out.indexVar;

  // 文本内容走默认插槽，不作为 DOM 属性
  if (
    textSlot.value !== undefined &&
    !["ElFormItem", "ElDescriptionsItem", "ElStep", "ElTabPane", "ElTimelineItem", "ElOption"].includes(t)
  ) {
    delete out.label;
    delete out.text;
    delete out.content;
  }
  if (t === "ElIcon") delete out.name;
  if (t === "ElTable" || t === "ElTableColumn") {
    delete out.field;
  }
  if (t === "ElSelect" || t === "ElRadioGroup" || t === "ElCheckboxGroup") delete out.field;

  // 表单根：让 ElForm/ElFormItem 的校验拿到内部 values。
  if (t === "ElForm") out.model = ownFormValues;

  // 表单字段 / 受控组件
  if (isFormField.value) {
    out.modelValue = modelValue.value;
    out["onUpdate:modelValue"] = updateModel;
  } else if (["ElTabs", "ElCollapse", "ElPagination", "ElCalendar"].includes(t)) {
    out.modelValue = modelValue.value;
    out["onUpdate:modelValue"] = updateModel;
  }
  if (t === "ElPagination") {
    out.currentPage = resolvedProps.value.currentPage ?? 1;
    out.pageSize = resolvedProps.value.pageSize ?? 10;
  }

  // 弹窗 / 抽屉
  if (t === "ElDialog" || t === "ElDrawer") {
    out.modelValue = dialogVisible.value;
    out["onUpdate:modelValue"] = (v: boolean) => {
      if (!v && scope) {
        if (t === "ElDrawer" && scope.closeDrawer) scope.closeDrawer(node.value.id);
        else scope.closeModal(node.value.id);
      }
    };
  }
  if (t === "ElDrawer" && scope?.drawerNodeIds?.has(node.value.id)) out.modelValue = true;

  // 选择组适配器需要 kind
  if (t === "ElRadioGroup" || t === "ElCheckboxGroup") out.kind = t === "ElCheckboxGroup" ? "checkbox" : "radio";

  // ElContainer 的 background/padding 是注册表扩展属性，Element 本身没有对应 prop。
  if (t === "ElContainer") {
    const style: Record<string, any> = { ...(out.style || {}) };
    if (out.background) style.background = out.background;
    if (out.padding !== undefined && out.padding !== "") style.padding = typeof out.padding === "number" ? `${out.padding}px` : out.padding;
    out.style = style;
    delete out.background;
    delete out.padding;
  }

  // 高级组件需要知道设计/运行态（Portal 在运行态才 teleport）
  if (t === "component-slot" || t === "portal") out.mode = mode.value;

  // 复合组件：直接生成真实子组件 VNode，避免 NodeRenderer 包装破坏 useOrderedChildren。
  if (COMPOSITE_CHILDREN[t]) {
    out.rootElement = meta.value?.element || t;
    out.childElement = COMPOSITE_CHILDREN[t];
    out.childIds = node.value.children || [];
    out.nodes = props.nodes;
    out.mode = mode.value;
  }

  // 富文本：设计态直接回写 schema；运行态写入本地模型，供表单/动作读取。
  if (t === "rich-text") {
    out.modelValue = localModel.value !== undefined ? localModel.value : resolvedProps.value.content ?? "";
    out["onUpdate:modelValue"] = (v: string) => {
      localModel.value = v;
      if (mode.value === "design") schemaStore.setNodeProp(node.value.id, "content", v);
    };
  }

  // 图标按钮：把字符串 icon 名换成组件
  if (out.icon && typeof out.icon === "string") {
    const icon = getElementIcon(out.icon);
    if (icon) out.icon = icon;
  }

  // 原生布局容器：把面板里的布局 props 编译为 CSS，避免变成无效 HTML 属性。
  if (source === "native" && t === "img") {
    const style: Record<string, any> = { ...(out.style || {}) };
    if (out.objectFit) style.objectFit = out.objectFit;
    if (out.borderRadius !== undefined && out.borderRadius !== "") style.borderRadius = `${out.borderRadius}px`;
    out.style = style;
    delete out.objectFit;
    delete out.borderRadius;
  }

  if (source === "native" && ["div", "section", "flex-box", "grid-box"].includes(t)) {
    const style: Record<string, any> = { ...(out.style || {}) };
    const px = (v: any) => (typeof v === "number" ? `${v}px` : v);
    if (out.padding !== undefined && out.padding !== "") style.padding = px(out.padding);
    if (out.background) style.background = out.background;
    if (out.minHeight) style.minHeight = out.minHeight;
    if (t === "flex-box") {
      style.display = "flex";
      if (out.direction) style.flexDirection = out.direction;
      if (out.gap !== undefined && out.gap !== "") style.gap = px(out.gap);
      if (out.align) style.alignItems = out.align;
      if (out.justify) style.justifyContent = out.justify;
      if (out.wrap) style.flexWrap = out.wrap;
    }
    if (t === "grid-box") {
      style.display = "grid";
      const cols = Math.max(1, Number(out.columns) || 2);
      style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
      if (out.gap !== undefined && out.gap !== "") style.gap = px(out.gap);
      if (out.rowGap !== undefined && out.rowGap !== "") style.rowGap = px(out.rowGap);
    }
    out.style = style;
    for (const k of ["padding", "background", "minHeight", "direction", "gap", "align", "justify", "wrap", "columns", "rowGap"]) delete out[k];
  }

  // 设计态状态预览：同步到组件根元素，避免样式只落在 display:contents 包装层上。
  if (mode.value === "design" && Object.keys(previewStateStyle.value).length) {
    out.style = { ...(out.style || {}), ...previewStateStyle.value };
  }

  // 运行态：为 props 状态覆盖监听真实交互。事件在组件根元素上冒泡，
  // 与 v-on="eventHandlers" 合并，不覆盖页面动作事件。
  if (mode.value === "runtime" && hasInteractiveStates.value) {
    out.onMouseenter = () => {
      hovered.value = true;
    };
    out.onMouseleave = () => {
      hovered.value = false;
      pressed.value = false;
    };
    out.onMousedown = () => {
      pressed.value = true;
    };
    out.onMouseup = () => {
      pressed.value = false;
    };
    out.onTouchstart = () => {
      pressed.value = true;
    };
    out.onTouchend = () => {
      pressed.value = false;
    };
    out.onFocusin = () => {
      focused.value = true;
    };
    out.onFocusout = () => {
      focused.value = false;
    };
  }

  // 结构化组件没有外层 div，样式直接挂到组件根元素
  if (isWrapperless.value) out.style = { ...nodeStyle.value, ...(out.style || {}) };
  return out;
});

const textSlot = computed<string | undefined>(() => {
  const p = resolvedProps.value;
  const t = node.value.type;
  if (t === "ElIcon") return undefined;
  if (t === "ElAlert") return p.description ?? p.content;
  if (t === "ElDivider") return p.content;
  if (t === "ElCard") return undefined;
  if (t === "ElSubMenu") return p.title;
  if (t === "ElDropdown") return p.label ?? p.text;
  if (TEXT_SLOT_ELEMENTS.has(t) || meta.value?.source === "native") {
    const v = p.text ?? p.label ?? p.content;
    return v === undefined || v === null || v === "" ? undefined : String(v);
  }
  if (t === "ElOption") return p.label;
  return undefined;
});

const iconChild = computed(() => getElementIcon(resolvedProps.value.name || "Star"));

const hasChildren = computed(() => childrenList.value.length > 0);
const hasSlot = computed(() => hasChildren.value || textSlot.value !== undefined || (isIcon.value && !!iconChild.value));

const eventHandlers = computed(() => {
  if (mode.value !== "runtime" || !scope) return {};
  const out: Record<string, (e: any) => void> = {};
  for (const [name, steps] of Object.entries(node.value.events || {})) {
    if (name === "update:modelValue") continue;
    if (!Array.isArray(steps) || steps.length === 0) continue;
    out[name] = (e: any) => {
      void runSteps(steps, scope as any, { event: e, value: e });
    };
  }
  return out;
});

// 表单根：把 formValues 写回页面级 scope（供 form_<id> 绑定读取）
watch(
  () => ({ ...(form.value?.values || {}) }),
  (values) => {
    if (scope && isFormRoot.value) scope.formValues[node.value.id] = values;
  },
  { immediate: true, deep: true }
);

onMounted(() => {
  if (mode.value === "runtime" && scope) {
    if (isFormRoot.value && scope.formValidators) {
      scope.formValidators[node.value.id] = ownForm.validate!;
    }
    const loadSteps = node.value.events?.load;
    if (Array.isArray(loadSteps) && loadSteps.length) void runSteps(loadSteps, scope as any, { event: "load" });
  }
});

onUnmounted(() => {
  if (scope?.formValidators) delete scope.formValidators[node.value.id];
});

// ---------- 自定义 CSS / 响应式 CSS ----------
let cssEl: HTMLStyleElement | null = null;
function cssObjectToText(style: Record<string, any>): string {
  return Object.entries(style || {})
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${k.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())}: ${v};`)
    .join(" ");
}
const BREAKPOINTS: Record<string, { min?: number; max?: number }> = {
  xs: { max: 575 },
  sm: { min: 576, max: 767 },
  md: { min: 768, max: 991 },
  lg: { min: 992, max: 1199 },
  xl: { min: 1200 },
};
function applyNodeCss(): void {
  if (typeof document === "undefined" || props.loopItem) return;
  const id = `wp-node-css-${node.value.id}`;
  const selector = `[data-wp-node="${node.value.id}"]`;
  const chunks: string[] = [];
  if (node.value.customCss) chunks.push(`${selector}{${node.value.customCss}}`);
  for (const [bp, style] of Object.entries(node.value.responsive || {})) {
    const cfg = BREAKPOINTS[bp];
    if (!cfg || !style || !Object.keys(style).length) continue;
    const cond = [cfg.min ? `(min-width:${cfg.min}px)` : "", cfg.max ? `(max-width:${cfg.max}px)` : ""].filter(Boolean).join(" and ");
    if (cond) chunks.push(`@media ${cond}{${selector}{${cssObjectToText(style)}}}`);
  }
  for (const bp of node.value.hideOn || []) {
    const cfg = BREAKPOINTS[bp];
    if (!cfg) continue;
    const cond = [cfg.min ? `(min-width:${cfg.min}px)` : "", cfg.max ? `(max-width:${cfg.max}px)` : ""].filter(Boolean).join(" and ");
    if (cond) chunks.push(`@media ${cond}{${selector}{display:none!important}}`);
  }
  // 运行态：hover/active/focus/disabled 状态样式（设计态通过预览内联应用）。
  if (mode.value === "runtime") {
    const stateCss = buildStateCss(node.value);
    if (stateCss) chunks.push(stateCss);
  }
  if (!chunks.length) {
    cssEl?.remove();
    cssEl = null;
    return;
  }
  cssEl = (document.getElementById(id) as HTMLStyleElement | null) ?? null;
  if (!cssEl) {
    cssEl = document.createElement("style");
    cssEl.id = id;
    document.head.appendChild(cssEl);
  }
  cssEl.textContent = chunks.join("\n");
}
onMounted(applyNodeCss);
onUnmounted(() => {
  cssEl?.remove();
  cssEl = null;
});
watch(
  () => [node.value.customCss, node.value.responsive, node.value.hideOn, node.value.states],
  () => applyNodeCss(),
  { deep: true }
);

// ---------- 子节点 / 插槽 ----------
const childrenList = computed<SchemaNode[]>(() => {
  const ids = [...(node.value.children || []), ...(node.value.slots?.default || [])];
  return ids.map((id) => props.nodes[id]).filter((n) => !!n);
});

const slotNodes = computed<Record<string, SchemaNode[]>>(() => {
  const out: Record<string, SchemaNode[]> = {};
  for (const [slotName, ids] of Object.entries(node.value.slots || {})) {
    if (slotName === "default") continue;
    out[slotName] = (ids || []).map((id) => props.nodes[id]).filter((n) => !!n);
  }
  return out;
});
const namedSlotNodes = slotNodes;

// 运行态所有节点都不包 .wp-node：否则 ElRow/ElCol、ElSpace 等布局组件拿到的
// 直接子节点是 div 包装层，flex-basis/百分比宽度会失效。设计态仍保留包装层用于选中。
const isWrapperless = computed(() => mode.value === "runtime");

const canvasStyle = computed<Record<string, string>>(() => ({
  position: "relative",
  ...(props.canvasStyle || {}),
}));

const viewportWidth = ref(typeof window !== "undefined" ? window.innerWidth : 1200);
function onViewportResize() {
  viewportWidth.value = window.innerWidth;
}
onMounted(() => window.addEventListener("resize", onViewportResize));
onUnmounted(() => window.removeEventListener("resize", onViewportResize));

const activeLayout = computed(() => {
  const base = node.value.layout;
  if (!base || mode.value === "design") return base;
  const key = viewportWidth.value <= 480 ? "phone" : viewportWidth.value <= 900 ? "tablet" : "desktop";
  const override = key === "desktop" ? null : (node.value as any).responsiveLayout?.[key];
  return override ? { ...base, ...override } : base;
});

const nodeStyle = computed<Record<string, any>>(() => {
  const s: Record<string, any> = {
    ...(node.value.style || {}),
    ...variantStyle.value,
    ...runtimeStateStyle.value,
    ...previewStateStyle.value,
  };
  if (activeLayout.value) {
    Object.assign(s, {
      position: "absolute",
      left: `${activeLayout.value.x}px`,
      top: `${activeLayout.value.y}px`,
      width: `${activeLayout.value.width}px`,
      height: `${activeLayout.value.height}px`,
    });
  }
  return s;
});

</script>

<style scoped>
.wp-conditional-placeholder {
  padding: 8px 10px;
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-unknown {
  padding: 8px;
  border: 1px dashed var(--el-color-danger);
  color: var(--el-color-danger);
  font-size: 12px;
}
.wp-repeater {
  width: 100%;
}
/* 设计态状态预览标记：虚线描边提示当前为临时预览。 */
.wp-node[data-state-preview] {
  outline: 1px dashed var(--el-color-warning);
  outline-offset: 1px;
}
</style>
