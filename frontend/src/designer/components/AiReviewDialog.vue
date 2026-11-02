<template>
  <el-dialog
    :model-value="modelValue"
    title="AI 评审"
    width="760px"
    @update:model-value="emit('update:modelValue', $event)"
    @open="onOpen"
  >
    <el-tabs v-model="mode" @tab-change="onTabChange">
      <el-tab-pane label="结构评审" name="structure">
        <div v-loading="loading" class="wp-ai-review">
          <div v-if="structure" class="wp-ai-review-score">
            <el-progress type="circle" :percentage="structure.score" :width="86" :color="scoreColor(structure.score)" />
            <div>
              <strong>{{ structure.summary }}</strong>
              <p>基于页面结构、数据绑定、SEO 和可维护性规则检查。</p>
            </div>
          </div>
          <el-table v-if="structure" :data="structure.issues" size="small" border max-height="360">
            <el-table-column label="级别" width="80">
              <template #default="{ row }">
                <el-tag size="small" :type="row.level === 'error' ? 'danger' : row.level === 'warning' ? 'warning' : 'info'">
                  {{ row.level }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="问题" min-width="210" />
            <el-table-column prop="suggestion" label="建议" min-width="210" />
          </el-table>
          <el-empty v-if="structure && !structure.issues.length" description="页面结构良好，没有发现明显问题" :image-size="60" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="截图评审" name="visual">
        <div v-loading="visualLoading" class="wp-ai-review">
          <div class="wp-ai-visual-toolbar">
            <el-button type="primary" plain :loading="visualLoading" @click="runVisual">截取当前画布并评审</el-button>
            <span class="wp-ai-hint">把画布渲染成图片，检查留白、对比度、配色与视觉层级。</span>
          </div>
          <div v-if="visual" class="wp-ai-visual-body">
            <div class="wp-ai-visual-left">
              <img v-if="snapshot" :src="snapshot" alt="画布截图" class="wp-ai-snapshot" />
              <div class="wp-ai-metrics">
                <el-tag size="small" effect="plain">模式：{{ visual.mode === "vision" ? `视觉模型 ${visual.model}` : "本地像素" }}</el-tag>
                <el-tag size="small" effect="plain">{{ visual.metrics.width }}×{{ visual.metrics.height }}</el-tag>
                <el-tag size="small" effect="plain">留白 {{ Math.round((visual.metrics.blank_ratio || 0) * 100) }}%</el-tag>
                <el-tag size="small" effect="plain">对比度 {{ visual.metrics.contrast }}</el-tag>
              </div>
            </div>
            <div class="wp-ai-visual-right">
              <div class="wp-ai-review-score compact">
                <el-progress type="circle" :percentage="visual.score" :width="72" :color="scoreColor(visual.score)" />
                <div><strong>{{ visual.summary }}</strong></div>
              </div>
              <el-table :data="visual.issues" size="small" border max-height="300">
                <el-table-column label="级别" width="74">
                  <template #default="{ row }">
                    <el-tag size="small" :type="row.level === 'error' ? 'danger' : row.level === 'warning' ? 'warning' : 'info'">
                      {{ row.level }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="message" label="问题" min-width="180" />
                <el-table-column prop="suggestion" label="建议" min-width="180" />
              </el-table>
            </div>
          </div>
          <el-alert v-if="visual?.warnings?.length" type="info" :closable="false" show-icon style="margin-top: 10px">
            <div v-for="warning in visual.warnings" :key="warning">{{ warning }}</div>
          </el-alert>
          <el-empty v-if="!visual && !visualLoading" description="点击上方按钮生成截图评审" :image-size="60" />
        </div>
      </el-tab-pane>
    </el-tabs>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" :loading="loading || visualLoading" @click="onTabChange(mode)">重新评审</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { PageSchema } from "@/types";
import { captureElement, findCanvasElement } from "../screenshot";

const props = defineProps<{ modelValue: boolean; appId: number; schema: PageSchema | null; pageName?: string }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void }>();

const mode = ref("structure");
const loading = ref(false);
const visualLoading = ref(false);
const structure = ref<any>(null);
const visual = ref<any>(null);
const snapshot = ref("");

function scoreColor(score: number) {
  return score >= 85 ? "#67c23a" : score >= 60 ? "#e6a23c" : "#f56c6c";
}

function onOpen() {
  if (mode.value === "structure" && !structure.value) runStructure();
  if (mode.value === "visual" && !visual.value) runVisual();
}

function onTabChange(name: string) {
  if (name === "structure") runStructure();
  else runVisual();
}

async function runStructure() {
  if (!props.schema) return;
  loading.value = true;
  structure.value = null;
  try {
    structure.value = await api.post("/ai/design/review/", { app_id: props.appId, schema: props.schema });
  } catch (e: any) {
    ElMessage.error(e?.message || "评审失败");
  } finally {
    loading.value = false;
  }
}

async function runVisual() {
  const canvas = findCanvasElement();
  if (!canvas) {
    ElMessage.warning("没有找到画布，请先打开页面");
    return;
  }
  visualLoading.value = true;
  visual.value = null;
  try {
    const shot = await captureElement(canvas);
    snapshot.value = shot.dataUrl;
    visual.value = await api.post("/ai/design/visual-review/", {
      app_id: props.appId,
      image: shot.dataUrl,
      schema: props.schema,
      page_name: props.pageName || "",
    });
  } catch (e: any) {
    ElMessage.error(e?.message || "截图评审失败");
  } finally {
    visualLoading.value = false;
  }
}
</script>

<style scoped>
.wp-ai-review-score {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: 16px;
  padding: 14px 16px;
  background: #f7f8fa;
  border-radius: 8px;
}
.wp-ai-review-score.compact {
  padding: 8px 10px;
  gap: 12px;
  margin-bottom: 8px;
}
.wp-ai-review-score strong {
  font-size: 15px;
}
.wp-ai-review-score p {
  margin: 5px 0 0;
  color: #86909c;
  font-size: 12px;
}
.wp-ai-visual-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.wp-ai-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-ai-visual-body {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 14px;
}
.wp-ai-snapshot {
  width: 100%;
  border: 1px solid var(--el-border-color-light);
  border-radius: 6px;
  background: #fff;
}
.wp-ai-metrics {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
</style>
