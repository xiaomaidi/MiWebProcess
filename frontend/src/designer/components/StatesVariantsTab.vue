<template>
  <div class="wp-sv">
    <el-empty v-if="!node" description="节点不存在" :image-size="50" />
    <template v-else>
      <!-- 设计态状态预览 -->
      <div class="wp-sv-block">
        <div class="wp-sv-section-title">设计预览</div>
        <div class="wp-sv-preview-row">
          <el-select
            :model-value="previewState || ''"
            size="small"
            class="wp-sv-preview-select"
            @change="onPreviewChange"
          >
            <el-option label="基础形态（无预览）" value="" />
            <el-option v-for="s in STATES" :key="s.key" :label="s.label" :value="s.key" />
          </el-select>
          <el-button size="small" :disabled="!previewState" @click="resetPreview">重置预览</el-button>
        </div>
        <div class="wp-sv-tip">仅设计器可见，不写入页面数据；运行时按真实交互触发。</div>
      </div>

      <!-- 变体 -->
      <div class="wp-sv-head">
        <span class="wp-sv-section-title">变体</span>
        <el-button size="small" type="primary" plain @click="addVariant">新增变体</el-button>
      </div>
      <div v-if="!variants.length" class="wp-sv-empty">暂无变体。新增后可覆盖 props / style，并随时激活切换。</div>
      <div
        v-for="v in variants"
        :key="v.id"
        class="wp-sv-variant"
        :class="{ 'is-active': node.activeVariant === v.id }"
      >
        <div class="wp-sv-variant-head">
          <el-tag v-if="node.activeVariant === v.id" size="small" type="success">当前</el-tag>
          <el-input
            :model-value="v.name"
            size="small"
            class="wp-sv-name"
            placeholder="变体名称"
            @change="(value: string) => renameVariant(v, value)"
          />
          <el-button size="small" :type="node.activeVariant === v.id ? 'warning' : 'default'" @click="toggleVariant(v)">
            {{ node.activeVariant === v.id ? "取消激活" : "激活" }}
          </el-button>
          <el-button size="small" @click="duplicateVariant(v)">复制</el-button>
          <el-popconfirm title="删除该变体？" confirm-button-text="删除" cancel-button-text="取消" width="200" @confirm="removeVariant(v)">
            <template #reference>
              <el-button size="small" type="danger" plain>删除</el-button>
            </template>
          </el-popconfirm>
        </div>
        <el-collapse v-model="openVariants" class="wp-sv-collapse">
          <el-collapse-item :title="`覆盖内容（${overrideSummary(v)}）`" :name="v.id">
            <div class="wp-sv-sub">
              <span>style 键值</span>
              <span class="wp-sv-sub-hint">覆盖基础样式</span>
            </div>
            <div v-for="[key, value] in variantStyleEntries(v)" :key="key" class="wp-sv-kv-row">
              <el-input
                :model-value="key"
                size="small"
                class="wp-sv-k"
                @change="(next: string) => renameVariantStyleKey(v, key, next)"
              />
              <el-input
                :model-value="styleValueText(value)"
                size="small"
                class="wp-sv-v"
                placeholder="值，如 #409eff"
                @change="(next: string) => setVariantStyleValue(v, key, next)"
              />
              <el-button size="small" text type="danger" @click="removeVariantStyleKey(v, key)">删</el-button>
            </div>
            <div class="wp-sv-kv-row">
              <el-input v-model="variantNewKey[v.id]" size="small" class="wp-sv-k" placeholder="新样式键，如 color" @keyup.enter="addVariantStyleRow(v)" />
              <el-input v-model="variantNewValue[v.id]" size="small" class="wp-sv-v" placeholder="值" @keyup.enter="addVariantStyleRow(v)" />
              <el-button size="small" @click="addVariantStyleRow(v)">加</el-button>
            </div>
            <div class="wp-sv-sub">
              <span>props JSON</span>
              <span class="wp-sv-sub-hint">静态值 / 绑定对象整体覆盖基础属性</span>
            </div>
            <el-input
              v-model="variantPropsJson[v.id]"
              type="textarea"
              :rows="3"
              class="wp-mono"
              placeholder='例如 {"type":"primary","size":"large"} 或 {"text":{"__binding__":{"source":"variable","ref":"title"}}}'
            />
            <div class="wp-sv-actions">
              <el-button size="small" type="primary" plain @click="applyVariantProps(v)">应用 props</el-button>
              <span class="wp-sv-tip-inline">{{ overrideSummary(v) }}</span>
            </div>

            <div class="wp-sv-sub">
              <span>数据绑定 / 表达式</span>
              <span class="wp-sv-sub-hint">选择属性 → 选择数据；绑定优先于基础 props</span>
            </div>
            <div v-if="variantBindingsOf(v).length" class="wp-sv-chips">
              <el-tag
                v-for="entry in variantBindingsOf(v)"
                :key="entry.key"
                size="small"
                :type="entry.kind === 'binding' ? 'primary' : 'warning'"
                effect="plain"
                closable
                class="wp-sv-chip"
                :title="bindingChipTitle(entry)"
                @click="editVariantBinding(v, entry)"
                @close="clearVariantBinding(v, entry.key)"
              >
                <span class="wp-sv-chip-key">{{ entry.key }}</span>
                <span class="wp-sv-chip-sep">·</span>
                <span class="wp-sv-chip-val">{{ bindingChipText(entry) }}</span>
              </el-tag>
              <el-button size="small" text type="danger" @click="clearVariantBindings(v)">清除绑定</el-button>
            </div>
            <div v-else class="wp-sv-empty-inline">暂无绑定 / 表达式，该变体 props 使用静态值。</div>
            <div class="wp-sv-kv-row">
              <el-select
                v-model="variantBindKey[v.id]"
                size="small"
                filterable
                allow-create
                default-first-option
                clearable
                class="wp-sv-bindkey"
                placeholder="选择属性键"
              >
                <el-option v-for="p in propKeyOptions" :key="p.key" :label="p.label" :value="p.key" />
              </el-select>
              <el-button size="small" :loading="bindingRefsLoading" @click="openVariantPicker(v)">选择数据</el-button>
              <el-button size="small" :disabled="!variantBindKey[v.id]" @click="fillBindingJson(v)">回填 JSON</el-button>
            </div>
            <el-input
              v-model="variantBindJson[v.id]"
              type="textarea"
              :rows="2"
              class="wp-mono"
              placeholder='绑定 JSON，如 {"source":"variable","ref":"title","field":"name"}（也可粘贴 {"__binding__":…}）'
            />
            <div class="wp-sv-actions">
              <el-button size="small" type="primary" plain @click="applyVariantBindingJson(v)">应用绑定 JSON</el-button>
              <span class="wp-sv-tip-inline">支持 variable / datasource / model / form</span>
            </div>
            <el-alert
              v-if="variantStyleWarn(v)"
              :title="variantStyleWarn(v)"
              type="warning"
              :closable="false"
              show-icon
              class="wp-sv-warn"
            />
          </el-collapse-item>
        </el-collapse>
      </div>

      <!-- 状态覆盖 -->
      <div class="wp-sv-head wp-sv-head-gap">
        <span class="wp-sv-section-title">状态覆盖</span>
        <el-button size="small" :disabled="!anyState" @click="clearAllStates">清空全部</el-button>
      </div>
      <el-collapse v-model="openStates" class="wp-sv-collapse">
        <el-collapse-item v-for="s in STATES" :key="s.key" :name="s.key">
          <template #title>
            <span class="wp-sv-state-title">{{ s.label }}</span>
            <el-tag size="small" type="info" effect="plain">{{ stateSummary(s.key) }}</el-tag>
          </template>
          <div class="wp-sv-sub">
            <span>style 键值</span>
            <span class="wp-sv-sub-hint">CSS 声明，仅该状态生效</span>
          </div>
          <div v-for="[key, value] in stateStyleEntries(s.key)" :key="key" class="wp-sv-kv-row">
            <el-input
              :model-value="key"
              size="small"
              class="wp-sv-k"
              @change="(next: string) => renameStateStyleKey(s.key, key, next)"
            />
            <el-input
              :model-value="String(value ?? '')"
              size="small"
              class="wp-sv-v"
              placeholder="值，如 #409eff"
              @change="(next: string) => setStateStyleValue(s.key, key, next)"
            />
            <el-button size="small" text type="danger" @click="removeStateStyleKey(s.key, key)">删</el-button>
          </div>
          <div class="wp-sv-kv-row">
            <el-input v-model="stateNewKey[s.key]" size="small" class="wp-sv-k" placeholder="新样式键，如 backgroundColor" @keyup.enter="addStateStyleRow(s.key)" />
            <el-input v-model="stateNewValue[s.key]" size="small" class="wp-sv-v" placeholder="值" @keyup.enter="addStateStyleRow(s.key)" />
            <el-button size="small" @click="addStateStyleRow(s.key)">加</el-button>
          </div>
          <div class="wp-sv-sub">
            <span>props JSON</span>
            <span class="wp-sv-sub-hint">该状态激活时覆盖组件属性</span>
          </div>
          <el-input
            v-model="statePropsJson[s.key]"
            type="textarea"
            :rows="3"
            class="wp-mono"
            placeholder='例如 {"disabled": true}'
          />
          <div class="wp-sv-actions">
            <el-button size="small" type="primary" plain @click="applyStateProps(s.key)">应用 props</el-button>
            <el-button size="small" @click="togglePreview(s.key)">
              {{ previewState === s.key ? "退出预览" : "预览" }}
            </el-button>
            <el-button size="small" :disabled="!node.states?.[s.key]" @click="clearStateEntry(s.key)">清空该状态</el-button>
          </div>
        </el-collapse-item>
      </el-collapse>

      <div class="wp-sv-tip">
        变体 / 状态仅覆盖节点自身；运行态 hover / active / focus 由真实交互触发，disabled 依据 disabled 属性。
        变体 props 支持数据绑定与双花括号模板表达式，设计画布会用页面变量当前值预览，其余来源运行时取值；
        变体 style 暂不支持绑定，请输入静态样式值。
      </div>

      <BindingPicker
        v-model="pickerOpen"
        title="为变体属性选择数据"
        :binding="pickerBinding"
        :datasources="datasources"
        :models="models"
        :variables="schema.schema?.variables"
        :target-label="pickerLabel"
        @select="onVariantPick"
      />
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import type { ComponentStateName, ComponentVariant, DataBinding, DataModelInfo, DataSourceDef } from "@/types";
import { isBindingValue } from "@/engine/binding";
import {
  COMPONENT_STATES,
  hasAnyState as nodeHasAnyState,
  overrideSummary,
  variantBindingEntries,
  variantStyleBindingKeys,
  type VariantBindingEntry,
} from "@/engine/state-variants";
import { clearStatePreview, previewedStateOf, setStatePreview } from "@/engine/state-preview";
import { bindingExpression, bindingSummary, type BindingPickPayload } from "../utils/bindingSources";
import BindingPicker from "./BindingPicker.vue";
import { asList, commit, parseJson, prettyJson } from "../util";

