<template>
  <div class="wp-ai-admin" v-loading="loading">
    <header class="wp-ai-admin-head">
      <div>
        <h2>AI 管理</h2>
        <p>配置 OpenAI-compatible 供应商；API Key 加密存储，不会回传到浏览器。</p>
      </div>
      <div>
        <el-button @click="load">刷新</el-button>
        <el-button type="primary" @click="openCreate">+ 添加 Provider</el-button>
      </div>
    </header>

    <el-alert
      v-if="!providers.length"
      title="当前未配置 Provider，AI 会使用环境变量或本地规则模式。"
      type="info"
      :closable="false"
      show-icon
      class="wp-ai-admin-note"
    />

    <el-card shadow="never">
      <el-table :data="providers" border stripe>
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column prop="provider_type" label="类型" width="120" />
        <el-table-column prop="model" label="模型" min-width="150" />
        <el-table-column prop="base_url" label="Base URL" min-width="220" show-overflow-tooltip />
        <el-table-column label="Key" width="120">
          <template #default="{ row }">{{ row.api_key || "未设置" }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag v-if="row.is_default" size="small" type="success">默认</el-tag>
            <el-tag v-else-if="row.enabled" size="small">启用</el-tag>
            <el-tag v-else size="small" type="info">停用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="最近测试" width="180">
          <template #default="{ row }">
            <span v-if="row.last_error" class="wp-ai-error">{{ row.last_error }}</span>
            <span v-else-if="row.last_test_at">{{ new Date(row.last_test_at).toLocaleString() }}</span>
            <span v-else class="wp-ai-muted">未测试</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="270" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :loading="testingId === row.id" @click="test(row)">测试</el-button>
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="!row.is_default" size="small" type="success" plain @click="setDefault(row)">设为默认</el-button>
            <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card shadow="never" class="wp-ai-usage">
      <template #header>
        <div class="wp-ai-usage-head">
          <span>AI 使用情况</span>
          <span class="wp-ai-muted">按字符数估算 token</span>
        </div>
      </template>
      <div class="wp-ai-usage-stats" v-if="usage">
        <div><strong>{{ usage.totals?.calls || 0 }}</strong><span>调用次数</span></div>
        <div><strong>{{ usage.totals?.tokens || 0 }}</strong><span>估算 tokens</span></div>
        <div><strong>{{ usage.totals?.prompt_chars || 0 }}</strong><span>输入字符</span></div>
        <div><strong>{{ usage.totals?.response_chars || 0 }}</strong><span>输出字符</span></div>
      </div>
      <el-table :data="usage?.by_action || []" size="small" border max-height="220">
        <el-table-column prop="action" label="操作" />
        <el-table-column prop="calls" label="次数" width="90" />
        <el-table-column prop="tokens" label="估算 tokens" width="120" />
      </el-table>
    </el-card>

    <el-dialog v-model="dialogOpen" :title="editing ? '编辑 Provider' : '添加 Provider'" width="620px">
      <el-form label-position="top">
        <el-form-item label="名称"><el-input v-model="form.name" placeholder="例如 DeepSeek 生产环境" /></el-form-item>
        <el-form-item label="供应商类型">
          <el-select v-model="form.provider_type" style="width: 100%" @change="applyPreset">
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="OpenAI" value="openai" />
            <el-option label="Ollama" value="ollama" />
            <el-option label="OpenAI-compatible" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL"><el-input v-model="form.base_url" placeholder="https://api.deepseek.com/v1" /></el-form-item>
        <el-form-item label="模型"><el-input v-model="form.model" placeholder="deepseek-chat" /></el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            :placeholder="editing ? '已保存；留空表示不修改' : 'sk-...'"
          />
        </el-form-item>
        <div class="wp-ai-form-grid">
          <el-form-item label="Temperature">
            <el-input-number v-model="form.temperature" :min="0" :max="2" :step="0.1" style="width: 100%" />
          </el-form-item>
          <el-form-item label="超时秒数">
            <el-input-number v-model="form.timeout" :min="5" :max="300" style="width: 100%" />
          </el-form-item>
        </div>
        <el-form-item label="状态">
          <el-switch v-model="form.enabled" active-text="启用" inactive-text="停用" />
          <el-switch v-model="form.is_default" active-text="设为默认" style="margin-left: 20px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";

const providers = ref<any[]>([]);
const usage = ref<any>(null);
const loading = ref(false);
const dialogOpen = ref(false);
const editing = ref<any>(null);
const saving = ref(false);
const testingId = ref<number | null>(null);

