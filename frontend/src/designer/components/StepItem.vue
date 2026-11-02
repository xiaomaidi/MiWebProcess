<template>
  <div class="wp-step">
    <div class="wp-step-head">
      <el-select v-model="local.kind" size="small" style="width: 178px" @change="emitStep">
        <el-option label="设置变量 setVariable" value="setVariable" />
        <el-option label="调用数据源 callDatasource" value="callDatasource" />
        <el-option label="跳转 navigate" value="navigate" />
        <el-option label="打开弹窗 openModal" value="openModal" />
        <el-option label="关闭弹窗 closeModal" value="closeModal" />
        <el-option label="打开抽屉 openDrawer" value="openDrawer" />
        <el-option label="关闭抽屉 closeDrawer" value="closeDrawer" />
        <el-option label="提示 message" value="message" />
        <el-option label="通知 notification" value="notification" />
        <el-option label="确认 confirm" value="confirm" />
        <el-option label="数据操作 record" value="record" />
        <el-option label="条件 condition" value="condition" />
        <el-option label="循环 loop" value="loop" />
        <el-option label="并行 parallel" value="parallel" />
        <el-option label="异常捕获 tryCatch" value="tryCatch" />
        <el-option label="延时 delay" value="delay" />
        <el-option label="改样式 setStyle" value="setStyle" />
        <el-option label="触发事件 emit" value="emit" />
        <el-option label="提交表单 submitForm" value="submitForm" />
        <el-option label="重置表单 resetForm" value="resetForm" />
        <el-option label="下载 download" value="download" />
        <el-option label="复制 copy" value="copy" />
        <el-option label="打印 print" value="print" />
        <el-option label="HTTP 请求 http" value="http" />
        <el-option label="受限 JS js" value="js" />
      </el-select>
      <span class="wp-step-index">步骤 {{ index + 1 }}</span>
      <div class="wp-step-ops">
        <el-button size="small" text @click="$emit('move', -1)">上移</el-button>
        <el-button size="small" text @click="$emit('move', 1)">下移</el-button>
        <el-button size="small" text type="danger" @click="$emit('remove')">删除</el-button>
      </div>
    </div>

    <div class="wp-step-body">
      <template v-if="local.kind === 'setVariable'">
        <div class="wp-step-row">
          <el-input v-model="local.name" size="small" placeholder="变量名" style="width: 180px" @change="emitStep" />
          <el-input v-model="local.value" size="small" placeholder="值（字面量或表达式）" style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'callDatasource'">
        <div class="wp-step-row">
          <el-select v-model="local.ref" size="small" style="width: 200px" @change="emitStep">
            <el-option v-for="ds in datasources" :key="ds.id" :label="`${ds.name} (#${ds.id})`" :value="`ds_${ds.id}`" />
          </el-select>
          <el-input v-model="local.paramsText" size="small" placeholder='params JSON，如 {"page": 1}' style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'navigate'">
        <div class="wp-step-row">
          <el-input v-model="local.path" size="small" placeholder="目标路径，如 /users/1" style="flex: 1" @change="emitStep" />
          <el-select v-model="local.target" size="small" style="width: 120px" @change="emitStep">
            <el-option label="当前页 _self" value="_self" />
            <el-option label="新窗口 _blank" value="_blank" />
          </el-select>
        </div>
      </template>

      <template v-else-if="['openModal', 'closeModal', 'openDrawer', 'closeDrawer'].includes(local.kind)">
        <div class="wp-step-row">
          <el-input v-model="local.nodeId" size="small" placeholder="目标节点 id（schema 中该节点的 id）" style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'message' || local.kind === 'notification'">
        <div class="wp-step-row">
          <el-input v-if="local.kind === 'notification'" v-model="local.title" size="small" placeholder="通知标题" style="width: 140px" @change="emitStep" />
          <el-input v-model="local.text" size="small" placeholder="提示文本" style="flex: 1" @change="emitStep" />
          <el-select v-model="local.msgType" size="small" style="width: 110px" @change="emitStep">
            <el-option label="success" value="success" />
            <el-option label="info" value="info" />
            <el-option label="warning" value="warning" />
            <el-option label="error" value="error" />
          </el-select>
        </div>
      </template>

      <template v-else-if="local.kind === 'confirm'">
        <div class="wp-step-row">
          <el-input v-model="local.title" size="small" placeholder="标题" style="width: 130px" @change="emitStep" />
          <el-input v-model="local.text" size="small" placeholder="确认文案" style="flex: 1" @change="emitStep" />
        </div>
        <div class="wp-cond">
          <div class="wp-cond-col">
            <div class="wp-cond-title">确认 then</div>
            <StepList :model-value="step.then ?? []" :datasources="datasources" :models="models" @update="onThen" />
          </div>
          <div class="wp-cond-col">
            <div class="wp-cond-title">取消 else</div>
            <StepList :model-value="step.else ?? []" :datasources="datasources" :models="models" @update="onElse" />
          </div>
        </div>
      </template>

      <template v-else-if="local.kind === 'record'">
        <div class="wp-step-row">
          <el-select v-model="local.modelId" size="small" style="width: 180px" @change="emitStep">
            <el-option v-for="m in models" :key="m.id" :label="`${m.name} (#${m.id})`" :value="m.id" />
          </el-select>
          <el-select v-model="local.op" size="small" style="width: 110px" @change="emitStep">
            <el-option label="查询 list" value="list" />
            <el-option label="新增 create" value="create" />
            <el-option label="更新 update" value="update" />
            <el-option label="删除 remove" value="remove" />
          </el-select>
          <el-input v-if="local.op !== 'list'" v-model="local.recordId" size="small" placeholder="记录 id" style="width: 100px" @change="emitStep" />
          <el-input v-if="local.op === 'list'" v-model="local.varName" size="small" placeholder="存入变量名" style="width: 120px" @change="emitStep" />
        </div>
        <div class="wp-step-row">
          <el-input
            v-if="local.op === 'list'"
            v-model="local.paramsText"
            size="small"
            type="textarea"
            :rows="2"
            placeholder='查询 params JSON，如 {"page": 1, "page_size": 20}'
            @change="emitStep"
          />
          <el-input
            v-else-if="local.op === 'create' || local.op === 'update'"
            v-model="local.dataText"
            size="small"
            type="textarea"
            :rows="2"
            placeholder='data JSON，如 {"name": "新值"}'
            @change="emitStep"
          />
        </div>
      </template>

      <template v-else-if="local.kind === 'condition'">
        <div class="wp-step-row">
          <el-input v-model="local.expr" size="small" placeholder="条件表达式，如 user.role === 'admin'" style="flex: 1" @change="emitStep" />
        </div>
        <div class="wp-cond">
          <div class="wp-cond-col">
            <div class="wp-cond-title">满足 then</div>
            <StepList :model-value="step.then ?? []" :datasources="datasources" :models="models" @update="onThen" />
          </div>
          <div class="wp-cond-col">
            <div class="wp-cond-title">否则 else</div>
            <StepList :model-value="step.else ?? []" :datasources="datasources" :models="models" @update="onElse" />
          </div>
        </div>
      </template>

      <template v-else-if="local.kind === 'loop'">
        <div class="wp-step-row">
          <el-input v-model="local.listExpr" size="small" placeholder="数组表达式，如 users" style="flex: 1" @change="emitStep" />
          <el-input v-model="local.itemVar" size="small" placeholder="item" style="width: 90px" @change="emitStep" />
          <el-input v-model="local.indexVar" size="small" placeholder="index" style="width: 90px" @change="emitStep" />
        </div>
        <StepList :model-value="step.then ?? []" :datasources="datasources" :models="models" @update="onThen" />
      </template>

      <template v-else-if="local.kind === 'parallel' || local.kind === 'tryCatch'">
        <div class="wp-cond-title">{{ local.kind === 'parallel' ? '并行执行' : '尝试 try' }}</div>
        <StepList :model-value="step.then ?? []" :datasources="datasources" :models="models" @update="onThen" />
        <template v-if="local.kind === 'tryCatch'">
          <div class="wp-cond-title" v-pre>捕获 catch（可使用 {{error.message}}）</div>
          <StepList :model-value="step.catch ?? step.else ?? []" :datasources="datasources" :models="models" @update="onCatch" />
        </template>
      </template>

      <template v-else-if="local.kind === 'delay'">
        <div class="wp-step-row">
          <el-input-number v-model="local.delayMs" :min="0" :max="60000" :step="100" size="small" controls-position="right" @change="emitStep" />
          <span class="wp-step-hint">毫秒（最大 60000）</span>
        </div>
      </template>

      <template v-else-if="local.kind === 'setStyle'">
        <div class="wp-step-row">
          <el-input v-model="local.nodeId" size="small" placeholder="节点 id" style="width: 200px" @change="emitStep" />
          <el-input v-model="local.styleText" size="small" placeholder='style JSON，如 {"color":"#f56c6c"}' style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'emit'">
        <div class="wp-step-row">
          <el-input v-model="local.event" size="small" placeholder="事件名" style="width: 180px" @change="emitStep" />
          <el-input v-model="local.payloadText" size="small" placeholder="payload JSON（可选）" style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'submitForm'">
        <div class="wp-step-row">
          <el-input v-model="local.formId" size="small" placeholder="表单节点 id（可选）" style="width: 150px" @change="emitStep" />
          <el-select v-model="local.submitModelId" size="small" style="width: 180px" clearable @change="emitStep">
            <el-option v-for="m in models" :key="m.id" :label="`${m.name} (#${m.id})`" :value="m.id" />
          </el-select>
          <el-select v-model="local.submitOp" size="small" style="width: 110px" @change="emitStep">
            <el-option label="新增 create" value="create" />
            <el-option label="更新 update" value="update" />
          </el-select>
        </div>
        <div class="wp-step-row">
          <el-input v-if="local.submitOp === 'update'" v-model="local.submitRecordId" size="small" placeholder="记录 ID / 表达式" style="width: 180px" @change="emitStep" />
          <el-input v-model="local.varName" size="small" placeholder="提交后存入变量名（可选）" style="width: 180px" @change="emitStep" />
          <el-input v-model="local.successText" size="small" placeholder="成功提示" style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'resetForm'">
        <div class="wp-step-row">
          <el-input v-model="local.formId" size="small" placeholder="表单节点 id（可选，留空重置全部）" style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'download'">
        <div class="wp-step-row">
          <el-input v-model="local.filename" size="small" placeholder="文件名" style="width: 160px" @change="emitStep" />
          <el-input v-model="local.mime" size="small" placeholder="MIME" style="width: 150px" @change="emitStep" />
        </div>
        <div class="wp-step-row">
          <el-input v-model="local.text" size="small" type="textarea" :rows="2" placeholder="文件内容（支持表达式）" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'copy'">
        <div class="wp-step-row">
          <el-input v-model="local.text" size="small" placeholder="复制内容（支持表达式）" style="flex: 1" @change="emitStep" />
        </div>
      </template>

      <template v-else-if="local.kind === 'print'">
        <div class="wp-step-hint">调用浏览器打印当前页面。</div>
      </template>

      <template v-else-if="local.kind === 'js'">
        <div class="wp-step-row">
          <el-input v-model="local.code" size="small" type="textarea" :rows="3" placeholder="仅允许表达式，如 users.length > 0 ? 'ok' : 'empty'" @change="emitStep" />
        </div>
        <div class="wp-step-row">
          <el-input v-model="local.varName" size="small" placeholder="结果存入变量名（可选）" style="width: 220px" @change="emitStep" />
          <span class="wp-step-hint">发布时会做 AST 白名单校验；禁止语句、eval、new Function、window。</span>
        </div>
      </template>

      <template v-else-if="local.kind === 'http'">
        <div class="wp-step-row">
          <el-select v-model="local.method" size="small" style="width: 100px" @change="emitStep">
            <el-option label="GET" value="GET" />
            <el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" />
            <el-option label="DELETE" value="DELETE" />
          </el-select>
          <el-input v-model="local.path" size="small" placeholder="API 路径（不含 /api 前缀）" style="flex: 1" @change="emitStep" />
          <el-input v-model="local.varName" size="small" placeholder="存入变量名（可选）" style="width: 120px" @change="emitStep" />
        </div>
        <div v-if="local.method === 'POST' || local.method === 'PUT'" class="wp-step-row">
          <el-input v-model="local.bodyText" size="small" type="textarea" :rows="2" placeholder="body JSON" @change="emitStep" />
        </div>
      </template>

      <template v-else>
        <div class="wp-step-hint">该动作无参数。</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from "vue";
