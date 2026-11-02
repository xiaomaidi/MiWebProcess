<template>
  <span class="wp-text" :style="box" @click="on_click">
    <slot>{{ content }}</slot>
  </span>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    content?: string;
    fontSize?: number;
    color?: string;
    fontWeight?: 400 | 500 | 700;
    lineHeight?: number;
    align?: "left" | "center" | "right";
    italic?: boolean;
    ellipsis?: boolean;
  }>(),
  {
    content: "双击文本进行编辑",
    fontSize: 14,
    color: "#303133",
    fontWeight: 400,
    lineHeight: 1.5,
    align: "left",
    italic: false,
    ellipsis: false,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed(() => ({
  fontSize: `${props.fontSize}px`,
  color: props.color,
  fontWeight: String(props.fontWeight),
  lineHeight: String(props.lineHeight),
  textAlign: props.align,
  fontStyle: props.italic ? "italic" : "normal",
  whiteSpace: props.ellipsis ? "nowrap" : "normal",
  overflow: props.ellipsis ? "hidden" : "visible",
  textOverflow: props.ellipsis ? "ellipsis" : "clip",
  display: props.ellipsis ? "block" : "inline",
}));

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>
