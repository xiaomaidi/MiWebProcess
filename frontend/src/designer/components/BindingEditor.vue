<template>
  <div class="wp-binding">
    <div class="wp-be-head">
      <span v-if="propTitle" class="wp-be-title">{{ propTitle }}</span>
      <el-tag v-if="expectedType" size="small" effect="plain">期望 {{ expectedType }}</el-tag>
      <span class="wp-be-summary" :title="summary">{{ summary }}</span>
    </div>
    <div class="wp-be-current">
      <span class="k">当前表达式</span>
      <code class="wp-be-code">{{ expression }}</code>
      <el-button size="small" type="primary" plain @click="pickerOpen = true">可视化选择</el-button>
    </div>

    <el-form label-position="top" size="small">
      <el-form-item label="来源 source">
        <el-select v-model="form.source" style="width: 100%" @change="onSourceChange">
          <el-option label="变量 variable" value="variable" />
          <el-option label="数据源 datasource" value="datasource" />
          <el-option label="数据模型 model" value="model" />
          <el-option label="表单 form" value="form" />
        </el-select>
        <div class="wp-be-hint">数据源 / 模型 / 变量均可；绑定语法与旧数据完全兼容。</div>
      </el-form-item>

      <el-form-item label="引用 ref">
        <div class="wp-be-row">
          <el-select
            v-if="form.source === 'datasource'"
            v-model="form.ref"
            class="wp-be-grow"
            placeholder="选择数据源"
            filterable
          >
            <el-option
              v-for="ds in datasources"
              :key="ds.id"
              :label="`${ds.name} (#${ds.id})`"
              :value="`ds_${ds.id}`"
            />
          </el-select>
          <el-select
            v-else-if="form.source === 'model'"
            v-model="form.ref"
            class="wp-be-grow"
            placeholder="选择数据模型"
            filterable
          >
            <el-option
              v-for="m in models"
              :key="m.id"
              :label="`${m.name} (#${m.id})`"
              :value="`model_${m.id}`"
            />
          </el-select>
          <el-select
            v-else-if="form.source === 'variable'"
            v-model="form.ref"
            class="wp-be-grow"
            filterable
            placeholder="选择变量 key"
          >
            <el-option v-for="k in variableKeys" :key="k" :label="k" :value="k" />
          </el-select>
          <el-input v-else v-model="form.ref" class="wp-be-grow" placeholder="表单引用（如 formId 或字段名）" />
          <el-button v-if="form.ref" size="small" text type="danger" @click="clearRef">清空</el-button>
        </div>
        <div v-if="form.source === 'variable' && !variableKeys.length" class="wp-be-warn">
          暂无页面变量，可在左侧「变量」面板创建后再绑定。
        </div>
        <div v-if="form.source === 'datasource' && !datasources.length" class="wp-be-warn">暂无数据源。</div>
        <div v-if="form.source === 'model' && !models.length" class="wp-be-warn">暂无数据模型。</div>
      </el-form-item>

      <el-form-item label="字段 field（点路径，可选）">
        <div class="wp-be-row">
          <el-input v-model="form.field" class="wp-be-grow" placeholder="如 data[*].name；留空取整体" />
          <el-button v-if="form.field" size="small" text type="danger" @click="clearField">清空</el-button>
        </div>
        <div class="wp-be-samples">
          <span>示例：</span>
          <el-button link type="primary" size="small" @click="form.field = 'data'">data</el-button>
          <el-button link type="primary" size="small" @click="form.field = 'data.list'">data.list</el-button>
          <el-button link type="primary" size="small" @click="form.field = 'results[*].name'">results[*].name</el-button>
          <el-button link type="primary" size="small" @click="form.field = '[0].id'">[0].id</el-button>
        </div>
      </el-form-item>

      <el-form-item v-if="showLoopVar" label="循环变量 loopVar（可选）">
        <div class="wp-be-row">
          <el-input v-model="form.loopVar" class="wp-be-grow" placeholder="循环时每个元素注入作用域的名字，如 item" />
          <el-button v-if="form.loopVar" size="small" text type="danger" @click="clearLoop">清空</el-button>
        </div>
        <div class="wp-be-hint">列表绑定时子节点可通过 {{ form.loopVar || "item" }}.字段 访问当前元素。</div>
      </el-form-item>

      <el-form-item label="默认值 defaultValue（JSON，可选）">
        <div class="wp-be-row">
          <el-input v-model="form.defaultText" class="wp-be-grow" placeholder='如 null、""、[1,2,3]；留空表示无' />
          <el-button v-if="form.defaultText" size="small" text type="danger" @click="clearDefault">清空</el-button>
        </div>
        <div class="wp-be-samples">
          <span>示例：</span>
          <el-button link type="primary" size="small" @click="form.defaultText = 'null'">null</el-button>
          <el-button link type="primary" size="small" @click="form.defaultText = '[]'">[]</el-button>
          <el-button link type="primary" size="small" @click="form.defaultText = '{}'">{}</el-button>
          <el-button link type="primary" size="small" @click="setEmptyStringDefault">&quot;&quot;</el-button>
        </div>
        <div v-if="defaultJsonState.kind === 'literal'" class="wp-be-warn">
          不是合法 JSON，保存时将按字符串字面量使用。
        </div>
        <div v-else-if="defaultJsonState.kind === 'valid'" class="wp-be-ok">合法 JSON，取数失败时作为兜底值。</div>
      </el-form-item>

      <el-form-item label="变换 transform（表达式，可选）">
        <div class="wp-be-row">
          <el-input v-model="form.transform" class="wp-be-grow" placeholder="如 len(value)；value 为解析结果" />
          <el-button v-if="form.transform" size="small" text type="danger" @click="clearTransform">清空</el-button>
        </div>
        <div class="wp-be-samples">
          <span>示例：</span>
          <el-button link type="primary" size="small" @click="form.transform = 'len(value)'">len(value)</el-button>
          <el-button link type="primary" size="small" @click="form.transform = 'value[0]'">value[0]</el-button>
          <el-button link type="primary" size="small" @click="form.transform = 'value * 100'">value * 100</el-button>
        </div>
        <div v-if="transformCheck && !transformCheck.ok" class="wp-be-invalid">
          表达式无法解析：{{ transformCheck.error || "语法错误" }}
        </div>
        <div v-else-if="form.transform.trim()" class="wp-be-ok">表达式语法有效。</div>
      </el-form-item>
    </el-form>

    <BindingPicker
      v-model="pickerOpen"
      title="为属性选择数据"
      :binding="currentBinding"
      :datasources="datasources"
      :models="models"
      :variables="variables"
      :expected-type="expectedType"
      :target-label="propTitle"
      :allow-expression="false"
      @select="onPick"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { checkExpression } from "@/engine/expr";
