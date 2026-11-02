<template>
  <div class="wp-container" :style="box" @click="on_click">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    layout?: "flex" | "grid";
    direction?: "column" | "row";
    gap?: number;
    padding?: number;
    background?: string;
    color?: string;
    align?: "stretch" | "center" | "flex-start" | "flex-end";
    justify?: "flex-start" | "center" | "flex-end" | "space-between";
    borderRadius?: number;
  }>(),
  {
    layout: "flex",
    direction: "column",
    gap: 8,
    padding: 8,
    background: "#f5f7fa",
    color: "#303133",
    align: "stretch",
    justify: "flex-start",
    borderRadius: 4,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed(() => {
  const s: Record<string, string | number> = {
    gap: String(props.gap),
    padding: String(props.padding),
    background: props.background,
    color: props.color,
    borderRadius: String(props.borderRadius),
  };
  if (props.layout === "grid") {
    s.display = "grid";
    s.gridAutoFlow = "column";
    s.gridAutoColumns = "1fr";
  } else {
    s.display = "flex";
    s.flexDirection = props.direction;
    s.alignItems = props.align;
    s.justifyContent = props.justify;
  }
  return s;
});

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>
