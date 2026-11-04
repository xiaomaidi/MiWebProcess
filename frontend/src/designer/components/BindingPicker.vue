<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="860px"
    append-to-body
    class="wp-bpick-dialog"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="wp-bpick">
      <div v-if="targetLabel || expectedType" class="wp-bpick-target">
        <span class="k">目标属性</span>
        <strong>{{ targetLabel || "未命名属性" }}</strong>
        <el-tag v-if="expectedType" size="small" effect="plain">期望类型 {{ expectedType }}</el-tag>
        <span class="k">选择数据后写入该属性，不改动其他属性。</span>
      </div>

      <div class="wp-bpick-sources">
        <el-radio-group :model-value="source" size="small" @change="onSourcePick">
          <el-radio-button v-for="opt in sourceOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </el-radio-button>
        </el-radio-group>
        <el-input v-model="search" size="small" clearable placeholder="搜索来源或字段" class="wp-bpick-search" />
      </div>

      <div class="wp-bpick-body">
        <aside class="wp-bpick-refs">
          <div class="wp-bpick-col-title">{{ SOURCE_LABELS[source] }}（{{ filteredRefs.length }}）</div>
          <el-scrollbar height="246px">
            <button
              v-if="orphanRef"
              class="wp-bpick-ref wp-bpick-ref-orphan"
              :class="{ active: refKey === orphanRef }"
              type="button"
              @click="pickRef(orphanRef)"
            >
              <span class="name">{{ orphanRef }}</span>
              <span class="sub">当前引用未在列表中找到</span>
            </button>
            <button
              v-for="opt in filteredRefs"
              :key="opt.value"
              type="button"
              class="wp-bpick-ref"
              :class="{ active: opt.value === refKey }"
              @click="pickRef(opt.value)"
            >
              <span class="name">{{ opt.label }}</span>
              <span class="sub">{{ opt.sub || opt.value }}</span>
              <span v-if="opt.preview" class="preview" :title="opt.preview">{{ opt.preview }}</span>
            </button>
            <el-empty v-if="!filteredRefs.length && !orphanRef" :description="emptyRefText" :image-size="46" />
          </el-scrollbar>
          <el-button
            v-if="canPreview"
            size="small"
            plain
            class="wp-bpick-preview-btn"
            :loading="previewLoading"
            @click="loadPreview"
          >
            {{ previewLoaded ? "重新预览数据" : "预览数据" }}
          </el-button>
        </aside>

        <section class="wp-bpick-fields">
          <div class="wp-bpick-col-title">
            <span>可选字段 / 数据路径</span>
            <el-radio-group v-if="hasArrayShape" v-model="arrayAccess" size="small" class="wp-bpick-range">
              <el-radio-button value="*">全部行 [*]</el-radio-button>
              <el-radio-button value="0">首行 [0]</el-radio-button>
            </el-radio-group>
          </div>

          <div class="wp-bpick-custom">
            <el-input
              v-model="field"
              size="small"
              clearable
              placeholder="也可直接输入字段路径，如 data.list、results[*].name"
            />
          </div>

          <div v-if="!refKey" class="wp-bpick-state">请先在左侧选择页面变量、数据源或数据模型。</div>
          <div v-else-if="previewLoading" class="wp-bpick-state">
            <el-icon class="is-loading"><Loading /></el-icon>
            正在读取数据并解析字段…
          </div>
          <el-alert v-else-if="previewError" type="error" :closable="false" show-icon class="wp-bpick-error">
            <template #title>预览失败：{{ previewError }}</template>
            <el-button size="small" @click="loadPreview">重试</el-button>
          </el-alert>
          <div v-else-if="!filteredFields.length" class="wp-bpick-state">
            <p>{{ fieldsEmptyText }}</p>
            <el-button v-if="canPreview" size="small" type="primary" plain :loading="previewLoading" @click="loadPreview">
              预览数据以生成字段
            </el-button>
          </div>
          <el-scrollbar v-else height="246px">
            <button
              v-for="f in filteredFields"
              :key="f.field || '__root__'"
              type="button"
              class="wp-bpick-field"
              :class="{ active: f.field === field }"
              @click="pickField(f)"
            >
              <span class="path">{{ f.label }}</span>
              <el-tag size="small" effect="plain" class="wp-bpick-type">{{ kindTag(f.type) }}</el-tag>
              <span class="sample" :title="f.sample">{{ f.sample }}</span>
            </button>
          </el-scrollbar>
        </section>
      </div>

      <div class="wp-bpick-preview">
        <div class="wp-bpick-preview-head">
          <span class="title">当前选择</span>
          <el-tag size="small" type="info" effect="plain">{{ summary }}</el-tag>
          <el-tag v-if="previewLoaded" size="small" type="success" effect="plain">已预览数据</el-tag>
        </div>
        <div class="wp-bpick-preview-row">
          <span class="k">表达式</span>
          <code class="v mono">{{ displayedExpression }}</code>
          <el-button size="small" text type="primary" @click="copyExpression">复制</el-button>
        </div>
        <div class="wp-bpick-preview-row">
          <span class="k">设计时预览</span>
          <span class="v wp-bpick-preview-value">{{ selectedPreviewText }}</span>
        </div>
        <div v-if="selectedPreviewHint" class="wp-bpick-hint">{{ selectedPreviewHint }}</div>
        <el-alert v-if="compatText" :title="compatText" type="warning" :closable="false" show-icon class="wp-bpick-warn" />
        <div v-if="allowExpression" class="wp-bpick-mode">
          <span class="k">&#20889;&#20837;&#26041;&#24335;</span>
          <el-radio-group v-model="mode" size="small">
            <el-radio-button value="binding">&#32467;&#26500;&#21270;&#32465;&#23450;</el-radio-button>
            <el-radio-button value="expression">&#27169;&#26495;&#34920;&#36798;&#24335;</el-radio-button>
          </el-radio-group>
          <span class="wp-bpick-mode-hint">
            {{ mode === "binding" ? "\u4fdd\u7559\u7ed3\u6784\u5316\u7ed1\u5b9a\u4e0e\u9ed8\u8ba4\u503c" : "\u5199\u5165\u8868\u8fbe\u5f0f\u5b57\u7b26\u4e32\uff0c\u517c\u5bb9\u73b0\u6709\u6a21\u677f\u8bed\u6cd5" }}
          </span>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :disabled="!canConfirm" @click="confirm">
        {{ mode === "expression" ? "插入表达式" : "插入绑定" }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { Loading } from "@element-plus/icons-vue";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import type { DataBinding, DataModelInfo, DataSourceDef } from "@/types";
import { getPathValue } from "@/utils";
import {
  SOURCE_LABELS,
  bindingExpression,
  bindingSummary,
  compatibilityWarning,
  datasourceHint,
  findDatasource,
  findModel,
  formatValue,
  kindOfModelField,
  responseMapFields,
  shapeLabel,
  staticDatasourceData,
  valueKind,
  valueKindLabel,
  type BindingPickPayload,
  type BindingRefOption,
  type BindingSource,
  type ValueKind,
} from "../utils/bindingSources";

interface PickerField {
  field: string;
  label: string;
  type: ValueKind;
  sample: string;
  description?: string;
}

interface PreviewState {
  loading: boolean;
  loaded: boolean;
  error: string;
  data: any;
}

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    title?: string;
    /** 已有绑定（编辑时回填）。 */
    binding?: DataBinding | null;
    datasources: DataSourceDef[];
    models: DataModelInfo[];
    variables?: Record<string, { value: any; scope?: string }>;
    /** 目标属性 schema.type，用于类型兼容提示。 */
    expectedType?: string;
    /** 目标属性标题，显示在弹窗顶部。 */
    targetLabel?: string;
    /** 是否允许写入 {{...}} 模板表达式（默认允许）。 */
    allowExpression?: boolean;
  }>(),
  {
    title: "可视化选择数据",
    binding: null,
    variables: () => ({}),
    expectedType: "",
    targetLabel: "",
    allowExpression: true,
  }
);
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "select", payload: BindingPickPayload): void;
}>();

