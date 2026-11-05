<template>
  <div class="wp-rec">
    <div class="wp-rec-head">
      <div class="wp-rec-title">
        <strong>操作录制</strong>
        <el-tag size="small" :type="statusTagType" effect="light">{{ statusText }}</el-tag>
      </div>
      <div class="wp-rec-head-actions">
        <el-button
          v-if="!recordingActive && !replaying && actions.length"
          size="small"
          text
          @click="onContinue"
        >
          续录
        </el-button>
        <el-button
          v-if="!recordingActive && !replaying"
          size="small"
          type="primary"
          @click="onStart"
        >
          ● 录制
        </el-button>
        <el-button v-else-if="status === 'recording'" size="small" @click="pause">暂停</el-button>
        <el-button v-else-if="status === 'paused'" size="small" type="primary" @click="resume">继续</el-button>
        <el-button size="small" :disabled="!recordingActive" @click="onStop">停止</el-button>
        <el-button size="small" :disabled="!actions.length || replaying" @click="onClear">清空</el-button>
      </div>
    </div>

    <div class="wp-rec-meta">
      <span>{{ actions.length }} / {{ RECORDER_MAX_ACTIONS }} 条</span>
      <span>内存 {{ memoryText }}</span>
      <span v-if="dropped" class="wp-rec-warn">已丢弃 {{ dropped }} 条</span>
    </div>

    <div class="wp-rec-tools">
      <el-button size="small" :disabled="!actions.length" @click="onExport">导出</el-button>
      <el-button size="small" @click="triggerImport">导入</el-button>
      <el-checkbox v-model="persistSession" size="small">记住会话</el-checkbox>
      <input
        ref="fileInput"
        type="file"
        accept="application/json,.json"
        hidden
        @change="onFile"
      />
    </div>

    <div class="wp-rec-replay">
      <div class="wp-rec-replay-head">
        <span>回放</span>
        <span class="wp-rec-replay-progress">{{ actions.length ? `${Math.max(replayIndex + 1, 0)} / ${actions.length}` : "-" }}</span>
      </div>
      <div class="wp-rec-replay-row">
        <el-button size="small" :disabled="!actions.length" @click="onPlay">
          {{ replaying ? "回放中" : "回放" }}
        </el-button>
        <el-button v-if="replaying" size="small" @click="replayPaused ? resumeReplay() : pauseReplay()">
          {{ replayPaused ? "继续" : "暂停" }}
        </el-button>
        <el-button v-if="replaying" size="small" type="danger" plain @click="stopReplay">停止</el-button>
        <span class="wp-rec-speed">{{ speed }}ms</span>
      </div>
      <el-slider
        v-model="speed"
        :min="RECORDER_SPEED_MIN"
        :max="RECORDER_SPEED_MAX"
        :step="100"
        :show-tooltip="false"
        size="small"
        class="wp-rec-slider"
      />
    </div>

    <div ref="listRef" class="wp-rec-list">
      <button
        v-for="(item, index) in actions"
        :key="item.id"
        type="button"
        class="wp-rec-row"
        :class="{ 'is-active': index === replayIndex, 'is-omitted': !item.after }"
        :data-index="index"
        :title="rowTitle(item)"
        @click="onJump(index)"
      >
        <span class="wp-rec-seq">{{ pad(item.seq) }}</span>
        <span class="wp-rec-time">{{ time(item.at) }}</span>
        <span class="wp-rec-source" :class="`is-${item.source}`">{{ sourceLabel(item.source) }}</span>
        <span class="wp-rec-label">{{ item.label }}</span>
        <span v-if="item.snapshotOmitted" class="wp-rec-warn">无快照</span>
        <span v-else-if="item.truncated" class="wp-rec-warn">已截断</span>
        <span class="wp-rec-dur">{{ item.durationMs }}ms</span>
      </button>
      <el-empty v-if="!actions.length" description="暂无录制，点击「录制」开始" :image-size="42" />
    </div>

    <div class="wp-rec-foot">
      <span v-if="lastError" class="wp-rec-error">{{ lastError }}</span>
      <span v-else-if="hint" class="wp-rec-hint">{{ hint }}</span>
      <span v-else class="wp-rec-hint">点击行跳转快照；回放不会清空撤销历史</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 操作录制面板（紧凑中文 UI）。
 *
 * 自成一体：直接使用共享 recorder 引擎，不依赖 DesignerView 的 props。
 * 接入方式（无需修改本文件）：
 *   import RecorderPanel from "@/designer/components/RecorderPanel.vue";
 *   <el-drawer v-model="recorderOpen" title="操作录制" size="460px">
 *     <RecorderPanel />
 *   </el-drawer>
 * 建议抽屉常驻挂载（不要 destroy-on-close），或在设计器根组件提前 start()。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  RECORDER_MAX_ACTIONS,
  RECORDER_SOURCE_LABELS,
  RECORDER_SPEED_MAX,
  RECORDER_SPEED_MIN,
  useActionRecorder,
  type RecordedAction,
  type RecorderSource,
} from "../recorder";

