<template>
  <el-dialog
    :model-value="modelValue"
    :title="mode === 'edit' ? 'AI 修改页面' : 'AI 生成页面'"
    width="720px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
    @open="loadStatus"
  >
    <el-radio-group v-model="mode" class="wp-ai-mode" @change="result = null">
      <el-radio-button value="generate">生成新页面</el-radio-button>
      <el-radio-button value="edit" :disabled="!schema">修改当前页面</el-radio-button>
    </el-radio-group>
    <el-alert
      :title="status?.configured ? `模型模式：${status.model}` : '本地模板模式：未配置 AI_API_KEY'"
      :description="status?.configured ? 'AI 只生成/修改草稿，应用到画布后仍需你检查并保存。' : '当前使用内置规则生成/编辑；配置 AI_API_KEY 后会切换为模型生成。'"
      type="info"
      :closable="false"
      show-icon
      class="wp-ai-note"
    />
    <el-form label-position="top">
      <el-form-item :label="mode === 'edit' ? '你希望怎么修改当前页面？' : '你希望生成什么页面？'">
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="5"
          maxlength="3000"
          show-word-limit
          :placeholder="mode === 'edit' ? '例如：把首屏改成深色，标题改为「游戏资讯」，按钮文字改为「开始浏览」。' : '例如：做一个游戏资讯首页，顶部导航，首屏大标题和按钮，下面是文章卡片列表，整体深色风格。'"
        />
      </el-form-item>
    </el-form>
    <div class="wp-ai-examples">
      <span>示例：</span>
      <el-button v-for="ex in examples" :key="ex" size="small" text @click="prompt = ex">{{ ex }}</el-button>
    </div>

    <div v-if="variants.length" class="wp-ai-result">
      <el-radio-group v-model="selectedVariant" class="wp-ai-variants">
        <el-radio-button v-for="(v, i) in variants" :key="v.code" :value="i">
          {{ v.code }} · {{ v.label }}
        </el-radio-button>
      </el-radio-group>
      <div class="wp-ai-summary">
        <span>生成方式：本地主题方案</span>
        <span>节点数：{{ variants[selectedVariant]?.schema?.nodes ? Object.keys(variants[selectedVariant].schema.nodes).length : 0 }}</span>
      </div>
      <div class="wp-ai-preview">
        <strong>页面结构预览</strong>
        <pre>{{ structurePreview }}</pre>
      </div>
    </div>

    <div v-else-if="result" class="wp-ai-result">
      <el-alert
        v-for="w in result.warnings || []"
        :key="w"
        :title="w"
        type="warning"
        :closable="false"
        show-icon
        class="wp-ai-warn"
      />
      <div class="wp-ai-summary">
        <span>生成方式：{{ result.provider }}</span>
        <span>节点数：{{ result.summary?.nodes }}</span>
        <span>标题：{{ result.summary?.title }}</span>
      </div>
      <div class="wp-ai-preview">
        <strong>页面结构预览</strong>
        <pre>{{ structurePreview }}</pre>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button v-if="mode === 'generate'" :loading="loading" @click="generateVariants">生成 3 个方案</el-button>
      <el-button type="primary" :loading="loading" @click="generate">{{ mode === "edit" ? "执行修改" : "生成草稿" }}</el-button>
      <el-button v-if="result || variants.length" type="success" @click="apply">应用到画布</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { PageSchema } from "@/types";

const props = defineProps<{
  modelValue: boolean;
  appId: number;
  schema?: PageSchema | null;
}>();
const mode = ref<"generate" | "edit">("generate");
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "generated", schema: PageSchema): void;
}>();

const prompt = ref("");
const loading = ref(false);
const result = ref<any>(null);
const variants = ref<any[]>([]);
const selectedVariant = ref(0);
const status = ref<any>(null);
const generateExamples = [
  "做一个游戏资讯首页，深色风格，顶部导航、首屏标题、文章卡片列表",
  "做一个企业官网首页，蓝色主题，产品介绍、客户案例和联系按钮",
  "做一个采购订单管理页，顶部标题和订单数据表格",
  "做一个数据报表页，展示分组统计和柱状图",
];
const editExamples = [
  "把首屏改成深色，所有正文变浅色",
  "把首屏大标题改为「游戏资讯」",
  "把第一个按钮文字改为「开始浏览」",
];
const examples = computed(() => (mode.value === "edit" ? editExamples : generateExamples));

const activeSchema = computed<PageSchema | null>(() =>
  variants.value.length ? variants.value[selectedVariant.value]?.schema || null : result.value?.schema || null
);

const structurePreview = computed(() => {
  const nodes = activeSchema.value?.nodes || {};
  return Object.values(nodes)
    .slice(0, 18)
    .map((n: any) => `${n.type} · ${n.id}`)
    .join("\n");
});

async function loadStatus() {
  try {
    status.value = await api.get("/ai/status/");
  } catch {
    status.value = { configured: false, model: "local" };
  }
}

async function generate() {
  if (!prompt.value.trim()) {
    ElMessage.warning("请先描述你的需求");
    return;
  }
  if (mode.value === "edit" && !props.schema) {
    ElMessage.warning("当前没有可修改的页面");
    return;
  }
  loading.value = true;
  result.value = null;
  variants.value = [];
  try {
    if (mode.value === "edit") {
      result.value = await api.post("/ai/pages/edit/", {
        app_id: props.appId,
        prompt: prompt.value.trim(),
        schema: props.schema,
      });
      if (!result.value.changed) {
        ElMessage.warning("没有识别到可执行的修改，请换一种说法");
      } else {
        ElMessage.success("页面修改已生成");
      }
    } else {
      result.value = await api.post("/ai/pages/generate/", {
        app_id: props.appId,
        prompt: prompt.value.trim(),
      });
      ElMessage.success("页面草稿已生成");
    }
  } catch (e: any) {
    ElMessage.error(e?.message || "生成失败");
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    mode.value = "generate";
    prompt.value = "";
    result.value = null;
    variants.value = [];
    loadStatus();
  }
);

async function generateVariants() {
  if (!prompt.value.trim()) {
    ElMessage.warning("请先描述你想要的页面");
    return;
  }
  loading.value = true;
  result.value = null;
  variants.value = [];
  try {
    const res = await api.post("/ai/pages/variants/", {
      app_id: props.appId,
      prompt: prompt.value.trim(),
    });
    variants.value = res.variants || [];
    selectedVariant.value = 0;
    ElMessage.success("已生成 3 个主题方案");
  } catch (e: any) {
    ElMessage.error(e?.message || "生成方案失败");
  } finally {
    loading.value = false;
  }
}

function apply() {
  const target = activeSchema.value;
  if (!target) return;
  emit("generated", target);
  emit("update:modelValue", false);
}
</script>

<style scoped>
.wp-ai-mode {
  margin-bottom: 14px;
}
.wp-ai-variants {
  margin-bottom: 10px;
}
.wp-ai-note {
  margin-bottom: 16px;
}
.wp-ai-examples {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
  margin-top: -8px;
  color: #909399;
  font-size: 12px;
}
.wp-ai-result {
  margin-top: 16px;
}
.wp-ai-warn {
  margin-bottom: 8px;
}
.wp-ai-summary {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 12px;
  background: #f7f8fa;
  border-radius: 6px;
  color: #606266;
  font-size: 12px;
}
.wp-ai-preview {
  margin-top: 10px;
  font-size: 12px;
  color: #606266;
}
.wp-ai-preview pre {
  max-height: 180px;
  overflow: auto;
  background: #0f172a;
  color: #cbd5e1;
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.6;
}
</style>
