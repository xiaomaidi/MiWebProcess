<template>
  <div class="wp-steps">
    <template v-for="(s, i) in modelValue" :key="s.id || i">
      <StepItem
        :step="s"
        :index="i"
        :datasources="datasources"
        :models="models"
        @update="onUpdate(i, $event)"
        @remove="onRemove(i)"
        @move="onMove(i, $event)"
      />
    </template>
    <el-button size="small" @click="onAdd">+ 添加步骤</el-button>
  </div>
</template>

<script setup lang="ts">
import type { ActionStep, DataModelInfo, DataSourceDef } from "@/types";
import StepItem from "./StepItem.vue";

const props = defineProps<{
  modelValue: ActionStep[];
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();
const emit = defineEmits<{ (e: "update", steps: ActionStep[]): void }>();

function copy(steps: ActionStep[]): ActionStep[] {
  return steps.map((s) => ({ ...s }));
}

function onUpdate(i: number, step: ActionStep) {
  const next = copy(props.modelValue);
  next[i] = step;
  emit("update", next);
}

function onRemove(i: number) {
  const next = copy(props.modelValue);
  next.splice(i, 1);
  emit("update", next);
}

function onMove(i: number, dir: -1 | 1) {
  const j = i + dir;
  if (j < 0 || j >= props.modelValue.length) return;
  const next = copy(props.modelValue);
  const [s] = next.splice(i, 1);
  next.splice(j, 0, s);
  emit("update", next);
}

function onAdd() {
  const next = copy(props.modelValue);
  next.push({ id: crypto.randomUUID(), kind: "message", params: { text: "", type: "info" } });
  emit("update", next);
}
</script>
