<template>
  <article class="wp-article">
    <div v-if="loading" class="wp-article-tip">加载中…</div>
    <div v-else-if="!record" class="wp-article-tip">{{ emptyText }}</div>
    <template v-else>
      <nav class="wp-article-crumb">
        <a :href="hrefOf(backPath)" @click.prevent="go(backPath)">首页</a>
        <span>/</span>
        <a v-if="category" :href="hrefOf(categoryPath)" @click.prevent="go(categoryPath)">{{ category }}</a>
        <span v-if="category">/</span>
        <span class="current">{{ record[titleField] }}</span>
      </nav>

      <header class="wp-article-head">
        <h1>{{ record[titleField] }}</h1>
        <p v-if="summaryField && record[summaryField]" class="wp-article-summary">{{ record[summaryField] }}</p>
        <div class="wp-article-meta">
          <span v-if="authorField && record[authorField]">{{ record[authorField] }}</span>
          <span v-if="dateField && record[dateField]">{{ formatContentDate(record[dateField]) }}</span>
          <span v-if="record.views != null">{{ record.views }} 阅读</span>
          <span v-for="tag in tags" :key="tag" class="wp-article-tag">{{ tag }}</span>
        </div>
      </header>

      <figure v-if="coverField && record[coverField]" class="wp-article-cover">
        <img :src="String(record[coverField])" :alt="String(record[titleField] ?? '')" />
      </figure>

      <div class="wp-article-content" v-html="contentHtml"></div>

      <footer v-if="showRelated && related.length" class="wp-article-related">
        <h2>相关阅读</h2>
        <div class="wp-related-grid">
          <a
            v-for="item in related"
            :key="item.id"
            class="wp-related-item"
            :href="hrefOf(articlePath(item))"
            @click.prevent="go(articlePath(item))"
          >
            <strong>{{ item[titleField] }}</strong>
            <span v-if="dateField && item[dateField]">{{ formatContentDate(item[dateField]) }}</span>
          </a>
        </div>
      </footer>
    </template>
  </article>
</template>

<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, onServerPrefetch, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import type { RuntimeScope } from "@/types";
import { api } from "@/api";
import { sanitizeHtml } from "@/engine/sanitize";
import { cachePrefetch, getPrefetch } from "@/ssr/prefetch";
import {
  contentAppCode,
  contentRows,
  fetchContentBySlug,
  fetchContentList,
  fetchContentRecord,
  formatContentDate,
} from "../content-api";

