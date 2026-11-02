<template>
  <div ref="host" class="wp-monaco" :style="{ height }" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/esm/vs/editor/editor.worker?worker";
import TsWorker from "monaco-editor/esm/vs/language/typescript/ts.worker?worker";

(self as any).MonacoEnvironment = {
  getWorker(_workerId: string, label: string) {
    if (label === "typescript" || label === "javascript") return new TsWorker();
    return new EditorWorker();
  },
};

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    language?: string;
    height?: string;
    errorLine?: number;
    errorMessage?: string;
    readOnly?: boolean;
  }>(),
  {
    modelValue: "",
    language: "html",
    height: "460px",
    errorLine: 0,
    errorMessage: "",
    readOnly: false,
  }
);

const emit = defineEmits<{ (e: "update:modelValue", value: string): void }>();
const host = ref<HTMLElement | null>(null);
let editor: monaco.editor.IStandaloneCodeEditor | null = null;
let resizeObserver: ResizeObserver | null = null;
let suppress = false;

function applyErrorMarker(line: number) {
  if (!editor) return;
  const model = editor.getModel();
  if (!model) return;
  if (!line) {
    monaco.editor.setModelMarkers(model, "wp-component", []);
    return;
  }
  monaco.editor.setModelMarkers(model, "wp-component", [
    {
      startLineNumber: line,
      startColumn: 1,
      endLineNumber: line,
      endColumn: Math.max(2, model.getLineMaxColumn(line)),
      message: props.errorMessage || "编译错误",
      severity: monaco.MarkerSeverity.Error,
    },
  ]);
  editor.revealLineInCenter(line);
  editor.setPosition({ lineNumber: line, column: 1 });
}

onMounted(() => {
  if (!host.value) return;
  editor = monaco.editor.create(host.value, {
    value: props.modelValue,
    language: props.language,
    theme: "vs-dark",
    automaticLayout: true,
    minimap: { enabled: false },
    fontSize: 13,
    lineHeight: 20,
    tabSize: 2,
    scrollBeyondLastLine: false,
    readOnly: props.readOnly,
    wordWrap: "on",
  });
  editor.onDidChangeModelContent(() => {
    if (suppress) return;
    emit("update:modelValue", editor?.getValue() || "");
  });
  applyErrorMarker(props.errorLine);
  resizeObserver = new ResizeObserver(() => editor?.layout());
  resizeObserver.observe(host.value);
});

watch(
  () => props.modelValue,
  (value) => {
    if (!editor || editor.getValue() === (value || "")) return;
    suppress = true;
    editor.setValue(value || "");
    suppress = false;
  }
);

watch(
  () => [props.errorLine, props.errorMessage],
  () => applyErrorMarker(props.errorLine)
);

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  editor?.dispose();
  editor = null;
});
</script>

<style scoped>
.wp-monaco {
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  overflow: hidden;
}
</style>
