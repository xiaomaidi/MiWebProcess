<template>
  <div class="wp-ctl">
    <el-input
      v-if="kind === 'text'"
      :model-value="draft === undefined || draft === null ? '' : String(draft)"
      @update:model-value="onText"
      @change="commit"
    />

    <el-input
      v-else-if="kind === 'textarea' || kind === 'code' || kind === 'expression'"
      type="textarea"
      :rows="kind === 'code' ? 6 : 3"
      :class="{ 'wp-mono': kind === 'code' || kind === 'expression' }"
      :model-value="draft === undefined || draft === null ? '' : String(draft)"
      :placeholder="kind === 'expression' ? '表达式，如 user.role === \'admin\' 或 {{user.name}}' : ''"
      @update:model-value="onText"
      @change="commit"
    />

    <el-color-picker
      v-else-if="kind === 'color'"
      :model-value="draft || undefined"
      show-alpha
      @change="(v: string | null) => commit(v || '')"
    />

    <el-input-number
      v-else-if="kind === 'number'"
      :model-value="draft === undefined || draft === null || draft === '' ? undefined : Number(draft)"
      :min="schema?.minimum"
      :max="schema?.maximum"
      :step="schema?.type === 'number' && schema?.multipleOf ? schema.multipleOf : 1"
      controls-position="right"
      style="width: 100%"
      @change="(v: number | undefined) => commit(v === null || v === undefined ? '' : Number(v))"
    />

    <el-slider
      v-else-if="kind === 'slider'"
      :model-value="Number(draft) || 0"
      :min="schema?.minimum ?? 0"
      :max="schema?.maximum ?? 100"
      :step="schema?.multipleOf ?? 1"
      show-input
      @change="(v: number | number[]) => commit(Array.isArray(v) ? v[0] : v)"
    />

    <el-switch
      v-else-if="kind === 'switch'"
      :model-value="draft === true"
      @change="(v: any) => commit(Boolean(v))"
    />

    <el-date-picker
      v-else-if="kind === 'date'"
      :model-value="draft || undefined"
      type="datetime"
      value-format="YYYY-MM-DD HH:mm:ss"
      style="width: 100%"
      @update:model-value="(v: any) => commit(v || '')"
    />

    <el-select
      v-else-if="kind === 'select'"
      :model-value="draft"
      style="width: 100%"
      clearable
      @change="(v: any) => commit(v)"
    >
      <el-option v-for="o in options" :key="String(o.value)" :label="o.label" :value="o.value" />
    </el-select>

    <el-select
      v-else-if="kind === 'model'"
      :model-value="draft === '' || draft === undefined ? undefined : Number(draft)"
      style="width: 100%"
      clearable
      filterable
      placeholder="选择数据模型"
      @change="(v: any) => commit(v)"
    >
      <el-option v-for="o in modelOptions" :key="String(o.value)" :label="o.label" :value="o.value" />
    </el-select>

    <div v-else-if="kind === 'tableColumns'" class="wp-columns-editor">
      <div v-for="(col, i) in columnRows" :key="i" class="wp-column-row">
        <el-input v-model="col.key" size="small" placeholder="字段 key" style="width: 28%" @change="commitColumns" />
        <el-input v-model="col.label" size="small" placeholder="标题" style="width: 28%" @change="commitColumns" />
        <el-select v-model="col.cellType" size="small" style="width: 110px" clearable placeholder="text" @change="commitColumns">
          <el-option v-for="t in cellTypes" :key="t" :label="t" :value="t" />
        </el-select>
        <el-input v-model="col.width" size="small" placeholder="宽" style="width: 58px" @change="commitColumns" />
        <el-button size="small" text type="danger" @click="removeColumn(i)">×</el-button>
      </div>
      <el-button size="small" @click="addColumn">+ 添加列</el-button>
    </div>

    <div v-else-if="kind === 'icon'" class="wp-icon-editor">
      <el-input v-model="draft" size="small" placeholder="Element Plus 图标名，如 Star" @change="commit" />
      <component :is="iconComp" v-if="iconComp" class="wp-icon-preview" />
    </div>

    <div v-else-if="kind === 'image'" class="wp-image-editor">
      <el-input v-model="draft" size="small" placeholder="图片 URL" @change="commit" />
      <img v-if="draft" :src="draft" class="wp-image-preview" alt="" />
    </div>

    <el-input
      v-else
      type="textarea"
      :rows="4"
      :class="{ 'wp-mono': true }"
      :model-value="draft"
      placeholder="JSON"
      @update:model-value="(v: string) => (draft = v)"
      @change="commitJson"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { getElementIcon } from "@/engine/element-components";
