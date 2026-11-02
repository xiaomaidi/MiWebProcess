<template>
  <div class="wp-card" :style="box" @click="on_click">
    <div v-if="$slots.header || title" class="wp-card-header" :style="{ padding: padding > 0 ? `0 0 ${Math.round(padding / 2)}px 0` : undefined }">
      <slot name="header">
        <template v-if="title">{{ title }}</template>
      </slot>
    </div>
    <div class="wp-card-body" :style="{ padding: padding > 0 ? `0 ${padding}px ${padding}px` : undefined }">
      <slot />
    </div>
    <div v-if="$slots.footer" class="wp-card-footer" :style="{ padding: padding > 0 ? `0 ${padding}px ${padding}px` : undefined }">
      <slot name="footer" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    title?: string;
    background?: string;
    padding?: number;
    shadow?: boolean;
    bordered?: boolean;
    borderRadius?: number;
  }>(),
  {
    title: "",
    background: "#ffffff",
    padding: 16,
    shadow: true,
    bordered: false,
    borderRadius: 8,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed(() => {
  const s: Record<string, string> = {
    background: props.background,
    borderRadius: `${props.borderRadius}px`,
  };
  if (props.shadow) s.boxShadow = "0 2px 12px 0 rgba(0, 0, 0, 0.1)";
  if (props.bordered) s.border = "1px solid #ebeef5";
  return s;
});

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>

<style scoped>
.wp-card-header {
  font-weight: 600;
  color: #303133;
  padding-left: 16px;
  padding-right: 16px;
}
.wp-card-footer {
  border-top: 1px solid #ebeef5;
}
</style>
