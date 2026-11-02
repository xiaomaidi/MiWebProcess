<template>
  <section class="wp-content-list" :class="`is-${mode}`">
    <header v-if="heading || showSearch" class="wp-content-head">
      <h2 v-if="heading" class="wp-content-title">{{ heading }}</h2>
      <el-input
        v-if="showSearch"
        v-model="searchValue"
        class="wp-content-search"
        :placeholder="searchPlaceholder"
        clearable
        @change="onSearch"
        @clear="onSearch"
      >
        <template #prefix>⌕</template>
      </el-input>
    </header>

    <div v-if="showCategoryTabs && categories.length" class="wp-content-tabs">
      <button type="button" :class="{ active: !activeCategory }" @click="selectCategory('')">全部</button>
      <button
        v-for="c in categories"
        :key="String(c[categorySlugField] ?? c.id)"
        type="button"
        :class="{ active: activeCategory === String(c[categorySlugField] ?? '') }"
        @click="selectCategory(String(c[categorySlugField] ?? ''))"
      >
        {{ c[categoryLabelField] ?? c.name ?? c.title }}
      </button>
    </div>

    <div v-loading="loading" class="wp-content-body">
      <UiState v-if="!rows.length && !loading" state="empty" :title="emptyText" />

      <template v-else>
        <article
          v-for="(row, index) in rows"
          :key="row.id ?? index"
          class="wp-content-item"
          @click="open(row)"
        >
          <span v-if="mode === 'ranking'" class="wp-ranking-no" :class="{ top: index < 3 }">{{ index + 1 + (page - 1) * pageSize }}</span>
          <a
            v-if="coverField && row[coverField]"
            class="wp-content-cover"
            :href="hrefOf(row)"
            @click.prevent.stop="open(row)"
          >
            <img :src="String(row[coverField])" :alt="String(row[titleField] ?? '')" loading="lazy" />
          </a>
          <div v-else-if="mode !== 'ranking'" class="wp-content-cover is-placeholder">
            <span>{{ String(row[titleField] ?? "·").slice(0, 2) }}</span>
          </div>
          <div class="wp-content-main">
            <h3 class="wp-content-item-title">
              <a :href="hrefOf(row)" @click.prevent.stop="open(row)">{{ row[titleField] || "未命名内容" }}</a>
            </h3>
            <p v-if="summaryField && row[summaryField]" class="wp-content-summary">{{ row[summaryField] }}</p>
            <div class="wp-content-meta">
              <span v-if="authorField && row[authorField]">{{ row[authorField] }}</span>
              <span v-if="dateField && row[dateField]">{{ formatContentDate(row[dateField]) }}</span>
              <span v-for="tag in tagsOf(row)" :key="tag" class="wp-content-tag">{{ tag }}</span>
            </div>
          </div>
        </article>
      </template>
    </div>

    <div v-if="showPagination && total > pageSize" class="wp-content-pager">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="prev, pager, next"
        background
        @current-change="load"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import type { RuntimeScope } from "@/types";
import {
  contentAppCode,
  contentRows,
  fetchContentList,
  formatContentDate,
} from "../content-api";
import UiState from "./ui-state.vue";

interface ContentCategory {
  id?: number;
  name?: string;
  slug?: string;
  [key: string]: any;
}

