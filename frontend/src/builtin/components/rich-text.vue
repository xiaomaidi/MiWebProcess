<template>
  <div class="wp-rich" :style="{ height: height ? height + 'px' : undefined }">
    <div v-if="toolbar && !readonly" class="wp-rich-toolbar">
      <button type="button" title="加粗" @mousedown.prevent="cmd('bold')"><b>B</b></button>
      <button type="button" title="斜体" @mousedown.prevent="cmd('italic')"><i>I</i></button>
      <button type="button" title="下划线" @mousedown.prevent="cmd('underline')"><u>U</u></button>
      <button type="button" title="删除线" @mousedown.prevent="cmd('strikeThrough')"><s>S</s></button>
      <span class="wp-rich-sep" />
      <button type="button" title="无序列表" @mousedown.prevent="cmd('insertUnorderedList')">• 列表</button>
      <button type="button" title="有序列表" @mousedown.prevent="cmd('insertOrderedList')">1. 列表</button>
      <button type="button" title="引用" @mousedown.prevent="cmd('formatBlock', 'blockquote')">引用</button>
      <button type="button" title="代码块" @mousedown.prevent="cmd('formatBlock', 'pre')">代码</button>
      <span class="wp-rich-sep" />
      <button type="button" title="链接" @mousedown.prevent="insertLink">链接</button>
      <button type="button" title="清除格式" @mousedown.prevent="cmd('removeFormat')">清除</button>
    </div>
    <div
      ref="editorRef"
      class="wp-rich-editor"
      :contenteditable="!readonly"
      :data-placeholder="placeholder"
      spellcheck="false"
      @input="onInput"
      @blur="onBlur"
    />
    <div v-if="readonly" class="wp-rich-readonly-mask" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { sanitizeHtml } from "@/engine/sanitize";

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    content?: string;
    placeholder?: string;
    readonly?: boolean;
    height?: number;
    toolbar?: boolean;
  }>(),
  {
    content: "",
    placeholder: "请输入内容",
    readonly: false,
    height: 220,
    toolbar: true,
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", v: string): void;
  (e: "input", v: string): void;
  (e: "change", v: string): void;
}>();

const editorRef = ref<HTMLElement | null>(null);
const value = computed(() => (props.modelValue !== undefined ? props.modelValue : props.content || ""));

function applyValue() {
  const el = editorRef.value;
  if (!el) return;
  const html = sanitizeHtml(value.value);
  if (el.innerHTML !== html) el.innerHTML = html;
}

onMounted(() => nextTick(applyValue));
watch(value, () => nextTick(applyValue));

function onInput() {
  const html = editorRef.value?.innerHTML ?? "";
  emit("update:modelValue", html);
  emit("input", html);
}

function onBlur() {
  const el = editorRef.value;
  if (!el) return;
  const html = sanitizeHtml(el.innerHTML);
  if (el.innerHTML !== html) el.innerHTML = html;
  emit("update:modelValue", html);
  emit("change", html);
}

function cmd(command: string, arg?: string) {
  editorRef.value?.focus();
  document.execCommand(command, false, arg);
  onInput();
}

function insertLink() {
  const url = window.prompt("链接地址", "https://");
  if (url) cmd("createLink", url);
}
</script>

<style scoped>
.wp-rich {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  background: var(--el-bg-color);
  overflow: hidden;
}
.wp-rich-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  padding: 4px 6px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-light);
}
.wp-rich-toolbar button {
  border: none;
  background: transparent;
  color: var(--el-text-color-regular);
  font-size: 12px;
  padding: 3px 6px;
  border-radius: 3px;
  cursor: pointer;
}
.wp-rich-toolbar button:hover {
  background: var(--el-fill-color-dark);
}
.wp-rich-sep {
  width: 1px;
  height: 16px;
  background: var(--el-border-color);
  margin: 0 4px;
}
.wp-rich-editor {
  flex: 1;
  min-height: 100px;
  padding: 8px 10px;
  overflow: auto;
  outline: none;
  font-size: 14px;
  line-height: 1.7;
}
.wp-rich-editor:empty::before {
  content: attr(data-placeholder);
  color: var(--el-text-color-placeholder);
  pointer-events: none;
}
.wp-rich-readonly-mask {
  display: none;
}
</style>
