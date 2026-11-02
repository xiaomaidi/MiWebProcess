<template>
  <section class="wp-site-search">
    <header class="wp-site-search-head">
      <h2>{{ heading }}</h2>
      <p>{{ description }}</p>
    </header>
    <div class="wp-site-search-bar">
      <el-input
        v-model="keyword"
        :placeholder="placeholder"
        clearable
        size="large"
        @keyup.enter="search"
      />
      <el-button type="primary" size="large" :loading="loading" @click="search">搜索</el-button>
    </div>
    <div v-if="searched && !loading" class="wp-site-search-count">
      找到 {{ results.length }} 条与「{{ lastKeyword }}」相关的内容
    </div>
    <div v-loading="loading" class="wp-site-search-list">
      <article v-for="item in results" :key="`${item.model_id}-${item.id}`" class="wp-site-search-item" @click="open(item)">
        <h3>{{ item.title }}</h3>
        <p>{{ item.summary || "暂无摘要" }}</p>
        <span class="wp-site-search-link">阅读全文 →</span>
      </article>
      <el-empty v-if="searched && !loading && !results.length" description="没有找到相关内容" :image-size="60" />
    </div>
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    heading?: string;
    description?: string;
    placeholder?: string;
    limit?: number;
  }>(),
  {
    heading: "站内搜索",
    description: "搜索已发布的文章、资讯和专题内容。",
    placeholder: "输入关键词，回车搜索…",
    limit: 20,
  }
);

const scope = inject<RuntimeScope | null>("wp.scope", null);
const route = useRoute();
const keyword = ref("");
const lastKeyword = ref("");
const results = ref<any[]>([]);
const loading = ref(false);
const searched = ref(false);

function appCode(): string {
  const app = scope?.variables?.app as { code?: string } | undefined;
  return String(app?.code || "");
}

async function search() {
  const q = keyword.value.trim();
  if (!q) {
    results.value = [];
    searched.value = false;
    return;
  }
  const code = appCode();
  if (!code) {
    ElMessage.warning("设计态无法调用公开搜索，请在运行态预览");
    return;
  }
  loading.value = true;
  try {
    const res = await api.get<any>(`/runtime/${code}/search/?q=${encodeURIComponent(q)}`);
    results.value = Array.isArray(res?.results) ? res.results : [];
    lastKeyword.value = q;
    searched.value = true;
  } catch (e: any) {
    ElMessage.error(e?.message || "搜索失败");
  } finally {
    loading.value = false;
  }
}

function open(item: any) {
  const code = appCode();
  if (!code || !scope?.navigate) {
    window.open(item.url, "_blank");
    return;
  }
  try {
    const url = new URL(item.url);
    const prefix = `/run/${code}/`;
    scope.navigate(url.pathname.startsWith(prefix) ? url.pathname.slice(prefix.length) : url.pathname);
  } catch {
    window.open(item.url, "_blank");
  }
}

onMounted(() => {
  const q = String(route.query.q || "");
  if (q) {
    keyword.value = q;
    search();
  }
});
</script>

<style scoped>
.wp-site-search {
  max-width: 820px;
  margin: 0 auto;
  padding: 8px 0 40px;
}
.wp-site-search-head h2 {
  margin: 0 0 6px;
  font-size: 28px;
}
.wp-site-search-head p {
  margin: 0 0 20px;
  color: #86909c;
  font-size: 13px;
}
.wp-site-search-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}
.wp-site-search-count {
  color: #86909c;
  font-size: 12px;
  margin-bottom: 10px;
}
.wp-site-search-list {
  min-height: 120px;
}
.wp-site-search-item {
  padding: 16px 18px;
  border: 1px solid #eef0f3;
  border-radius: 8px;
  margin-bottom: 10px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.wp-site-search-item:hover {
  border-color: #c6d6ff;
  box-shadow: 0 4px 16px rgba(64, 128, 255, 0.08);
}
.wp-site-search-item h3 {
  margin: 0 0 6px;
  font-size: 17px;
  color: #1d2129;
}
.wp-site-search-item p {
  margin: 0 0 8px;
  color: #6b7280;
  font-size: 13px;
  line-height: 1.6;
}
.wp-site-search-link {
  color: #2f6bff;
  font-size: 12px;
}
</style>
