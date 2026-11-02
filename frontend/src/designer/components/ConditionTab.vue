<template>
  <div class="wp-cond">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <div v-if="!hasCond" class="wp-cond-empty">
        <p>设置条件表达式后，节点仅当表达式为真时渲染（运行态）。</p>
        <el-button size="small" type="primary" @click="enable">启用条件</el-button>
      </div>
      <template v-else>
        <el-form label-position="top" size="small">
          <el-form-item label="条件表达式 condition.expr">
            <el-input v-model="expr" type="textarea" :rows="3" class="wp-mono" placeholder="如 scope.user?.role === 'admin'" />
          </el-form-item>
          <el-form-item>
            <div class="wp-cond-actions">
              <el-button size="small" @click="apply">应用</el-button>
              <el-button size="small" @click="check">校验表达式</el-button>
              <el-button size="small" type="danger" plain @click="remove">移除条件</el-button>
            </div>
            <div v-if="checkResult !== null" class="wp-cond-result" :class="{ ok: checkResult.ok }">
              {{ checkResult.text }}
            </div>
          </el-form-item>
        </el-form>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { checkExpression } from "@/engine/expr";
import { useSchemaStore } from "@/store/schema";
import { commit } from "../util";

const props = defineProps<{ nodeId: string }>();
const schema = useSchemaStore();
const node = computed(() => schema.node(props.nodeId));
const hasCond = computed(() => !!node.value?.condition?.expr);

const expr = ref("");
const checkResult = ref<{ ok: boolean; text: string } | null>(null);

function sync() {
  expr.value = node.value?.condition?.expr ?? "";
  checkResult.value = null;
}
watch(
  () => props.nodeId,
  () => sync(),
  { immediate: true }
);
watch(
  () => node.value?.condition,
  (c) => {
    const next = c?.expr ?? "";
    if (next !== expr.value) expr.value = next;
  },
  { deep: true }
);

function enable() {
  commit("启用条件", () => {
    const n = node.value;
    if (!n) return;
    n.condition = { expr: "true" };
  });
  sync();
}

function apply() {
  const v = expr.value.trim();
  if (!v) {
    remove();
    return;
  }
  commit("条件表达式", () => {
    const n = node.value;
    if (!n) return;
    n.condition = { expr: v };
  });
  check();
}

function check() {
  const v = expr.value.trim();
  if (!v) {
    checkResult.value = { ok: false, text: "表达式为空" };
    return;
  }
  const r = checkExpression(v);
  checkResult.value = r.ok
    ? { ok: true, text: "表达式有效" }
    : { ok: false, text: `表达式无效：${r.error ?? "解析失败"}` };
}

function remove() {
  commit("移除条件", () => {
    const n = node.value;
    if (!n) return;
    delete n.condition;
  });
  sync();
}
</script>

<style scoped>
.wp-cond {
  font-size: 13px;
  padding: 4px 2px;
}
.wp-cond-empty p {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-bottom: 8px;
}
.wp-cond-actions {
  display: flex;
  gap: 8px;
}
.wp-cond-result {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-color-danger);
}
.wp-cond-result.ok {
  color: var(--el-color-success);
}
.wp-mono :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
</style>
