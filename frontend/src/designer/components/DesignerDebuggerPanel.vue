<template>
  <div class="wp-debug">
    <div class="wp-debug-head">
      <div>
        <strong>交互调试</strong>
        <small>{{ filtered.length }} / {{ events.length }} 条</small>
      </div>
      <div class="wp-debug-actions">
        <el-button size="small" @click="paused ? resume() : pause()">{{ paused ? "继续" : "暂停" }}</el-button>
        <el-button size="small" @click="clear">清空</el-button>
        <el-button size="small" @click="exportJson">导出</el-button>
      </div>
    </div>
    <div class="wp-debug-tools">
      <el-radio-group v-model="kind" size="small">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button v-for="item in kinds" :key="item" :value="item">{{ labels[item] }}</el-radio-button>
      </el-radio-group>
      <el-input v-model="keyword" size="small" clearable placeholder="搜索事件 / 节点" />
    </div>
    <div class="wp-debug-summary">
      <span v-for="item in kinds" :key="item">{{ labels[item] }} {{ summary[item] }}</span>
    </div>
    <div class="wp-debug-list">
      <details v-for="item in filtered" :key="item.id" class="wp-debug-item" :class="`is-${item.kind}`">
        <summary>
          <span class="wp-debug-time">{{ time(item.at) }}</span>
          <el-tag size="small" :type="tagType(item.kind)">{{ labels[item.kind] }}</el-tag>
          <span class="wp-debug-label">{{ item.label }}</span>
          <code v-if="item.nodeId">{{ item.nodeId }}</code>
        </summary>
        <pre v-if="item.detail !== undefined">{{ pretty(item.detail) }}</pre>
      </details>
      <el-empty v-if="!filtered.length" description="暂无调试事件" :image-size="48" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  DEBUG_EVENT_KINDS,
  DEBUG_KIND_LABELS,
  debugEventSummary,
  debugEvents,
  debugPaused,
  useDesignerDebugger,
  type DebugEventKind,
} from "../debugger";

const kinds = DEBUG_EVENT_KINDS;
const labels = DEBUG_KIND_LABELS;
const events = debugEvents;
const paused = debugPaused;
const kind = ref<"all" | DebugEventKind>("all");
const keyword = ref("");
let handle: ReturnType<typeof useDesignerDebugger> | null = null;

const summary = computed(() => debugEventSummary(events.value));
const filtered = computed(() => {
  const text = keyword.value.trim().toLowerCase();
  return events.value.filter((item) => {
    if (kind.value !== "all" && item.kind !== kind.value) return false;
    if (!text) return true;
    return `${item.label} ${item.nodeId || ""} ${item.kind}`.toLowerCase().includes(text);
  });
});
function time(value: number) {
  return new Date(value).toLocaleTimeString();
}
function tagType(value: DebugEventKind) {
  return ({ error: "danger", action: "success", event: "primary", binding: "warning", navigation: "info", data: "info" } as Record<string, string>)[value] as any;
}
function pretty(value: unknown) {
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}
function clear() { handle?.clear(); }
function pause() { handle?.pause(); }
function resume() { handle?.resume(); }
function exportJson() {
  const blob = new Blob([JSON.stringify(events.value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "designer-debug-events.json";
  anchor.click();
  URL.revokeObjectURL(url);
}
onMounted(() => { handle = useDesignerDebugger(); });
onBeforeUnmount(() => { handle?.stop(); });
</script>

<style scoped>
.wp-debug { display: flex; flex-direction: column; gap: 9px; }
.wp-debug-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.wp-debug-head strong { display: block; color: #0f172a; font-size: 13px; }
.wp-debug-head small { color: #94a3b8; font-size: 9px; }
.wp-debug-actions { display: flex; gap: 4px; }
.wp-debug-tools { display: flex; flex-direction: column; gap: 6px; }
.wp-debug-summary { display: flex; flex-wrap: wrap; gap: 8px; color: #94a3b8; font-size: 9px; }
.wp-debug-list { display: flex; flex-direction: column; gap: 4px; max-height: 520px; overflow-y: auto; }
.wp-debug-item { padding: 6px 7px; border: 1px solid #eef2f8; border-radius: 7px; background: #fff; font-size: 10px; }
.wp-debug-item summary { display: flex; align-items: center; gap: 6px; cursor: pointer; list-style: none; }
.wp-debug-item summary::-webkit-details-marker { display: none; }
.wp-debug-time { flex: none; color: #94a3b8; font-size: 9px; }
.wp-debug-label { flex: 1; overflow: hidden; color: #334155; text-overflow: ellipsis; white-space: nowrap; }
.wp-debug-item code { color: #2563eb; font-size: 8px; }
.wp-debug-item pre { max-height: 220px; margin: 7px 0 0; padding: 6px; overflow: auto; border-radius: 5px; background: #f8fafc; color: #475569; font-size: 9px; white-space: pre-wrap; word-break: break-word; }
</style>
