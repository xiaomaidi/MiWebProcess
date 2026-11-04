<template>
  <div class="wp-auto-form" v-loading="loading">
    <el-form
      ref="formRef"
      :model="values"
      :rules="rules"
      :label-width="labelWidthValue"
      :label-position="labelPosition"
      :disabled="disabled"
      @submit.prevent="submit"
    >
      <el-row :gutter="16">
        <el-col v-for="field in visibleFields" :key="field.name" :span="spanOf(field)">
          <el-form-item :label="field.label || field.name" :prop="field.name">
            <RichText
              v-if="field.ui === 'richtext' || field.type === 'richtext'"
              v-model="values[field.name]"
              :height="220"
              :placeholder="field.description || `请输入${field.label || field.name}`"
            />
            <GeoPicker v-else-if="field.type === 'geolocation'" v-model="values[field.name]" />
            <SignaturePad v-else-if="field.type === 'signature'" v-model="values[field.name]" />
            <el-input
              v-else-if="['longtext', 'json'].includes(field.type) || field.ui === 'textarea'"
              v-model="values[field.name]"
              type="textarea"
              :rows="field.type === 'json' || field.type === 'geolocation' ? 5 : 3"
              :placeholder="field.placeholder || field.description || `请输入${field.label || field.name}`"
            />
            <el-select
              v-else-if="['select', 'multiselect', 'tags'].includes(field.type)"
              v-model="values[field.name]"
              :multiple="field.type !== 'select'"
              filterable
              clearable
              allow-create
              style="width: 100%"
            >
              <el-option v-for="o in field.options || []" :key="String(o.value)" :label="o.label" :value="o.value" />
            </el-select>
            <el-input-number
              v-else-if="['number', 'integer', 'decimal', 'money', 'percent'].includes(field.type)"
              v-model="values[field.name]"
              :precision="field.precision"
              :min="field.min"
              :max="field.max"
              controls-position="right"
              style="width: 100%"
            />
            <el-rate v-else-if="field.type === 'rating'" v-model="values[field.name]" />
            <el-switch v-else-if="field.type === 'boolean'" v-model="values[field.name]" />
            <el-date-picker
              v-else-if="['date', 'datetime', 'time'].includes(field.type)"
              v-model="values[field.name]"
              :type="field.type === 'datetime' ? 'datetime' : field.type"
              :value-format="field.type === 'date' ? 'YYYY-MM-DD' : field.type === 'time' ? 'HH:mm:ss' : 'YYYY-MM-DD HH:mm:ss'"
              style="width: 100%"
            />
            <el-color-picker v-else-if="field.type === 'color'" v-model="values[field.name]" />
            <RelationSelect
              v-else-if="['reference', 'references'].includes(field.type)"
              v-model="values[field.name]"
              :app-id="appId"
              :ref-model="field.ref_model || ''"
              :multiple="field.type === 'references'"
              :options="field.options || []"
              :ref-display="field.ref_display || ''"
              :placeholder="field.placeholder || field.description || `请选择${field.label || field.name}`"
              :disabled="disabled"
            />
            <AttachmentField
              v-else-if="field.type === 'attachments'"
              v-model="values[field.name]"
              :app-id="appId"
              :accept="field.accept || ''"
              :max="20"
              :disabled="disabled"
            />
            <div v-else-if="['image', 'file'].includes(field.type)" class="wp-upload-field">
              <el-image v-if="field.type === 'image' && values[field.name]" :src="values[field.name]" fit="cover" class="wp-upload-preview" preview-teleported :preview-src-list="[values[field.name]]" />
              <el-link v-if="field.type === 'file' && values[field.name]" :href="values[field.name]" target="_blank" type="primary">查看附件</el-link>
              <el-input v-model="values[field.name]" size="small" placeholder="文件 URL" style="flex: 1" />
              <input :id="'upload-' + field.name" type="file" hidden :accept="field.accept || undefined" @change="onFileChange($event, field)" />
              <el-button size="small" :loading="uploading === field.name" @click="pickFile(field)">上传</el-button>
            </div>
            <el-select
              v-else-if="field.type === 'user'"
              v-model="values[field.name]"
              filterable
              clearable
              style="width: 100%"
            >
              <el-option v-for="u in userOptions" :key="u.id" :label="u.display_name || u.username || `用户 ${u.id}`" :value="u.id" />
            </el-select>
            <el-select
              v-else-if="field.type === 'department'"
              v-model="values[field.name]"
              filterable
              clearable
              style="width: 100%"
            >
              <el-option v-for="d in deptOptions" :key="d.id" :label="d.name || `部门 ${d.id}`" :value="d.id" />
            </el-select>
            <el-input
              v-else-if="['barcode', 'duration'].includes(field.type)"
              v-model="values[field.name]"
              :placeholder="field.type === 'image' || field.type === 'file' ? '文件 URL' : field.placeholder || '请输入'"
              clearable
            />
            <el-input
              v-else
              v-model="values[field.name]"
              :type="field.type === 'password' ? 'password' : 'text'"
              :show-password="field.type === 'password'"
              :disabled="['formula', 'auto_number'].includes(field.type)"
              :placeholder="field.type === 'formula' ? '保存后自动计算' : field.placeholder || field.description || `请输入${field.label || field.name}`"
              clearable
            />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item v-if="captchaQuestion" label="验证码">
        <span class="wp-captcha-question">{{ captchaQuestion }}</span>
        <el-input v-model="captchaAnswer" placeholder="请输入答案" style="width: 140px; margin-left: 10px" />
      </el-form-item>
      <div class="wp-auto-form-actions">
        <el-button v-if="showReset" @click="reset">重置</el-button>
        <el-button type="primary" :loading="saving" @click="submit">{{ submitText }}</el-button>
      </div>
    </el-form>
    <el-empty v-if="!loading && !effectiveFields.length" description="没有可渲染的字段，请选择数据模型" :image-size="60" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api, getToken } from "@/api";
