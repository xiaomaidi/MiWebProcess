<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>应用设计 Token</h2>
        <p class="wp-page-desc">应用下所有未单独设置 Token 的页面会自动继承这里的设计变量。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="router.push(`/admin/apps/${appId}`)">返回应用</el-button>
        <el-button @click="exportTokens">导出 JSON</el-button>
        <el-button @click="fileInput?.click()">导入 JSON</el-button>
        <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="importTokens" />
        <el-button type="primary" :loading="saving" @click="save">保存并发布</el-button>
      </div>
    </div>

    <el-card>
      <el-form label-position="top" size="small">
        <el-form-item label="Token 预设">
          <el-select v-model="preset" style="width: 260px" @change="applyPreset">
            <el-option label="深色游戏" value="dark-game" />
            <el-option label="浅色后台" value="light-admin" />
            <el-option label="企业蓝" value="corporate-blue" />
            <el-option label="数据大屏" value="dashboard-dark" />
            <el-option label="暖色内容" value="warm" />
          </el-select>
        </el-form-item>
      </el-form>

      <div v-for="group in tokenGroups" :key="group.title" class="wp-app-token-group">
        <div class="wp-app-token-title">{{ group.title }}</div>
        <div class="wp-app-token-grid">
          <label v-for="field in group.fields" :key="field.path" class="wp-app-token-field">
            <span>{{ field.label }}</span>
            <el-color-picker
              v-if="field.color"
              :model-value="tokenValue(field.path)"
              size="small"
              @change="(value: string | null) => setToken(field.path, value || '')"
            />
            <el-input
              v-else
              :model-value="tokenValue(field.path)"
              size="small"
              @input="(value: string) => setToken(field.path, value)"
            />
          </label>
        </div>
      </div>
    </el-card>

    <el-card style="margin-top: 14px">
      <template #header>
        <div class="wp-app-token-history-head">
          <strong>Token 版本历史</strong>
          <span>最近 20 个版本</span>
        </div>
      </template>
      <el-table :data="history" size="small" border>
        <el-table-column label="时间" width="190">
          <template #default="{ row }">{{ formatTime(row.saved_at) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="操作人" width="120" />
        <el-table-column label="预设" min-width="140">
          <template #default="{ row }">{{ row.tokens?.preset || "custom" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ $index }">
            <el-button size="small" @click="rollback($index)">回滚</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="还没有历史版本" :image-size="50" /></template>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";
import { formatTime } from "@/utils";
import { TOKEN_PRESETS, clone, normalizeTokens, type DesignTokens } from "@/design/tokens";

const route = useRoute();
const router = useRouter();
const appId = Number(route.params.appId);
const saving = ref(false);
const preset = ref("light-admin");
const fileInput = ref<HTMLInputElement | null>(null);
const history = ref<any[]>([]);
const form = reactive<DesignTokens>(normalizeTokens({ preset: "light-admin" }));

const tokenGroups = [
  {
    title: "颜色",
    fields: [
      { path: "color.bg", label: "背景", color: true },
      { path: "color.surface", label: "卡片", color: true },
      { path: "color.text", label: "正文", color: true },
      { path: "color.muted", label: "次要文字", color: true },
      { path: "color.accent", label: "强调色", color: true },
      { path: "color.border", label: "边框", color: true },
      { path: "color.success", label: "成功", color: true },
      { path: "color.warning", label: "警告", color: true },
      { path: "color.danger", label: "危险", color: true },
    ],
  },
  {
    title: "间距",
    fields: [
      { path: "space.xs", label: "XS", color: false },
      { path: "space.sm", label: "SM", color: false },
      { path: "space.md", label: "MD", color: false },
      { path: "space.lg", label: "LG", color: false },
      { path: "space.xl", label: "XL", color: false },
    ],
  },
  {
    title: "字体",
    fields: [
      { path: "font.family", label: "字体", color: false },
      { path: "font.body", label: "正文", color: false },
      { path: "font.title", label: "标题", color: false },
      { path: "font.mono", label: "等宽", color: false },
    ],
  },
  {
    title: "圆角 / 阴影",
    fields: [
      { path: "radius.sm", label: "圆角 SM", color: false },
      { path: "radius.md", label: "圆角 MD", color: false },
      { path: "radius.lg", label: "圆角 LG", color: false },
      { path: "shadow.sm", label: "阴影 SM", color: false },
      { path: "shadow.md", label: "阴影 MD", color: false },
      { path: "shadow.lg", label: "阴影 LG", color: false },
    ],
  },
  {
    title: "响应式断点",
    fields: [
      { path: "breakpoint.sm", label: "SM", color: false },
      { path: "breakpoint.md", label: "MD", color: false },
      { path: "breakpoint.lg", label: "LG", color: false },
      { path: "breakpoint.xl", label: "XL", color: false },
    ],
  },
] as const;

function tokenValue(path: string): string {
  const [group, key] = path.split(".");
  return String((form as any)[group]?.[key] ?? "");
}

function setToken(path: string, value: string) {
  const [group, key] = path.split(".");
  (form as any)[group][key] = value;
}

function applyPreset() {
  const next = TOKEN_PRESETS[preset.value] || TOKEN_PRESETS["light-admin"];
  Object.assign(form, clone(next));
}

async function load() {
  const [app, versions] = await Promise.all([
    api.get<any>(`/apps/${appId}/`),
    api.get<any>(`/apps/${appId}/design-tokens/versions/`),
  ]);
  const tokens = normalizeTokens(app.design_tokens || { preset: "light-admin" });
  Object.assign(form, tokens);
  preset.value = tokens.preset || "light-admin";
  history.value = versions.history || [];
}

async function save() {
  saving.value = true;
  try {
    await api.patch(`/apps/${appId}/`, { design_tokens: clone(form) });
    ElMessage.success("应用 Token 已保存，页面刷新后生效");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function rollback(index: number) {
  try {
    await ElMessageBox.confirm("回滚到该 Token 版本？", "确认", { type: "warning" });
    await api.post(`/apps/${appId}/design-tokens/versions/`, { index });
    ElMessage.success("已回滚");
    await load();
  } catch {
    /* 取消或已提示 */
  }
}

function exportTokens() {
  const blob = new Blob([JSON.stringify(form, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "app-design-tokens.json";
  link.click();
  URL.revokeObjectURL(url);
}

function importTokens(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      Object.assign(form, normalizeTokens(JSON.parse(String(reader.result || "{}"))));
      preset.value = form.preset || "custom";
      ElMessage.success("Token JSON 已导入");
    } catch {
      ElMessage.error("Token JSON 格式不正确");
    }
  };
  reader.readAsText(file);
  input.value = "";
}

onMounted(load);
</script>

<style scoped>
.wp-app-token-group {
  margin-bottom: 16px;
}
.wp-app-token-title {
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.wp-app-token-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px 16px;
}
.wp-app-token-field {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-app-token-field > span {
  width: 64px;
  flex: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-app-token-history-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.wp-app-token-history-head span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
@media (max-width: 900px) {
  .wp-app-token-grid {
    grid-template-columns: 1fr;
  }
}
</style>
