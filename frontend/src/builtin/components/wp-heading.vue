<template>
  <component :is="tag" class="wp-heading" :style="box" @click="on_click">
    <slot>{{ content }}</slot>
  </component>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    content?: string;
    level?: 1 | 2 | 3 | 4 | 5 | 6;
    color?: string;
    align?: "left" | "center" | "right";
    marginBottom?: number;
  }>(),
  {
    content: "标题",
    level: 2,
    color: "#303133",
    align: "left",
    marginBottom: 8,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const tag = computed(() => `h${Math.min(6, Math.max(1, props.level))}`);

const box = computed(() => ({
  color: props.color,
  textAlign: props.align,
  marginBottom: `${props.marginBottom}px`,
}));

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>
