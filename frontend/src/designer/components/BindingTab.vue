<template>
  <div class="wp-bind-tab">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <section class="wp-bind-section">
        <div class="wp-bind-row">
          <span class="wp-bind-label">循环绑定（dataBinding）</span>
          <el-switch v-model="enabled" @change="onToggle" />
        </div>
        <p class="wp-bind-tip">
          开启后，本节点按绑定数组的元素逐个渲染（loopVar 注入作用域）；绑定一个数据源 / 模型 / 变量的数组即可。
        </p>

        <template v-if="enabled">
          <div v-if="loopBinding" class="wp-bind-summary">
            <div class="wp-bind-summary-row">
              <span class="k">摘要</span>
              <span class="v">{{ loopSummary }}</span>
            </div>
            <div class="wp-bind-summary-row">
              <span class="k">表达式</span>
              <code class="v">{{ loopExpression }}</code>
            </div>
            <div class="wp-bind-summary-row">
              <span class="k">设计时预览</span>
              <span class="v">{{ loopPreview.text }}</span>
            </div>
          </div>
          <el-alert
            v-if="loopWarning"
            :title="loopWarning"
            type="warning"
            :closable="false"
            show-icon
            class="wp-bind-warn"
          />
          <BindingEditor
            :model-value="loopBinding"
            :datasources="datasources"
            :models="models"
            :variable-keys="variableKeys"
            :variables="schema.schema?.variables"
            :show-loop-var="true"
            prop-title="循环绑定"
            expected-type="array"
            @update="onUpdate"
          />
        </template>
      </section>

      <section class="wp-bind-section">
        <div class="wp-bind-list-head">
          <span class="wp-bind-label">属性绑定（{{ boundProps.length }}）</span>
          <el-tag size="small" effect="plain">选择属性 → 选择数据 → 自动写入</el-tag>
        </div>
        <p class="wp-bind-tip">以可视化列表管理本节点所有 `__binding__` 属性绑定；可新增、编辑、移除，不会改动其他字面量属性。</p>

        <div v-if="!boundProps.length" class="wp-bind-empty">该节点还没有属性绑定。</div>

        <div v-for="row in boundProps" :key="row.key" class="wp-bind-item">
          <div class="wp-bind-item-head">
            <span class="wp-bind-item-label">{{ row.label }}</span>
            <code class="wp-bind-item-expr" :title="row.expression">{{ row.expression }}</code>
            <el-button size="small" text @click="toggleEdit(row.key)">
              {{ editingKey === row.key ? "收起" : "编辑" }}
            </el-button>
            <el-button size="small" text type="primary" @click="openPicker(row.key)">选择数据</el-button>
            <el-popconfirm
              :title="`移除「${row.label}」的绑定并恢复字面量？`"
              confirm-button-text="移除"
              cancel-button-text="取消"
              width="230"
              @confirm="removeBinding(row.key)"
            >
              <template #reference>
                <el-button size="small" text type="danger">移除</el-button>
              </template>
            </el-popconfirm>
          </div>
          <div class="wp-bind-item-summary">
            {{ row.summary }}
            <span v-if="row.preview" class="wp-bind-item-preview">· {{ row.preview }}</span>
          </div>
          <BindingEditor
            v-if="editingKey === row.key"
            :model-value="row.binding"
            :datasources="datasources"
            :models="models"
            :variable-keys="variableKeys"
            :variables="schema.schema?.variables"
            :prop-title="row.label"
            :expected-type="row.expectedType"
            @update="setBound(row.key, $event)"
          />
        </div>

        <div class="wp-bind-add">
          <el-select
            v-model="pendingKey"
            size="small"
            placeholder="选择要绑定的属性"
            filterable
            clearable
            class="wp-bind-add-select"
          >
            <el-option v-for="p in availableProps" :key="p.key" :label="p.label" :value="p.key" />
          </el-select>
          <el-button size="small" type="primary" plain :disabled="!pendingKey" @click="openPickerForAdd">
            选择数据并绑定
          </el-button>
          <span v-if="!availableProps.length" class="wp-bind-add-hint">没有可新增绑定的属性</span>
        </div>
      </section>

      <BindingPicker
        v-model="pickerOpen"
        title="为属性选择数据"
        :binding="pickerBinding"
        :datasources="datasources"
        :models="models"
        :variables="schema.schema?.variables"
        :expected-type="pickerExpectedType"
        :target-label="pickerLabel"
        @select="onPick"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { isBindingValue } from "@/engine/binding";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { DataBinding, DataModelInfo, DataSourceDef } from "@/types";