const props = defineProps<{ nodeId: string }>();
const schema = useSchemaStore();
const components = useComponentStore();
const node = computed(() => schema.node(props.nodeId));
const meta = computed(() => (node.value ? components.meta(node.value.type) : undefined));
const variants = computed<ComponentVariant[]>(() => node.value?.variants || []);
const STATES = COMPONENT_STATES;
const anyState = computed(() => nodeHasAnyState(node.value));

// ---------- 绑定来源数据（数据源 / 数据模型；页面变量直接读 schema） ----------
const datasources = ref<DataSourceDef[]>([]);
const models = ref<DataModelInfo[]>([]);
const bindingRefsLoading = ref(false);
const bindingContext = computed(() => ({
  datasources: datasources.value,
  models: models.value,
  variables: schema.schema?.variables,
}));
let bindingRefsAppId = 0;

/** 懒加载数据源 / 模型列表，供 BindingPicker 选择来源（失败不阻塞变量/表单绑定）。 */
async function ensureBindingRefs() {
  const appId = schema.appId;
  if (!appId || bindingRefsLoading.value || bindingRefsAppId === appId) return;
  bindingRefsLoading.value = true;
  try {
    const [dsRes, modelRes] = await Promise.all([
      api.get<unknown>(`/apps/${appId}/datasources/`, { silent: true }),
      api.get<unknown>(`/apps/${appId}/models/`, { silent: true }),
    ]);
    datasources.value = asList<DataSourceDef>(dsRes);
    models.value = asList<DataModelInfo>(modelRes);
    bindingRefsAppId = appId;
  } catch {
    /* 静默失败：仍可绑定页面变量 / 表单，摘要显示「未找到」 */
  } finally {
    bindingRefsLoading.value = false;
  }
}
onMounted(() => {
  void ensureBindingRefs();
});

