<template>
  <el-button
    :type="type"
    :size="size"
    :plain="plain"
    :round="round"
    :circle="circle"
    :disabled="disabled"
    :block="block"
    @click="on_click"
  >
    {{ label }}
  </el-button>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    label?: string;
    type?: "primary" | "success" | "warning" | "danger" | "info" | "default";
    size?: "small" | "default" | "large";
    plain?: boolean;
    round?: boolean;
    circle?: boolean;
    disabled?: boolean;
    block?: boolean;
  }>(),
  {
    label: "按钮",
    type: "primary",
    size: "default",
    plain: false,
    round: false,
    circle: false,
    disabled: false,
    block: false,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

function on_click(e: MouseEvent) {
  if (props.disabled) return;
  emit("click", e);
}
</script>