import type { ComponentPropSchema } from "@/types";

type Kind =
  | "text"
  | "textarea"
  | "color"
  | "number"
  | "switch"
  | "select"
  | "json"
  | "date"
  | "slider"
  | "code"
  | "expression"
  | "tableColumns"
  | "icon"
  | "image"
  | "model";

const props = defineProps<{
  modelValue: any;
  kind: Kind;
  options?: { label: string; value: any }[];
  modelOptions?: { label: string; value: any }[];
  schema?: ComponentPropSchema;
}>();
const emit = defineEmits<{ (e: "commit", v: any): void }>();

const draft = ref<any>(clone(props.modelValue));

const columnRows = ref<Record<string, any>[]>(Array.isArray(props.modelValue) ? props.modelValue.map((x) => ({ ...x })) : []);
const cellTypes = ["text", "tag", "button", "link", "image", "progress", "actions", "component"];

function clone(v: any): any {
  return v === undefined ? "" : typeof v === "object" ? JSON.stringify(v, null, 2) : v;
}

function normalize(v: any): string {
  if (props.kind === "json") {
    let t: string;
    if (typeof v === "string") t = v.trim();
    else if (v === undefined || v === null) t = "";
    else t = JSON.stringify(v);
    if (!t) return "";
    try {
      return JSON.stringify(JSON.parse(t));
    } catch {
      return `__invalid__${t}`;
    }
  }
  return v === undefined || v === null ? "" : String(v);
}

watch(
  () => props.modelValue,
  (v) => {
    const nv = normalize(v);
    const dv = normalize(draft.value);
    if (nv !== dv && !(nv.startsWith("__invalid__") || dv.startsWith("__invalid__"))) {
      draft.value = clone(v);
    }
    if (props.kind === "tableColumns") {
      columnRows.value = Array.isArray(v) ? v.map((x: any) => ({ ...x })) : [];
    }
  },
  { immediate: true }
);

const iconComp = computed(() => getElementIcon(String(draft.value || "")));

function onText(v: string) {
  draft.value = v;
}

function commit(v?: any) {
  if (v !== undefined) draft.value = v;
  if (props.kind === "json") {
    commitJson();
    return;
  }
  let out: any = draft.value;
  if (out === "") out = props.kind === "number" || props.kind === "slider" ? undefined : "";
  emit("commit", out);
}

function commitJson() {
  const t = (draft.value ?? "").trim();
  let v: any = undefined;
  if (t) {
    try {
      v = JSON.parse(t);
    } catch {
      ElMessage.error("JSON 格式不正确，未应用");
      return;
    }
  }
  draft.value = v === undefined ? "" : JSON.stringify(v, null, 2);
  emit("commit", v);
}

function addColumn() {
  columnRows.value.push({ key: `field${columnRows.value.length + 1}`, label: "新列" });
  commitColumns();
}
function removeColumn(i: number) {
  columnRows.value.splice(i, 1);
  commitColumns();
}
function commitColumns() {
  emit("commit", columnRows.value.map((c) => ({ ...c })));
}
</script>

<style scoped>
.wp-mono :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
.wp-columns-editor {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 6px;
}
.wp-column-row {
  display: flex;
  gap: 4px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.wp-icon-editor,
.wp-image-editor {
  display: flex;
  align-items: center;
  gap: 6px;
}
.wp-icon-preview {
  width: 20px;
  height: 20px;
}
.wp-image-preview {
  width: 40px;
  height: 30px;
  object-fit: cover;
  border-radius: 3px;
  border: 1px solid var(--el-border-color-lighter);
}
</style>