/** 属性键选项：组件声明的 props + 节点基础 props + 变体已有 props。 */
const propKeyOptions = computed(() => {
  const out: { key: string; label: string }[] = [];
  const seen = new Set<string>();
  const declared = meta.value?.props_schema?.properties ?? {};
  for (const [key, ps] of Object.entries(declared)) {
    if (ps?.["x-bindable"] === false) continue;
    out.push({ key, label: ps?.title || key });
    seen.add(key);
  }
  for (const key of Object.keys(node.value?.props || {})) {
    if (seen.has(key)) continue;
    out.push({ key, label: key });
    seen.add(key);
  }
  for (const v of variants.value) {
    for (const key of Object.keys(v.props || {})) {
      if (seen.has(key)) continue;
      out.push({ key, label: key });
      seen.add(key);
    }
  }
  return out;
});

function propLabel(key: string): string {
  const declared = meta.value?.props_schema?.properties?.[key];
  return declared?.title || key || "属性";
}

// ---------- 预览 ----------
const previewState = computed<ComponentStateName | null>(() => previewedStateOf(props.nodeId));

function onPreviewChange(value: any) {
  const state = value ? (value as ComponentStateName) : null;
  setStatePreview(props.nodeId, state);
}

function resetPreview() {
  clearStatePreview(props.nodeId);
}

