<template>
  <el-dialog v-model="visible" title="发布页面" width="480px" :close-on-click-modal="false">
    <el-alert v-if="issues.length" :title="`发布前检查：${summary.error} 个错误，${summary.warning} 个警告`" :type="summary.error ? 'error' : 'warning'" :closable="false" show-icon style="margin-bottom: 12px">
      <div style="font-size: 11px">{{ issues.slice(0, 3).map(i => i.message).join('；') }}</div>
    </el-alert>
    <el-form label-position="top" size="small">
      <el-form-item label="发布说明 changelog">
        <el-input
          v-model="changelog"
          type="textarea"
          :rows="4"
          placeholder="本次发布的内容摘要"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="busy" @click="publish">发布</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { useSchemaStore } from "@/store/schema";
import { auditPage, auditSummary } from "../quality";

const props = defineProps<{ modelValue: boolean; pageId: number }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "published", info: { version: number; changelog?: string }): void }>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

const changelog = ref("");
const busy = ref(false);
const schemaStore = useSchemaStore();
const issues = computed(() => auditPage(schemaStore.schema));
const summary = computed(() => {
  const value = auditSummary(issues.value);
  return { error: value.error, warning: value.warn, total: value.total };
});

async function publish() {
  if (!props.pageId) return;
  if (summary.value.error) {
    try {
      await ElMessageBox.confirm(`有 ${summary.value.error} 个发布错误，仍要继续发布？`, "发布检查", { type: "warning" });
    } catch { return; }
  }
  busy.value = true;
  try {
    const res = await api.post(`/pages/${props.pageId}/publish/`, { changelog: changelog.value.trim() });
    ElMessage.success(`已发布 v${res?.version ?? ""}`);
    changelog.value = "";
    visible.value = false;
    emit("published", { version: res?.version, changelog: res?.changelog });
  } catch (err: any) {
    ElMessage.error(err?.message || "发布失败");
  } finally {
    busy.value = false;
  }
}
</script>
