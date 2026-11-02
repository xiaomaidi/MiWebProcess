<template>
  <div class="wp-field" :class="{ 'wp-field-inline': form && form.inline }">
    <label v-if="props.label" class="wp-field-label" :style="labelStyle">{{ props.label }}</label>
    <el-select
      class="wp-field-control"
      v-model="model"
      :placeholder="props.placeholder"
      :multiple="props.multiple"
      :clearable="props.clearable"
      :disabled="disabled"
      @change="onChange"
    >
      <el-option v-for="opt in props.options" :key="opt.value" :label="opt.label" :value="opt.value" />
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import type { RuntimeScope } from "@/types";
import type { WpFormContext } from "./form-context";
import { wpFormContextKey } from "./form-context";

const scope = inject<RuntimeScope | null>("wp.scope", null);
void scope;

interface SelectOption {
  label: string;
  value: string;
}

const props = withDefaults(
  defineProps<{
    field?: string;
    label?: string;
    options?: SelectOption[];
    placeholder?: string;
    multiple?: boolean;
    clearable?: boolean;
    disabled?: boolean;
  }>(),
  {
    field: "field",
    label: "",
    options: () => [
      { label: "选项一", value: "1" },
      { label: "选项二", value: "2" },
    ],
    placeholder: "请选择",
    multiple: false,
    clearable: true,
    disabled: false,
  }
);

const emit = defineEmits<{
  (e: "change", value: string | string[]): void;
}>();

const form = inject<WpFormContext | null>(wpFormContextKey, null);

type ModelValue = string | string[];
const stored = form ? form.values[props.field] : undefined;
const model = ref<ModelValue>(
  props.multiple ? (Array.isArray(stored) ? stored : []) : typeof stored === "string" ? stored : ""
);

if (form) form.register(props.field, model.value);

const disabled = computed(() => props.disabled || (form ? form.disabled : false));

const labelStyle = computed(() => {
  if (!form || form.labelPosition === "top") return {};
  return { flex: `0 0 ${form.labelWidth}px`, width: `${form.labelWidth}px` };
});

function onChange(value: string | string[]): void {
  emit("change", value);
}

watch(model, (value) => {
  if (form) form.setField(props.field, value);
});

watch(
  () => (form ? form.values[props.field] : undefined),
  (value) => {
    if (value !== model.value) model.value = value as ModelValue;
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
