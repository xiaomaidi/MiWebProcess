<template>
  <div class="wp-list" :style="style">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, type CSSProperties } from "vue";
import type { RuntimeScope } from "@/types";

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

const props = withDefaults(
  defineProps<{
    direction?: "vertical" | "horizontal";
    gap?: number;
    padding?: number;
    background?: string;
    borderRadius?: number;
  }>(),
  {
    direction: "vertical",
    gap: 8,
    padding: 8,
    background: "#ffffff",
    borderRadius: 4,
  }
);

const style = computed<CSSProperties>(() => ({
  display: "flex",
  flexDirection: props.direction === "horizontal" ? "row" : "column",
  gap: `${props.gap}px`,
  padding: `${props.padding}px`,
  background: props.background,
  borderRadius: `${props.borderRadius}px`,
}));
</script>
