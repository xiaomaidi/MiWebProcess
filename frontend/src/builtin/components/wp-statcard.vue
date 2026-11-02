<template>
  <div class="wp-statcard" :style="cardStyle" @click="onClick">
    <div class="wp-statcard-value" :style="{ color: props.color, fontSize: `${props.fontSize}px` }">
      {{ displayValue }}{{ props.suffix }}
    </div>
    <div class="wp-statcard-label">{{ props.label }}</div>
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";
import { metricFromScope } from "../scope-data";

const props = withDefaults(
  defineProps<{
    label?: string;
    suffix?: string;
    color?: string;
    fontSize?: number;
    background?: string;
    padding?: number;
    borderRadius?: number;
  }>(),
  {
    label: "指标",
    suffix: "",
    color: "#409eff",
    fontSize: 28,
    background: "#ffffff",
    padding: 16,
    borderRadius: 8,
  }
);

const emit = defineEmits<{
  (e: "click", event: MouseEvent): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const value = computed(() => metricFromScope(scope, props.label));

const displayValue = computed(() => (value.value === null ? "--" : String(value.value)));

const cardStyle = computed(() => ({
  background: props.background,
  padding: `${props.padding}px`,
  borderRadius: `${props.borderRadius}px`,
}));

function onClick(event: MouseEvent): void {
  emit("click", event);
}
</script>

<style scoped>
.wp-statcard {
  box-sizing: border-box;
  cursor: pointer;
  min-width: 96px;
}
.wp-statcard-value {
  font-weight: 600;
  line-height: 1.2;
}
.wp-statcard-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}
</style>
