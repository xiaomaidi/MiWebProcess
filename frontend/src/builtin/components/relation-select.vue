<template>
  <div class="wp-relation-select">
    <el-select
      v-model="innerValue"
      class="wp-relation-select-input"
      :multiple="multiple"
      filterable
      remote
      reserve-keyword
      clearable
      :remote-method="onRemoteSearch"
      :loading="loading || loadingMore"
      :disabled="disabled"
      :placeholder="placeholder || (multiple ? '搜索并选择记录（可多选）' : '搜索并选择记录')"
      :no-data-text="errorText || '无匹配记录'"
      @clear="onClear"
    >
      <el-option
        v-for="option in options"
        :key="String(option.value)"
        :label="option.label"
        :value="option.value"
      />
      <template #footer>
        <div class="wp-relation-footer">
          <el-button
            v-if="hasMore"
            link
            type="primary"
            size="small"
            :loading="loadingMore"
            @click.stop="loadMore"
          >
            加载更多（已加载 {{ fetchedCount }}/{{ total }}）
          </el-button>
          <span v-else-if="total > 0" class="wp-relation-total">共 {{ total }} 条</span>
          <span v-if="errorText" class="wp-relation-error">{{ errorText }}</span>
        </div>
      </template>
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { api } from "@/api";

interface RelationOption {
  label: string;
  value: number;
}

const PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 280;

/** appId → 模型列表（同一表单内多个 reference 字段共用一次请求）。 */
const modelListCache = new Map<number, Promise<any[]>>();

