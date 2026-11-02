<template>
  <el-link :type="type" :underline="underline" :disabled="disabled" :href="href" :target="target" @click="on_click">
    {{ label }}
  </el-link>
</template>

<script setup lang="ts">
import { inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    label?: string;
    href?: string;
    target?: "_self" | "_blank";
    type?: "primary" | "success" | "warning" | "danger" | "info";
    underline?: boolean;
    disabled?: boolean;
  }>(),
  {
    label: "链接",
    href: "#",
    target: "_self",
    type: "primary",
    underline: true,
    disabled: false,
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
