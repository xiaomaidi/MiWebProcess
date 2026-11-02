<template>
  <div class="wp-events">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <div class="wp-events-row">
        <label>事件</label>
        <el-select
          v-model="activeEvent"
          size="small"
          placeholder="选择事件"
          clearable
          @change="setActive"
        >
          <el-option v-for="n in eventNames" :key="n" :label="n" :value="n" />
        </el-select>
        <el-button v-if="activeEvent" size="small" type="danger" plain @click="clearEvent">
          清除
        </el-button>
      </div>
      <p v-if="!activeEvent" class="wp-events-hint">选择事件后添加动作步骤（支持嵌套条件）。</p>
      <StepList v-else :model-value="steps" :datasources="datasources" :models="models" @update="setSteps" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { ActionStep, DataModelInfo, DataSourceDef } from "@/types";
import { commit } from "../util";
import StepList from "./StepList.vue";

const props = defineProps<{
  nodeId: string;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();

const schema = useSchemaStore();
const components = useComponentStore();
const node = computed(() => schema.node(props.nodeId));
const meta = computed(() => (node.value ? components.meta(node.value.type) : undefined));

const activeEvent = ref<string>("");
const eventNames = computed<string[]>(() => {
  const fromMeta: string[] = meta.value?.events ?? [];
  const used = Object.keys(node.value?.events ?? {});
  const base = fromMeta.length ? fromMeta : ["click", "dblclick", "change", "input"];
  return [...new Set([...base, ...used])];
});
const steps = computed<ActionStep[]>(() => node.value?.events?.[activeEvent.value] ?? []);

function syncActive() {
  if (!activeEvent.value && eventNames.value.length) {
    activeEvent.value = eventNames.value[0];
  }
}
watch(eventNames, syncActive, { immediate: true });
watch(
  () => props.nodeId,
  () => {
    activeEvent.value = "";
    syncActive();
  }
);

function setActive() {
  // 仅切换显示；steps 由 node.events 驱动
}

function setSteps(list: ActionStep[]) {
  const name = activeEvent.value;
  if (!name) return;
  commit(`事件 ${name}`, () => {
    const n = node.value;
    if (!n) return;
    n.events = { ...(n.events ?? {}) };
    if (list.length) n.events[name] = list;
    else delete n.events[name];
  });
}

function clearEvent() {
  const name = activeEvent.value;
  if (!name) return;
  commit(`清除事件 ${name}`, () => {
    const n = node.value;
    if (!n) return;
    n.events = { ...(n.events ?? {}) };
    delete n.events[name];
  });
}
</script>

<style scoped>
.wp-events {
  font-size: 13px;
  padding: 4px 2px;
}
.wp-events-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.wp-events-row label {
  width: 32px;
  flex: none;
  color: var(--el-text-color-regular);
  font-size: 12px;
}
.wp-events-row :deep(.el-select) {
  flex: 1;
}
.wp-events-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
