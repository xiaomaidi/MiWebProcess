<template>
  <el-alert
    :title="title || content"
    :description="title ? content : undefined"
    :type="alertType"
    :closable="closable"
    :center="center"
    :show-icon="true"
    @close="on_close"
  />
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    title?: string;
    content?: string;
    type?: "success" | "info" | "warning" | "danger";
    closable?: boolean;
    center?: boolean;
  }>(),
  {
    title: "",
    content: "这是一条警告提示",
    type: "info",
    closable: false,
    center: false,
  }
);

const emit = defineEmits<{ (e: "close", payload?: undefined): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

/** registry 的 danger 映射到 el-alert 的 error */
const alertType = computed(() => (props.type === "danger" ? "error" : props.type));

function on_close() {
  emit("close");
}
</script>