const {
  actions,
  status,
  replayPaused,
  replayIndex,
  replaySpeed,
  memoryBytes,
  dropped,
  lastError,
  start,
  pause,
  resume,
  stop,
  clear,
  jumpTo,
  play,
  pauseReplay,
  resumeReplay,
  stopReplay: stopReplayEngine,
  setReplaySpeed,
  exportJson,
  importJson,
  hasSession,
  sessionInfo,
  restoreSession,
  setSessionPersistence,
  isSessionPersistenceEnabled,
} = useActionRecorder();

const fileInput = ref<HTMLInputElement | null>(null);
const listRef = ref<HTMLElement | null>(null);
const speed = ref(replaySpeed.value);
const persistSession = ref(false);
const hint = ref("");
let hintTimer: ReturnType<typeof setTimeout> | null = null;

const recordingActive = computed(() => status.value === "recording" || status.value === "paused");
const replaying = computed(() => status.value === "replaying");
const statusText = computed(() => {
  if (status.value === "recording") return "录制中";
  if (status.value === "paused") return "已暂停";
  if (status.value === "replaying") return replayPaused.value ? "回放已暂停" : "回放中";
  return "未开始";
});
const statusTagType = computed<"success" | "warning" | "primary" | "info">(() => {
  if (status.value === "recording") return "success";
  if (status.value === "paused") return "warning";
  if (status.value === "replaying") return "primary";
  return "info";
});
const memoryText = computed(() => formatBytes(memoryBytes.value));

watch(speed, (value) => {
  setReplaySpeed(value);
});
watch(persistSession, (value) => {
  setSessionPersistence(value);
});
watch(replayIndex, async (value) => {
  if (value < 0) return;
  await nextTick();
  const row = listRef.value?.querySelector<HTMLElement>(`[data-index="${value}"]`);
  row?.scrollIntoView({ block: "nearest" });
});

function setHint(text: string) {
  hint.value = text;
  if (hintTimer) clearTimeout(hintTimer);
  hintTimer = setTimeout(() => {
    hint.value = "";
    hintTimer = null;
  }, 4000);
}

function time(value: number) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "--:--:--"
    : date.toLocaleTimeString("zh-CN", { hour12: false });
}

function pad(value: number) {
  return String(value).padStart(2, "0");
}

function sourceLabel(source: RecorderSource) {
  return RECORDER_SOURCE_LABELS[source] || "变更";
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 KB";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function rowTitle(item: RecordedAction) {
  const nodes = item.after ? Object.keys(item.after.nodes || {}).length : 0;
  const selected = item.selection.selectedIds.length;
  return [
    item.label,
    `时间：${new Date(item.at).toLocaleString()}`,
    `来源：${sourceLabel(item.source)} · 耗时 ${item.durationMs}ms`,
    `选中：${selected} 个节点`,
    `结构：${nodes} 个节点 · ${formatBytes(item.afterBytes)}`,
    item.after ? "点击跳转到该快照" : "该条没有可用快照",
  ].join("\n");
}

async function onStart() {
  if (actions.value.length) {
    try {
      await ElMessageBox.confirm("开始新的录制会清空当前记录，是否继续？", "开始录制", {
        type: "warning",
        confirmButtonText: "清空并开始",
        cancelButtonText: "取消",
      });
    } catch {
      return;
    }
  }
  start(true);
  setHint("已开始录制");
}

function onContinue() {
  start(false);
  setHint("已继续录制，后续动作会追加到当前时间线");
}

function onStop() {
  stop();
  setHint(`已停止，共 ${actions.value.length} 条`);
}

async function onClear() {
  if (!actions.value.length) return;
  try {
    await ElMessageBox.confirm("确定清空全部录制记录（含会话缓存）？", "清空记录", {
      type: "warning",
    });
  } catch {
    return;
  }
  clear();
  setHint("已清空录制记录");
}

function onJump(index: number) {
  void jumpTo(index).then((ok) => {
    if (ok) setHint(`已跳转到 #${actions.value[index]?.seq ?? index + 1}`);
  });
}

async function onPlay() {
  await play({ speedMs: speed.value });
}

