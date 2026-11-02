<template>
  <div class="wp-svg" :style="{ width, height }" v-html="safeSvg" />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { sanitizeSvg } from "@/engine/sanitize";

const props = withDefaults(defineProps<{ code?: string; width?: string; height?: string }>(), {
  code: "",
  width: "160px",
  height: "160px",
});

const safeSvg = computed(() => sanitizeSvg(props.code || ""));
</script>

<style scoped>
.wp-svg {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.wp-svg :deep(svg) {
  max-width: 100%;
  max-height: 100%;
}
</style>
