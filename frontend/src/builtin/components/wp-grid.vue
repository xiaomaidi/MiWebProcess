<template>
  <div class="wp-grid" :style="box" @click="on_click">
    <slot />
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    columns?: number;
    gap?: number;
    padding?: number;
    background?: string;
  }>(),
  {
    columns: 4,
    gap: 8,
    padding: 8,
    background: "#f5f7fa",
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed(() => ({
  display: "grid",
  gridTemplateColumns: `repeat(${Math.max(1, props.columns)}, minmax(0, 1fr))`,
  gap: String(props.gap),
  padding: String(props.padding),
  background: props.background,
}));

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>