const schemaStore = useSchemaStore();
const source = ref<BindingSource>("variable");
const refKey = ref("");
const field = ref("");
const search = ref("");
const mode = ref<"binding" | "expression">("binding");
const arrayAccess = ref<"*" | "0">("*");
const previews = reactive<Record<string, PreviewState>>({});

const sourceOptions = computed<{ value: BindingSource; label: string }[]>(() => [
  { value: "variable", label: `页面变量 (${Object.keys(props.variables ?? {}).length})` },
  { value: "datasource", label: `数据源 (${props.datasources.length})` },
  { value: "model", label: `数据模型 (${props.models.length})` },
  { value: "form", label: "表单" },
]);

const formRefs = computed(() => {
  const nodes = schemaStore.schema?.nodes ?? {};
  return Object.values(nodes)
    .filter((n) => /form/i.test(n.type))
    .map((n) => ({
      id: n.id,
      label: String(n.props?.label || n.props?.title || n.type),
    }));
});

const refOptions = computed<BindingRefOption[]>(() => {
  if (source.value === "variable") {
    return Object.entries(props.variables ?? {}).map(([key, def]) => ({
      value: key,
      label: key,
      sub: def?.scope === "global" ? "全局变量" : "页面变量",
      preview: formatValue(def?.value, 44),
      type: valueKind(def?.value),
    }));
  }
  if (source.value === "datasource") {
    return props.datasources.map((ds) => ({
      value: `ds_${ds.id}`,
      label: ds.name,
      sub: `#${ds.id} · ${ds.type}`,
      preview: datasourceHint(ds),
    }));
  }
  if (source.value === "model") {
    return props.models.map((m) => ({
      value: `model_${m.id}`,
      label: m.name,
      sub: `#${m.id} · ${(m.fields ?? []).length} 个字段`,
      preview: (m.fields ?? []).map((f) => f.name).slice(0, 4).join("、"),
    }));
  }
  return formRefs.value.map((n) => ({
    value: `form_${n.id}`,
    label: n.label,
    sub: n.id,
    preview: "表单值（运行时）",
  }));
});

