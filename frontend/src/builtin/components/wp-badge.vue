<template>
  <el-badge :value="value" :max="max" :is-dot="dot" :type="type" class="wp-badge">
    <slot />
  </el-badge>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    value?: number;
    max?: number;
    dot?: boolean;
    type?: "primary" | "success" | "warning" | "danger" | "info";
  }>(),
  {
    value: 0,
    max: 99,
    dot: false,
    type: "danger",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;
void props;
</script>
