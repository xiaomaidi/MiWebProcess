<template>
  <div class="wp-bind-tab">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <div class="wp-bind-row">
        <span class="wp-bind-label">循环绑定（dataBinding）</span>
        <el-switch v-model="enabled" @change="onToggle" />
      </div>
      <p class="wp-bind-tip">
        开启后，本节点按绑定数组的元素逐个渲染（loopVar 注入作用域）；绑定一个数据源/模型/变量的数组即可。
      </p>
      <BindingEditor
        v-if="enabled"
        :model-value="node.dataBinding"
        :datasources="datasources"
        :models="models"
        :variable-keys="variableKeys"
        :show-loop-var="true"
        @update="onUpdate"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useSchemaStore } from "@/store/schema";
import type { DataBinding, DataModelInfo, DataSourceDef } from "@/types";
import BindingEditor from "./BindingEditor.vue";
import { commit } from "../util";

const props = defineProps<{
  nodeId: string;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();
const schema = useSchemaStore();
const node = computed(() => schema.node(props.nodeId));

const enabled = ref(false);
const variableKeys = computed(() => (schema.schema?.variables ? Object.keys(schema.schema.variables) : []));

watch(
  () => props.nodeId,
  () => {
    enabled.value = !!node.value?.dataBinding;
  },
  { immediate: true }
);
watch(
  () => node.value?.dataBinding,
  (v) => {
    enabled.value = !!v;
  },
  { deep: true }
);

function onToggle(v: string | number | boolean) {
  const on = !!v;
  commit("循环绑定开关", () => {
    const n = node.value;
    if (!n) return;
    if (on) {
      n.dataBinding = n.dataBinding ?? { source: "variable", ref: "" };
    } else {
      n.dataBinding = null;
    }
  });
}

function onUpdate(binding: DataBinding) {
  commit("循环绑定", () => {
    const n = node.value;
    if (n) n.dataBinding = binding;
  });
}
</script>

<style scoped>
.wp-bind-tab {
  font-size: 13px;
  padding: 4px 2px;
}
.wp-bind-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.wp-bind-label {
  font-weight: 600;
}
.wp-bind-tip {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin: 0 0 8px;
}
</style>