const filteredRefs = computed(() => {
  const q = search.value.trim().toLowerCase();
  if (!q) return refOptions.value;
  return refOptions.value.filter((o) => `${o.label} ${o.sub ?? ""} ${o.preview ?? ""}`.toLowerCase().includes(q));
});

const orphanRef = computed(() => (refKey.value && !refOptions.value.some((o) => o.value === refKey.value) ? refKey.value : ""));

const emptyRefText = computed(() => {
  if (source.value === "variable") return "暂无页面变量，可在左侧变量面板添加";
  if (source.value === "datasource") return "暂无数据源，请先在数据源面板创建";
  if (source.value === "model") return "暂无数据模型";
  return "当前页面没有表单节点";
});

const previewKey = computed(() => `${source.value}:${refKey.value}`);
const previewState = computed<PreviewState | undefined>(() => previews[previewKey.value]);
const previewLoading = computed(() => !!previewState.value?.loading);
const previewError = computed(() => previewState.value?.error ?? "");
const previewLoaded = computed(() => !!previewState.value?.loaded);
/** 设计时预览：模型与只读数据源可安全预览；WebSocket / 非 GET REST 不自动执行。 */
const canPreview = computed(() => {
  if (!refKey.value) return false;
  if (source.value === "model") return true;
  if (source.value !== "datasource") return false;
  const ds = findDatasource(props.datasources, refKey.value);
  if (!ds) return false;
  const type = String(ds.type ?? "").toLowerCase();
  if (type === "websocket") return false;
  if (type === "rest") {
    const cfg = (ds.config ?? {}) as Record<string, any>;
    return String(cfg.method || "GET").toUpperCase() === "GET";
  }
  return true;
});

const currentDatasource = computed(() => (source.value === "datasource" ? findDatasource(props.datasources, refKey.value) : undefined));
const currentModel = computed(() => (source.value === "model" ? findModel(props.models, refKey.value) : undefined));

/** 可用于生成字段的设计时基础数据。 */
const baseData = computed<{ value: any; hasValue: boolean; note: string }>(() => {
  if (!refKey.value) return { value: undefined, hasValue: false, note: "请选择来源" };
  if (source.value === "variable") {
    if (!props.variables || !Object.prototype.hasOwnProperty.call(props.variables, refKey.value)) {
      return { value: undefined, hasValue: false, note: "变量未定义" };
    }
    return { value: props.variables[refKey.value]?.value, hasValue: true, note: "变量当前值" };
  }
  if (source.value === "datasource") {
    if (!currentDatasource.value) return { value: undefined, hasValue: false, note: "数据源未找到" };
    if (previewState.value?.loaded) return { value: previewState.value.data, hasValue: true, note: "预览数据" };
    const stat = staticDatasourceData(currentDatasource.value);
    if (stat !== undefined) return { value: stat, hasValue: true, note: "静态数据" };
    return { value: undefined, hasValue: false, note: "点击「预览数据」获取字段" };
  }
  if (source.value === "model") {
    if (!currentModel.value) return { value: undefined, hasValue: false, note: "数据模型未找到" };
    if (previewState.value?.loaded) return { value: previewState.value.data, hasValue: true, note: "预览数据" };
    return { value: undefined, hasValue: false, note: "字段形状来自模型定义" };
  }
  return { value: undefined, hasValue: false, note: "运行时取表单值" };
});

