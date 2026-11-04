<template>
  <div class="wp-events">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <div class="wp-events-row">
        <label>事件</label>
        <el-select v-model="activeEvent" size="small" placeholder="选择事件" filterable class="wp-events-select">
          <el-option v-for="n in eventNames" :key="n" :label="eventLabel(n)" :value="n">
            <span class="wp-events-option">
              <span>{{ eventLabel(n) }}</span>
              <el-tag v-if="eventCount(n)" size="small" effect="plain">{{ eventCount(n) }}</el-tag>
            </span>
          </el-option>
        </el-select>
        <el-popconfirm
          v-if="activeEvent && steps.length"
          :title="`清空「${eventLabel(activeEvent)}」的 ${steps.length} 个动作？`"
          confirm-button-text="清空"
          cancel-button-text="取消"
          width="240"
          @confirm="clearEvent"
        >
          <template #reference>
            <el-button size="small" type="danger" plain>清空</el-button>
          </template>
        </el-popconfirm>
      </div>

      <p v-if="!activeEvent" class="wp-events-hint">该节点没有可用事件。</p>
      <template v-else>
        <div class="wp-events-meta">
          <span class="wp-events-meta-name">{{ eventLabel(activeEvent) }}</span>
          <el-tag size="small" effect="plain">{{ steps.length }} 个动作</el-tag>
          <el-tag v-if="errorIssues.length" size="small" type="danger">{{ errorIssues.length }} 个错误</el-tag>
          <el-tag v-else-if="warningIssues.length" size="small" type="warning">{{ warningIssues.length }} 个提醒</el-tag>
          <el-tag v-else-if="steps.length" size="small" type="success">校验通过</el-tag>
          <span class="wp-events-meta-hint">动作按从上到下的顺序执行</span>
        </div>

        <div v-if="steps.length" class="wp-events-flow">
          <div
            v-for="(item, i) in steps"
            :id="`wp-step-${i}`"
            :key="item.id || i"
            class="wp-events-flow-item"
          >
            <span class="wp-events-flow-index">{{ i + 1 }}</span>
            <span class="wp-events-flow-text" :title="summaries[i]">{{ summaries[i] }}</span>
            <el-tag v-if="issueCount(i)" size="small" :type="hasErrorAt(i) ? 'danger' : 'warning'">
              {{ issueCount(i) }} 项待完善
            </el-tag>
            <div class="wp-events-flow-ops">
              <el-button size="small" text :disabled="i === 0" @click="moveStep(i, -1)">上移</el-button>
              <el-button size="small" text :disabled="i === steps.length - 1" @click="moveStep(i, 1)">下移</el-button>
              <el-popconfirm
                title="删除这个动作？删除后不可直接恢复（可撤销）。"
                confirm-button-text="删除"
                cancel-button-text="取消"
                width="230"
                @confirm="removeStep(i)"
              >
                <template #reference>
                  <el-button size="small" text type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </div>
          </div>
        </div>
        <div v-else class="wp-events-empty">该事件暂无动作，使用下方菜单快速添加。</div>

        <div v-if="issues.length" class="wp-events-issues">
          <div class="wp-events-issues-head">
            <el-tag v-if="errorIssues.length" size="small" type="danger">错误 {{ errorIssues.length }}</el-tag>
            <el-tag v-if="warningIssues.length" size="small" type="warning">提醒 {{ warningIssues.length }}</el-tag>
            <span>点击问题可定位到对应动作</span>
          </div>
          <button
            v-for="(issue, i) in issues"
            :key="`${issue.anchor}-${i}-${issue.message}`"
            type="button"
            class="wp-events-issue"
            :class="issue.level"
            @click="focusIssue(issue)"
          >
            <span class="tag">{{ issue.level === "error" ? "错误" : "提醒" }}</span>
            <span class="path">{{ issue.path }}</span>
            <span class="msg">{{ issue.message }}</span>
          </button>
        </div>

        <div class="wp-events-add">
          <el-dropdown trigger="click" @command="onAddCommand">
            <el-button size="small" type="primary" plain>＋ 快速添加动作</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <template v-for="(item, i) in QUICK_ACTIONS" :key="item.kind">
                  <el-dropdown-item v-if="i === 0 || QUICK_ACTIONS[i - 1].group !== item.group" disabled class="wp-events-group">
                    {{ item.group }}
                  </el-dropdown-item>
                  <el-dropdown-item :command="item.kind">{{ item.label }}</el-dropdown-item>
                </template>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span class="wp-events-add-hint">添加后可在下方详情中填写参数</span>
        </div>

        <div class="wp-events-detail-head">动作详情</div>
        <StepList :model-value="steps" :datasources="datasources" :models="models" @update="handleStepListUpdate" />
      </template>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { ActionKind, ActionStep, DataModelInfo, DataSourceDef } from "@/types";