import BindingEditor from "./BindingEditor.vue";
import BindingPicker from "./BindingPicker.vue";
import { commit } from "../util";
import {
  bindingExpression,
  bindingPreview,
  bindingSummary,
  literalForSchema,
  type BindingPickPayload,
} from "../utils/bindingSources";

const props = defineProps<{
  nodeId: string;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();
const schema = useSchemaStore();
const components = useComponentStore();
const node = computed(() => schema.node(props.nodeId));
const meta = computed(() => (node.value ? components.meta(node.value.type) : undefined));

const enabled = ref(false);
const variableKeys = computed(() => (schema.schema?.variables ? Object.keys(schema.schema.variables) : []));
const loopBinding = computed<DataBinding | null>(() => node.value?.dataBinding ?? null);
const loopSummary = computed(() =>
  bindingSummary(loopBinding.value, {
    datasources: props.datasources,
    models: props.models,
    variables: schema.schema?.variables,
  })
);
const loopExpression = computed(() => (loopBinding.value ? bindingExpression(loopBinding.value) : ""));
const loopPreview = computed(() =>
  bindingPreview(loopBinding.value, {
    datasources: props.datasources,
    models: props.models,
    variables: schema.schema?.variables,
  })
);
const loopWarning = computed(() => {
  if (!loopBinding.value) return "";
  const preview = loopPreview.value;
  if (!preview.available) return "";
  const value = preview.value;
  if (Array.isArray(value)) return "";
  if (
    value &&
    typeof value === "object" &&
    ["results", "rows", "items", "data", "records"].some((key) => Array.isArray((value as any)[key]))
  ) {
    return "";
  }
  return "当前预览值不是数组，循环可能不会渲染任何子节点；请确认字段或使用 transform 转换。";
});

const editingKey = ref("");
const pendingKey = ref("");
const pickerOpen = ref(false);
const pickerKey = ref("");

const boundProps = computed(() => {
  const propsObj = node.value?.props ?? {};
  const schemaProps = meta.value?.props_schema?.properties ?? {};
  return Object.entries(propsObj)
    .filter(([, value]) => isBindingValue(value))
    .map(([key, value]) => {
      const binding = (value as { __binding__: DataBinding }).__binding__;
      const preview = bindingPreview(binding, {
        datasources: props.datasources,
        models: props.models,
        variables: schema.schema?.variables,
      });
      return {
        key,
        label: schemaProps[key]?.title || key,
        binding,
        expectedType: schemaProps[key]?.type ?? "",
        summary: bindingSummary(binding, {
          datasources: props.datasources,
          models: props.models,
          variables: schema.schema?.variables,
        }),
        expression: bindingExpression(binding),
        preview: preview.available ? preview.text : "",
      };
    });
});

const availableProps = computed(() => {
  const schemaProps = meta.value?.props_schema?.properties ?? {};
  const propsObj = node.value?.props ?? {};
  return Object.entries(schemaProps)
    .filter(([key, ps]) => ps?.["x-bindable"] !== false && !isBindingValue(propsObj[key]))
    .map(([key, ps]) => ({ key, label: ps?.title || key }));
});

const pickerBinding = computed<DataBinding | null>(() => {
  const key = pickerKey.value;
  if (!key) return null;
  const value = node.value?.props?.[key];
  return isBindingValue(value) ? (value as { __binding__: DataBinding }).__binding__ : null;
});
const pickerLabel = computed(() => {
  const key = pickerKey.value;
  if (!key) return "";
  return meta.value?.props_schema?.properties?.[key]?.title || key;
});
const pickerExpectedType = computed(() => {
  const key = pickerKey.value;
  if (!key) return "";
  return meta.value?.props_schema?.properties?.[key]?.type ?? "";
});

watch(
  () => props.nodeId,
  () => {
    enabled.value = !!node.value?.dataBinding;
    editingKey.value = "";
    pendingKey.value = "";
    pickerKey.value = "";
    pickerOpen.value = false;
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
watch(availableProps, (list) => {
  if (pendingKey.value && !list.some((p) => p.key === pendingKey.value)) pendingKey.value = "";
});

function defaultLoopBinding(): DataBinding {
  const firstVar = variableKeys.value[0];
  if (firstVar) return { source: "variable", ref: firstVar, field: "" };
  if (props.datasources.length) return { source: "datasource", ref: `ds_${props.datasources[0].id}`, field: "" };
  if (props.models.length) return { source: "model", ref: `model_${props.models[0].id}`, field: "results" };
  return { source: "variable", ref: "", field: "" };
}

async function onToggle(v: string | number | boolean) {
  const on = !!v;
  if (!on && node.value?.dataBinding) {
    try {
      await ElMessageBox.confirm(
        "关闭循环绑定后，本节点将不再按数据数组重复渲染，已配置的循环变量也会失效。",
        "关闭循环绑定",
        { type: "warning", confirmButtonText: "关闭并移除", cancelButtonText: "取消" }
      );
    } catch {
      enabled.value = true;
      return;
    }
  }
  commit("循环绑定开关", () => {
    const n = node.value;
    if (!n) return;
    if (on) {
      n.dataBinding = n.dataBinding ?? defaultLoopBinding();
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

function writeProp(key: string, value: any) {
  commit(`绑定属性 ${key}`, () => {
    const n = node.value;
    if (!n) return;
    n.props = { ...(n.props ?? {}), [key]: value };
  });
}

function setBound(key: string, binding: DataBinding) {
  writeProp(key, { __binding__: binding });
}

function removeBinding(key: string) {
  const ps = meta.value?.props_schema?.properties?.[key];
  writeProp(key, literalForSchema(ps));
  const label = ps?.title || key;
  if (editingKey.value === key) editingKey.value = "";
  ElMessage.success(`已移除「${label}」的绑定`);
}

function toggleEdit(key: string) {
  editingKey.value = editingKey.value === key ? "" : key;
}

function openPicker(key: string) {
  pickerKey.value = key;
  pickerOpen.value = true;
}

function openPickerForAdd() {
  if (!pendingKey.value) return;
  openPicker(pendingKey.value);
}

function onPick(payload: BindingPickPayload) {
  const key = pickerKey.value;
  if (!key) return;
  if (payload.mode === "expression") {
    writeProp(key, `{{${payload.expression}}}`);
    ElMessage.success(`已写入「${pickerLabel.value}」的模板表达式`);
  } else {
    setBound(key, payload.binding);
    editingKey.value = key;
    ElMessage.success(`已绑定「${pickerLabel.value}」`);
  }
  pendingKey.value = "";
}
</script>

<style scoped>
.wp-bind-tab {
  font-size: 13px;
  padding: 4px 2px;
}
.wp-bind-section {
  margin-bottom: 14px;
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
  line-height: 1.6;
}
.wp-bind-summary {
  padding: 7px 9px;
  margin-bottom: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  border-left: 3px solid var(--el-color-primary);
}
.wp-bind-summary-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  line-height: 1.7;
}
.wp-bind-summary-row .k {
  width: 64px;
  flex: none;
  color: var(--el-text-color-secondary);
}
.wp-bind-summary-row .v {
  min-width: 0;
  overflow-wrap: anywhere;
  font-family: ui-monospace, Consolas, monospace;
}
.wp-bind-warn {
  margin-bottom: 8px;
}
.wp-bind-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.wp-bind-empty {
  padding: 10px;
  margin-bottom: 8px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
}
.wp-bind-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 7px 8px;
  margin-bottom: 8px;
  background: var(--el-fill-color-blank);
}
.wp-bind-item-head {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-bind-item-label {
  font-weight: 600;
}
.wp-bind-item-expr {
  flex: 1;
  min-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.wp-bind-item-summary {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  margin: 2px 0 4px;
  overflow-wrap: anywhere;
}
.wp-bind-item-preview {
  color: var(--el-text-color-placeholder);
}
.wp-bind-add {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-bind-add-select {
  flex: 1;
  min-width: 150px;
}
.wp-bind-add-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
</style>