function buildValueFields(
  value: any,
  baseField: string,
  labelBase: string,
  access: "*" | "0",
  depth: number,
  out: PickerField[]
): PickerField[] {
  if (out.length >= 160 || depth > 4) return out;
  if (Array.isArray(value)) {
    const item = value[0];
    const token = access === "*" ? "[*]" : "[0]";
    const arrField = `${baseField}${token}`;
    if (item && typeof item === "object" && !Array.isArray(item)) {
      for (const [key, child] of Object.entries(item)) {
        const childField = `${arrField}.${key}`;
        const childLabel = `${labelBase}${token}.${key}`.replace(/^\./, "");
        const res = getPathValue(value, childField);
        out.push({
          field: childField,
          label: childLabel,
          type: valueKind(res.value),
          sample: formatValue(res.value, 44),
        });
        if (out.length >= 160) break;
        if (child && typeof child === "object") buildValueFields(child, childField, childLabel, access, depth + 1, out);
      }
    } else if (item !== undefined) {
      out.push({ field: arrField, label: `${labelBase}${token}`, type: valueKind(item), sample: formatValue(value, 44) });
    }
    return out;
  }
  if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      if (out.length >= 160) break;
      const childField = baseField ? `${baseField}.${key}` : key;
      const childLabel = labelBase ? `${labelBase}.${key}` : key;
      out.push({ field: childField, label: childLabel, type: valueKind(child), sample: formatValue(child, 44) });
      if (child && typeof child === "object") buildValueFields(child, childField, childLabel, access, depth + 1, out);
    }
  }
  return out;
}

function buildModelFields(model: DataModelInfo, access: "*" | "0"): PickerField[] {
  const prefix = `results${access === "*" ? "[*]" : "[0]"}`;
  const previewData = previewState.value?.loaded ? previewState.value.data : undefined;
  const out: PickerField[] = [
    { field: "", label: "整个分页结果", type: "object", sample: "{ count, results }" },
    {
      field: "count",
      label: "记录总数 count",
      type: "number",
      sample: previewData ? formatValue(previewData.count, 32) : "number",
    },
    {
      field: "results",
      label: "记录列表 results",
      type: "array",
      sample: previewData?.results ? shapeLabel(previewData.results) : "array",
    },
  ];
  for (const f of model.fields ?? []) {
    const fieldPath = `${prefix}.${f.name}`;
    const res = previewData ? getPathValue(previewData, fieldPath).value : undefined;
    out.push({
      field: fieldPath,
      label: `${f.label || f.name}（${f.name}）`,
      type: kindOfModelField(f.type),
      sample: previewData ? formatValue(res, 44) : `${f.type}${f.required ? " · 必填" : ""}`,
      description: f.description,
    });
    if (out.length >= 160) break;
  }
  return out;
}

const fields = computed<PickerField[]>(() => {
  if (!refKey.value) return [];
  if (source.value === "form") return [];
  if (source.value === "model") {
    if (!currentModel.value) return [];
    return buildModelFields(currentModel.value, arrayAccess.value);
  }
  if (baseData.value.hasValue) {
    const value = baseData.value.value;
    const out: PickerField[] = [{ field: "", label: "整个结果", type: valueKind(value), sample: formatValue(value, 44) }];
    if (value && typeof value === "object") buildValueFields(value, "", "", arrayAccess.value, 0, out);
    return out;
  }
  if (source.value === "datasource" && currentDatasource.value) {
    const keys = responseMapFields(currentDatasource.value);
    return keys.map((key) => ({ field: key, label: `映射字段 ${key}`, type: "unknown", sample: "response_map" }));
  }
  return [];
});

const filteredFields = computed(() => {
  const q = search.value.trim().toLowerCase();
  if (!q) return fields.value;
  return fields.value.filter((f) => `${f.label} ${f.field} ${f.type} ${f.sample}`.toLowerCase().includes(q));
});

const hasArrayShape = computed(() => {
  if (source.value === "model") return true;
  const value = baseData.value.value;
  if (Array.isArray(value)) return true;
  if (value && typeof value === "object" && Array.isArray((value as any).results)) return true;
  return fields.value.some((f) => f.field.includes("[*]"));
});

