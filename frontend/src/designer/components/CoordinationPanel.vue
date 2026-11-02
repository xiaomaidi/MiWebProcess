<template>
  <div class="wp-coord">
    <div class="wp-coord-head">
      <strong>页面协同</strong>
      <el-button size="small" type="primary" @click="openCreate">新建状态</el-button>
    </div>

    <el-table :data="stateRows" size="small" border>
      <el-table-column prop="key" label="状态键" min-width="120" />
      <el-table-column prop="type" label="类型" width="80" />
      <el-table-column label="默认值" min-width="100">
        <template #default="{ row }">{{ preview(row.default) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button size="small" link @click="openEdit(row)">编辑</el-button>
          <el-button size="small" link type="danger" @click="removeState(row.key)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty><el-empty description="还没有页面状态" :image-size="40" /></template>
    </el-table>

    <el-divider content-position="left">页面事件</el-divider>
    <el-input v-model="eventsJson" type="textarea" :rows="5" class="wp-coord-json" placeholder='{"stock:selected":{"payload":{"id":"string"}}}' />
    <div class="wp-coord-actions"><el-button size="small" @click="saveEvents">保存事件</el-button></div>

    <el-divider content-position="left">生命周期</el-divider>
    <div class="wp-coord-life">
      <el-radio-group v-model="lifePhase" size="small">
        <el-radio-button value="onLoad">onLoad</el-radio-button>
        <el-radio-button value="onReady">onReady</el-radio-button>
        <el-radio-button value="onUnload">onUnload</el-radio-button>
      </el-radio-group>
      <div v-for="(step, index) in phaseSteps" :key="index" class="wp-coord-action">
        <el-tag size="small" type="info">{{ step.kind }}</el-tag>
        <span class="wp-coord-action-text">{{ actionSummary(step) }}</span>
        <el-button size="small" link @click="openAction(index)">编辑</el-button>
        <el-button size="small" link :disabled="index === 0" @click="moveAction(index, -1)">上移</el-button>
        <el-button size="small" link :disabled="index === phaseSteps.length - 1" @click="moveAction(index, 1)">下移</el-button>
        <el-button size="small" link type="danger" @click="removeAction(index)">删除</el-button>
      </div>
      <div v-if="!phaseSteps.length" class="wp-coord-muted">还没有动作</div>
      <el-button size="small" plain @click="openAction()">添加动作</el-button>
    </div>

    <el-divider content-position="left">协同诊断</el-divider>
    <div v-if="!diagnostics.length" class="wp-coord-ok">没有发现明显问题</div>
    <el-alert
      v-for="(item, index) in diagnostics"
      :key="index"
      :type="item.level === 'error' ? 'error' : 'warning'"
      :title="item.message"
      :closable="false"
      show-icon
      class="wp-coord-alert"
    />

    <el-divider content-position="left">状态引用</el-divider>
    <el-table :data="stateUsageRows" size="small" border>
      <el-table-column prop="key" label="状态" min-width="120" />
      <el-table-column label="写入" min-width="120">
        <template #default="{ row }">{{ row.setters.join("、") || "—" }}</template>
      </el-table-column>
      <el-table-column label="读取" min-width="120">
        <template #default="{ row }">{{ row.readers.join("、") || "—" }}</template>
      </el-table-column>
      <el-table-column label="提供" min-width="120">
        <template #default="{ row }">{{ row.providers.join("、") || "—" }}</template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">事件发送 / 接收</el-divider>
    <div class="wp-event-graph">
      <svg :viewBox="`0 0 640 ${eventGraphHeight}`" role="img" aria-label="事件发送接收关系图">
        <g v-for="(row, index) in eventRows" :key="row.event">
          <line :x1="170" :y1="40 + index * 100" :x2="265" :y2="40 + index * 100" class="wp-graph-line" />
          <line :x1="395" :y1="40 + index * 100" :x2="490" :y2="40 + index * 100" class="wp-graph-line" />
          <rect x="20" :y="18 + index * 100" width="150" height="44" rx="8" class="wp-graph-sender" />
          <text x="95" :y="45 + index * 100" text-anchor="middle" class="wp-graph-text">{{ graphText(row.senders) }}</text>
          <rect x="265" :y="16 + index * 100" width="130" height="48" rx="10" class="wp-graph-event" />
          <text x="330" :y="45 + index * 100" text-anchor="middle" class="wp-graph-event-text">{{ row.event }}</text>
          <rect x="490" :y="18 + index * 100" width="130" height="44" rx="8" class="wp-graph-receiver" />
          <text x="555" :y="45 + index * 100" text-anchor="middle" class="wp-graph-text">{{ graphText(row.receivers) }}</text>
          <text x="330" :y="78 + index * 100" text-anchor="middle" class="wp-graph-hint">{{ row.defined ? "已声明" : "未声明" }}</text>
        </g>
      </svg>
      <div v-if="!eventRows.length" class="wp-coord-muted">还没有事件关系</div>
    </div>
    <el-table :data="eventRows" size="small" border>
      <el-table-column prop="event" label="事件" min-width="140" />
      <el-table-column label="已声明" width="80">
        <template #default="{ row }">
          <el-tag :type="row.defined ? 'success' : 'warning'" size="small">{{ row.defined ? "是" : "否" }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="发送方" min-width="130">
        <template #default="{ row }">{{ row.senders.join("、") || "—" }}</template>
      </el-table-column>
      <el-table-column label="接收方" min-width="130">
        <template #default="{ row }">{{ row.receivers.join("、") || "—" }}</template>
      </el-table-column>
    </el-table>

    <el-divider content-position="left">组件依赖</el-divider>
    <div class="wp-dep-graph">
      <svg :viewBox="`0 0 640 ${depGraphHeight}`" role="img" aria-label="组件依赖关系图">
        <g v-for="(row, index) in dependencyRows" :key="row.label + index">
          <line x1="180" :y1="38 + index * 86" x2="265" :y2="38 + index * 86" class="wp-graph-line" />
          <line x1="375" :y1="38 + index * 86" x2="460" :y2="38 + index * 86" class="wp-graph-line" />
          <rect x="265" :y="16 + index * 86" width="110" height="44" rx="8" class="wp-graph-event" />
          <text x="320" :y="43 + index * 86" text-anchor="middle" class="wp-graph-event-text">{{ graphText([row.label]) }}</text>
          <text x="90" :y="34 + index * 86" text-anchor="middle" class="wp-graph-hint">provides</text>
          <text x="90" :y="50 + index * 86" text-anchor="middle" class="wp-graph-text">{{ graphText(row.provides) }}</text>
          <text x="550" :y="34 + index * 86" text-anchor="middle" class="wp-graph-hint">consumes</text>
          <text x="550" :y="50 + index * 86" text-anchor="middle" class="wp-graph-text">{{ graphText(row.consumes) }}</text>
        </g>
      </svg>
      <div v-if="!dependencyRows.length" class="wp-coord-muted">还没有组件依赖声明</div>
    </div>
    <el-table :data="dependencyRows" size="small" border>
      <el-table-column prop="label" label="组件" min-width="150" />
      <el-table-column label="provides" min-width="130">
        <template #default="{ row }">{{ row.provides.join("、") || "—" }}</template>
      </el-table-column>
      <el-table-column label="consumes" min-width="130">
        <template #default="{ row }">{{ row.consumes.join("、") || "—" }}</template>
      </el-table-column>
    </el-table>
  </div>

  <el-dialog v-model="dialogOpen" :title="editingKey ? `编辑状态：${editingKey}` : '新建状态'" width="480px">
    <el-form label-position="top">
      <el-form-item label="状态键 key">
        <el-input v-model="form.key" :disabled="!!editingKey" placeholder="例如 stock:selectedId" />
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.type" style="width: 100%">
          <el-option label="string" value="string" />
          <el-option label="number" value="number" />
          <el-option label="boolean" value="boolean" />
          <el-option label="object" value="object" />
          <el-option label="array" value="array" />
          <el-option label="any" value="any" />
        </el-select>
      </el-form-item>
      <el-form-item label="默认值（JSON）">
        <el-input v-model="form.default" type="textarea" :rows="3" class="wp-mono" placeholder='"text" / 0 / true / {} / []' />
      </el-form-item>
      <el-form-item label="说明">
        <el-input v-model="form.description" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialogOpen = false">取消</el-button>
      <el-button type="primary" @click="saveState">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="actionDialog" :title="actionEditing === null ? '添加生命周期动作' : '编辑生命周期动作'" width="520px">
    <el-form label-position="top">
      <el-form-item label="动作类型">
        <el-select v-model="actionForm.kind" style="width: 100%">
          <el-option v-for="kind in actionKinds" :key="kind" :label="kind" :value="kind" />
        </el-select>
      </el-form-item>
      <el-form-item label="参数（JSON）">
        <el-input v-model="actionForm.params" type="textarea" :rows="5" class="wp-mono" />
      </el-form-item>
      <template v-if="hasBranches">
        <el-form-item label="then 分支（JSON 数组）">
          <el-input v-model="actionForm.then" type="textarea" :rows="3" class="wp-mono" />
        </el-form-item>
        <el-form-item label="else / 失败分支（JSON 数组）">
          <el-input v-model="actionForm.else" type="textarea" :rows="3" class="wp-mono" />
        </el-form-item>
        <el-form-item v-if="actionForm.kind === 'tryCatch'" label="catch 分支（JSON 数组）">
          <el-input v-model="actionForm.catch" type="textarea" :rows="3" class="wp-mono" />
        </el-form-item>
      </template>
    </el-form>
    <template #footer>
      <el-button @click="actionDialog = false">取消</el-button>
      <el-button type="primary" @click="saveAction">保存动作</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import { parseJson, prettyJson } from "../util";
import { analyzeCoordination } from "../coordination";
import type { ActionStep } from "@/types";

const schema = useSchemaStore();
const components = useComponentStore();
const dialogOpen = ref(false);
const editingKey = ref<string | null>(null);
const form = reactive({ key: "", type: "string", default: "", description: "" });
const eventsJson = ref("{}");
const onLoadJson = ref("[]");
const onReadyJson = ref("[]");
const onUnloadJson = ref("[]");
const lifePhase = ref<"onLoad" | "onReady" | "onUnload">("onLoad");
const actionDialog = ref(false);
const actionEditing = ref<number | null>(null);
const actionForm = reactive({
  kind: "setVariable",
  params: "{}",
  then: "[]",
  else: "[]",
  catch: "[]",
});
const hasBranches = computed(() => ["condition", "loop", "parallel", "tryCatch"].includes(actionForm.kind));
const actionKinds = [
  "setVariable",
  "callDatasource",
  "navigate",
  "message",
  "notification",
  "emit",
  "record",
  "submitForm",
  "delay",
  "condition",
  "loop",
  "parallel",
  "tryCatch",
  "confirm",
];

const phaseSteps = computed<ActionStep[]>(() => {
  const steps = schema.schema?.lifecycle?.[lifePhase.value];
  return Array.isArray(steps) ? steps : [];
});

function actionSummary(step: ActionStep): string {
  const params = JSON.stringify(step.params || {});
  return params.length > 70 ? `${params.slice(0, 70)}…` : params;
}

function setPhaseSteps(steps: ActionStep[]) {
  if (!schema.schema) return;
  schema.schema.lifecycle = {
    ...(schema.schema.lifecycle || {}),
    [lifePhase.value]: steps,
  };
  schema.dirty = true;
}

function openAction(index: number | null = null) {
  actionEditing.value = index;
  const step = index === null ? null : phaseSteps.value[index];
  actionForm.kind = step?.kind || "setVariable";
  actionForm.params = prettyJson(step?.params || {});
  actionForm.then = prettyJson(step?.then || []);
  actionForm.else = prettyJson(step?.else || []);
  actionForm.catch = prettyJson(step?.catch || []);
  actionDialog.value = true;
}

function parseStepList(text: string, label: string): ActionStep[] | null {
  const parsed = parseJson(text);
  if (!Array.isArray(parsed)) {
    ElMessage.error(`${label} 必须是动作数组`);
    return null;
  }
  return parsed as ActionStep[];
}

function saveAction() {
  const params = parseJson(actionForm.params);
  if (!params || typeof params !== "object" || Array.isArray(params)) {
    ElMessage.error("动作参数必须是 JSON 对象");
    return;
  }
  const steps: ActionStep[] = phaseSteps.value.map((step): ActionStep => ({
    ...step,
    params: { ...(step.params || {}) },
    then: step.then ? [...step.then] : undefined,
    else: step.else ? [...step.else] : undefined,
    catch: step.catch ? [...step.catch] : undefined,
  }));
  const next: ActionStep = { kind: actionForm.kind as ActionStep["kind"], params: params as Record<string, any> };
  if (hasBranches.value) {
    const thenSteps = parseStepList(actionForm.then, "then 分支");
    const elseSteps = parseStepList(actionForm.else, "else 分支");
    const catchSteps = parseStepList(actionForm.catch, "catch 分支");
    if (!thenSteps || !elseSteps || !catchSteps) return;
    next.then = thenSteps;
    next.else = elseSteps;
    next.catch = catchSteps;
  }
  if (actionEditing.value === null) steps.push(next);
  else steps[actionEditing.value] = next;
  setPhaseSteps(steps);
  actionDialog.value = false;
  ElMessage.success("生命周期动作已保存，记得保存页面");
}

function removeAction(index: number) {
  setPhaseSteps(phaseSteps.value.filter((_, i) => i !== index));
}

function moveAction(index: number, delta: number) {
  const steps = [...phaseSteps.value];
  const target = index + delta;
  if (target < 0 || target >= steps.length) return;
  [steps[index], steps[target]] = [steps[target], steps[index]];
  setPhaseSteps(steps);
}

const stateRows = computed(() =>
  Object.entries(schema.schema?.state || {}).map(([key, def]) => ({
    key,
    type: def?.type || "any",
    default: def?.default,
    description: def?.description || "",
  }))
);

function preview(value: any): string {
  const text = typeof value === "string" ? value : prettyJson(value);
  return text.length > 28 ? `${text.slice(0, 28)}…` : text;
}

function syncJson() {
  eventsJson.value = prettyJson(schema.schema?.events || {});
  onLoadJson.value = prettyJson(schema.schema?.lifecycle?.onLoad || []);
  onReadyJson.value = prettyJson(schema.schema?.lifecycle?.onReady || []);
  onUnloadJson.value = prettyJson(schema.schema?.lifecycle?.onUnload || []);
}

watch(() => schema.schema, syncJson, { immediate: true, deep: false });

function openCreate() {
  editingKey.value = null;
  form.key = "";
  form.type = "string";
  form.default = '""';
  form.description = "";
  dialogOpen.value = true;
}

function openEdit(row: any) {
  editingKey.value = row.key;
  form.key = row.key;
  form.type = row.type || "any";
  form.default = prettyJson(row.default);
  form.description = row.description || "";
  dialogOpen.value = true;
}

function saveState() {
  if (!schema.schema) return;
  const key = form.key.trim();
  if (!/^[A-Za-z_$][\w$:.-]*$/.test(key)) {
    ElMessage.warning("状态键格式不正确");
    return;
  }
  const value = parseJson(form.default);
  const def = {
    type: form.type as any,
    default: value === null && form.default.trim() === "" ? null : value,
    description: form.description.trim(),
  };
  const next = { ...(schema.schema.state || {}) };
  next[key] = def;
  schema.schema.state = next;
  schema.dirty = true;
  dialogOpen.value = false;
  ElMessage.success("页面状态已保存，记得保存页面");
}

function removeState(key: string) {
  if (!schema.schema?.state) return;
  const next = { ...schema.schema.state };
  delete next[key];
  schema.schema.state = next;
  schema.dirty = true;
}

function saveEvents() {
  if (!schema.schema) return;
  const parsed = parseJson(eventsJson.value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    ElMessage.error("事件定义必须是 JSON 对象");
    return;
  }
  schema.schema.events = parsed as any;
  schema.dirty = true;
  ElMessage.success("事件定义已保存");
}

function saveLifecycle() {
  if (!schema.schema) return;
  const load = parseJson(onLoadJson.value);
  const ready = parseJson(onReadyJson.value);
  const unload = parseJson(onUnloadJson.value);
  for (const [label, value] of [["onLoad", load], ["onReady", ready], ["onUnload", unload]]) {
    if (!Array.isArray(value)) {
      ElMessage.error(`${label} 必须是动作数组`);
      return;
    }
  }
  schema.schema.lifecycle = {
    onLoad: load as any,
    onReady: ready as any,
    onUnload: unload as any,
  };
  schema.dirty = true;
  ElMessage.success("生命周期已保存");
}

const diagnostics = computed(() => {
  const s = schema.schema;
  const out: { level: "warning" | "error"; message: string }[] = [];
  if (!s) return out;
  const stateKeys = new Set(Object.keys(s.state || {}));
  const eventKeys = new Set(Object.keys(s.events || {}));
  const providers = new Map<string, string[]>();
  for (const [key, def] of Object.entries(s.state || {})) {
    if (!/^[A-Za-z_$][\w$:.-]*$/.test(key)) out.push({ level: "error", message: `状态键不合法：${key}` });
    const type = def?.type || "any";
    if (type !== "any" && def?.default !== undefined && def?.default !== null) {
      const actual = Array.isArray(def.default) ? "array" : typeof def.default;
      if (actual !== type) out.push({ level: "warning", message: `状态 ${key} 默认值与类型 ${type} 不匹配` });
    }
  }
  for (const [name, def] of Object.entries(s.events || {})) {
    if (def?.payload && typeof def.payload !== "object") out.push({ level: "error", message: `事件 ${name} 的 payload 必须是对象` });
  }
  for (const node of Object.values(s.nodes || {})) {
    if (node.id === s.rootId) continue;
    const meta = components.meta(node.type);
    if (!meta) continue;
    for (const item of meta.provides || []) {
      const list = providers.get(item) || [];
      list.push(node.type);
      providers.set(item, list);
    }
    for (const item of meta.consumes || []) {
      if (item.startsWith("state:") && !stateKeys.has(item.slice(6))) {
        out.push({ level: "warning", message: `${node.type} 依赖状态 ${item.slice(6)}，但页面未定义` });
      }
      if (item.startsWith("event:") && !eventKeys.has(item.slice(6))) {
        out.push({ level: "warning", message: `${node.type} 依赖事件 ${item.slice(6)}，但页面未定义` });
      }
    }
    for (const eventName of Object.keys(node.events || {})) {
      if (eventKeys.size && !eventKeys.has(eventName)) {
        out.push({ level: "warning", message: `${node.type} 使用了未声明的事件 ${eventName}` });
      }
    }
  }
  for (const [key, list] of providers) {
    if (list.length > 1) out.push({ level: "warning", message: `多个组件都提供 ${key}：${list.join("、")}` });
  }
  return out;
});

const astAnalysis = computed(() => analyzeCoordination(schema.schema, (type) => components.meta(type)));
const stateUsageRows = computed(() => astAnalysis.value.states);
const eventRows = computed(() => astAnalysis.value.events);
const dependencyRows = computed(() => astAnalysis.value.dependencies);
const eventGraphHeight = computed(() => Math.max(140, eventRows.value.length * 100 + 30));
const depGraphHeight = computed(() => Math.max(110, dependencyRows.value.length * 86 + 20));

function graphText(items: string[]): string {
  const text = items.join("、") || "—";
  return text.length > 18 ? `${text.slice(0, 18)}…` : text;
}
</script>

<style scoped>
.wp-coord {
  padding: 8px;
  font-size: 13px;
}
.wp-coord-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.wp-coord-json :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.wp-coord-actions {
  margin-top: 6px;
  text-align: right;
}
.wp-coord-life {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wp-coord-life label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-coord-action {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 6px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
}
.wp-coord-action-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-secondary);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
}
.wp-coord-muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-coord-ok {
  color: var(--el-color-success);
  font-size: 12px;
}
.wp-event-graph {
  overflow-x: auto;
  margin-bottom: 8px;
}
.wp-dep-graph {
  overflow-x: auto;
  margin-bottom: 8px;
}
.wp-dep-graph svg {
  width: 100%;
  min-width: 560px;
  height: auto;
}
.wp-event-graph svg {
  width: 100%;
  min-width: 560px;
  height: auto;
}
.wp-graph-line {
  stroke: var(--el-border-color);
  stroke-width: 1.5;
}
.wp-graph-sender {
  fill: var(--el-color-primary-light-9);
  stroke: var(--el-color-primary-light-5);
}
.wp-graph-receiver {
  fill: var(--el-color-success-light-9);
  stroke: var(--el-color-success-light-5);
}
.wp-graph-event {
  fill: var(--el-fill-color);
  stroke: var(--el-color-warning-light-5);
}
.wp-graph-text,
.wp-graph-event-text,
.wp-graph-hint {
  fill: var(--el-text-color-regular);
  font-size: 11px;
}
.wp-graph-event-text {
  font-weight: 600;
}
.wp-graph-hint {
  fill: var(--el-text-color-secondary);
  font-size: 10px;
}
.wp-coord-alert {
  margin-bottom: 6px;
}
</style>
