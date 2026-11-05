<template>
  <div v-loading="loading" class="wp-bvd">
    <div v-if="error" class="wp-bvd-error">{{ error }}</div>
    <template v-else-if="diff">
      <div class="wp-bvd-summary">
        <span>v{{ diff.from?.version }} → v{{ diff.to?.version }}</span>
        <span class="added">+{{ diff.summary.added }} 新增</span>
        <span class="removed">-{{ diff.summary.removed }} 删除</span>
        <span class="changed">~{{ diff.summary.changed }} 修改</span>
        <span>{{ diff.summary.unchanged }} 未变</span>
      </div>
      <div v-if="diff.added.length" class="wp-bvd-section">
        <strong>新增节点</strong>
        <div v-for="row in diff.added" :key="`a-${row.id}`" class="wp-bvd-row is-added">
          <code>{{ row.id }}</code><span>{{ row.type }}</span><em>{{ row.label }}</em>
        </div>
      </div>
      <div v-if="diff.removed.length" class="wp-bvd-section">
        <strong>删除节点</strong>
        <div v-for="row in diff.removed" :key="`r-${row.id}`" class="wp-bvd-row is-removed">
          <code>{{ row.id }}</code><span>{{ row.type }}</span><em>{{ row.label }}</em>
        </div>
      </div>
      <div v-if="diff.changed.length" class="wp-bvd-section">
        <strong>修改节点</strong>
        <div v-for="row in diff.changed" :key="`c-${row.id}`" class="wp-bvd-row is-changed">
          <div class="wp-bvd-row-head"><code>{{ row.id }}</code><span>{{ row.type }}</span><em>{{ row.label }}</em></div>
          <div v-for="(field, name) in row.fields" :key="name" class="wp-bvd-field">
            <b>{{ name }}</b>
            <span class="wp-bvd-old">{{ field.from }}</span>
            <span>→</span>
            <span class="wp-bvd-new">{{ field.to }}</span>
          </div>
        </div>
      </div>
      <el-empty v-if="!diff.added.length && !diff.removed.length && !diff.changed.length" description="两个版本没有差异" :image-size="48" />
      <p v-if="diff.truncated" class="wp-bvd-truncated">差异过多，仅展示前 500 条。</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { api } from "@/api";

const props = defineProps<{ blockId: number; from: number; to: number }>();
const loading = ref(false);
const error = ref("");
const diff = ref<any>(null);

async function load() {
  if (!props.blockId || !props.from || !props.to) return;
  loading.value = true;
  error.value = "";
  diff.value = null;
  try {
    diff.value = await api.get<any>(`/blocks/${props.blockId}/versions/diff/?from=${props.from}&to=${props.to}`);
  } catch (e: any) {
    error.value = e?.message || "版本差异加载失败";
  } finally { loading.value = false; }
}
watch(() => [props.blockId, props.from, props.to], load);
onMounted(load);
</script>

<style scoped>
.wp-bvd { min-height: 100px; display: flex; flex-direction: column; gap: 8px; }
.wp-bvd-error { color: #dc2626; font-size: 12px; }
.wp-bvd-summary { display: flex; flex-wrap: wrap; gap: 10px; padding: 7px 9px; border-radius: 7px; background: #f8fafc; color: #475569; font-size: 10px; }
.wp-bvd-summary .added { color: #15803d; } .wp-bvd-summary .removed { color: #b91c1c; } .wp-bvd-summary .changed { color: #b45309; }
.wp-bvd-section { display: flex; flex-direction: column; gap: 4px; }
.wp-bvd-section > strong { color: #334155; font-size: 11px; }
.wp-bvd-row { padding: 5px 7px; border: 1px solid #eef2f8; border-radius: 6px; font-size: 10px; }
.wp-bvd-row code { margin-right: 6px; color: #64748b; font-size: 9px; }
.wp-bvd-row em { margin-left: 6px; color: #94a3b8; font-style: normal; }
.wp-bvd-row.is-added { border-left: 3px solid #22c55e; }
.wp-bvd-row.is-removed { border-left: 3px solid #ef4444; }
.wp-bvd-row.is-changed { border-left: 3px solid #f59e0b; }
.wp-bvd-row-head { display: flex; align-items: center; gap: 6px; }
.wp-bvd-field { display: flex; gap: 5px; margin-top: 4px; color: #64748b; font-size: 9px; word-break: break-all; }
.wp-bvd-field b { flex: none; color: #475569; }
.wp-bvd-old { color: #b91c1c; text-decoration: line-through; }
.wp-bvd-new { color: #15803d; }
.wp-bvd-truncated { color: #94a3b8; font-size: 9px; }
</style>