import { contentAppCode } from "../content-api";
import RichText from "./rich-text.vue";
import SignaturePad from "./signature-pad.vue";
import GeoPicker from "./geo-picker.vue";
import AttachmentField from "./attachment-field.vue";
import RelationSelect from "./relation-select.vue";
import type { DataModelField, DataModelInfo, RuntimeScope } from "@/types";
import { inject } from "vue";

const props = withDefaults(
  defineProps<{
    modelId?: number | string;
    fields?: DataModelField[];
    mode?: "create" | "edit";
    recordId?: number | string;
    publicToken?: string;
    labelWidth?: string;
    labelPosition?: "left" | "right" | "top";
    disabled?: boolean;
    submitText?: string;
    showReset?: boolean;
    successMessage?: string;
    defaultValues?: Record<string, any>;
    hiddenFields?: string[];
    columns?: number;
    /** 每行字段数：1/2/3；0 或 1 时单列。 */
    fieldColumns?: number;
  }>(),
  {
    modelId: 0,
    fields: () => [],
    mode: "create",
    recordId: 0,
    publicToken: "",
    labelWidth: "100px",
    labelPosition: "right",
    disabled: false,
    submitText: "提交",
    showReset: true,
    successMessage: "保存成功",
    defaultValues: () => ({}),
    hiddenFields: () => [],
    columns: 0,
    fieldColumns: 1,
  }
);

const emit = defineEmits<{
  (e: "submit", values: Record<string, any>): void;
  (e: "saved", record: any): void;
  (e: "reset"): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);
const formRef = ref<any>(null);
const loading = ref(false);
const saving = ref(false);
const captchaQuestion = ref("");
const captchaToken = ref("");
const captchaAnswer = ref("");
const remoteFields = ref<DataModelField[]>([]);
const values = reactive<Record<string, any>>({});
const appId = ref(0);
const userOptions = ref<any[]>([]);
const deptOptions = ref<any[]>([]);
const uploading = ref("");

const effectiveFields = computed<DataModelField[]>(() =>
  Array.isArray(props.fields) && props.fields.length ? props.fields : remoteFields.value
);
const visibleFields = computed(() => {
  const hidden = new Set(props.hiddenFields || []);
  return effectiveFields.value.filter((f) => !hidden.has(f.name) && !["created_at", "updated_at"].includes(f.type));
});
const labelWidthValue = computed(() => props.labelWidth);
const normalizedColumns = computed(() => {
  const n = Number(props.fieldColumns || props.columns || 1);
  return n > 0 ? Math.min(3, n) : 1;
});
const spanOf = (field: DataModelField) => {
  if (["json", "attachments"].includes(field.type)) return 24;
  return Math.floor(24 / normalizedColumns.value);
};

