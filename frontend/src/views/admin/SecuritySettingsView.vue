<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>安全设置</h2>
        <p class="wp-page-desc">SSRF 白名单：控制数据源/AI 出站请求允许访问的主机。</p>
      </div>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </div>

    <el-card>
      <el-form label-position="top">
        <el-form-item label="允许访问的主机（逗号或换行分隔）">
          <el-input
            v-model="hostsText"
            type="textarea"
            :rows="6"
            placeholder="api.deepseek.com&#10;localhost"
          />
          <div class="wp-security-hint">
            只写主机名，不要带 http://、端口或路径；支持子域名，例如 example.com 会放行 api.example.com。
          </div>
        </el-form-item>
        <el-form-item label="允许内网地址">
          <el-switch v-model="allowPrivate" />
          <span class="wp-security-hint" style="margin-left: 10px">
            本地 Ollama / 内网服务才需要开启；生产环境建议关闭。
          </span>
        </el-form-item>
        <el-form-item label="环境变量默认值">
          <el-tag type="info" effect="plain">
            主机：{{ envHosts || "（空）" }}
          </el-tag>
          <el-tag type="info" effect="plain" style="margin-left: 6px">
            内网：{{ envPrivate ? "允许" : "拒绝" }}
          </el-tag>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card style="margin-top: 14px">
      <template #header><strong>测试出站地址</strong></template>
      <div class="wp-security-test">
        <el-input v-model="testUrl" placeholder="http://localhost:11434/api/tags" />
        <el-button :loading="testing" @click="testUrlNow">测试</el-button>
      </div>
      <el-alert
        v-if="testResult"
        :type="testResult.allowed ? 'success' : 'error'"
        :title="testResult.allowed ? '允许访问' : '已拦截'"
        :description="testResult.detail"
        :closable="false"
        show-icon
      />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const hostsText = ref("");
const allowPrivate = ref(false);
const envHosts = ref("");
const envPrivate = ref(false);
const saving = ref(false);
const testing = ref(false);
const testUrl = ref("");
const testResult = ref<{ allowed: boolean; detail: string } | null>(null);

async function load() {
  const data = await api.get<any>("/security/settings/");
  hostsText.value = (data.ssrf_allowed_hosts || []).join("\n");
  allowPrivate.value = !!data.ssrf_allow_private;
  envHosts.value = (data.env_defaults?.ssrf_allowed_hosts || []).join(", ");
  envPrivate.value = !!data.env_defaults?.ssrf_allow_private;
}

async function save() {
  saving.value = true;
  try {
    await api.put("/security/settings/", {
      ssrf_allowed_hosts: hostsText.value,
      ssrf_allow_private: allowPrivate.value,
    });
    ElMessage.success("安全设置已保存，立即生效");
    await load();
  } catch (error: any) {
    ElMessage.error(error?.message || "保存失败");
  } finally {
    saving.value = false;
  }
}

async function testUrlNow() {
  if (!testUrl.value.trim()) return ElMessage.warning("请输入 URL");
  testing.value = true;
  try {
    testResult.value = await api.post<any>("/security/test-url/", { url: testUrl.value.trim() });
  } catch (error: any) {
    ElMessage.error(error?.message || "测试失败");
  } finally {
    testing.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.wp-security-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.wp-security-test {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
</style>
