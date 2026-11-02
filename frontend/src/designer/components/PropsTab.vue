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
              <el-button size="small" text @click="toLiteral(key)">字面量</el-button>
            </div>
            <BindingEditor
              :model-value="boundValue(key)"
              :datasources="datasources"
              :models="models"
              :variable-keys="variableKeys"
              @update="setBound(key, $event)"
            />
          </template>
          <template v-else>
            <div class="wp-prop-head">
              <span class="wp-prop-label">{{ labelOf(key) }}</span>
              <el-button v-if="bindableOf(key)" size="small" text @click="toBinding(key)">绑定</el-button>
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
import PropControl from "./PropControl.vue";

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

function toBinding(key: string) {
  const b: DataBinding = { source: "variable", ref: variableKeys.value[0] ?? "" };
  history.run(`绑定属性 ${key}`, () => schema.setNodeProp(props.nodeId, key, { __binding__: b }));
}

function toLiteral(key: string) {
  const ps = properties.value[key];
  const fallback =
    ps?.default !== undefined
      ? ps.default
      : ps?.type === "number" || ps?.type === "integer"
        ? 0
        : ps?.type === "boolean"
          ? false
          : ps?.type === "array"
            ? []
            : ps?.type === "object"
              ? {}
              : "";
  history.run(`属性 ${key}`, () => schema.setNodeProp(props.nodeId, key, fallback));
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
