<template>
  <div class="wp-props">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <el-empty
      v-else-if="!meta || !propKeys.length"
      description="该组件无可编辑属性，可在「其他属性」中直接写 JSON"
      :image-size="50"
    />
    <template v-else>
      <div v-for="group in groups" :key="group.name" class="wp-prop-group">
        <div class="wp-prop-group-title">{{ group.name }}</div>
        <div v-for="key in group.keys" :key="key" class="wp-prop">
          <template v-if="isBound(key)">
            <div class="wp-prop-head">
              <span class="wp-prop-label">{{ labelOf(key) }}</span>
              <el-tag size="small" type="warning">绑定</el-tag>
              <span class="wp-prop-bind-summary" :title="bindingSummaryOf(key)">{{ bindingSummaryOf(key) }}</span>
              <el-button size="small" text type="primary" @click="openPicker(key)">选择数据</el-button>
              <el-popconfirm
                :title="`清除「${labelOf(key)}」的绑定并恢复字面量？`"
                confirm-button-text="清除"
                cancel-button-text="取消"
                width="230"
                @confirm="toLiteral(key)"
              >
                <template #reference>
                  <el-button size="small" text type="danger">清除绑定</el-button>
                </template>
              </el-popconfirm>
            </div>
            <div class="wp-prop-binding-line">
              <code class="wp-prop-expression">{{ bindingExpressionOf(key) }}</code>
              <el-tag v-if="expectedTypeOf(key)" size="small" effect="plain">期望 {{ expectedTypeOf(key) }}</el-tag>
              <el-tag v-if="bindingLoopVarOf(key)" size="small" type="success" effect="plain">
                循环变量 {{ bindingLoopVarOf(key) }}
              </el-tag>
            </div>
            <div class="wp-prop-preview">
              <span class="k">设计时预览</span>
              <span class="v">{{ previewOf(key).text }}</span>
              <span v-if="previewOf(key).hint" class="hint">{{ previewOf(key).hint }}</span>
            </div>
            <el-alert
              v-if="compatOf(key)"
              :title="compatOf(key)"
              type="warning"
              :closable="false"
              show-icon
              class="wp-prop-warn"
            />
            <BindingEditor
              :model-value="boundValue(key)"
              :datasources="datasources"
              :models="models"
              :variable-keys="variableKeys"
              :variables="schema.schema?.variables"
              :prop-title="labelOf(key)"
              :expected-type="expectedTypeOf(key)"
              @update="setBound(key, $event)"
            />
          </template>
          <template v-else>
            <div class="wp-prop-head">
              <span class="wp-prop-label">{{ labelOf(key) }}</span>
              <el-tag v-if="typeLabelOf(key)" size="small" effect="plain" class="wp-prop-type">{{ typeLabelOf(key) }}</el-tag>
              <el-button v-if="bindableOf(key)" size="small" text type="primary" @click="openPicker(key)">绑定数据</el-button>
            </div>
            <PropControl
              :model-value="valueOf(key)"
              :kind="kindOf(key)"
              :schema="properties[key]"
              :options="optionsOf(key)"
              :model-options="modelOptions"
              @commit="setProp(key, $event)"
            />
            <div v-if="properties[key]?.description" class="wp-prop-desc">{{ properties[key].description }}</div>
          </template>
        </div>
      </div>

      <div v-if="isTable" class="wp-prop-group wp-table-tools">
        <div class="wp-prop-group-title">数据模型表格</div>
        <div class="wp-table-tools-hint">
          选择数据模型后，可一键生成列、服务端分页和操作列。
        </div>
        <div class="wp-table-tools-row">
          <el-button size="small" type="primary" plain :disabled="!tableModelId" @click="generateColumns">
            从数据模型生成列
          </el-button>
          <el-button size="small" :disabled="!tableModelId" @click="enableRemote">启用服务端分页</el-button>
        </div>
        <div class="wp-table-tools-row">
          <el-button size="small" @click="addActionColumn">添加操作列</el-button>
          <el-button size="small" @click="editColumnsJson = !editColumnsJson">
            {{ editColumnsJson ? "收起列 JSON" : "列 JSON（高级）" }}
          </el-button>
        </div>
        <PropControl
          v-if="editColumnsJson"
          :model-value="node?.props?.columns"
          kind="json"
          @commit="setProp('columns', $event)"
        />
      </div>

      <div v-if="extraKeys.length" class="wp-prop-group">
        <div class="wp-prop-group-title">其他属性（JSON）</div>
        <PropControl :model-value="extraValue" kind="json" @commit="setExtra" />
      </div>

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
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { isBindingValue } from "@/engine/binding";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import { useHistoryStore } from "@/store/history";
import type { ComponentPropSchema, DataBinding, DataModelInfo, DataSourceDef } from "@/types";
import BindingEditor from "./BindingEditor.vue";
import BindingPicker from "./BindingPicker.vue";
import PropControl from "./PropControl.vue";
import {
  bindingExpression,
  bindingPreview,
  bindingSummary,
  compatibilityWarning,
  findModel,
  kindOfModelField,
  literalForSchema,
  valueKind,
  type BindingPickPayload,
  type BindingPreview,
  type ValueKind,
} from "../utils/bindingSources";

