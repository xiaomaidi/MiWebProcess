<template>
  <div class="wp-html" v-html="safeHtml" />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { sanitizeHtml } from "@/engine/sanitize";

const props = withDefaults(defineProps<{ html?: string; sanitize?: boolean }>(), {
  html: "",
  sanitize: true,
});

const safeHtml = computed(() => sanitizeHtml(props.html || ""));
</script>

<style scoped>
.wp-html {
  min-height: 1px;
}
</style>
