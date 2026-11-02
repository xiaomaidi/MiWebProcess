<template>
  <div class="wp-binding">
    <el-form label-position="top" size="small">
      <el-form-item label="来源 source">
        <el-select v-model="form.source" style="width: 100%" @change="onSourceChange">
          <el-option label="变量 variable" value="variable" />
          <el-option label="数据源 datasource" value="datasource" />
          <el-option label="数据模型 model" value="model" />
          <el-option label="表单 form" value="form" />
        </el-select>
      </el-form-item>
      <el-form-item label="引用 ref">
        <el-select
          v-if="form.source === 'datasource'"
          v-model="form.ref"
          style="width: 100%"
          placeholder="选择数据源"
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
          style="width: 100%"
          placeholder="选择数据模型"
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
          style="width: 100%"
          filterable
          placeholder="选择变量 key"
        >
          <el-option v-for="k in variableKeys" :key="k" :label="k" :value="k" />
        </el-select>
        <el-input v-else v-model="form.ref" placeholder="表单引用（如 formId 或字段名）" />
      </el-form-item>
      <el-form-item label="字段 field（点路径，可选）">
        <el-input v-model="form.field" placeholder="如 data[*].name；留空取整体" />
      </el-form-item>
      <el-form-item v-if="showLoopVar" label="循环变量 loopVar（可选）">
        <el-input v-model="form.loopVar" placeholder="循环时每个元素注入作用域的名字，如 item" />
      </el-form-item>
      <el-form-item label="默认值 defaultValue（JSON，可选）">
        <el-input v-model="form.defaultText" placeholder='如 null、""、[1,2,3]；留空表示无' />
      </el-form-item>
      <el-form-item label="变换 transform（表达式，可选）">
        <el-input v-model="form.transform" placeholder="如 value.length；value 为解析结果" />
      </el-form-item>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { reactive, watch } from "vue";
import type { DataBinding, DataModelInfo, DataSourceDef } from "@/types";

const props = defineProps<{
  modelValue: DataBinding | null | undefined;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
  variableKeys: string[];
  showLoopVar?: boolean;
}>();
const emit = defineEmits<{ (e: "update", v: DataBinding): void }>();

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
  form.defaultText =
    value?.defaultValue === undefined ? "" : typeof value.defaultValue === "string" ? value.defaultValue : JSON.stringify(value.defaultValue);
  form.transform = value?.transform ?? "";
}

watch(
  () => props.modelValue,
  (v) => syncFrom(v),
  { immediate: true }
);

function onSourceChange() {
  // 切换来源时重置不兼容的 ref
  if (form.source === "datasource" && !form.ref.startsWith("ds_")) {
    form.ref = props.datasources[0] ? `ds_${props.datasources[0].id}` : "";
  } else if (form.source === "model" && !form.ref.startsWith("model_")) {
    form.ref = props.models[0] ? `model_${props.models[0].id}` : "";
  } else if (form.source === "variable" && form.ref && !props.variableKeys.includes(form.ref)) {
    form.ref = "";
  } else if (form.source === "form" && form.ref.startsWith("ds_") || form.source === "form" && form.ref.startsWith("model_")) {
    form.ref = "";
  }
}

function apply() {
  let defaultValue: any = undefined;
  const t = form.defaultText.trim();
  if (t) {
    try {
      defaultValue = JSON.parse(t);
    } catch {
      defaultValue = t; // 非 JSON 时按字面量字符串
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

// 任一字段变化即向外提交
watch(form, apply, { deep: true });
</script>

<style scoped>
.wp-binding {
  font-size: 13px;
}
</style>