function onExport() {
  if (!actions.value.length) return;
  const blob = new Blob([exportJson(true)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `designer-recording-${fileStamp()}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
  setHint(`已导出 ${actions.value.length} 条记录`);
}

function triggerImport() {
  fileInput.value?.click();
}

async function onFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  try {
    const text = await file.text();
    const result = importJson(text);
    if (result.ok) {
      setHint(`已导入 ${result.count} 条${result.dropped ? `，忽略 ${result.dropped} 条` : ""}`);
      ElMessage.success(`已导入 ${result.count} 条录制记录`);
    } else {
      ElMessage.error(result.error || "导入失败");
    }
  } catch (error: any) {
    ElMessage.error(error?.message || "读取文件失败");
  }
}

function stopReplay() {
  stopReplayEngine();
}

function fileStamp() {
  const date = new Date();
  const pad2 = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}-${pad2(date.getHours())}${pad2(date.getMinutes())}`;
}

onMounted(() => {
  persistSession.value = isSessionPersistenceEnabled();
  speed.value = replaySpeed.value;
  if (!actions.value.length && hasSession()) {
    const info = sessionInfo();
    const result = restoreSession();
    if (result.ok) {
      const savedAt = info?.savedAt ? new Date(info.savedAt).toLocaleString() : "";
      setHint(`已恢复上次会话 ${result.count} 条${savedAt ? `（${savedAt}）` : ""}`);
    }
  }
});

onBeforeUnmount(() => {
  if (hintTimer) {
    clearTimeout(hintTimer);
    hintTimer = null;
  }
});
</script>

<style scoped>
.wp-rec { display: flex; flex-direction: column; gap: 8px; color: #334155; font-size: 11px; }
.wp-rec-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.wp-rec-title { display: flex; align-items: center; gap: 6px; }
.wp-rec-title strong { color: #0f172a; font-size: 13px; }
.wp-rec-head-actions { display: flex; gap: 4px; }
.wp-rec-meta { display: flex; flex-wrap: wrap; gap: 10px; color: #94a3b8; font-size: 9px; }
.wp-rec-tools { display: flex; align-items: center; gap: 6px; padding-bottom: 2px; border-bottom: 1px solid #eef2f8; }
.wp-rec-tools .el-checkbox { margin-left: auto; }
.wp-rec-replay { padding: 7px 8px; border: 1px solid #e8edf5; border-radius: 9px; background: #f8fafc; }
.wp-rec-replay-head { display: flex; align-items: center; justify-content: space-between; color: #64748b; font-size: 10px; }
.wp-rec-replay-progress { color: #94a3b8; font-size: 9px; }
.wp-rec-replay-row { display: flex; align-items: center; gap: 5px; margin-top: 5px; }
.wp-rec-speed { margin-left: auto; color: #64748b; font-size: 9px; font-variant-numeric: tabular-nums; }
.wp-rec-slider { margin: 2px 4px 0; }
.wp-rec-list { display: flex; flex-direction: column; gap: 3px; max-height: 430px; overflow-y: auto; padding-right: 2px; }
.wp-rec-row { display: flex; align-items: center; gap: 6px; width: 100%; padding: 5px 6px; border: 1px solid #eef2f8; border-radius: 7px; background: #fff; color: #334155; font-size: 10px; text-align: left; cursor: pointer; }
.wp-rec-row:hover { border-color: #bfdbfe; background: #f8fbff; }
.wp-rec-row.is-active { border-color: #2563eb; background: #eff6ff; box-shadow: inset 2px 0 0 #2563eb; }
.wp-rec-row.is-omitted { opacity: 0.62; }
.wp-rec-seq { flex: none; color: #94a3b8; font-size: 9px; font-variant-numeric: tabular-nums; }
.wp-rec-time { flex: none; color: #94a3b8; font-size: 9px; font-variant-numeric: tabular-nums; }
.wp-rec-source { flex: none; padding: 0 4px; border-radius: 4px; background: #f1f5f9; color: #64748b; font-size: 8px; line-height: 15px; }
.wp-rec-source.is-history { background: #ecfdf5; color: #059669; }
.wp-rec-source.is-undo, .wp-rec-source.is-redo { background: #fff7ed; color: #d97706; }
.wp-rec-source.is-baseline { background: #eff6ff; color: #2563eb; }
.wp-rec-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wp-rec-dur { flex: none; color: #94a3b8; font-size: 9px; font-variant-numeric: tabular-nums; }
.wp-rec-warn { flex: none; color: #d97706; font-size: 8px; }
.wp-rec-foot { min-height: 14px; color: #94a3b8; font-size: 9px; }
.wp-rec-hint { color: #94a3b8; }
.wp-rec-error { color: #dc2626; }
</style>
