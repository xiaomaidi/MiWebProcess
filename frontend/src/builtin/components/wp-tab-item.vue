<template>
  <el-tab-pane :label="props.label" :disabled="props.disabled" @click="onClick">
    <slot />
  </el-tab-pane>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

const props = withDefaults(
  defineProps<{
    label?: string;
    disabled?: boolean;
  }>(),
  {
    label: "选项卡",
    disabled: false,
  }
);

const emit = defineEmits<{
  (e: "click", event: MouseEvent): void;
}>();

function onClick(event: MouseEvent): void {
  emit("click", event);
}
</script>