function togglePreview(state: ComponentStateName) {
  if (previewState.value === state) clearStatePreview(props.nodeId);
  else setStatePreview(props.nodeId, state);
}

// ---------- 折叠面板 ----------
const openStates = ref<string[]>(["hover"]);
const openVariants = ref<string[]>([]);

// ---------- 草稿：避免 schema 更新 / 撤销时把未应用的编辑冲掉 ----------
const variantPropsJson = reactive<Record<string, string>>({});
const statePropsJson = reactive<Record<string, string>>({});
const lastVariantPropsJson = reactive<Record<string, string>>({});
const lastStatePropsJson = reactive<Record<string, string>>({});
const variantNewKey = reactive<Record<string, string>>({});
const variantNewValue = reactive<Record<string, string>>({});
const stateNewKey = reactive<Record<string, string>>({});
const stateNewValue = reactive<Record<string, string>>({});
// 变体绑定迷你编辑器草稿：选中的属性键 + 直接粘贴的绑定 JSON。
const variantBindKey = reactive<Record<string, string>>({});
const variantBindJson = reactive<Record<string, string>>({});

function syncDrafts() {
  const alive = new Set<string>();
  for (const v of variants.value) {
    alive.add(v.id);
    const canonical = prettyJson(v.props || {});
    if (lastVariantPropsJson[v.id] !== canonical) {
      lastVariantPropsJson[v.id] = canonical;
      variantPropsJson[v.id] = canonical;
    }
  }
  for (const key of Object.keys(variantPropsJson)) {
    if (!alive.has(key)) {
      delete variantPropsJson[key];
      delete lastVariantPropsJson[key];
      delete variantNewKey[key];
      delete variantNewValue[key];
    }
  }
  for (const key of Object.keys(variantBindKey)) {
    if (!alive.has(key)) delete variantBindKey[key];
  }
  for (const key of Object.keys(variantBindJson)) {
    if (!alive.has(key)) delete variantBindJson[key];
  }
  for (const { key } of STATES) {
    const canonical = prettyJson(node.value?.states?.[key]?.props || {});
    if (lastStatePropsJson[key] !== canonical) {
      lastStatePropsJson[key] = canonical;
      statePropsJson[key] = canonical;
    }
  }
}