const rules = computed<Record<string, any[]>>(() => {
  const out: Record<string, any[]> = {};
  for (const f of effectiveFields.value) {
    const list: any[] = [];
    if (f.required) {
      const arrayType = ["references", "attachments", "multiselect", "tags"].includes(f.type);
      const changeTriggered = [
        "number", "boolean", "date", "reference", "references", "attachments", "multiselect", "tags",
      ].includes(f.type);
      const rule: Record<string, any> = {
        required: true,
        message: `请填写${f.label || f.name}`,
        trigger: changeTriggered ? "change" : "blur",
      };
      // 空数组对默认 string 规则不算空，显式声明 type=array 才能拦住必填附件/多选。
      if (arrayType) rule.type = "array";
      list.push(rule);
    }
    if (Array.isArray(f.rules)) list.push(...f.rules);
    if (list.length) out[f.name] = list;
  }
  return out;
});

function defaultValue(field: DataModelField): any {
  if (props.defaultValues && props.defaultValues[field.name] !== undefined) return props.defaultValues[field.name];
  if (field.default !== undefined) return field.default;
  if (field.type === "boolean") return false;
  if (field.type === "number") return 0;
  if (field.type === "json") return "";
  if (field.type === "attachments" || field.type === "references") return [];
  if (field.type === "reference") return null;
  return "";
}

function setDefaults() {
  for (const f of effectiveFields.value) {
    if (values[f.name] === undefined) values[f.name] = defaultValue(f);
  }
}

async function loadModel() {
  const id = Number(props.modelId);
  if (!id) return;
  if (Array.isArray(props.fields) && props.fields.length) {
    // 字段由外部传入时仍要解析 appId：附件上传与关联远程搜索都依赖它。
    if (!appId.value && !props.publicToken && getToken()) {
      try {
        const model = await api.get<DataModelInfo>(`/models/${id}/`);
        appId.value = Number(model.app_id || 0);
        await loadAuxiliary();
      } catch {
        /* 公开表单 / 无权限时保持 appId=0，组件回退到字段静态选项 */
      }
    }
    return;
  }
  try {
    const model = await api.get<DataModelInfo>(`/models/${id}/`);
    appId.value = Number(model.app_id || 0);
    remoteFields.value = Array.isArray(model.fields) ? model.fields : [];
    setDefaults();
    await loadAuxiliary();
  } catch {
    remoteFields.value = [];
  }
}

async function loadRecord() {
  const id = Number(props.modelId);
  const rid = Number(props.recordId);
  if (props.mode !== "edit" || !id || !rid) return;
  try {
    const rec = await (scope ? scope.record.get(id, rid) : api.get<any>(`/models/${id}/records/${rid}/`));
    const data = rec?.data ?? rec ?? {};
    Object.assign(values, data);
  } catch (e: any) {
    ElMessage.error(`加载记录失败：${e?.message || e}`);
  }
}

async function loadAuxiliary() {
  if (!appId.value) return;
  const fields = effectiveFields.value;
  const wantsUsers = fields.some((f) => f.type === "user");
  const wantsDepts = fields.some((f) => f.type === "department");
  try {
    if (wantsUsers) {
      const data = await api.get<any>("/org/users/?size=200");
      userOptions.value = data.results || data || [];
    }
  } catch { userOptions.value = []; }
  try {
    if (wantsDepts) {
      const data = await api.get<any>("/org/departments/?size=200");
      deptOptions.value = data.results || data || [];
    }
  } catch { deptOptions.value = []; }
}

function pickFile(field: DataModelField) {
  const el = document.getElementById(`upload-${field.name}`) as HTMLInputElement | null;
  el?.click();
}
async function onFileChange(e: Event, field: DataModelField) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (!appId.value) {
    ElMessage.warning("缺少应用 ID，无法上传");
    return;
  }
  uploading.value = field.name;
  try {
    const asset = await api.upload<{ url: string }>(`/assets/?app_id=${appId.value}`, file);
    values[field.name] = asset.url;
    ElMessage.success("文件已上传");
  } catch (err: any) {
    ElMessage.error(err?.message || "上传失败");
  } finally {
    uploading.value = "";
  }
}

