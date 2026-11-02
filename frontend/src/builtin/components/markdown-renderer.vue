<template>
  <div class="wp-markdown" :style="{ height: height || undefined, overflow: height ? 'auto' : undefined }" v-html="html" />
</template>

<script setup lang="ts">
import { computed } from "vue";
import { renderMarkdown } from "@/engine/sanitize";

const props = withDefaults(defineProps<{ content?: string; height?: string }>(), {
  content: "",
  height: "",
});

const html = computed(() => renderMarkdown(props.content || ""));
</script>

<style scoped>
.wp-markdown {
  font-size: 14px;
  line-height: 1.75;
  color: var(--el-text-color-primary);
  word-break: break-word;
}
.wp-markdown :deep(h1),
.wp-markdown :deep(h2),
.wp-markdown :deep(h3) {
  margin: 0.8em 0 0.4em;
  line-height: 1.35;
}
.wp-markdown :deep(pre) {
  padding: 10px 12px;
  background: #0f172a;
  color: #e2e8f0;
  border-radius: 6px;
  overflow: auto;
}
.wp-markdown :deep(code) {
  padding: 1px 4px;
  background: var(--el-fill-color);
  border-radius: 3px;
  font-family: ui-monospace, Consolas, monospace;
}
.wp-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}
.wp-markdown :deep(blockquote) {
  margin: 8px 0;
  padding: 4px 12px;
  border-left: 3px solid var(--el-color-primary);
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
}
.wp-markdown :deep(table) {
  border-collapse: collapse;
  width: 100%;
}
.wp-markdown :deep(td),
.wp-markdown :deep(th) {
  border: 1px solid var(--el-border-color);
  padding: 6px 8px;
}
</style>