watch(
  () => props.nodeId,
  (id, oldId) => {
    if (oldId) clearStatePreview(oldId);
    openVariants.value = [];
    syncDrafts();
  },
  { immediate: true }
);
watch(() => node.value?.variants, syncDrafts, { deep: true });
watch(() => node.value?.states, syncDrafts, { deep: true });
onBeforeUnmount(() => clearStatePreview(props.nodeId));

// ---------- 变体操作 ----------
function toggleVariant(v: ComponentVariant) {
  const active = node.value?.activeVariant === v.id;
  commit(active ? "取消激活变体" : "激活变体", () => schema.activateVariant(props.nodeId, active ? null : v.id));
}

function addVariant() {
  let newId = "";
  commit("新增变体", () => {
    newId = schema.addVariant(props.nodeId);
  });
  if (newId) {
    openVariants.value = [...new Set([...openVariants.value, newId])];
    syncDrafts();
  }
}

function duplicateVariant(v: ComponentVariant) {
  let newId = "";
  commit("复制变体", () => {
    newId = schema.duplicateVariant(props.nodeId, v.id);
    if (newId) schema.activateVariant(props.nodeId, newId);
  });
  if (newId) {
    openVariants.value = [...new Set([...openVariants.value, newId])];
    syncDrafts();
  }
}

function removeVariant(v: ComponentVariant) {
  commit("删除变体", () => schema.removeVariant(props.nodeId, v.id));
  delete variantPropsJson[v.id];
  delete lastVariantPropsJson[v.id];
  delete variantNewKey[v.id];
  delete variantNewValue[v.id];
  delete variantBindKey[v.id];
  delete variantBindJson[v.id];
  openVariants.value = openVariants.value.filter((id) => id !== v.id);
  syncDrafts();
}

function renameVariant(v: ComponentVariant, value: string) {
  const name = String(value ?? "").trim();
  if (!name) {
    ElMessage.warning("变体名称不能为空");
    return;
  }
  if (name === v.name) return;
  commit("重命名变体", () => schema.updateVariant(props.nodeId, v.id, { name }));
}

// ---------- 变体 style ----------
function variantStyleEntries(v: ComponentVariant): [string, any][] {
  return Object.entries(v.style || {});
}

/** style 值可能是绑定对象；用 JSON 文本展示，避免出现 [object Object]。 */
function styleValueText(value: any): string {
  if (value && typeof value === "object") return prettyJson(value);
  return String(value ?? "");
}

function setVariantStyle(v: ComponentVariant, style: Record<string, any>) {
  commit("变体样式", () => schema.updateVariant(props.nodeId, v.id, { style }));
}

function setVariantStyleValue(v: ComponentVariant, key: string, value: string) {
  const next = { ...(v.style || {}) };
  const text = String(value ?? "").trim();
  if (text) next[key] = text;
  else delete next[key];
  setVariantStyle(v, next);
}

function renameVariantStyleKey(v: ComponentVariant, oldKey: string, newKey: string) {
  const key = String(newKey ?? "").trim();
  if (!key || key === oldKey) return;
  if (key in (v.style || {})) {
    ElMessage.warning("样式键已存在");
    return;
  }
  const next: Record<string, any> = {};
  for (const [k, value] of Object.entries(v.style || {})) next[k === oldKey ? key : k] = value;
  setVariantStyle(v, next);
}

function addVariantStyleRow(v: ComponentVariant) {
  const key = String(variantNewKey[v.id] || "").trim();
  if (!key) {
    ElMessage.warning("请输入样式键");
    return;
  }
  if (key in (v.style || {})) {
    ElMessage.warning("样式键已存在");
    return;
  }
  setVariantStyle(v, { ...(v.style || {}), [key]: variantNewValue[v.id] ?? "" });
  variantNewKey[v.id] = "";
  variantNewValue[v.id] = "";
}

