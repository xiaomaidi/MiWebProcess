<template>
  <div class="wp-field" :class="{ 'wp-field-inline': form && form.inline }">
    <label v-if="props.label" class="wp-field-label" :style="labelStyle">{{ props.label }}</label>
    <el-input
      class="wp-field-control"
      type="textarea"
      :model-value="model"
      :placeholder="props.placeholder"
      :rows="props.rows"
      :disabled="disabled"
      :maxlength="props.maxlength || undefined"
      @update:model-value="onInput"
      @change="onChange"
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
    placeholder?: string;
    rows?: number;
    disabled?: boolean;
    maxlength?: number;
  }>(),
  {
    field: "field",
    label: "",
    placeholder: "请输入",
    rows: 3,
    disabled: false,
    maxlength: 500,
  }
);

const emit = defineEmits<{
  (e: "input", value: string): void;
  (e: "change", value: string): void;
}>();

const form = inject<WpFormContext | null>(wpFormContextKey, null);

const stored = form ? form.values[props.field] : undefined;
const model = ref<string>(typeof stored === "string" ? stored : "");

if (form) form.register(props.field, model.value);

const disabled = computed(() => props.disabled || (form ? form.disabled : false));

const labelStyle = computed(() => {
  if (!form || form.labelPosition === "top") return {};
  return { flex: `0 0 ${form.labelWidth}px`, width: `${form.labelWidth}px` };
});

function onInput(value: string): void {
  model.value = value;
  emit("input", value);
}

function onChange(value: string): void {
  emit("change", value);
}

watch(model, (value) => {
  if (form) form.setField(props.field, value);
});

watch(
  () => (form ? form.values[props.field] : undefined),
  (value) => {
    if (typeof value === "string" && value !== model.value) model.value = value;
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
