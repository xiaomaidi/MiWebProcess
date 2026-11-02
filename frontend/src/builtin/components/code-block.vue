<template>
  <div class="wp-code" :style="{ height: height || undefined }">
    <div class="wp-code-bar">
      <span>{{ language }}</span>
      <button type="button" @click="copy">{{ copied ? "已复制" : "复制" }}</button>
    </div>
    <pre class="wp-code-pre"><code v-html="html" /></pre>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { highlightCode } from "@/engine/sanitize";

const props = withDefaults(
  defineProps<{
    code?: string;
    language?: string;
    showLineNumbers?: boolean;
    height?: string;
  }>(),
  {
    code: "",
    language: "text",
    showLineNumbers: true,
    height: "",
  }
);

const copied = ref(false);
const html = computed(() => {
  const code = highlightCode(props.code || "", props.language || "text");
  if (!props.showLineNumbers) return code;
  return code
    .split("\n")
    .map((line, i) => `<span class="wp-code-line"><span class="wp-code-ln">${i + 1}</span>${line || " "}</span>`)
    .join("\n");
});

async function copy() {
  try {
    await navigator.clipboard.writeText(props.code || "");
    copied.value = true;
    setTimeout(() => (copied.value = false), 1500);
  } catch {
    /* ignore */
  }
}
</script>

<style scoped>
.wp-code {
  border: 1px solid #1e293b;
  border-radius: 8px;
  overflow: hidden;
  background: #0f172a;
  color: #e2e8f0;
}
.wp-code-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 10px;
  background: #1e293b;
  color: #94a3b8;
  font-size: 12px;
  font-family: ui-monospace, Consolas, monospace;
}
.wp-code-bar button {
  border: none;
  background: transparent;
  color: #93c5fd;
  cursor: pointer;
  font-size: 12px;
}
.wp-code-pre {
  margin: 0;
  padding: 10px 0;
  overflow: auto;
  max-height: 100%;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.65;
}
.wp-code-line {
  display: block;
  padding: 0 12px;
}
.wp-code-ln {
  display: inline-block;
  width: 32px;
  margin-right: 12px;
  text-align: right;
  color: #64748b;
  user-select: none;
}
.wp-code :deep(.tok-key) {
  color: #c792ea;
}
.wp-code :deep(.tok-string) {
  color: #a5d6a7;
}
.wp-code :deep(.tok-comment) {
  color: #64748b;
  font-style: italic;
}
</style>