import type { DataBinding, DataModelInfo, DataSourceDef } from "@/types";
import { bindingExpression, bindingSummary, type BindingPickPayload } from "../utils/bindingSources";
import BindingPicker from "./BindingPicker.vue";

const props = withDefaults(
  defineProps<{
    modelValue: DataBinding | null | undefined;
    datasources: DataSourceDef[];
    models: DataModelInfo[];
    variableKeys: string[];
    showLoopVar?: boolean;
    /** 属性标题（展示在编辑顶部）。 */
    propTitle?: string;
    /** 目标属性的 schema.type，用于类型提示。 */
    expectedType?: string;
    /** 页面变量定义，供可视化选择器预览当前值。 */
    variables?: Record<string, { value: any; scope?: string }>;
  }>(),
  {
    showLoopVar: false,
    propTitle: "",
    expectedType: "",
    variables: () => ({}),
  }
);
const emit = defineEmits<{ (e: "update", v: DataBinding): void }>();

const pickerOpen = ref(false);
const form = reactive({
  source: "variable" as DataBinding["source"],
  ref: "",
  field: "",
  loopVar: "",
  defaultText: "",
  transform: "",
});

function syncFrom(value: DataBinding | null | undefined) {
  form.source = value?.source ?? "variable";
  form.ref = value?.ref ?? "";
  form.field = value?.field ?? "";
  form.loopVar = value?.loopVar ?? "";
  form.defaultText = value?.defaultValue === undefined ? "" : JSON.stringify(value.defaultValue);
  form.transform = value?.transform ?? "";
}