import { ElMessage } from "element-plus";
import type { ActionStep, ActionKind, DataModelInfo, DataSourceDef } from "@/types";
import StepList from "./StepList.vue";

const props = defineProps<{
  step: ActionStep;
  index: number;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
}>();
const emit = defineEmits<{
  (e: "update", step: ActionStep): void;
  (e: "remove"): void;
  (e: "move", dir: -1 | 1): void;
}>();

const local = reactive({
  kind: "setVariable" as ActionKind,
  name: "",
  value: "",
  ref: "",
  paramsText: "",
  path: "",
  target: "_self",
  nodeId: "",
  text: "",
  title: "",
  msgType: "info",
  modelId: undefined as number | undefined,
  op: "list",
  recordId: "",
  varName: "",
  dataText: "",
  expr: "",
  listExpr: "",
  itemVar: "item",
  indexVar: "index",
  delayMs: 300,
  styleText: "",
  event: "custom",
  payloadText: "",
  formId: "",
  submitModelId: undefined as number | undefined,
  submitOp: "create",
  submitRecordId: "",
  successText: "提交成功",
  filename: "download.txt",
  mime: "text/plain;charset=utf-8",
  code: "",
  method: "POST",
  bodyText: "",
});

function syncFrom(step: ActionStep) {
  const p = step.params || {};
  local.kind = step.kind;
  local.name = p.name ?? "";
  local.value = typeof p.value === "string" ? p.value : JSON.stringify(p.value ?? "");
  local.ref = p.ref ?? p.id ?? "";
  local.paramsText = p.params ? JSON.stringify(p.params) : "";
  local.path = p.path ?? "";
  local.target = p.target ?? "_self";
  local.nodeId = p.nodeId ?? "";
  local.text = p.text ?? "";
  local.title = p.title ?? "";
  local.msgType = p.type ?? "info";
  local.modelId = p.modelId ?? (p.ref ? Number(String(p.ref).replace(/^model_/, "")) || undefined : undefined);
  local.op = p.op ?? "list";
  local.recordId = p.id != null ? String(p.id) : "";
  local.varName = p.varName ?? "";
  local.dataText = p.data ? JSON.stringify(p.data) : "";
  local.expr = p.expr ?? "";
  local.listExpr = p.list ?? "";
  local.itemVar = p.itemVar ?? "item";
  local.indexVar = p.indexVar ?? "index";
  local.delayMs = Number(p.ms ?? p.duration ?? 300) || 0;
  local.styleText = p.style ? JSON.stringify(p.style) : "";
  local.event = p.event ?? "custom";
  local.payloadText = p.payload ? JSON.stringify(p.payload) : "";
  local.formId = p.formId ?? "";
  local.submitModelId = p.modelId != null ? Number(p.modelId) : undefined;
  local.submitOp = p.op ?? "create";
  local.submitRecordId = p.recordId != null ? String(p.recordId) : "";
  local.successText = p.successText ?? "提交成功";
  local.filename = p.filename ?? "download.txt";
  local.mime = p.mime ?? "text/plain;charset=utf-8";
  local.code = p.code ?? p.expr ?? "";
  local.method = p.method ?? "POST";
  local.bodyText = p.body ? JSON.stringify(p.body) : "";
}

