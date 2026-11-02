<template>
  <div class="wp-choice-field">
    <label v-if="label" class="wp-choice-label">{{ label }}</label>
    <el-select
      :model-value="modelValue"
      :placeholder="placeholder"
      :multiple="multiple"
      :clearable="clearable"
      :filterable="filterable"
      :disabled="disabled"
      style="width: 100%"
      @update:model-value="(v: any) => emit('update:modelValue', v)"
      @change="(v: any) => emit('change', v)"
    >
      <el-option v-for="opt in normalizedOptions" :key="String(opt.value)" :label="String(opt.label)" :value="opt.value" />
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

interface OptionDef {
  label: string;
  value: any;
  disabled?: boolean;
}

const props = withDefaults(
  defineProps<{
    modelValue?: any;
    options?: OptionDef[];
    placeholder?: string;
    multiple?: boolean;
    clearable?: boolean;
    filterable?: boolean;
    disabled?: boolean;
    label?: string;
    field?: string;
  }>(),
  {
    modelValue: "",
    options: () => [
      { label: "选项一", value: "1" },
      { label: "选项二", value: "2" },
    ],
    placeholder: "请选择",
    multiple: false,
    clearable: true,
    filterable: false,
    disabled: false,
    label: "",
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", v: any): void;
  (e: "change", v: any): void;
}>();

const normalizedOptions = computed<OptionDef[]>(() => (Array.isArray(props.options) ? props.options : []));
</script>

<style scoped>
.wp-choice-field {
  width: 100%;
}
.wp-choice-label {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
</style>
