<template>
  <el-progress
    :percentage="clamped"
    :stroke-width="height"
    :color="strokeColor"
    :show-text="showText"
    class="wp-progress"
  />
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    percent?: number;
    strokeColor?: string;
    height?: number;
    showText?: boolean;
  }>(),
  {
    percent: 50,
    strokeColor: "#409eff",
    height: 8,
    showText: true,
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

const clamped = computed(() => {
  const n = Number(props.percent);
  if (!Number.isFinite(n)) return 0;
  return Math.min(100, Math.max(0, Math.round(n)));
});
</script>