watch(() => props.step, (s) => syncFrom(s), { immediate: true, deep: true });

function parseJson(text: string): any {
  const t = (text || "").trim();
  if (!t) return undefined;
  try {
    return JSON.parse(t);
  } catch {
    ElMessage.warning("JSON 格式不正确，未应用");
    return undefined;
  }
}

function emitStep() {
  const kind = local.kind;
  let params: Record<string, any> = {};
  switch (kind) {
    case "setVariable":
      params = { name: local.name.trim(), value: local.value.trim() };
      break;
    case "callDatasource": {
      params = { ref: local.ref };
      const pj = parseJson(local.paramsText);
      if (pj !== undefined) params.params = pj;
      break;
    }
    case "navigate":
      params = { path: local.path.trim(), target: local.target };
      break;
    case "openModal":
    case "closeModal":
    case "openDrawer":
    case "closeDrawer":
      params = { nodeId: local.nodeId.trim() };
      break;
    case "message":
      params = { text: local.text, type: local.msgType };
      break;
    case "notification":
      params = { text: local.text, title: local.title, type: local.msgType };
      break;
    case "confirm":
      params = { text: local.text, title: local.title };
      break;
    case "record": {
      params = { modelId: local.modelId, op: local.op };
      if (local.op === "list") {
        const pj = parseJson(local.paramsText);
        if (pj !== undefined) params.params = pj;
        if (local.varName.trim()) params.varName = local.varName.trim();
      } else {
        if (local.recordId) params.id = Number(local.recordId);
        if (local.op === "create" || local.op === "update") {
          const dj = parseJson(local.dataText);
          if (dj !== undefined) params.data = dj;
        }
      }
      break;
    }
    case "condition":
      params = { expr: local.expr.trim() };
      break;
    case "loop":
      params = { list: local.listExpr.trim(), itemVar: local.itemVar.trim() || "item", indexVar: local.indexVar.trim() || "index" };
      break;
    case "parallel":
      params = {};
      break;
    case "tryCatch":
      params = {};
      break;
    case "delay":
      params = { ms: local.delayMs };
      break;
    case "setStyle":
      params = { nodeId: local.nodeId.trim(), style: parseJson(local.styleText) || {} };
      break;
    case "emit":
      params = { event: local.event.trim() || "custom", payload: parseJson(local.payloadText) };
      break;
    case "submitForm":
      params = {
        formId: local.formId.trim(),
        varName: local.varName.trim(),
        successText: local.successText,
        modelId: local.submitModelId,
        op: local.submitOp,
        recordId: local.submitRecordId.trim(),
      };
      break;
    case "resetForm":
      params = { formId: local.formId.trim() };
      break;
    case "download":
      params = { filename: local.filename.trim(), mime: local.mime.trim(), content: local.text };
      break;
    case "copy":
      params = { text: local.text };
      break;
    case "print":
      params = {};
      break;
    case "http": {
      params = { method: local.method, path: local.path.trim() };
      if (local.method === "POST" || local.method === "PUT") {
        const bj = parseJson(local.bodyText);
        if (bj !== undefined) params.body = bj;
      }
      if (local.varName.trim()) params.varName = local.varName.trim();
      break;
    }
    case "js":
      params = { code: local.code.trim(), varName: local.varName.trim() };
      break;
  }
  const next: ActionStep = {
    id: props.step.id || crypto.randomUUID(),
    kind,
    params,
  };
  if (["condition", "loop", "parallel", "tryCatch", "confirm"].includes(kind)) {
    next.then = props.step.then ?? [];
    next.else = props.step.else ?? [];
    next.catch = props.step.catch ?? [];
  }
  emit("update", next);
}

function onThen(steps: ActionStep[]) {
  emit("update", { ...props.step, then: steps });
}
function onElse(steps: ActionStep[]) {
  emit("update", { ...props.step, else: steps });
}
function onCatch(steps: ActionStep[]) {
  emit("update", { ...props.step, catch: steps });
}
</script>

<style scoped>
.wp-step {
  border: 1px solid var(--el-border-color);
  border-radius: 4px;
  padding: 6px;
  margin-bottom: 6px;
  background: var(--el-fill-color-light);
}
.wp-step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.wp-step-index {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-step-ops {
  margin-left: auto;
  display: flex;
}
.wp-step-body {
  font-size: 13px;
}
.wp-step-row {
  display: flex;
  gap: 6px;
  margin-bottom: 4px;
}
.wp-step-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.6;
}
.wp-cond {
  display: flex;
  gap: 8px;
}
.wp-cond-col {
  flex: 1;
}
.wp-cond-title {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: 4px 0;
}
</style>
