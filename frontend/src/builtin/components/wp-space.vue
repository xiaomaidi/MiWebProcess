<template>
  <el-space :size="size" :direction="direction" class="wp-space">
    <slot />
  </el-space>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    size?: "small" | "default" | "large";
    direction?: "horizontal" | "vertical";
  }>(),
  {
    size: "default",
    direction: "horizontal",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;
</script>