async function load() {
  loading.value = true;
  try {
    await loadModel();
    setDefaults();
    if (!props.publicToken) await loadRecord();
  } finally {
    loading.value = false;
  }
}

async function loadCaptcha() {
  if (props.mode !== "create") return;
  const id = Number(props.modelId);
  const code = contentAppCode(scope);
  if (!id || !code) return;
  try {
    const result = await api.get<any>(`/runtime/${code}/content/${id}/challenge/`, { silent: true });
    if (result?.required) {
      captchaQuestion.value = String(result.question || "");
      captchaToken.value = String(result.token || "");
      captchaAnswer.value = "";
    }
  } catch {
    /* 该表单未开启验证码 */
  }
}

onMounted(() => {
  load();
  loadCaptcha();
});
watch(
  () => [props.modelId, props.recordId],
  () => load()
);

function parseJSONFields(data: Record<string, any>) {
  const out = { ...data };
  for (const f of effectiveFields.value) {
    if (f.type === "json" && typeof out[f.name] === "string") {
      const text = out[f.name].trim();
      if (!text) out[f.name] = null;
      else {
        try {
          out[f.name] = JSON.parse(text);
        } catch {
          /* 保持字符串，由后端/自定义规则处理 */
        }
      }
    }
  }
  return out;
}

async function submit() {
  if (!formRef.value) return;
  saving.value = true;
  try {
    const valid = await new Promise<boolean>((resolve) => {
      formRef.value.validate((ok: boolean) => resolve(!!ok));
    });
    if (!valid) return;
    const data = parseJSONFields(values);
    const id = Number(props.modelId);
    const appCode = contentAppCode(scope);
    // 登录态下的后台表单走模型管理 API；匿名公开表单才走 public content API。
    const publicSubmission = !getToken() || !!props.publicToken;
    if (id && appCode && publicSubmission && (props.mode === "create" || (props.mode === "edit" && props.publicToken))) {
      if (props.mode === "edit" && Number(props.recordId)) {
        await api.post(`/runtime/${appCode}/content/${id}/${Number(props.recordId)}/update/`, {
          ...data, public_token: props.publicToken,
        });
        emit("saved", { ...data, id: Number(props.recordId), public_token: props.publicToken });
        emit("submit", data);
        scope?.message("修改已提交，等待审核", "success");
        return;
      }
      if (captchaQuestion.value) {
        data._captcha_token = captchaToken.value;
        data._captcha_answer = captchaAnswer.value;
      }
      const rec = await api.post<any>(`/runtime/${appCode}/content/${id}/submit/`, data);
      emit("saved", rec);
      emit("submit", data);
      reset();
      if (rec?.forward && !rec.forward.ok && !rec.forward.skipped) {
        scope?.message(`已提交，但第三方同步失败：${rec.forward.error || "请稍后重试"}`, "warning");
      } else {
        scope?.message(props.successMessage, "success");
      }
      return;
    }
    if (id) {
      const rid = Number(props.recordId);
      const rec =
        props.mode === "edit" && rid
          ? await (scope ? scope.record.update(id, rid, data) : api.put(`/models/${id}/records/${rid}/`, { data }))
          : await (scope ? scope.record.create(id, data) : api.post(`/models/${id}/records/`, { data }));
      emit("saved", rec);
      window.dispatchEvent(new CustomEvent("wp:data-changed", { detail: { modelId: id } }));
    }
    emit("submit", data);
    if (props.mode !== "edit") reset();
    scope?.message(props.successMessage, "success");
    if (!scope) ElMessage.success(props.successMessage);
  } catch (e: any) {
    const msg = e?.detail || e?.message || "提交失败";
    if (scope) scope.message(String(msg), "error");
    else ElMessage.error(String(msg));
    if (captchaQuestion.value) loadCaptcha();
  } finally {
    saving.value = false;
  }
}

function reset() {
  formRef.value?.resetFields?.();
  for (const key of Object.keys(values)) delete values[key];
  setDefaults();
  emit("reset");
}
</script>

<style scoped>
.wp-auto-form {
  width: 100%;
}
.wp-upload-field { display: flex; align-items: center; gap: 7px; width: 100%; }
.wp-upload-preview { width: 42px; height: 32px; flex: none; border-radius: 4px; }
.wp-auto-form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
}
</style>
