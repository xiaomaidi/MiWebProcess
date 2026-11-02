<template>
  <el-dialog v-model="visible" title="AI 生成工作流" width="620px">
    <el-alert
      title="生成流程节点草稿；应用后会作为新流程填入编辑器，仍需保存和发布。"
      type="info"
      :closable="false"
      show-icon
      class="wp-ai-wf-note"
    />
    <el-form label-position="top">
      <el-form-item label="描述审批流程">
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="4"
          maxlength="1500"
          show-word-limit
          placeholder="例如：采购订单先由部门审批，金额超过 2 万进入财务会签，否则直接通过。"
        />
      </el-form-item>
    </el-form>
    <div class="wp-ai-wf-examples">
      <span>示例：</span>
      <el-button size="small" text @click="prompt = '采购订单先由部门审批，金额超过 2 万进入财务会签，否则直接通过'">采购审批</el-button>
      <el-button size="small" text @click="prompt = '员工请假先由直属主管审批，再由人事审批'">请假审批</el-button>
    </div>
    <el-alert v-for="w in warnings" :key="w" :title="w" type="warning" :closable="false" show-icon class="wp-ai-wf-warn" />
    <el-table v-if="draft" :data="draft.nodes" size="small" border class="wp-ai-wf-preview">
      <el-table-column prop="name" label="节点" min-width="150" />
      <el-table-column prop="type" label="类型" width="90" />
      <el-table-column label="配置" min-width="220">
        <template #default="{ row }">
          <span v-if="row.type === 'approval'">
            {{ row.assignee_role }} / {{ row.mode }} / {{ row.timeout_hours || 0 }}h
          </span>
          <span v-else>
            {{ row.condition?.field }} {{ row.condition?.operator }} {{ row.condition?.value }}
          </span>
        </template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="generate">生成流程</el-button>
      <el-button v-if="draft" type="success" @click="useDraft">应用到设计器</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const props = defineProps<{ modelValue: boolean; appId: number }>();
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "generated", draft: any): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});
const prompt = ref("");
const draft = ref<any>(null);
const warnings = ref<string[]>([]);
const loading = ref(false);

async function generate() {
  if (!prompt.value.trim()) {
    ElMessage.warning("请描述审批流程");
    return;
  }
  loading.value = true;
  draft.value = null;
  try {
    const res = await api.post("/ai/workflows/draft/", {
      app_id: props.appId,
      prompt: prompt.value.trim(),
    });
    draft.value = res.draft;
    warnings.value = res.warnings || [];
    if (!warnings.value.length) ElMessage.success("流程草稿已生成");
  } catch (e: any) {
    ElMessage.error(e?.message || "生成失败");
  } finally {
    loading.value = false;
  }
}

function useDraft() {
  if (draft.value) emit("generated", draft.value);
  visible.value = false;
}
</script>

<style scoped>
.wp-ai-wf-note {
  margin-bottom: 14px;
}
.wp-ai-wf-examples {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: -8px;
  color: #909399;
  font-size: 12px;
}
.wp-ai-wf-warn {
  margin-top: 8px;
}
.wp-ai-wf-preview {
  margin-top: 12px;
}
</style>