function removeVariantStyleKey(v: ComponentVariant, key: string) {
  const next = { ...(v.style || {}) };
  delete next[key];
  setVariantStyle(v, next);
}

function readPropsJson(text: string): Record<string, any> | null {
  const raw = String(text ?? "").trim();
  if (!raw) return {};
  const parsed = parseJson(raw);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  return parsed as Record<string, any>;
}

function applyVariantProps(v: ComponentVariant) {
  const parsed = readPropsJson(variantPropsJson[v.id] ?? "");
  if (parsed === null) {
    ElMessage.error("props 必须是 JSON 对象");
    syncDrafts();
    return;
  }
  commit("变体 props", () => schema.updateVariant(props.nodeId, v.id, { props: parsed }));
  const canonical = prettyJson(parsed);
  variantPropsJson[v.id] = canonical;
  lastVariantPropsJson[v.id] = canonical;
}

// ---------- 变体数据绑定（props 值 → { __binding__ } 或 {{...}} 表达式） ----------
const BINDING_SOURCES: DataBinding["source"][] = ["variable", "datasource", "model", "form"];
const pickerOpen = ref(false);
const pickerVariantId = ref("");
const pickerKey = ref("");

function bindingKeyFor(v: ComponentVariant): string {
  return String(variantBindKey[v.id] || "").trim();
}

function variantBindingsOf(v: ComponentVariant): VariantBindingEntry[] {
  return variantBindingEntries(v);
}

function bindingChipText(entry: VariantBindingEntry): string {
  if (entry.kind === "expression") return String(entry.value ?? "");
  return entry.binding ? bindingSummary(entry.binding, bindingContext.value) : "未选择来源";
}

function bindingChipTitle(entry: VariantBindingEntry): string {
  if (entry.kind === "expression") return `表达式 ${String(entry.value ?? "")}`;
  return entry.binding ? bindingExpression(entry.binding) : "";
}

