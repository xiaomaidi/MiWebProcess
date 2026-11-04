<template>
  <div class="wp-cond">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <div v-if="!hasCond" class="wp-cond-empty">
        <p>设置条件表达式后，节点仅当表达式为真时渲染（运行态）。</p>
        <el-button size="small" type="primary" @click="enable">启用条件</el-button>
        <div class="wp-cond-quick">
          <span>快速启用：</span>
          <el-button link type="primary" size="small" @click="enableWith('true')">始终显示</el-button>
          <el-button link type="primary" size="small" @click="enableWith('false')">始终隐藏</el-button>
          <el-button link type="primary" size="small" @click="enableWith('len(list) > 0')">列表非空时显示</el-button>
        </div>
      </div>

      <template v-else>
        <div class="wp-cond-summary">
          <div class="wp-cond-summary-label">条件摘要</div>
          <div class="wp-cond-summary-text">当「{{ summary }}」时，组件才会渲染；否则隐藏。</div>
        </div>

        <el-form label-position="top" size="small">
          <el-form-item label="条件表达式 condition.expr">
            <el-input
              v-model="draft"
              type="textarea"
              :rows="3"
              class="wp-mono"
              placeholder="如 user.role === 'admin'、state.status === 'active'"
            />
            <div class="wp-cond-snippets">
              <span>插入示例：</span>
              <el-button
                v-for="s in snippets"
                :key="s.expr"
                link
                type="primary"
                size="small"
                @click="appendSnippet(s.expr)"
              >
                {{ s.label }}
              </el-button>
            </div>
            <div class="wp-cond-status">
              <el-tag v-if="!draft.trim()" size="small" type="info">未填写</el-tag>
              <el-tag v-else-if="validation.ok" size="small" type="success">语法有效</el-tag>
              <el-tag v-else size="small" type="danger">语法错误</el-tag>
              <el-tag v-if="dirty" size="small" type="warning" effect="plain">有未应用修改</el-tag>
              <el-tag v-else-if="hasCond" size="small" effect="plain">已应用</el-tag>
              <span v-if="dirty" class="wp-cond-dirty-hint">点击「应用」写入页面 schema</span>
            </div>
            <el-alert
              v-if="draft.trim() && !validation.ok"
              :title="`表达式无法解析：${validation.error || '语法错误'}`"
              type="error"
              :closable="false"
              show-icon
              class="wp-cond-alert"
            />
          </el-form-item>
          <el-form-item>
            <div class="wp-cond-actions">
              <el-button size="small" type="primary" :disabled="!canApply" @click="apply">应用</el-button>
              <el-button
                v-if="draft.trim() && !validation.ok"
                size="small"
                plain
                @click="forceSave"
              >
                仍然保存
              </el-button>
              <el-button size="small" :disabled="!dirty" @click="resetDraft">撤销修改</el-button>
              <el-popconfirm
                title="移除条件后，该节点将不再受条件控制，是否继续？"
                confirm-button-text="移除"
                cancel-button-text="取消"
                width="240"
                @confirm="remove"
              >
                <template #reference>
                  <el-button size="small" type="danger" plain>移除条件</el-button>
                </template>
              </el-popconfirm>
            </div>
          </el-form-item>
        </el-form>
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { checkExpression } from "@/engine/expr";
import { useSchemaStore } from "@/store/schema";
import { commit } from "../util";
import { describeCondition } from "../utils/bindingSources";

const props = defineProps<{ nodeId: string }>();
const schema = useSchemaStore();
const node = computed(() => schema.node(props.nodeId));
const hasCond = computed(() => !!node.value?.condition?.expr);

const draft = ref("");
const snippets = [
  { label: "管理员可见", expr: "user.role === 'admin'" },
  { label: "状态为启用", expr: "state.status === 'active'" },
  { label: "列表非空", expr: "len(list) > 0" },
  { label: "表单已填写", expr: "len(form.name) > 0" },
  { label: "路由参数存在", expr: "route.id != null" },
];

const validation = computed(() => {
  const expr = draft.value.trim();
  if (!expr) return { ok: false, error: "表达式为空" };
  return checkExpression(expr);
});
const summary = computed(() => describeCondition(draft.value));
const savedExpr = computed(() => node.value?.condition?.expr ?? "");
const dirty = computed(() => draft.value.trim() !== savedExpr.value.trim());
const canApply = computed(() => dirty.value && !!draft.value.trim() && validation.value.ok);

function sync() {
  draft.value = node.value?.condition?.expr ?? "";
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
    if (next !== draft.value) draft.value = next;
  },
  { deep: true }
);

function enable() {
  enableWith("true");
}

function enableWith(expr: string) {
  commit("启用条件", () => {
    const n = node.value;
    if (!n) return;
    n.condition = { expr };
  });
  sync();
}

function apply() {
  const v = draft.value.trim();
  if (!v) {
    ElMessage.warning("表达式为空，如需取消条件请使用「移除条件」");
    return;
  }
  if (!validation.value.ok) {
    ElMessage.error(`表达式无效：${validation.value.error || "语法错误"}`);
    return;
  }
  commit("条件表达式", () => {
    const n = node.value;
    if (!n) return;
    n.condition = { expr: v };
  });
  sync();
  ElMessage.success("条件已应用");
}

function forceSave() {
  const v = draft.value.trim();
  if (!v) return;
  commit("条件表达式", () => {
    const n = node.value;
    if (!n) return;
    n.condition = { expr: v };
  });
  sync();
  ElMessage.warning("已保存无效表达式；运行时会被判定为不成立");
}

function remove() {
  commit("移除条件", () => {
    const n = node.value;
    if (!n) return;
    delete n.condition;
  });
  sync();
  ElMessage.success("条件已移除");
}

function resetDraft() {
  draft.value = savedExpr.value;
}

function appendSnippet(expr: string) {
  const current = draft.value.trim();
  draft.value = current ? `${current} && ${expr}` : expr;
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
  line-height: 1.6;
}
.wp-cond-quick {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-cond-summary {
  padding: 7px 9px;
  margin-bottom: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-primary);
}
.wp-cond-summary-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}
.wp-cond-summary-text {
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}
.wp-cond-snippets {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  margin-top: 2px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.wp-cond-status {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.wp-cond-dirty-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-cond-alert {
  margin-top: 6px;
}
.wp-cond-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-mono :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
</style>
