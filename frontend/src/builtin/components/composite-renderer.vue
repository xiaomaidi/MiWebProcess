<template>
  <component :is="RootRenderer" />
</template>

<script setup lang="ts">
/**
 * 组合组件适配器：ElTabs/ElSteps/ElCarousel/ElSplitter/ElTour 通过
 * useOrderedChildren 按 vnode.type.name 收集直接子组件；NodeRenderer 包一层
 * 会导致收集失败。这里由 render 函数直接生成真实子组件 VNode。
 */
import { computed, defineAsyncComponent, h, inject, useAttrs, defineComponent } from "vue";
import type { SchemaNode, RuntimeScope, ComponentMeta } from "@/types";
import { useComponentStore } from "@/store/component";
import { resolveProps } from "@/engine/binding";
import { runSteps } from "@/engine/actions";
import { getElementComponent } from "@/engine/element-components";

const props = withDefaults(
  defineProps<{
    rootElement: string;
    childElement?: string;
    childIds?: string[];
    nodes?: Record<string, SchemaNode>;
    mode?: "design" | "runtime";
    wpNodeId?: string;
  }>(),
  {
    childElement: "",
    childIds: () => [],
    nodes: () => ({}),
    mode: "runtime",
    wpNodeId: "",
  }
);

const attrs = useAttrs();
const components = useComponentStore();
const scope = inject<RuntimeScope | null>("wp.scope", null);
const design = inject<{
  selectedId: string | null;
  selectedIds: string[];
  onSelect: (id: string | null, additive?: boolean) => void;
} | null>("wp.design", null);
const NodeRenderer = defineAsyncComponent(() => import("@/engine/NodeRenderer.vue"));

const rootComp = computed(() => getElementComponent(props.rootElement));

function childListeners(node: SchemaNode): Record<string, (e: any) => void> {
  if (props.mode !== "runtime" || !scope) return {};
  const out: Record<string, (e: any) => void> = {};
  for (const [name, steps] of Object.entries(node.events || {})) {
    if (name === "update:modelValue") continue;
    if (!Array.isArray(steps) || !steps.length) continue;
    const key = `on${name.charAt(0).toUpperCase()}${name.slice(1)}`;
    out[key] = (e: any) => {
      void runSteps(steps, scope as any, { event: e, value: e });
    };
  }
  return out;
}

function childVNode(id: string) {
  const child = props.nodes[id];
  if (!child) return null;
  const meta: ComponentMeta | undefined = components.meta(child.type);
  const el = meta?.element || props.childElement || "div";
  const comp = getElementComponent(el) || getElementComponent(props.childElement) || "div";
  const p: Record<string, any> = scope ? resolveProps(child.props || {}, scope as any) : { ...(child.props || {}) };
  delete p.field;
  const ids = [...(child.children || []), ...(child.slots?.default || [])];
  const text = p.text ?? p.label ?? p.content;
  const slots: Record<string, () => any[]> = {
    default: () =>
      ids.length
        ? ids
            .filter((cid) => !!props.nodes[cid])
            .map((cid) => h(NodeRenderer, { node: props.nodes[cid], nodes: props.nodes, mode: props.mode }))
        : text !== undefined && text !== ""
          ? [String(text)]
          : [],
  };
  if (el === "ElSubMenu" && (p.title || p.label)) {
    const title = String(p.title ?? p.label);
    slots.title = () => [title];
  }
  const listeners: Record<string, any> = { ...childListeners(child) };
  if (props.mode === "design" && design) {
    listeners.onClick = (e: MouseEvent) => {
      e.stopPropagation();
      design.onSelect(child.id, e.ctrlKey || e.metaKey || e.shiftKey);
    };
  }
  return h(comp as any, { ...p, ...listeners, "data-wp-node": child.id }, slots as any);
}

const RootRenderer = defineComponent({
  name: "WpCompositeRoot",
  setup() {
    return () =>
      rootComp.value
        ? h(
            rootComp.value as any,
            { ...attrs },
            { default: () => props.childIds.map(childVNode).filter(Boolean) } as any
          )
        : null;
  },
});
</script>