const props = withDefaults(
  defineProps<{
    dataModelId?: number | string;
    mode?: "list" | "grid" | "compact" | "ranking";
    heading?: string;
    categoryField?: string;
    category?: string;
    categoryModelId?: number | string;
    categoryBasePath?: string;
    categoryLabelField?: string;
    categorySlugField?: string;
    titleField?: string;
    summaryField?: string;
    coverField?: string;
    dateField?: string;
    authorField?: string;
    tagsField?: string;
    hrefPattern?: string;
    pageSize?: number;
    sort?: string;
    filters?: Record<string, any>;
    showPagination?: boolean;
    showSearch?: boolean;
    searchPlaceholder?: string;
    showCategoryTabs?: boolean;
    emptyText?: string;
  }>(),
  {
    dataModelId: 0,
    mode: "list",
    heading: "",
    categoryField: "",
    category: "",
    categoryModelId: 0,
    categoryBasePath: "news",
    categoryLabelField: "name",
    categorySlugField: "slug",
    titleField: "title",
    summaryField: "summary",
    coverField: "cover",
    dateField: "published_at",
    authorField: "author",
    tagsField: "tags",
    hrefPattern: "article/{id}",
    pageSize: 10,
    sort: "-published_at",
    filters: () => ({}),
    showPagination: true,
    showSearch: false,
    searchPlaceholder: "搜索内容…",
    showCategoryTabs: false,
    emptyText: "暂无内容",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const router = useRouter();
const route = useRoute();
const rows = ref<Record<string, any>[]>([]);
const categories = ref<ContentCategory[]>([]);
const total = ref(0);
const page = ref(1);
const loading = ref(false);
const searchValue = ref("");
const activeCategory = ref("");
const appCode = computed(() => contentAppCode(scope) || String(route.params.appCode || ""));
let pendingReload = false;

const routeCategory = computed(() => String(scope?.routeParams?.category || route.params.category || ""));
const effectiveCategory = computed(() => props.category || routeCategory.value || activeCategory.value);

const hrefOf = (row: Record<string, any>): string => {
  const pattern = props.hrefPattern || "article/{id}";
  const path = pattern.replace(/\{([\w.]+)\}/g, (_m, key) => {
    if (key === "category") return String(row[props.categoryField] ?? effectiveCategory.value ?? "");
    return String(row[key] ?? row.id ?? "");
  });
  return `/run/${appCode.value}/${path.replace(/^\/+/, "")}`;
};

function open(row: Record<string, any>) {
  const href = hrefOf(row);
  if (!appCode.value) return;
  if (scope?.navigate) scope.navigate(href.replace(`/run/${appCode.value}/`, ""));
  else router.push(href);
}

function tagsOf(row: Record<string, any>): string[] {
  const v = props.tagsField ? row[props.tagsField] : null;
  if (!v) return [];
  if (Array.isArray(v)) return v.map(String).slice(0, 3);
  return String(v).split(/[,，/|]/).map((x) => x.trim()).filter(Boolean).slice(0, 3);
}

function selectCategory(slug: string) {
  activeCategory.value = slug;
  page.value = 1;
  const base = (props.categoryBasePath || "news").replace(/^\/+|\/+$/g, "");
  const target = slug ? `${base}/${slug}` : base;
  if (!appCode.value) return;
  if (scope?.navigate) scope.navigate(target);
  else router.push(`/run/${appCode.value}/${target}`);
}

function onSearch() {
  page.value = 1;
  load();
}

async function loadCategories() {
  if (!props.showCategoryTabs || !Number(props.categoryModelId)) return;
  try {
    const res = await fetchContentList(scope, Number(props.categoryModelId), { page: 1, size: 100, sort: "sort" });
    categories.value = contentRows(res) as ContentCategory[];
  } catch {
    categories.value = [];
  }
}

async function load() {
  const modelId = Number(props.dataModelId);
  if (!modelId) return;
  if (loading.value) {
    pendingReload = true;
    return;
  }
  loading.value = true;
  try {
    const params: Record<string, any> = {
      page: page.value,
      size: props.pageSize,
      sort: props.sort,
      ...(props.filters || {}),
    };
    if (searchValue.value) params.search = searchValue.value;
    if (props.categoryField && effectiveCategory.value) params[props.categoryField] = effectiveCategory.value;
    const res = await fetchContentList(scope, modelId, params);
    rows.value = contentRows(res);
    total.value = Number(res?.count) || rows.value.length;
    // 供同一页面的图表/指标卡/表格读取（公开 content API 拉到的数据）。
    if (scope) scope.modelResults[modelId] = { ...(res as any), results: rows.value };
  } catch (e: any) {
    ElMessage.error(e?.message || "内容加载失败");
  } finally {
    loading.value = false;
    if (pendingReload) {
      pendingReload = false;
      await load();
    }
  }
}

onMounted(async () => {
  activeCategory.value = routeCategory.value;
  await Promise.all([loadCategories(), load()]);
});

watch(
  () => [props.dataModelId, props.category, routeCategory.value],
  async () => {
    activeCategory.value = routeCategory.value;
    page.value = 1;
    await load();
  }
);
</script>

<style scoped>
.wp-content-list {
  width: 100%;
  color: #1f2329;
}
.wp-content-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.wp-content-title {
  margin: 0;
  font-size: 22px;
  line-height: 1.3;
  border-left: 4px solid #e4393c;
  padding-left: 10px;
}
.wp-content-search {
  width: 240px;
}
.wp-content-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.wp-content-tabs button {
  border: 1px solid #e5e6eb;
  background: #fff;
  color: #4e5969;
  border-radius: 16px;
  padding: 4px 14px;
  font-size: 13px;
  cursor: pointer;
}
.wp-content-tabs button.active,
.wp-content-tabs button:hover {
  color: #e4393c;
  border-color: #e4393c;
  background: #fff5f5;
}
.wp-content-body {
  min-height: 120px;
}
.wp-content-empty {
  padding: 40px 0;
  text-align: center;
  color: #86909c;
}
.wp-content-item {
  display: flex;
  gap: 14px;
  padding: 14px 0;
  border-bottom: 1px solid #f0f1f3;
  cursor: pointer;
}
.wp-content-item:hover .wp-content-item-title a {
  color: #e4393c;
}
.wp-content-cover {
  flex: none;
  width: 148px;
  height: 94px;
  border-radius: 4px;
  overflow: hidden;
  background: #f2f3f5;
  display: block;
}
.wp-content-cover img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.wp-content-cover.is-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #2a2d36, #555b6e);
  color: #fff;
  font-size: 22px;
  font-weight: 700;
}
.wp-content-main {
  min-width: 0;
  flex: 1;
}
.wp-content-item-title {
  margin: 2px 0 8px;
  font-size: 17px;
  line-height: 1.45;
}
.wp-content-item-title a {
  color: inherit;
  text-decoration: none;
}
.wp-content-summary {
  margin: 0 0 10px;
  font-size: 13px;
  line-height: 1.65;
  color: #6b7280;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.wp-content-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #9aa3af;
}
.wp-content-tag {
  color: #e4393c;
  background: #fff0f0;
  border-radius: 3px;
  padding: 0 5px;
}
.wp-content-pager {
  display: flex;
  justify-content: center;
  margin-top: 18px;
}
.wp-content-list.is-grid .wp-content-body {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 16px;
}
.wp-content-list.is-grid .wp-content-item {
  display: block;
  border: 1px solid #eef0f3;
  border-radius: 6px;
  overflow: hidden;
  padding: 0;
  background: #fff;
}
.wp-content-list.is-grid .wp-content-cover {
  width: 100%;
  height: 150px;
}
.wp-content-list.is-grid .wp-content-main {
  padding: 12px 14px 14px;
}
.wp-content-list.is-compact .wp-content-cover {
  display: none;
}
.wp-content-list.is-ranking .wp-content-item {
  align-items: center;
  gap: 10px;
  padding: 10px 0;
}
.wp-content-list.is-ranking .wp-content-cover {
  width: 80px;
  height: 54px;
}
.wp-ranking-no {
  flex: none;
  width: 22px;
  text-align: center;
  color: #86909c;
  font-size: 14px;
  font-weight: 700;
}
.wp-ranking-no.top {
  color: #e4393c;
}
@media (max-width: 640px) {
  .wp-content-cover {
    width: 104px;
    height: 70px;
  }
  .wp-content-head {
    flex-direction: column;
    align-items: stretch;
  }
  .wp-content-search {
    width: 100%;
  }
}
</style>