watch(
  () => props.modelValue,
  (v) => syncFrom(v),
  { immediate: true }
);

const currentBinding = computed<DataBinding>(() => ({
  source: form.source,
  ref: form.ref,
  ...(form.field.trim() ? { field: form.field.trim() } : {}),
  ...(form.loopVar.trim() ? { loopVar: form.loopVar.trim() } : {}),
  ...(form.transform.trim() ? { transform: form.transform.trim() } : {}),
}));

const summary = computed(() =>
  bindingSummary(currentBinding.value, {
    datasources: props.datasources,
    models: props.models,
    variables: props.variables,
  })
);
const expression = computed(() => bindingExpression(currentBinding.value));

const defaultJsonState = computed<{ kind: "empty" | "valid" | "literal"; message: string }>(() => {
  const text = form.defaultText.trim();
  if (!text) return { kind: "empty", message: "" };
  try {
    JSON.parse(text);
    return { kind: "valid", message: "合法 JSON，取数失败时作为兜底值。" };
  } catch {
    return { kind: "literal", message: "不是合法 JSON，保存时将按字符串字面量使用。" };
  }
});

const transformCheck = computed(() => (form.transform.trim() ? checkExpression(form.transform.trim()) : null));

function onSourceChange() {
  // 切换来源时重置不兼容的 ref
  if (form.source === "datasource") {
    if (!/^ds_\d+$/.test(form.ref)) form.ref = props.datasources[0] ? `ds_${props.datasources[0].id}` : "";
  } else if (form.source === "model") {
    if (!/^model_\d+$/.test(form.ref)) form.ref = props.models[0] ? `model_${props.models[0].id}` : "";
  } else if (form.source === "variable") {
    if (form.ref && !props.variableKeys.includes(form.ref)) form.ref = props.variableKeys[0] ?? "";
  } else if (form.source === "form") {
    if (/^(ds|model)_/.test(form.ref)) form.ref = "";
  }
}

function onPick(payload: BindingPickPayload) {
  form.source = payload.binding.source;
  form.ref = payload.binding.ref;
  form.field = payload.binding.field ?? "";
}

function clearRef() {
  form.ref = "";
}
function clearField() {
  form.field = "";
}
function clearLoop() {
  form.loopVar = "";
}
function clearDefault() {
  form.defaultText = "";
}
function setEmptyStringDefault() {
  form.defaultText = JSON.stringify("");
}
function clearTransform() {
  form.transform = "";
}

function apply() {
  let defaultValue: any = undefined;
  const t = form.defaultText.trim();
  if (t) {
    try {
      defaultValue = JSON.parse(t);
    } catch {
      defaultValue = t; // 非 JSON 时按字面量字符串（保持旧行为）
    }
  }
  emit("update", {
    source: form.source,
    ref: form.ref,
    field: form.field.trim() || undefined,
    loopVar: form.loopVar.trim() || undefined,
    transform: form.transform.trim() || undefined,
    defaultValue,
  });
}

// 任一字段变化即向外提交（保持原有即时保存行为）
watch(form, apply, { deep: true });
</script>

<style scoped>
.wp-binding {
  font-size: 13px;
}
.wp-be-head {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
  min-height: 20px;
}
.wp-be-title {
  font-weight: 600;
}
.wp-be-summary {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.wp-be-current {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  margin-bottom: 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.wp-be-current .k {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  flex: none;
}
.wp-be-code {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.wp-be-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}
.wp-be-grow {
  flex: 1;
  min-width: 0;
}
.wp-be-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.5;
  margin-top: 2px;
}
.wp-be-samples {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  margin-top: 2px;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.wp-be-warn {
  color: var(--el-color-warning);
  font-size: 11px;
  line-height: 1.5;
  margin-top: 2px;
}
.wp-be-ok {
  color: var(--el-color-success);
  font-size: 11px;
  line-height: 1.5;
  margin-top: 2px;
}
.wp-be-invalid {
  color: var(--el-color-danger);
  font-size: 11px;
  line-height: 1.5;
  margin-top: 2px;
}
</style>
