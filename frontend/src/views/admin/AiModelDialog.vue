<template>
  <el-dialog v-model="visible" title="AI 建模" width="620px">
    <el-alert
      title="根据业务描述生成字段草稿，创建前仍可在模型编辑器中调整。"
      type="info"
      :closable="false"
      show-icon
      class="wp-ai-model-note"
    />
    <el-form label-position="top">
      <el-form-item label="你希望管理什么业务数据？">
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="4"
          maxlength="1000"
          show-word-limit
          placeholder="例如：采购订单，需要订单号、供应商、金额、状态、下单日期和备注。"
        />
      </el-form-item>
    </el-form>
    <div class="wp-ai-model-examples">
      <span>示例：</span>
      <el-button size="small" text @click="prompt = '采购订单，需要订单号、供应商、金额、状态、下单日期和备注'">采购订单</el-button>
      <el-button size="small" text @click="prompt = '客户资料，需要姓名、电话、邮箱、公司和客户等级'">客户资料</el-button>
      <el-button size="small" text @click="prompt = '资讯文章，需要标题、摘要、正文、封面、作者和发布时间'">资讯文章</el-button>
    </div>

    <div v-if="draft" class="wp-ai-model-result">
      <el-alert v-for="w in warnings" :key="w" :title="w" type="warning" :closable="false" show-icon />
      <el-table :data="draft.fields" size="small" border>
        <el-table-column prop="name" label="字段名" width="130" />
        <el-table-column prop="label" label="显示名" width="120" />
        <el-table-column prop="type" label="类型" width="90" />
        <el-table-column label="必填" width="70">
          <template #default="{ row }">{{ row.required ? "是" : "否" }}</template>
        </el-table-column>
      </el-table>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="generate">生成字段</el-button>
      <el-button v-if="draft" type="success" @click="useDraft">在模型中编辑</el-button>
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
    ElMessage.warning("请描述业务数据");
    return;
  }
  loading.value = true;
  draft.value = null;
  try {
    const res = await api.post("/ai/models/draft/", {
      app_id: props.appId,
      prompt: prompt.value.trim(),
    });
    draft.value = res.draft;
    warnings.value = res.warnings || [];
    if (!warnings.value.length) ElMessage.success("字段草稿已生成");
  } catch (e: any) {
    ElMessage.error(e?.message || "AI 建模失败");
  } finally {
    loading.value = false;
  }
}

function useDraft() {
  emit("generated", draft.value);
  visible.value = false;
}
</script>

<style scoped>
.wp-ai-model-note {
  margin-bottom: 14px;
}
.wp-ai-model-examples {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  align-items: center;
  margin-top: -8px;
  color: #909399;
  font-size: 12px;
}
.wp-ai-model-result {
  margin-top: 14px;
}
.wp-ai-model-result :deep(.el-alert) {
  margin-bottom: 8px;
}
</style>