const fieldsEmptyText = computed(() => {
  if (source.value === "variable") return "该变量没有可展开的字段，可直接绑定整个变量。";
  if (source.value === "datasource") {
    return canPreview.value
      ? "该数据源没有可静态解析的字段，请点击下方按钮预览数据。"
      : "该数据源不支持设计时预览（WebSocket / 非 GET REST），可直接填写字段路径。";
  }
  if (source.value === "model") return "该数据模型暂无字段定义。";
  return "表单值需在运行时从表单节点获取，可直接填写引用。";
});

function defaultRef(src: BindingSource): string {
  if (src === "variable") return Object.keys(props.variables ?? {})[0] ?? "";
  if (src === "datasource") return props.datasources[0] ? `ds_${props.datasources[0].id}` : "";
  if (src === "model") return props.models[0] ? `model_${props.models[0].id}` : "";
  return formRefs.value[0] ? `form_${formRefs.value[0].id}` : "";
}

function init() {
  const b = props.binding;
  const initialSource: BindingSource = b?.source
    ? b.source
    : Object.keys(props.variables ?? {}).length
      ? "variable"
      : props.datasources.length
        ? "datasource"
        : props.models.length
          ? "model"
          : "variable";
  source.value = initialSource;
  refKey.value = b?.ref ?? defaultRef(source.value);
  field.value = b?.field ?? "";
  mode.value = "binding";
  search.value = "";
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) init();
  },
  { immediate: true }
);

function onSourcePick(value: string | number | boolean) {
  source.value = String(value) as BindingSource;
  refKey.value = defaultRef(source.value);
  field.value = "";
  search.value = "";
}

function pickRef(value: string) {
  refKey.value = value;
  field.value = "";
}

function pickField(f: PickerField) {
  field.value = f.field;
}

watch(arrayAccess, (next) => {
  if (!field.value) return;
  field.value = field.value.replace(/\[\*\]|\[\d+\]/, next === "*" ? "[*]" : "[0]");
});

const selectedRow = computed<PickerField | undefined>(() => {
  const found = fields.value.find((f) => f.field === field.value);
  if (found) return found;
  if (field.value) return { field: field.value, label: field.value, type: "unknown", sample: "自定义路径" };
  return fields.value[0];
});

const selectedValue = computed<{ available: boolean; value?: any; kind: ValueKind | "any"; text: string }>(() => {
  if (source.value === "form") return { available: false, kind: "any", text: "运行时取表单值" };
  if (baseData.value.hasValue) {
    if (!field.value) {
      const v = baseData.value.value;
      return { available: true, value: v, kind: valueKind(v), text: formatValue(v, 180) };
    }
    const res = getPathValue(baseData.value.value, field.value);
    if (res.found) return { available: true, value: res.value, kind: valueKind(res.value), text: formatValue(res.value, 180) };
    return { available: false, kind: selectedRow.value?.type ?? "unknown", text: "未命中该字段" };
  }
  if (selectedRow.value) {
    return {
      available: false,
      kind: selectedRow.value.type,
      text: `${valueKindLabel(selectedRow.value.type)} · ${selectedRow.value.sample}`,
    };
  }
  return { available: false, kind: "unknown", text: "请选择字段" };
});

const currentBinding = computed<DataBinding>(() => ({
  source: source.value,
  ref: refKey.value,
  ...(field.value ? { field: field.value } : {}),
}));

const summary = computed(() =>
  bindingSummary(currentBinding.value, { datasources: props.datasources, models: props.models, variables: props.variables })
);

const expression = computed(() => bindingExpression(currentBinding.value));
const displayedExpression = computed(() => (mode.value === "expression" ? `{{${expression.value}}}` : expression.value));

const selectedPreviewText = computed(() => selectedValue.value.text);
const selectedPreviewHint = computed(() => {
  if (selectedValue.value.available) return "";
  if (source.value === "model") return "模型字段形状来自字段定义；点击「预览数据」可拉取前 10 条记录做真实预览。";
  if (source.value === "datasource") return baseData.value.note;
  if (source.value === "form") return "表单值仅在运行时可用，设计器不做真实取值。";
  return baseData.value.note;
});

const compatText = computed(() => compatibilityWarning(props.expectedType, selectedValue.value.kind));

const canConfirm = computed(() => !!refKey.value);

function kindTag(type: ValueKind): string {
  return valueKindLabel(type);
}

