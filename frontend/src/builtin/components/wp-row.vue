<template>
  <div class="wp-row" :style="box" @click="on_click">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, type CSSProperties } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    gap?: number;
    align?: "stretch" | "center" | "flex-start" | "flex-end";
    justify?: "flex-start" | "center" | "flex-end" | "space-between";
    padding?: number;
    background?: string;
  }>(),
  {
    gap: 8,
    align: "center",
    justify: "flex-start",
    padding: 0,
    background: "transparent",
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed<CSSProperties>(() => ({
  display: "flex",
  flexDirection: "row",
  flexWrap: "wrap",
  gap: String(props.gap),
  alignItems: props.align,
  justifyContent: props.justify,
  padding: String(props.padding),
  background: props.background,
}));

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>
