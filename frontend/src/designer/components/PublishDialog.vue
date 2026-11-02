<template>
  <el-dialog v-model="visible" title="发布页面" width="480px" :close-on-click-modal="false">
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
import { ElMessage } from "element-plus";
import { api } from "@/api";

const props = defineProps<{ modelValue: boolean; pageId: number }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "published", info: { version: number; changelog?: string }): void }>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});

const changelog = ref("");
const busy = ref(false);

async function publish() {
  if (!props.pageId) return;
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
