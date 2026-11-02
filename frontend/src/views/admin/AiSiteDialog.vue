<template>
  <el-dialog v-model="visible" title="AI 建站" width="780px" @close="reset">
    <el-alert
      title="生成首页、列表页、详情页的草稿，不会自动发布。"
      description="你可以先修改页面路径；创建后逐页检查，再在设计器中发布。"
      type="info"
      :closable="false"
      show-icon
      class="wp-site-ai-note"
    />
    <el-form label-position="top">
      <el-form-item label="你希望建一个什么站点？">
        <el-input
          v-model="prompt"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          placeholder="例如：做一个游戏资讯站，包含首页、资讯列表和文章详情，深色科技风。"
        />
      </el-form-item>
    </el-form>
    <div class="wp-site-ai-examples">
      <span>示例：</span>
      <el-button size="small" text @click="prompt = '做一个游戏资讯站，包含首页、资讯列表和文章详情，深色科技风'">游戏资讯站</el-button>
      <el-button size="small" text @click="prompt = '做一个企业官网，包含首页、产品列表和产品详情，蓝色简洁风'">企业官网</el-button>
    </div>

    <el-table v-if="plan" :data="plan.pages" size="small" border class="wp-site-ai-pages">
      <el-table-column width="44">
        <template #default="{ row }"><el-checkbox v-model="row.selected" /></template>
      </el-table-column>
      <el-table-column label="页面名称" min-width="150">
        <template #default="{ row }"><el-input v-model="row.name" size="small" /></template>
      </el-table-column>
      <el-table-column label="路径" min-width="180">
        <template #default="{ row }"><el-input v-model="row.path" size="small" /></template>
      </el-table-column>
      <el-table-column prop="kind" label="类型" width="90" />
    </el-table>
    <el-alert
      v-for="w in plan?.warnings || []"
      :key="w"
      :title="w"
      type="warning"
      :closable="false"
      show-icon
      class="wp-site-ai-warn"
    />
    <div v-if="created.length" class="wp-site-ai-created">
      <strong>已创建草稿：</strong>
      <div v-for="item in created" :key="item.path">{{ item.name }} · /{{ item.path }}</div>
    </div>

    <template #footer>
      <el-button @click="visible = false">关闭</el-button>
      <el-button type="primary" :loading="generating" @click="generate">生成页面计划</el-button>
      <el-button v-if="plan" type="success" :loading="creating" @click="createPages">创建草稿页面</el-button>
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
  (e: "created"): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit("update:modelValue", v),
});
const prompt = ref("");
const plan = ref<any>(null);
const created = ref<any[]>([]);
const generating = ref(false);
const creating = ref(false);

async function generate() {
  if (!prompt.value.trim()) {
    ElMessage.warning("请先描述站点");
    return;
  }
  generating.value = true;
  plan.value = null;
  created.value = [];
  try {
    plan.value = await api.post("/ai/sites/plan/", { app_id: props.appId, prompt: prompt.value.trim() });
    for (const page of plan.value.pages || []) page.selected = true;
  } catch (e: any) {
    ElMessage.error(e?.message || "生成站点计划失败");
  } finally {
    generating.value = false;
  }
}

async function createPages() {
  const pages = (plan.value?.pages || []).filter((p: any) => p.selected);
  if (!pages.length) {
    ElMessage.warning("请至少选择一个页面");
    return;
  }
  creating.value = true;
  created.value = [];
  try {
    for (const page of pages) {
      const createdPage = await api.post(`/apps/${props.appId}/pages/`, {
        name: page.name,
        path: page.path,
        type: "page",
      });
      await api.put(`/pages/${createdPage.id}/schema/`, { schema: page.schema });
      created.value.push({ name: page.name, path: page.path, id: createdPage.id });
    }
    ElMessage.success(`已创建 ${created.value.length} 个草稿页面`);
    emit("created");
  } catch (e: any) {
    ElMessage.error(e?.message || "页面创建失败，请检查路径是否重复");
  } finally {
    creating.value = false;
  }
}

function reset() {
  prompt.value = "";
  plan.value = null;
  created.value = [];
}
</script>

<style scoped>
.wp-site-ai-note {
  margin-bottom: 14px;
}
.wp-site-ai-examples {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
  align-items: center;
  color: #909399;
  font-size: 12px;
  margin-top: -8px;
}
.wp-site-ai-pages {
  margin-top: 16px;
}
.wp-site-ai-warn {
  margin-top: 8px;
}
.wp-site-ai-created {
  margin-top: 12px;
  padding: 10px 12px;
  background: #f0f9eb;
  color: #529b2e;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.8;
}
</style>
