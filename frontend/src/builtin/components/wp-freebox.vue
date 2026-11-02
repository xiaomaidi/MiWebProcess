<template>
  <div class="wp-freebox" :style="box" @click="on_click">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, type CSSProperties } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    x?: number;
    y?: number;
    width?: number;
    height?: number;
    background?: string;
    borderRadius?: number;
    zIndex?: number;
  }>(),
  {
    x: 0,
    y: 0,
    width: 200,
    height: 100,
    background: "#ffffff",
    borderRadius: 4,
    zIndex: 0,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed<CSSProperties>(() => ({
  position: "absolute",
  left: `${props.x}px`,
  top: `${props.y}px`,
  width: `${props.width}px`,
  height: `${props.height}px`,
  background: props.background,
  borderRadius: `${props.borderRadius}px`,
  zIndex: String(props.zIndex),
}));

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>
