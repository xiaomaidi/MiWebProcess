<template>
  <el-dialog v-model="visible" title="AI 写内容" width="640px">
    <el-alert
      title="生成标题、摘要和正文草稿，确认后会填入新增记录表单，不会直接保存。"
      type="info"
      :closable="false"
      show-icon
      class="wp-ai-content-note"
    />
    <el-form label-position="top">
      <el-form-item label="写什么内容？">
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="4"
          maxlength="1500"
          show-word-limit
          placeholder="例如：写一篇 2026 年独立游戏趋势观察，面向游戏资讯站读者。"
        />
      </el-form-item>
      <el-form-item label="生成数量">
        <el-input-number v-model="count" :min="1" :max="5" />
        <span class="wp-ai-content-hint">批量生成会创建多篇不同角度的草稿</span>
      </el-form-item>
    </el-form>
    <div class="wp-ai-content-examples">
      <span>示例：</span>
      <el-button size="small" text @click="prompt = '写一篇本周游戏资讯盘点，覆盖新作、硬件和电竞赛事'">游戏周报</el-button>
      <el-button size="small" text @click="prompt = '写一篇 RTX 5090 深度评测，包含性能、功耗和购买建议'">硬件评测</el-button>
    </div>
    <el-alert v-for="w in warnings" :key="w" :title="w" type="warning" :closable="false" show-icon class="wp-ai-content-warn" />
    <el-table v-if="batchDrafts.length" :data="batchDrafts" size="small" border class="wp-ai-content-preview">
      <el-table-column type="index" width="45" />
      <el-table-column prop="title" label="标题" min-width="300" />
      <el-table-column prop="status" label="状态" width="90" />
    </el-table>
    <el-table v-else-if="draft" :data="previewRows" size="small" border class="wp-ai-content-preview">
      <el-table-column prop="key" label="字段" width="120" />
      <el-table-column prop="value" label="生成内容" show-overflow-tooltip />
    </el-table>
    <div v-if="draft && !batchDrafts.length" class="wp-ai-translate">
      <span>翻译草稿：</span>
      <el-select v-model="targetLang" size="small" style="width: 120px">
        <el-option label="English" value="en" />
        <el-option label="日本語" value="ja" />
        <el-option label="한국어" value="ko" />
      </el-select>
      <el-button size="small" :loading="translating" @click="translateDraft">翻译</el-button>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button v-if="count > 1" :loading="loading" @click="generateBatch">批量生成</el-button>
      <el-button type="primary" :loading="loading" @click="generate">生成内容</el-button>
      <el-button v-if="draft && !batchDrafts.length" type="success" @click="useDraft">填入新增表单</el-button>
      <el-button v-if="batchDrafts.length" type="success" @click="useBatch">创建全部草稿</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const props = defineProps<{
  modelValue: boolean;
  appId: number;
  modelId: number;
  modelName: string;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "generated", draft: Record<string, any>): void;
  (e: "batch", drafts: Record<string, any>[]): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});
const prompt = ref("");
const draft = ref<Record<string, any> | null>(null);
const batchDrafts = ref<any[]>([]);
const count = ref(1);
const warnings = ref<string[]>([]);
const loading = ref(false);
const translating = ref(false);
const targetLang = ref("en");
const previewRows = computed(() =>
  Object.entries(draft.value || {}).map(([key, value]) => ({
    key,
    value: typeof value === "string" ? value.replace(/<[^>]+>/g, " ").slice(0, 180) : JSON.stringify(value),
  }))
);

async function generate() {
  if (!prompt.value.trim()) {
    ElMessage.warning("请填写内容主题");
    return;
  }
  loading.value = true;
  draft.value = null;
  batchDrafts.value = [];
  try {
    const res = await api.post("/ai/content/draft/", {
      app_id: props.appId,
      model_id: props.modelId,
      prompt: prompt.value.trim(),
    });
    draft.value = res.draft;
    warnings.value = res.warnings || [];
    if (!warnings.value.length) ElMessage.success("内容草稿已生成");
  } catch (e: any) {
    ElMessage.error(e?.message || "生成失败");
  } finally {
    loading.value = false;
  }
}

async function generateBatch() {
  if (!prompt.value.trim()) {
    ElMessage.warning("请填写内容主题");
    return;
  }
  loading.value = true;
  draft.value = null;
  batchDrafts.value = [];
  try {
    const res = await api.post("/ai/content/batch/", {
      app_id: props.appId,
      model_id: props.modelId,
      prompt: prompt.value.trim(),
      count: count.value,
    });
    batchDrafts.value = res.drafts || [];
    warnings.value = res.warnings || [];
    ElMessage.success(`已生成 ${batchDrafts.value.length} 篇草稿`);
  } catch (e: any) {
    ElMessage.error(e?.message || "批量生成失败");
  } finally {
    loading.value = false;
  }
}

async function translateDraft() {
  if (!draft.value) return;
  translating.value = true;
  try {
    const res = await api.post("/ai/translate/", {
      app_id: props.appId,
      data: draft.value,
      target_lang: targetLang.value,
    });
    draft.value = res.data;
    warnings.value = res.warnings || [];
    if (res.provider === "llm") ElMessage.success("翻译完成");
  } catch (e: any) {
    ElMessage.error(e?.message || "翻译失败");
  } finally {
    translating.value = false;
  }
}

function useDraft() {
  if (draft.value) emit("generated", draft.value);
  visible.value = false;
}

function useBatch() {
  if (batchDrafts.value.length) emit("batch", batchDrafts.value);
  visible.value = false;
}
</script>

<style scoped>
.wp-ai-content-note {
  margin-bottom: 14px;
}
.wp-ai-content-hint {
  margin-left: 10px;
  color: #909399;
  font-size: 12px;
}
.wp-ai-content-examples {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: -8px;
  color: #909399;
  font-size: 12px;
}
.wp-ai-content-warn {
  margin-top: 8px;
}
.wp-ai-content-preview {
  margin-top: 12px;
}
.wp-ai-translate {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  color: #909399;
  font-size: 12px;
}
</style>
