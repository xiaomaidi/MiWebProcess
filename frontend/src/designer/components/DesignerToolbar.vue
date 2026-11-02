<template>
  <div class="wp-toolbar">
    <div class="wp-tb-group">
      <el-button size="small" :disabled="!history.canUndo" @click="undo">撤销</el-button>
      <el-button size="small" :disabled="!history.canRedo" @click="redo">重做</el-button>
    </div>

    <div class="wp-tb-group">
      <el-button size="small" :loading="saving" type="primary" @click="save(false)">保存草稿</el-button>
      <el-tag size="small" :type="statusType" effect="plain" class="wp-tb-dirty">{{ statusText }}</el-tag>
    </div>

    <div class="wp-tb-group">
      <el-button size="small" @click="$emit('preview')">预览</el-button>
      <el-button size="small" @click="$emit('publish')">发布</el-button>
      <el-button size="small" @click="$emit('versions')">版本</el-button>
    </div>

    <div class="wp-tb-group">
      <span class="wp-tb-label">布局</span>
      <el-radio-group :model-value="layoutMode" size="small" @change="onLayout">
        <el-radio-button value="flow">流式</el-radio-button>
        <el-radio-button value="free">自由</el-radio-button>
      </el-radio-group>
    </div>

    <div class="wp-tb-group">
      <span class="wp-tb-label">设备</span>
      <el-radio-group :model-value="editor.device" size="small" @change="onDevice">
        <el-radio-button value="desktop">桌面 1200</el-radio-button>
        <el-radio-button value="tablet">平板 768</el-radio-button>
        <el-radio-button value="phone">手机 375</el-radio-button>
      </el-radio-group>
    </div>

    <div class="wp-tb-group">
      <span class="wp-tb-label">缩放</span>
      <el-radio-group :model-value="zoomVal" size="small" @change="onZoom">
        <el-radio-button :value="0.5">50%</el-radio-button>
        <el-radio-button :value="1">100%</el-radio-button>
        <el-radio-button :value="1.5">150%</el-radio-button>
      </el-radio-group>
      <el-button size="small" text @click="editor.requestFit()">适应</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import { useHistoryStore } from "@/store/history";
import { useEditorStore } from "@/store/editor";
import type { PageInfo } from "@/types";

const props = defineProps<{ page: PageInfo | null; appId: number }>();
const emit = defineEmits<{
  (e: "preview"): void;
  (e: "publish"): void;
  (e: "versions"): void;
  (e: "saved", payload: any): void;
}>();

const schema = useSchemaStore();
const history = useHistoryStore();
const editor = useEditorStore();

const saving = ref(false);
const savedVersion = ref(0);
const dirty = computed(() => schema.dirty);
const layoutMode = computed(() => schema.layoutMode);
const zoomVal = computed(() => editor.zoom);

watch(
  () => props.page?.version,
  (version) => {
    if (version) savedVersion.value = version;
  },
  { immediate: true }
);

watch(
  () => schema.dirty,
  (isDirty) => {
    if (isDirty && !saving.value && editor.saveStatus !== "conflict") editor.saveStatus = "dirty";
  }
);

const statusText = computed(() => {
  if (saving.value || editor.saveStatus === "saving") return "保存中…";
  if (editor.saveStatus === "conflict") return "保存冲突";
  if (editor.saveStatus === "error") return "保存失败";
  if (dirty.value) return "未保存";
  return "已保存";
});
const statusType = computed(() => {
  if (editor.saveStatus === "conflict" || editor.saveStatus === "error") return "danger";
  if (saving.value || dirty.value) return "warning";
  return "success";
});

function undo() {
  history.undo();
}
function redo() {
  history.redo();
}

async function save(silent = false): Promise<boolean> {
  const pageId = props.page?.id || schema.pageId;
  if (!pageId || !schema.schema) {
    if (!silent) ElMessage.warning("页面未就绪");
    return false;
  }
  if (saving.value) return false;
  saving.value = true;
  editor.saveStatus = "saving";
  try {
    const res = await api.put(`/pages/${pageId}/schema/`, {
      schema: schema.schema,
      base_version: savedVersion.value || props.page?.version || undefined,
    });
    if (res?.page?.version) savedVersion.value = Number(res.page.version);
    schema.markSaved();
    editor.saveStatus = "saved";
    editor.lastSavedAt = new Date().toISOString();
    emit("saved", res);
    const warnings: string[] = Array.isArray(res?.warnings) ? res.warnings : [];
    if (!silent) {
      if (warnings.length) ElMessage.warning(`已保存，存在 ${warnings.length} 条告警`);
      else ElMessage.success("草稿已保存");
    }
    return true;
  } catch (err: any) {
    const conflict = Number(err?.status) === 409 || !!err?.data?.current_version;
    editor.saveStatus = conflict ? "conflict" : "error";
    if (!silent) {
      ElMessage.error(conflict ? "页面已被其他人保存，请刷新后再编辑" : err?.message || "保存失败");
    }
    return false;
  } finally {
    saving.value = false;
  }
}

function onLayout(mode: "flow" | "free" | string) {
  if (mode !== "flow" && mode !== "free") return;
  history.run("切换布局模式", () => schema.setLayoutMode(mode));
}

function onDevice(d: string) {
  if (d === "desktop" || d === "tablet" || d === "phone") editor.setDevice(d);
}

function onZoom(z: number | string) {
  const v = Number(z);
  if ([0.5, 1, 1.5].includes(v)) editor.setZoom(v);
}

defineExpose({ save, undo, redo });
</script>

<style scoped>
.wp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
  flex-wrap: wrap;
}
.wp-tb-group {
  display: flex;
  align-items: center;
  gap: 6px;
}
.wp-tb-label {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-tb-dirty {
  margin-left: 2px;
}
</style>
