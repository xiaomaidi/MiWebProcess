<template>
  <div class="wp-field" :class="{ 'wp-field-inline': form && form.inline }">
    <label v-if="props.label" class="wp-field-label" :style="labelStyle">{{ props.label }}</label>
    <el-input-number
      class="wp-field-control"
      :model-value="model"
      :min="props.min"
      :max="props.max"
      :step="props.step"
      :precision="props.precision"
      :disabled="disabled"
      @update:model-value="onChange"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import type { RuntimeScope } from "@/types";
import type { WpFormContext } from "./form-context";
import { wpFormContextKey } from "./form-context";

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

const props = withDefaults(
  defineProps<{
    field?: string;
    label?: string;
    min?: number;
    max?: number;
    step?: number;
    precision?: number;
    disabled?: boolean;
  }>(),
  {
    field: "field",
    label: "",
    min: 0,
    max: 100,
    step: 1,
    precision: 0,
    disabled: false,
  }
);

const emit = defineEmits<{
  (e: "change", value: number): void;
}>();

const form = inject<WpFormContext | null>(wpFormContextKey, null);

const stored = form ? form.values[props.field] : undefined;
const model = ref<number>(
  typeof stored === "number" && Number.isFinite(stored) ? stored : props.min
);

if (form) form.register(props.field, model.value);

const disabled = computed(() => props.disabled || (form ? form.disabled : false));

const labelStyle = computed(() => {
  if (!form || form.labelPosition === "top") return {};
  return { flex: `0 0 ${form.labelWidth}px`, width: `${form.labelWidth}px` };
});

function onChange(value: number | undefined): void {
  if (typeof value !== "number") return;
  model.value = value;
  emit("change", value);
}

watch(model, (value) => {
  if (form) form.setField(props.field, value);
});

watch(
  () => (form ? form.values[props.field] : undefined),
  (value) => {
    if (typeof value === "number" && value !== model.value) model.value = value;
  }
);
</script>

<style scoped>
.wp-field {
  display: flex;
  align-items: flex-start;
}
.wp-field-inline {
  display: inline-flex;
  margin-right: 12px;
}
.wp-field-label {
  flex: 0 0 auto;
  line-height: 32px;
  color: #606266;
  font-size: 14px;
}
.wp-field-control {
  flex: 1 1 auto;
}
</style>
