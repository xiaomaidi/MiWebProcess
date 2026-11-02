<template>
  <div class="wp-choice-group">
    <label v-if="label" class="wp-choice-label">{{ label }}</label>
    <el-radio-group
      v-if="kind !== 'checkbox'"
      :model-value="modelValue"
      :disabled="disabled"
      @update:model-value="(v: any) => emit('update:modelValue', v)"
      @change="(v: any) => emit('change', v)"
    >
      <el-radio v-for="opt in normalizedOptions" :key="String(opt.value)" :value="opt.value" :disabled="opt.disabled">
        {{ opt.label }}
      </el-radio>
    </el-radio-group>
    <el-checkbox-group
      v-else
      :model-value="modelValue"
      :disabled="disabled"
      :min="min || undefined"
      :max="max || undefined"
      @update:model-value="(v: any) => emit('update:modelValue', v)"
      @change="(v: any) => emit('change', v)"
    >
      <el-checkbox v-for="opt in normalizedOptions" :key="String(opt.value)" :value="opt.value" :disabled="opt.disabled">
        {{ opt.label }}
      </el-checkbox>
    </el-checkbox-group>
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
    label?: string;
    disabled?: boolean;
    kind?: "radio" | "checkbox";
    min?: number;
    max?: number;
    field?: string;
  }>(),
  {
    modelValue: "",
    options: () => [
      { label: "选项一", value: "1" },
      { label: "选项二", value: "2" },
    ],
    label: "",
    disabled: false,
    kind: "radio",
    min: 0,
    max: 0,
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", v: any): void;
  (e: "change", v: any): void;
}>();

const normalizedOptions = computed<OptionDef[]>(() => (Array.isArray(props.options) ? props.options : []));
</script>

<style scoped>
.wp-choice-group {
  width: 100%;
}
.wp-choice-label {
  display: block;
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 4px;
}
</style>