import { commit } from "../util";
import {
  QUICK_ACTIONS,
  actionLabel,
  makeDefaultStep,
  summarizeAction,
  validateActionSteps,
  type ActionContext,
  type ActionIssue,
} from "../utils/actionSummary";
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

const EVENT_LABELS: Record<string, string> = {
  click: "点击 click",
  dblclick: "双击 dblclick",
  change: "值变更 change",
  input: "输入 input",
  submit: "提交 submit",
  load: "加载 load",
  confirm: "确认 confirm",
  close: "关闭 close",
  open: "打开 open",
  focus: "聚焦 focus",
  blur: "失焦 blur",
  select: "选择 select",
  expand: "展开 expand",
  collapse: "收起 collapse",
  check: "勾选 check",
  currentchange: "页码变更 current-change",
};
function eventLabel(name: string): string {
  return EVENT_LABELS[name] || name;
}

const activeEvent = ref<string>("");
const eventNames = computed<string[]>(() => {
  const fromMeta: string[] = meta.value?.events ?? [];
  const used = Object.keys(node.value?.events ?? {});
  const base = fromMeta.length ? fromMeta : ["click", "dblclick", "change", "input"];
  return [...new Set([...base, ...used])];
});
const steps = computed<ActionStep[]>(() => node.value?.events?.[activeEvent.value] ?? []);
const eventCounts = computed<Record<string, number>>(() => {
  const out: Record<string, number> = {};
  for (const [name, list] of Object.entries(node.value?.events ?? {})) out[name] = Array.isArray(list) ? list.length : 0;
  return out;
});
function eventCount(name: string): number {
  return eventCounts.value[name] ?? 0;
}

const actionCtx = computed<ActionContext>(() => ({
  datasources: props.datasources,
  models: props.models,
  nodeIds: new Set(Object.keys(schema.schema?.nodes ?? {})),
  nodeLabel: (id: string) => {
    const n = schema.node(id);
    if (!n) return "";
    return components.meta(n.type)?.label || n.type;
  },
}));

const summaries = computed(() => steps.value.map((s) => summarizeAction(s, actionCtx.value)));
const issues = computed<ActionIssue[]>(() => validateActionSteps(steps.value, actionCtx.value));
const errorIssues = computed(() => issues.value.filter((i) => i.level === "error"));
const warningIssues = computed(() => issues.value.filter((i) => i.level === "warning"));
function issueCount(index: number): number {
  return issues.value.filter((i) => i.anchor === index).length;
}
function hasErrorAt(index: number): boolean {
  return issues.value.some((i) => i.anchor === index && i.level === "error");
}

function syncActive() {
  if (!eventNames.value.length) {
    activeEvent.value = "";
    return;
  }
  if (!activeEvent.value || !eventNames.value.includes(activeEvent.value)) {
    activeEvent.value = eventNames.value[0];
  }
}
watch(eventNames, syncActive, { immediate: true, deep: true });
watch(
  () => props.nodeId,
  () => {
    activeEvent.value = "";
    syncActive();
  }
);