const props = withDefaults(
  defineProps<{
    /** 单值：记录 id；多值：记录 id 数组。 */
    modelValue?: number | string | Array<number | string> | null;
    appId?: number | string;
    refModel: string;
    multiple?: boolean;
    /** 字段定义里的静态选项（无 appId 时作为兜底）。 */
    options?: { label: string; value: any }[];
    refDisplay?: string;
    disabled?: boolean;
    placeholder?: string;
  }>(),
  {
    modelValue: null,
    appId: 0,
    multiple: false,
    options: () => [],
    refDisplay: "",
    disabled: false,
    placeholder: "",
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", value: number | number[] | null): void;
}>();

const targetModelId = ref(0);
const options = ref<RelationOption[]>([]);
const selectedLabels = ref<Record<number, string>>({});
const total = ref(0);
const fetchedCount = ref(0);
const page = ref(1);
const loading = ref(false);
const loadingMore = ref(false);
const errorText = ref("");
const searchText = ref("");
const appliedSearch = ref("");
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let requestSeq = 0;

function toIds(value: unknown): number[] {
  const raw = Array.isArray(value) ? value : value === null || value === undefined || value === "" ? [] : [value];
  const ids: number[] = [];
  for (const item of raw) {
    const id = Number(item);
    if (Number.isInteger(id) && id > 0 && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

const selectedIds = computed<number[]>(() => {
  const ids = toIds(props.modelValue);
  return props.multiple ? ids : ids.slice(0, 1);
});

const innerValue = computed<any>({
  get: () => (props.multiple ? selectedIds.value : selectedIds.value[0] ?? null),
  set: (value: unknown) => {
    const ids = toIds(value);
    emit("update:modelValue", props.multiple ? ids : ids[0] ?? null);
  },
});

const hasMore = computed(() => fetchedCount.value < total.value);

function labelOf(row: any): string {
  const data = row?.data || {};
  const display = props.refDisplay ? data[props.refDisplay] : undefined;
  const candidate = display ?? data.title ?? data.name ?? data.label ?? data.summary;
  if (candidate !== undefined && candidate !== null && String(candidate).trim() !== "") {
    return String(candidate);
  }
  return `#${row?.id ?? ""}`;
}

function rememberLabels(list: RelationOption[]) {
  if (!list.length) return;
  const next = { ...selectedLabels.value };
  for (const option of list) next[option.value] = option.label;
  selectedLabels.value = next;
}

function withSelected(list: RelationOption[]): RelationOption[] {
  const merged = new Map<number, RelationOption>();
  for (const option of list) merged.set(option.value, option);
  for (const id of selectedIds.value) {
    if (!merged.has(id)) {
      merged.set(id, { value: id, label: selectedLabels.value[id] || `#${id}` });
    }
  }
  return [...merged.values()];
}

function seedStaticOptions() {
  const provided = (props.options || []).filter(
    (option) => option && option.value !== undefined && option.value !== null && option.value !== ""
  );
  if (!provided.length) return;
  const seeded: RelationOption[] = [];
  for (const option of provided) {
    const id = Number(option.value);
    if (!Number.isInteger(id) || id <= 0) continue;
    seeded.push({ value: id, label: String(option.label ?? option.value) });
  }
  if (!seeded.length) return;
  rememberLabels(seeded);
  options.value = withSelected([...options.value, ...seeded]);
  total.value = Math.max(total.value, seeded.length);
}

function getModelList(appId: number): Promise<any[]> {
  if (!modelListCache.has(appId)) {
    const request = api
      .get<any>(`/apps/${appId}/models/?size=100`, { silent: true })
      .then((data) => (Array.isArray(data) ? data : data?.results || []))
      .catch(() => {
        modelListCache.delete(appId);
        return [];
      });
    modelListCache.set(appId, request);
  }
  return modelListCache.get(appId)!;
}

async function resolveTargetModel(): Promise<number> {
  const appId = Number(props.appId);
  if (!appId || !props.refModel) return 0;
  const models = await getModelList(appId);
  const target = models.find((model: any) => model?.name === props.refModel);
  return Number(target?.id) || 0;
}

async function fetchPage(nextPage: number, search: string, mode: "replace" | "append") {
  const modelId = targetModelId.value;
  if (!modelId) return;
  const seq = ++requestSeq;
  if (mode === "append") loadingMore.value = true;
  else {
    loading.value = true;
    errorText.value = "";
  }
  try {
    const query = new URLSearchParams({ page: String(nextPage), size: String(PAGE_SIZE) });
    const keyword = search.trim();
    if (keyword) query.set("search", keyword);
    const response = await api.get<any>(`/models/${modelId}/records/?${query.toString()}`, {
      silent: true,
    });
    if (seq !== requestSeq) return;
    const rows = Array.isArray(response?.results) ? response.results : Array.isArray(response) ? response : [];
    const mapped: RelationOption[] = [];
    for (const row of rows) {
      const id = Number(row?.id);
      if (!Number.isInteger(id) || id <= 0) continue;
      mapped.push({ value: id, label: labelOf(row) });
    }
    rememberLabels(mapped);
    const count = Number(response?.count);
    total.value = Number.isFinite(count) ? count : mapped.length;
    page.value = nextPage;
    appliedSearch.value = search;
    if (mode === "append") {
      fetchedCount.value += mapped.length;
      options.value = withSelected([...options.value, ...mapped]);
    } else {
      fetchedCount.value = mapped.length;
      options.value = withSelected(mapped);
    }
    await ensureSelectedLabels();
  } catch {
    if (seq === requestSeq) errorText.value = "关联数据加载失败，请稍后重试";
  } finally {
    if (seq === requestSeq) {
      loading.value = false;
      loadingMore.value = false;
    }
  }
}

/** 选中记录可能不在首屏/搜索结果里，按 id 补查标签。 */
async function ensureSelectedLabels() {
  const modelId = targetModelId.value;
  if (!modelId) return;
  const known = new Set(options.value.map((option) => option.value));
  const missing = selectedIds.value.filter((id) => !known.has(id) && !selectedLabels.value[id]).slice(0, PAGE_SIZE);
  if (!missing.length) return;
  const fetched = await Promise.all(
    missing.map(async (id) => {
      try {
        const record = await api.get<any>(`/models/${modelId}/records/${id}/`, { silent: true });
        return { value: id, label: labelOf(record) };
      } catch {
        return { value: id, label: `#${id}` };
      }
    })
  );
  rememberLabels(fetched);
  options.value = withSelected([...options.value, ...fetched]);
}

function onRemoteSearch(query: string) {
  searchText.value = String(query || "");
  if (searchTimer) clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    page.value = 1;
    void fetchPage(1, searchText.value, "replace");
  }, SEARCH_DEBOUNCE_MS);
}

function loadMore() {
  if (!hasMore.value || loading.value || loadingMore.value) return;
  void fetchPage(page.value + 1, appliedSearch.value, "append");
}

function onClear() {
  if (props.multiple) emit("update:modelValue", []);
  else emit("update:modelValue", null);
}

async function bootstrap() {
  seedStaticOptions();
  const modelId = await resolveTargetModel();
  targetModelId.value = modelId;
  if (!modelId) {
    if (Number(props.appId) && props.refModel) errorText.value = `未找到关联模型 ${props.refModel}`;
    await ensureSelectedLabels();
    return;
  }
  await fetchPage(1, searchText.value, "replace");
}

onMounted(() => {
  void bootstrap();
});

watch(
  () => [props.appId, props.refModel],
  () => {
    requestSeq += 1;
    targetModelId.value = 0;
    options.value = [];
    selectedLabels.value = {};
    total.value = 0;
    fetchedCount.value = 0;
    page.value = 1;
    errorText.value = "";
    void bootstrap();
  }
);

watch(
  selectedIds,
  () => {
    void ensureSelectedLabels();
  },
  { deep: true }
);

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer);
  requestSeq += 1;
});
</script>

<style scoped>
.wp-relation-select {
  width: 100%;
}
.wp-relation-select-input {
  width: 100%;
}
.wp-relation-footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 2px 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-relation-total {
  color: var(--el-text-color-secondary);
}
.wp-relation-error {
  color: var(--el-color-warning);
  font-size: 12px;
}
</style>
