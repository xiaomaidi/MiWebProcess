<template>
  <el-tag
    :type="props.type"
    :size="size"
    :effect="effect"
    :closable="closable"
    @click="on_click"
    @close="on_close"
  >
    {{ label }}
  </el-tag>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    label?: string;
    type?: "success" | "info" | "warning" | "danger";
    size?: "small" | "default" | "large";
    effect?: "dark" | "plain" | "light";
    closable?: boolean;
  }>(),
  {
    label: "标签",
    type: "info",
    size: "default",
    effect: "light",
    closable: false,
  }
);

const emit = defineEmits<{
  (e: "click", payload: MouseEvent): void;
  (e: "close", payload?: undefined): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

function on_click(e: MouseEvent) {
  emit("click", e);
}

function on_close() {
  emit("close");
}
</script>