function commitSteps(list: ActionStep[]) {
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

function countAllSteps(list: ActionStep[]): number {
  return list.reduce((sum, step) => {
    const children = [...(step.then ?? []), ...(step.else ?? []), ...(step.catch ?? [])];
    return sum + 1 + countAllSteps(children);
  }, 0);
}

/** StepList 内部编辑提交：若检测到删除（含嵌套分支）先二次确认，避免误删。 */
async function handleStepListUpdate(list: ActionStep[]) {
  const eventName = activeEvent.value;
  const nodeId = props.nodeId;
  const before = countAllSteps(steps.value);
  const after = countAllSteps(list);
  if (after < before) {
    try {
      await ElMessageBox.confirm(
        `本次修改会删除 ${before - after} 个动作（含嵌套分支）。删除后可通过撤销恢复，是否继续？`,
        "删除动作",
        { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
      );
    } catch {
      return;
    }
  }
  // 确认期间切换了节点/事件时丢弃本次提交，避免改错目标。
  if (activeEvent.value !== eventName || props.nodeId !== nodeId) return;
  commitSteps(list);
}

function onAddCommand(command: string) {
  const kind = command as ActionKind;
  const next = [...steps.value, makeDefaultStep(kind, actionCtx.value)];
  commitSteps(next);
  ElMessage.success(`已添加「${actionLabel(kind)}」，请在下方补全参数`);
}

function moveStep(index: number, dir: -1 | 1) {
  const to = index + dir;
  if (to < 0 || to >= steps.value.length) return;
  const next = [...steps.value];
  const [step] = next.splice(index, 1);
  next.splice(to, 0, step);
  commitSteps(next);
}

function removeStep(index: number) {
  const next = steps.value.filter((_, i) => i !== index);
  commitSteps(next);
  ElMessage.success("动作已删除");
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
  ElMessage.success(`已清空「${eventLabel(name)}」的动作`);
}

function focusIssue(issue: ActionIssue) {
  if (typeof document === "undefined") return;
  const el = document.getElementById(`wp-step-${issue.anchor}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  el.classList.add("wp-flash");
  window.setTimeout(() => el.classList.remove("wp-flash"), 1400);
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
  margin-bottom: 8px;
}
.wp-events-row label {
  width: 32px;
  flex: none;
  color: var(--el-text-color-regular);
  font-size: 12px;
}
.wp-events-select {
  flex: 1;
}
.wp-events-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.wp-events-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-events-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.wp-events-meta-name {
  font-weight: 600;
}
.wp-events-meta-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-events-flow {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 8px;
}
.wp-events-flow-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
  transition: background 0.2s;
}
.wp-events-flow-item:last-child {
  border-bottom: none;
}
.wp-events-flow-index {
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: 50%;
  background: var(--el-fill-color-dark);
  color: var(--el-text-color-regular);
  font-size: 11px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.wp-events-flow-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-events-flow-ops {
  display: flex;
  flex: none;
}
.wp-events-empty {
  padding: 12px 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  text-align: center;
  border: 1px dashed var(--el-border-color);
  border-radius: 6px;
  margin-bottom: 8px;
}
.wp-events-issues {
  margin-bottom: 8px;
}
.wp-events-issues-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-events-issue {
  display: flex;
  align-items: baseline;
  gap: 6px;
  width: 100%;
  padding: 4px 8px;
  margin-bottom: 3px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: var(--el-fill-color-light);
  text-align: left;
  cursor: pointer;
  color: inherit;
  font-size: 12px;
}
.wp-events-issue.error {
  border-color: var(--el-color-danger-light-7);
  background: var(--el-color-danger-light-9);
}
.wp-events-issue.warning {
  border-color: var(--el-color-warning-light-7);
  background: var(--el-color-warning-light-9);
}
.wp-events-issue .tag {
  flex: none;
  font-weight: 600;
  color: var(--el-color-danger);
}
.wp-events-issue.warning .tag {
  color: var(--el-color-warning);
}
.wp-events-issue .path {
  flex: none;
  color: var(--el-text-color-secondary);
}
.wp-events-issue .msg {
  min-width: 0;
  overflow-wrap: anywhere;
}
.wp-events-add {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.wp-events-add-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-events-group {
  color: var(--el-text-color-secondary) !important;
  font-size: 11px;
}
.wp-events-detail-head {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  border-bottom: 1px solid var(--el-border-color-lighter);
  padding-bottom: 4px;
  margin-bottom: 6px;
}
.wp-flash {
  animation: wp-events-flash 0.7s ease-in-out 2;
}
@keyframes wp-events-flash {
  0%,
  100% {
    background: var(--el-fill-color-blank);
  }
  50% {
    background: var(--el-color-warning-light-9);
  }
}
</style>