/** 接受 `{source,ref,...}` 或 `{__binding__:{...}}` 两种 JSON 形态。 */
function parseBindingJson(text: string): DataBinding | null {
  const parsed = parseJson(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const raw = ((parsed as Record<string, any>).__binding__ ?? parsed) as Record<string, any>;
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const source = String(raw.source ?? "");
  if (!BINDING_SOURCES.includes(source as DataBinding["source"])) return null;
  const ref = typeof raw.ref === "string" ? raw.ref.trim() : "";
  if (!ref) return null;
  const binding: DataBinding = { source: source as DataBinding["source"], ref };
  if (typeof raw.field === "string" && raw.field.trim()) binding.field = raw.field.trim();
  if (typeof raw.transform === "string" && raw.transform.trim()) binding.transform = raw.transform;
  if (typeof raw.loopVar === "string" && raw.loopVar.trim()) binding.loopVar = raw.loopVar;
  if (raw.defaultValue !== undefined) binding.defaultValue = raw.defaultValue;
  return binding;
}

function editVariantBinding(v: ComponentVariant, entry: VariantBindingEntry) {
  variantBindKey[v.id] = entry.key;
  variantBindJson[v.id] = entry.kind === "binding" && entry.binding ? prettyJson(entry.binding) : "";
  openVariants.value = [...new Set([...openVariants.value, v.id])];
}

async function openVariantPicker(v: ComponentVariant) {
  const key = bindingKeyFor(v);
  if (!key) {
    ElMessage.warning("请先选择要绑定的属性键");
    return;
  }
  await ensureBindingRefs();
  const existing = v.props?.[key];
  if (isBindingValue(existing)) variantBindJson[v.id] = prettyJson(existing.__binding__);
  pickerVariantId.value = v.id;
  pickerKey.value = key;
  pickerOpen.value = true;
}

const pickerBinding = computed<DataBinding | null>(() => {
  const v = variants.value.find((item) => item.id === pickerVariantId.value);
  const existing = pickerKey.value ? v?.props?.[pickerKey.value] : undefined;
  if (isBindingValue(existing)) return existing.__binding__;
  return parseBindingJson(variantBindJson[pickerVariantId.value] ?? "");
});
const pickerLabel = computed(() => propLabel(pickerKey.value));

function onVariantPick(payload: BindingPickPayload) {
  const variantId = pickerVariantId.value;
  const key = pickerKey.value;
  if (!variantId || !key) return;
  if (payload.mode === "expression") {
    commit(`变体表达式 ${key}`, () => schema.setVariantProp(props.nodeId, variantId, key, `{{${payload.expression}}}`));
    variantBindJson[variantId] = "";
    ElMessage.success(`已写入「${propLabel(key)}」的表达式`);
  } else {
    commit(`变体绑定 ${key}`, () => schema.setVariantBinding(props.nodeId, variantId, key, payload.binding));
    variantBindJson[variantId] = prettyJson(payload.binding);
    ElMessage.success(`已绑定「${propLabel(key)}」`);
  }
  variantBindKey[variantId] = "";
}

function applyVariantBindingJson(v: ComponentVariant) {
  const key = bindingKeyFor(v);
  if (!key) {
    ElMessage.warning("请先选择要绑定的属性键");
    return;
  }
  const binding = parseBindingJson(variantBindJson[v.id] ?? "");
  if (!binding) {
    ElMessage.error('绑定 JSON 需包含 source（variable / datasource / model / form）与 ref');
    return;
  }
  commit(`变体绑定 ${key}`, () => schema.setVariantBinding(props.nodeId, v.id, key, binding));
  variantBindJson[v.id] = prettyJson(binding);
  ElMessage.success(`已绑定「${propLabel(key)}」`);
}

function fillBindingJson(v: ComponentVariant) {
  const key = bindingKeyFor(v);
  if (!key) {
    ElMessage.warning("请先选择要绑定的属性键");
    return;
  }
  const existing = v.props?.[key];
  if (isBindingValue(existing)) variantBindJson[v.id] = prettyJson(existing.__binding__);
  else ElMessage.info("该属性尚未绑定；请粘贴绑定 JSON 或点击「选择数据」");
}

function clearVariantBinding(v: ComponentVariant, key: string) {
  commit(`清除变体绑定 ${key}`, () => schema.removeVariantProp(props.nodeId, v.id, key));
  if (variantBindKey[v.id] === key) variantBindJson[v.id] = "";
}

function clearVariantBindings(v: ComponentVariant) {
  const entries = variantBindingEntries(v);
  if (!entries.length) return;
  commit("清除变体绑定", () => {
    for (const entry of entries) schema.removeVariantProp(props.nodeId, v.id, entry.key);
  });
  variantBindJson[v.id] = "";
}

function variantStyleWarn(v: ComponentVariant): string {
  const keys = variantStyleBindingKeys(v.style);
  return keys.length ? `样式暂不支持绑定：${keys.join("、")}。请改用 props 绑定或填写静态样式值。` : "";
}

// ---------- 状态操作 ----------
function stateSummary(state: ComponentStateName): string {
  return overrideSummary(node.value?.states?.[state]);
}

function stateStyleEntries(state: ComponentStateName): [string, any][] {
  return Object.entries(node.value?.states?.[state]?.style || {});
}

function setStateStyle(state: ComponentStateName, style: Record<string, any>) {
  commit(`状态样式 ${state}`, () => schema.setStateStyle(props.nodeId, state, style));
}

function setStateStyleValue(state: ComponentStateName, key: string, value: string) {
  const next: Record<string, any> = { ...(node.value?.states?.[state]?.style || {}) };
  const text = String(value ?? "").trim();
  if (text) next[key] = text;
  else delete next[key];
  setStateStyle(state, next);
}

function renameStateStyleKey(state: ComponentStateName, oldKey: string, newKey: string) {
  const key = String(newKey ?? "").trim();
  if (!key || key === oldKey) return;
  const current = node.value?.states?.[state]?.style || {};
  if (key in current) {
    ElMessage.warning("样式键已存在");
    return;
  }
  const next: Record<string, any> = {};
  for (const [k, value] of Object.entries(current)) next[k === oldKey ? key : k] = value;
  setStateStyle(state, next);
}

function addStateStyleRow(state: ComponentStateName) {
  const key = String(stateNewKey[state] || "").trim();
  if (!key) {
    ElMessage.warning("请输入样式键");
    return;
  }
  const current = node.value?.states?.[state]?.style || {};
  if (key in current) {
    ElMessage.warning("样式键已存在");
    return;
  }
  setStateStyle(state, { ...current, [key]: stateNewValue[state] ?? "" });
  stateNewKey[state] = "";
  stateNewValue[state] = "";
}

function removeStateStyleKey(state: ComponentStateName, key: string) {
  const next: Record<string, any> = { ...(node.value?.states?.[state]?.style || {}) };
  delete next[key];
  setStateStyle(state, next);
}

function applyStateProps(state: ComponentStateName) {
  const parsed = readPropsJson(statePropsJson[state] ?? "");
  if (parsed === null) {
    ElMessage.error("props 必须是 JSON 对象");
    syncDrafts();
    return;
  }
  commit(`状态 props ${state}`, () => schema.setStateProps(props.nodeId, state, parsed));
  const canonical = prettyJson(parsed);
  statePropsJson[state] = canonical;
  lastStatePropsJson[state] = canonical;
}

function clearStateEntry(state: ComponentStateName) {
  commit(`清空状态 ${state}`, () => schema.clearState(props.nodeId, state));
  statePropsJson[state] = "{}";
  lastStatePropsJson[state] = "{}";
  if (previewState.value === state) clearStatePreview(props.nodeId);
}

function clearAllStates() {
  commit("清空全部状态", () => {
    for (const { key } of STATES) schema.clearState(props.nodeId, key);
  });
  for (const { key } of STATES) {
    statePropsJson[key] = "{}";
    lastStatePropsJson[key] = "{}";
  }
  clearStatePreview(props.nodeId);
}
</script>

<style scoped>
.wp-sv {
  font-size: 13px;
  padding: 2px;
}
.wp-sv-block {
  margin-bottom: 12px;
}
.wp-sv-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.wp-sv-preview-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 6px 0;
}
.wp-sv-preview-select {
  flex: 1;
  min-width: 0;
}
.wp-sv-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 6px;
}
.wp-sv-head-gap {
  margin-top: 14px;
}
.wp-sv-empty {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
  padding: 6px 0 10px;
}
.wp-sv-variant {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  padding: 6px;
  margin-bottom: 8px;
}
.wp-sv-variant.is-active {
  border-color: var(--el-color-success);
  background: var(--el-color-success-light-9);
}
.wp-sv-variant-head {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.wp-sv-name {
  flex: 1;
  min-width: 90px;
}
.wp-sv-collapse {
  margin-top: 6px;
}
.wp-sv-collapse :deep(.el-collapse-item__header) {
  font-size: 12px;
  height: 30px;
  line-height: 30px;
  gap: 6px;
}
.wp-sv-collapse :deep(.el-collapse-item__content) {
  padding-bottom: 8px;
}
.wp-sv-state-title {
  margin-right: 6px;
  font-size: 12px;
}
.wp-sv-sub {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 8px 0 4px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.wp-sv-sub-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-sv-kv-row {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 4px;
}
.wp-sv-k {
  width: 42%;
  flex: none;
}
.wp-sv-v {
  flex: 1;
  min-width: 0;
}
.wp-sv-kv-row :deep(.el-input__inner) {
  font-size: 12px;
}
.wp-sv-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.wp-sv-tip {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.5;
  margin: 4px 0 8px;
}
.wp-sv-tip-inline {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-sv-chips {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}
.wp-sv-chip {
  max-width: 100%;
  cursor: pointer;
}
.wp-sv-chip-key {
  font-weight: 600;
}
.wp-sv-chip-sep {
  margin: 0 3px;
  opacity: 0.5;
}
.wp-sv-chip-val {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 11px;
  max-width: 210px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  display: inline-block;
}
.wp-sv-empty-inline {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  margin-bottom: 6px;
}
.wp-sv-bindkey {
  flex: 1;
  min-width: 0;
}
.wp-sv-warn {
  margin-top: 6px;
}
.wp-mono :deep(textarea) {
  font-family: ui-monospace, Consolas, monospace;
  font-size: 12px;
}
</style>