const form = reactive({
  name: "",
  provider_type: "deepseek",
  base_url: "https://api.deepseek.com/v1",
  model: "deepseek-chat",
  api_key: "",
  enabled: true,
  is_default: false,
  temperature: 0.4,
  timeout: 90,
});

const presets: Record<string, { base: string; model: string }> = {
  deepseek: { base: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  openai: { base: "https://api.openai.com/v1", model: "gpt-4o-mini" },
  ollama: { base: "http://127.0.0.1:11434/v1", model: "llama3.1" },
  custom: { base: "", model: "" },
};

function applyPreset(type: string) {
  const preset = presets[type];
  if (!preset) return;
  if (!form.base_url || form.base_url.startsWith("http")) form.base_url = preset.base;
  if (!form.model || form.model === "deepseek-chat") form.model = preset.model;
}

function resetForm() {
  Object.assign(form, {
    name: "",
    provider_type: "deepseek",
    base_url: "https://api.deepseek.com/v1",
    model: "deepseek-chat",
    api_key: "",
    enabled: true,
    is_default: false,
    temperature: 0.4,
    timeout: 90,
  });
}

function openCreate() {
  editing.value = null;
  resetForm();
  dialogOpen.value = true;
}

function openEdit(row: any) {
  editing.value = row;
  Object.assign(form, {
    name: row.name,
    provider_type: row.provider_type,
    base_url: row.base_url,
    model: row.model,
    api_key: "",
    enabled: row.enabled,
    is_default: row.is_default,
    temperature: row.temperature,
    timeout: row.timeout,
  });
  dialogOpen.value = true;
}

async function load() {
  loading.value = true;
  try {
    const [res, use] = await Promise.all([
      api.get<any>("/ai/providers/"),
      api.get<any>("/ai/usage/").catch(() => null),
    ]);
    providers.value = Array.isArray(res) ? res : res?.results || [];
    usage.value = use;
  } catch (e: any) {
    ElMessage.error(e?.message || "加载 Provider 失败");
  } finally {
    loading.value = false;
  }
}

async function save() {
  if (!form.name.trim() || !form.base_url.trim() || !form.model.trim()) {
    ElMessage.warning("请填写名称、Base URL 和模型");
    return;
  }
  saving.value = true;
  try {
    const body = { ...form, api_key: form.api_key || (editing.value ? "***" : "") };
    if (editing.value) {
      await api.patch(`/ai/providers/${editing.value.id}/`, body);
      ElMessage.success("Provider 已更新");
    } else {
      await api.post("/ai/providers/", body);
      ElMessage.success("Provider 已添加");
    }
    dialogOpen.value = false;
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function test(row: any) {
  testingId.value = row.id;
  try {
    const res = await api.post(`/ai/providers/${row.id}/test/`, {});
    if (res.ok) ElMessage.success(`连接成功 ${res.latency_ms}ms：${res.message}`);
    else ElMessage.error(`连接失败：${res.message}`);
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "测试失败");
  } finally {
    testingId.value = null;
  }
}

async function setDefault(row: any) {
  try {
    await api.post(`/ai/providers/${row.id}/default/`, {});
    ElMessage.success("已设为默认 Provider");
    await load();
  } catch (e: any) {
    ElMessage.error(e?.message || "设置失败");
  }
}

async function remove(row: any) {
  try {
    await ElMessageBox.confirm(`删除 Provider「${row.name}」？`, "确认", { type: "warning" });
    await api.del(`/ai/providers/${row.id}/`);
    ElMessage.success("已删除");
    await load();
  } catch {
    /* cancel */
  }
}

onMounted(load);
</script>

<style scoped>
.wp-ai-admin {
  max-width: 1400px;
  margin: 0 auto;
}
.wp-ai-admin-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.wp-ai-admin-head h2 {
  margin: 0 0 4px;
  font-size: 22px;
}
.wp-ai-admin-head p {
  margin: 0;
  color: #86909c;
  font-size: 12px;
}
.wp-ai-admin-note {
  margin-bottom: 14px;
}
.wp-ai-error {
  color: #f56c6c;
  font-size: 11px;
}
.wp-ai-muted {
  color: #aab1bb;
  font-size: 12px;
}
.wp-ai-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.wp-ai-usage {
  margin-top: 16px;
}
.wp-ai-usage-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.wp-ai-usage-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.wp-ai-usage-stats div {
  padding: 12px;
  background: #f7f8fa;
  border-radius: 6px;
}
.wp-ai-usage-stats strong {
  display: block;
  font-size: 20px;
}
.wp-ai-usage-stats span {
  color: #86909c;
  font-size: 12px;
}
</style>
