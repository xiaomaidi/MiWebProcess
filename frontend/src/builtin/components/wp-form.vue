<template>
  <form
    class="wp-form"
    :class="{ 'wp-form-inline': props.inline }"
    @submit.prevent="onSubmit"
    @reset="onReset"
  >
    <slot />
  </form>
</template>

<script setup lang="ts">
import { inject, provide, reactive, watch } from "vue";
import type { RuntimeScope } from "@/types";
import type { WpFormContext } from "./form-context";
import { wpFormContextKey } from "./form-context";

const scope = inject<RuntimeScope | null>("wp.scope", null);

const props = withDefaults(
  defineProps<{
    labelWidth?: number;
    labelPosition?: "right" | "top";
    inline?: boolean;
    disabled?: boolean;
    /** 节点 id：由 NodeRenderer 注入，供 form 绑定（ref: form_<nodeId>）读取 */
    wpNodeId?: string;
  }>(),
  {
    labelWidth: 100,
    labelPosition: "right",
    inline: false,
    disabled: false,
    wpNodeId: "",
  }
);

const emit = defineEmits<{
  (e: "submit", payload: { values: Record<string, any> }): void;
  (e: "reset"): void;
}>();

const values = reactive<Record<string, any>>({});
const initial = reactive<Record<string, any>>({});

function setField(field: string, value: any): void {
  values[field] = value;
}

function register(field: string, value: any): void {
  if (!(field in initial)) {
    initial[field] = value;
    if (!(field in values)) values[field] = value;
  }
}

function reset(): void {
  for (const key of Object.keys(values)) delete values[key];
  for (const key of Object.keys(initial)) values[key] = initial[key];
}

const context: WpFormContext = {
  values,
  setField,
  register,
  reset,
  get disabled() {
    return props.disabled;
  },
  get inline() {
    return props.inline;
  },
  get labelWidth() {
    return props.labelWidth;
  },
  get labelPosition() {
    return props.labelPosition;
  },
};

provide(wpFormContextKey, context);

/** 表单值实时写入 scope.formValues[wpNodeId]，供 source:"form" 绑定解析。 */
function syncToScope(): void {
  if (scope && props.wpNodeId) scope.formValues[props.wpNodeId] = { ...values };
}

watch(
  () => ({ ...values }),
  () => syncToScope(),
  { immediate: true }
);

function onSubmit(): void {
  syncToScope();
  emit("submit", { values: { ...values } });
}

function onReset(): void {
  reset();
  emit("reset");
}
</script>

<style scoped>
.wp-form {
  display: block;
}
.wp-form-inline .wp-field {
  display: inline-flex;
  margin-right: 12px;
}
</style>
