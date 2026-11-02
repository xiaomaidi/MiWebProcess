<template>
  <el-divider :direction="direction" class="wp-divider">
    <template v-if="text">{{ text }}</template>
  </el-divider>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    direction?: "horizontal" | "vertical";
    text?: string;
    color?: string;
  }>(),
  {
    direction: "horizontal",
    text: "",
    color: "#dcdfe6",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;
</script>

<style scoped>
.wp-divider {
  --el-divider-border-color: v-bind(color);
}
</style>