const props = withDefaults(
  defineProps<{
    dataModelId?: number | string;
    lookup?: "id" | "slug";
    slugField?: string;
    titleField?: string;
    summaryField?: string;
    contentField?: string;
    coverField?: string;
    authorField?: string;
    dateField?: string;
    categoryField?: string;
    tagsField?: string;
    categoryPathPrefix?: string;
    articlePath?: string;
    backPath?: string;
    showRelated?: boolean;
    relatedLimit?: number;
    emptyText?: string;
  }>(),
  {
    dataModelId: 0,
    lookup: "slug",
    slugField: "slug",
    titleField: "title",
    summaryField: "summary",
    contentField: "content",
    coverField: "cover",
    authorField: "author",
    dateField: "published_at",
    categoryField: "category",
    tagsField: "tags",
    categoryPathPrefix: "news",
    articlePath: "article/{id}",
    backPath: "home",
    showRelated: true,
    relatedLimit: 4,
    emptyText: "内容不存在或尚未发布",
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const route = useRoute();
const router = useRouter();
const cached = getPrefetch<{ record: Record<string, any> | null; related: Record<string, any>[] }>(prefetchKey());
const record = ref<Record<string, any> | null>(cached?.record ?? null);
const related = ref<Record<string, any>[]>(cached?.related ?? []);
const loading = ref(false);
const appCode = computed(() => contentAppCode(scope) || String(route.params.appCode || ""));
const category = computed(() => String(record.value?.[props.categoryField] ?? ""));
const categoryPath = computed(() => `${props.categoryPathPrefix}/${category.value}`);
const tags = computed<string[]>(() => {
  const v = record.value?.[props.tagsField];
  if (!v) return [];
  if (Array.isArray(v)) return v.map(String);
  return String(v).split(/[,，/|]/).map((x) => x.trim()).filter(Boolean);
});
const contentHtml = computed(() => sanitizeHtml(String(record.value?.[props.contentField] ?? "")));

function articlePath(row: Record<string, any>): string {
  return (props.articlePath || "article/{id}").replace(/\{([\w.]+)\}/g, (_m, key) => String(row[key] ?? row.id ?? ""));
}

function prefetchKey(): string {
  const params = scope?.routeParams || (route.params as Record<string, any>) || {};
  const id = params.id ?? route.params.id ?? "";
  const slug = params.slug ?? route.params.slug ?? "";
  const modelId = Number(props.dataModelId) || 0;
  return `article:${modelId}:${props.lookup === "id" ? id || slug : slug || id}`;
}

function hrefOf(path: string): string {
  return `/run/${appCode.value}/${String(path || "").replace(/^\/+/, "")}`;
}

function go(path: string) {
  if (!appCode.value) return;
  if (scope?.navigate) scope.navigate(String(path).replace(/^\/+/, ""));
  else router.push(hrefOf(path));
}

function applyJsonLd(row: Record<string, any>) {
  if (typeof document === "undefined") return;
  const payload = {
    "@context": "https://schema.org",
    "@type": "Article",
    headline: row[props.titleField] || "",
    description: row[props.summaryField] || "",
    image: row[props.coverField] || undefined,
    datePublished: row[props.dateField] || undefined,
    author: row[props.authorField] ? { "@type": "Person", name: row[props.authorField] } : undefined,
    mainEntityOfPage: window.location.href,
  };
  let el = document.getElementById("wp-article-jsonld") as HTMLScriptElement | null;
  if (!el) {
    el = document.createElement("script");
    el.id = "wp-article-jsonld";
    el.type = "application/ld+json";
    document.head.appendChild(el);
  }
  el.textContent = JSON.stringify(payload);
}

function normalize(raw: any): Record<string, any> | null {
  if (!raw) return null;
  if (raw.data && typeof raw.data === "object") return { ...raw.data, id: raw.id };
  return raw;
}

async function load() {
  const modelId = Number(props.dataModelId);
  if (!modelId) return;
  loading.value = true;
  try {
    const params = scope?.routeParams || (route.params as Record<string, any>);
    const id = Number(params.id || route.params.id || 0);
    const slug = String(params.slug || route.params.slug || "");
    if (props.lookup === "id" && !id) return;
    let row: Record<string, any> | null = null;
    if (props.lookup === "id" && id) {
      row = normalize(await fetchContentRecord(scope, modelId, id));
      if (!row) {
        const code = contentAppCode(scope);
        if (code) {
          try {
            row = normalize(await api.get(`/runtime/${code}/content/${modelId}/${id}/`));
          } catch {
            row = null;
          }
        }
      }
    } else if (slug) {
      row = await fetchContentBySlug(scope, modelId, props.slugField, slug);
    }
    record.value = row;
    if (row) {
      applyJsonLd(row);
      scope?.setPageMeta?.({
        title: String(row[props.titleField] ?? ""),
        description: String(row[props.summaryField] ?? ""),
        image: String(row[props.coverField] ?? ""),
        type: "article",
      });
      await loadRelated(row);
      if (typeof window === "undefined") {
        cachePrefetch(prefetchKey(), { record: row, related: related.value });
      }
    }
  } finally {
    loading.value = false;
  }
}

async function loadRelated(row: Record<string, any>) {
  if (!props.showRelated) return;
  try {
    const params: Record<string, any> = { page: 1, size: Number(props.relatedLimit) + 1, sort: "-published_at" };
    if (props.categoryField && row[props.categoryField]) params[props.categoryField] = row[props.categoryField];
    const res = await fetchContentList(scope, Number(props.dataModelId), params);
    related.value = contentRows(res).filter((x) => Number(x.id) !== Number(row.id)).slice(0, props.relatedLimit);
  } catch {
    related.value = [];
  }
}

onMounted(() => {
  if (cached?.record) {
    applyJsonLd(cached.record);
    scope?.setPageMeta?.({
      title: String(cached.record[props.titleField] ?? ""),
      description: String(cached.record[props.summaryField] ?? ""),
      image: String(cached.record[props.coverField] ?? ""),
      type: "article",
    });
    return;
  }
  void load();
});
// SSR 预取正文与相关阅读，保证首屏 HTML 含水合数据。
onServerPrefetch(async () => {
  try {
    await load();
  } catch {
    /* 预取失败时降级为空状态，客户端挂载后再取 */
  }
});
onBeforeUnmount(() => document.getElementById("wp-article-jsonld")?.remove());
watch(
  () => [props.dataModelId, route.params.id, route.params.slug, scope?.routeParams?.id, scope?.routeParams?.slug],
  () => load()
);
</script>

<style scoped>
.wp-article {
  max-width: 860px;
  margin: 0 auto;
  padding: 28px 20px 56px;
  color: #1f2329;
}
.wp-article-tip {
  padding: 80px 0;
  text-align: center;
  color: #86909c;
}
.wp-article-crumb {
  font-size: 12px;
  color: #86909c;
  margin-bottom: 18px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-article-crumb a {
  color: #4e5969;
  text-decoration: none;
}
.wp-article-crumb .current {
  color: #86909c;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 420px;
}
.wp-article-head h1 {
  font-size: 32px;
  line-height: 1.35;
  margin: 0 0 12px;
  letter-spacing: 0.2px;
}
.wp-article-summary {
  color: #6b7280;
  font-size: 15px;
  line-height: 1.75;
  margin: 0 0 14px;
}
.wp-article-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 12px;
  color: #9aa3af;
  padding-bottom: 18px;
  border-bottom: 1px solid #f0f1f3;
}
.wp-article-tag {
  color: #e4393c;
  background: #fff0f0;
  border-radius: 3px;
  padding: 1px 6px;
}
.wp-article-cover {
  margin: 22px 0;
}
.wp-article-cover img {
  width: 100%;
  max-height: 460px;
  object-fit: cover;
  border-radius: 6px;
  display: block;
}
.wp-article-content {
  font-size: 17px;
  line-height: 1.95;
  color: #2b2f36;
}
.wp-article-content :deep(p) {
  margin: 0 0 1.1em;
}
.wp-article-content :deep(h2),
.wp-article-content :deep(h3) {
  margin: 1.4em 0 0.7em;
  line-height: 1.4;
}
.wp-article-content :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 4px;
}
.wp-article-content :deep(blockquote) {
  margin: 1.2em 0;
  padding: 10px 16px;
  border-left: 3px solid #e4393c;
  background: #fafafa;
  color: #555;
}
.wp-article-content :deep(a) {
  color: #2f6fed;
}
.wp-article-related {
  margin-top: 44px;
  padding-top: 18px;
  border-top: 1px solid #eef0f3;
}
.wp-article-related h2 {
  font-size: 18px;
  margin: 0 0 14px;
}
.wp-related-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.wp-related-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border: 1px solid #eef0f3;
  border-radius: 5px;
  text-decoration: none;
  color: inherit;
  background: #fff;
}
.wp-related-item:hover {
  border-color: #e4393c;
}
.wp-related-item span {
  font-size: 12px;
  color: #9aa3af;
}
@media (max-width: 640px) {
  .wp-article-head h1 {
    font-size: 24px;
  }
  .wp-related-grid {
    grid-template-columns: 1fr;
  }
}
</style>