const props = defineProps<{
  nodeId: string;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();

const schema = useSchemaStore();
const components = useComponentStore();
const history = useHistoryStore();

const node = computed(() => schema.node(props.nodeId));
const meta = computed(() => (node.value ? components.meta(node.value.type) : undefined));
const variableKeys = computed(() => Object.keys(schema.schema?.variables ?? {}));
const modelOptions = computed(() => props.models.map((m) => ({ label: `${m.name} (#${m.id})`, value: m.id })));

type Ps = ComponentPropSchema;
const properties = computed<Record<string, Ps>>(() => (meta.value?.props_schema?.properties ?? {}) as Record<string, Ps>);
const propKeys = computed(() => Object.keys(properties.value));

const groups = computed<{ name: string; keys: string[] }[]>(() => {
  const map = new Map<string, string[]>();
  for (const key of propKeys.value) {
    const name = properties.value[key]?.["x-group"] || "常规";
    const list = map.get(name) || [];
    list.push(key);
    map.set(name, list);
  }
  const order = ["常规", "内容", "外观", "状态", "布局", "数据", "条件", "交互", "安全", "高级"];
  return [...map.entries()]
    .sort((a, b) => {
      const ia = order.indexOf(a[0]);
      const ib = order.indexOf(b[0]);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    })
    .map(([name, keys]) => ({ name, keys }));
});

const isTable = computed(() => node.value?.type === "ElTable");
const tableModelId = computed(() => Number(node.value?.props?.dataModelId) || 0);
const currentTableModel = computed(() => props.models.find((m) => m.id === tableModelId.value));
const editColumnsJson = ref(false);

const extraKeys = computed(() => Object.keys(node.value?.props ?? {}).filter((k) => !properties.value[k]));
const extraValue = computed(() => {
  const out: Record<string, any> = {};
  for (const k of extraKeys.value) out[k] = node.value?.props?.[k];
  return Object.keys(out).length ? out : undefined;
});

const pickerOpen = ref(false);
const pickerKey = ref("");

function valueOf(key: string): any {
  const v = node.value?.props?.[key];
  return v !== undefined ? v : properties.value[key]?.default;
}
function isBound(key: string): boolean {
  return isBindingValue(node.value?.props?.[key]);
}
function boundValue(key: string): DataBinding {
  return (node.value?.props?.[key] as { __binding__: DataBinding }).__binding__;
}
function labelOf(key: string): string {
  return properties.value[key]?.title || key;
}
function bindableOf(key: string): boolean {
  return properties.value[key]?.["x-bindable"] !== false;
}
function expectedTypeOf(key: string): string {
  return properties.value[key]?.type ?? "";
}

const TYPE_LABELS: Record<string, string> = {
  string: "文本",
  number: "数字",
  integer: "整数",
  boolean: "布尔",
  array: "数组",
  object: "对象",
};
function typeLabelOf(key: string): string {
  const type = expectedTypeOf(key);
  if (!type) return "";
  return `${TYPE_LABELS[type] || type} ${type}`;
}

function bindingSummaryOf(key: string): string {
  return bindingSummary(isBound(key) ? boundValue(key) : null, {
    datasources: props.datasources,
    models: props.models,
    variables: schema.schema?.variables,
  });
}
function bindingExpressionOf(key: string): string {
  return isBound(key) ? bindingExpression(boundValue(key)) : "";
}
function bindingLoopVarOf(key: string): string {
  return isBound(key) ? boundValue(key).loopVar || "" : "";
}
function previewOf(key: string): BindingPreview {
  if (!isBound(key)) return { available: false, text: "未绑定" };
  return bindingPreview(boundValue(key), {
    datasources: props.datasources,
    models: props.models,
    variables: schema.schema?.variables,
  });
}

function actualKindOf(key: string): ValueKind | "any" {
  if (!isBound(key)) return "any";
  const preview = previewOf(key);
  if (preview.available) return valueKind(preview.value);
  const binding = boundValue(key);
  if (binding.source === "model" && binding.field) {
    const model = findModel(props.models, binding.ref);
    const name = binding.field.split(".").pop()?.replace(/\[.*\]/g, "") || "";
    const field = (model?.fields ?? []).find((f) => f.name === name);
    if (field) return kindOfModelField(field.type);
  }
  return "any";
}
function compatOf(key: string): string {
  if (!isBound(key)) return "";
  return compatibilityWarning(expectedTypeOf(key), actualKindOf(key));
}

function kindOf(key: string): any {
  const ps = properties.value[key] || ({ type: "string" } as Ps);
  const xui = ps["x-ui"];
  if (xui === "modelPicker") return "model";
  if (xui === "tableColumnsEditor") return "tableColumns";
  if (xui === "echartsOption") return "json";
  if (xui === "iconPicker") return "icon";
  if (xui === "imagePicker") return "image";
  if (xui === "expression") return "expression";
  if (xui === "code") return "code";
  if (xui === "date") return "date";
  if (xui === "slider") return "slider";
  if (xui === "textarea") return "textarea";
  if (xui === "color") return "color";
  if (xui === "json" || ps.type === "object" || ps.type === "array") return "json";
  if (ps.type === "boolean") return "switch";
  if (ps.enum) return "select";
  if (ps.type === "number" || ps.type === "integer") return "number";
  return "text";
}

function optionsOf(key: string): { label: string; value: any }[] {
  const ps = properties.value[key];
  return (ps.enum ?? []).map((v) => ({ label: String(v === "" ? "（默认）" : v), value: v }));
}

function setProp(key: string, v: any) {
  history.run(`属性 ${key}`, () => schema.setNodeProp(props.nodeId, key, v));
}

function setBound(key: string, b: DataBinding) {
  history.run(`绑定属性 ${key}`, () => schema.setNodeProp(props.nodeId, key, { __binding__: b }));
}

function toLiteral(key: string) {
  const ps = properties.value[key];
  const fallback = literalForSchema(ps);
  history.run(`属性 ${key}`, () => schema.setNodeProp(props.nodeId, key, fallback));
  ElMessage.success(`已清除「${labelOf(key)}」的绑定`);
}

const pickerBinding = computed<DataBinding | null>(() => {
  const key = pickerKey.value;
  return key && isBound(key) ? boundValue(key) : null;
});
const pickerLabel = computed(() => (pickerKey.value ? labelOf(pickerKey.value) : ""));
const pickerExpectedType = computed(() => (pickerKey.value ? expectedTypeOf(pickerKey.value) : ""));

function openPicker(key: string) {
  pickerKey.value = key;
  pickerOpen.value = true;
}

function onPick(payload: BindingPickPayload) {
  const key = pickerKey.value;
  if (!key) return;
  if (payload.mode === "expression") {
    setProp(key, `{{${payload.expression}}}`);
    ElMessage.success(`已写入「${labelOf(key)}」的模板表达式`);
  } else {
    setBound(key, payload.binding);
    ElMessage.success(`已绑定「${labelOf(key)}」`);
  }
}

function generateColumns() {
  const model = currentTableModel.value;
  if (!model) return;
  const columns = (model.fields || []).map((f) => ({
    key: f.name,
    prop: f.name,
    label: f.label || f.name,
    cellType: f.type === "boolean" ? "tag" : "text",
    ...(f.type === "boolean" ? { valueMap: { true: "是", false: "否" }, tagType: "success" } : {}),
  }));
  history.run("从数据模型生成列", () => {
    schema.setNodeProp(props.nodeId, "dataModelId", model.id);
    schema.setNodeProp(props.nodeId, "columns", columns);
    schema.setNodeProp(props.nodeId, "autoColumns", false);
  });
}

function enableRemote() {
  history.run("启用服务端分页", () => {
    schema.setNodeProp(props.nodeId, "remote", true);
    schema.setNodeProp(props.nodeId, "showPagination", true);
    schema.setNodeProp(props.nodeId, "pageSize", 10);
  });
}

function addActionColumn() {
  const current = Array.isArray(node.value?.props?.columns) ? [...node.value!.props.columns] : [];
  const exists = current.some((c: any) => c.cellType === "actions");
  if (exists) {
    ElMessage.info("已存在操作列");
    return;
  }
  current.push({
    key: "actions",
    label: "操作",
    cellType: "actions",
    width: 150,
    rowActions: [
      { label: "编辑", kind: "edit", type: "primary" },
      { label: "删除", kind: "delete", type: "danger", confirm: "确认删除这条记录？" },
    ],
  });
  history.run("添加操作列", () => schema.setNodeProp(props.nodeId, "columns", current));
}

function setExtra(v: any) {
  history.run("其他属性", () => {
    const n = schema.node(props.nodeId);
    if (!n) return;
    const next = { ...(n.props ?? {}) };
    for (const k of extraKeys.value) delete next[k];
    if (v && typeof v === "object") Object.assign(next, v);
    n.props = next;
  });
}
</script>

<style scoped>
.wp-props {
  font-size: 13px;
  padding: 4px 2px;
}
.wp-prop-group {
  margin-bottom: 12px;
}
.wp-prop-group-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  border-bottom: 1px solid var(--el-border-color-lighter);
  padding-bottom: 4px;
  margin-bottom: 8px;
}
.wp-prop {
  margin-bottom: 10px;
}
.wp-prop-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.wp-prop-label {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.wp-prop-type {
  flex: none;
}
.wp-prop-bind-summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.wp-prop-binding-line {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.wp-prop-expression {
  max-width: 100%;
  overflow-wrap: anywhere;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  background: var(--el-fill-color-light);
}
.wp-prop-preview {
  display: flex;
  align-items: baseline;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 5px;
  font-size: 11px;
}
.wp-prop-preview .k {
  color: var(--el-text-color-secondary);
  flex: none;
}
.wp-prop-preview .v {
  color: var(--el-text-color-regular);
  overflow-wrap: anywhere;
}
.wp-prop-preview .hint {
  color: var(--el-text-color-placeholder);
}
.wp-prop-warn {
  margin-bottom: 6px;
}
.wp-prop-desc {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}
.wp-table-tools-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  margin-bottom: 6px;
}
.wp-table-tools-row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
</style>