function loadPreview() {
  if (!refKey.value || !canPreview.value) return;
  const key = previewKey.value;
  const id = Number(refKey.value.replace(/^(ds|model)_/, ""));
  previews[key] = { loading: true, loaded: false, error: "", data: undefined };
  const run = async () => {
    try {
      let data: any;
      if (source.value === "datasource") {
        const res = await api.post<{ data: unknown }>(`/datasources/${id}/query/`, { params: {} }, { silent: true });
        data = res?.data;
      } else {
        data = await api.get(`/models/${id}/records/?page=1&page_size=10`, { silent: true });
      }
      previews[key] = { loading: false, loaded: true, error: "", data };
      if (data === undefined || data === null || (Array.isArray(data) && data.length === 0)) {
        ElMessage.info("预览成功，但结果为空");
      }
    } catch (e: any) {
      previews[key] = { loading: false, loaded: false, error: e?.message || "请求失败，请稍后重试", data: undefined };
    }
  };
  void run();
}

async function copyExpression() {
  const text = displayedExpression.value;
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      ElMessage.success("表达式已复制");
      return;
    }
  } catch {
    /* 剪贴板不可用时退化为提示 */
  }
  ElMessage.info(`表达式：${text}`);
}

function confirm() {
  if (!refKey.value) {
    ElMessage.warning("请先选择页面变量、数据源或数据模型");
    return;
  }
  const next: DataBinding = {
    ...(props.binding ?? {}),
    source: source.value,
    ref: refKey.value,
  };
  if (field.value) next.field = field.value;
  else delete next.field;
  emit("select", {
    binding: next,
    expression: bindingExpression(next),
    mode: props.allowExpression ? mode.value : "binding",
  });
  emit("update:modelValue", false);
}
</script>

<style scoped>
.wp-bpick {
  font-size: 13px;
}
.wp-bpick-target {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
  padding: 7px 10px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}
.wp-bpick-target .k {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-bpick-sources {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.wp-bpick-search {
  width: 200px;
  flex: none;
}
.wp-bpick-body {
  display: flex;
  gap: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  overflow: hidden;
}
.wp-bpick-refs {
  width: 248px;
  flex: none;
  border-right: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
  display: flex;
  flex-direction: column;
}
.wp-bpick-col-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
  border-bottom: 1px solid var(--el-border-color-lighter);
  min-height: 26px;
}
.wp-bpick-ref {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  padding: 7px 10px;
  border: none;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: inherit;
}
.wp-bpick-ref:hover,
.wp-bpick-ref.active {
  background: var(--el-color-primary-light-9);
}
.wp-bpick-ref.active {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.wp-bpick-ref .name {
  font-weight: 600;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-bpick-ref .sub {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.wp-bpick-ref .preview {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-bpick-ref-orphan .sub {
  color: var(--el-color-warning);
}
.wp-bpick-preview-btn {
  margin: 6px 8px;
}
.wp-bpick-fields {
  flex: 1;
  min-width: 0;
}
.wp-bpick-range {
  flex: none;
}
.wp-bpick-custom {
  padding: 6px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.wp-bpick-field {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 6px 10px;
  border: none;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: transparent;
  text-align: left;
  cursor: pointer;
  color: inherit;
}
.wp-bpick-field:hover,
.wp-bpick-field.active {
  background: var(--el-color-primary-light-9);
}
.wp-bpick-field.active {
  box-shadow: inset 3px 0 0 var(--el-color-primary);
}
.wp-bpick-field .path {
  min-width: 120px;
  font-weight: 500;
}
.wp-bpick-field .sample {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.wp-bpick-type {
  flex: none;
}
.wp-bpick-state {
  padding: 26px 16px;
  text-align: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.wp-bpick-state p {
  margin: 0;
}
.wp-bpick-error {
  margin: 8px;
}
.wp-bpick-preview {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-light);
}
.wp-bpick-preview-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.wp-bpick-preview-head .title {
  font-weight: 600;
}
.wp-bpick-preview-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
}
.wp-bpick-preview-row .k {
  width: 74px;
  flex: none;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-bpick-preview-row .v {
  min-width: 0;
  overflow-wrap: anywhere;
}
.wp-bpick-preview-value {
  max-height: 54px;
  overflow: auto;
  white-space: pre-wrap;
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.mono {
  font-family: ui-monospace, Consolas, monospace;
  background: var(--el-fill-color-blank);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.wp-bpick-hint {
  margin: 2px 0 0 82px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.5;
}
.wp-bpick-warn {
  margin-top: 6px;
}
.wp-bpick-mode {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color);
}
.wp-bpick-mode .k {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-bpick-mode-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
</style>
