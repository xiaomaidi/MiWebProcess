<template>
  <div class="wp-attachment-field">
    <div v-if="files.length" class="wp-attachment-list">
      <div v-for="(url, index) in files" :key="`${index}-${url}`" class="wp-attachment-item">
        <el-tag size="small" effect="plain" class="wp-attachment-badge">附件</el-tag>
        <el-link
          :href="url"
          target="_blank"
          type="primary"
          :underline="false"
          class="wp-attachment-link"
          :title="url"
        >
          {{ displayName(url) }}
        </el-link>
        <el-button
          v-if="!disabled"
          link
          type="danger"
          size="small"
          class="wp-attachment-remove"
          :disabled="uploading"
          @click="removeAt(index)"
        >
          移除
        </el-button>
      </div>
    </div>
    <div v-else class="wp-attachment-empty">暂无附件</div>

    <div class="wp-attachment-actions">
      <input
        ref="inputRef"
        type="file"
        multiple
        hidden
        :accept="accept || undefined"
        @change="onFilesChange"
      />
      <el-button
        size="small"
        :disabled="disabled || uploading || files.length >= maxCount"
        :loading="uploading"
        @click="pickFiles"
      >
        {{ uploading ? `上传中 ${progress}%` : "上传附件" }}
      </el-button>
      <span class="wp-attachment-count">{{ files.length }}/{{ maxCount }}</span>
      <span class="wp-attachment-hint">可多选，按顺序上传</span>
    </div>

    <el-progress
      v-if="uploading"
      class="wp-attachment-progress"
      :percentage="progress"
      :stroke-width="4"
      :show-text="false"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";

const MAX_ATTACHMENTS = 20;
const MAX_URL_LENGTH = 500;

const props = withDefaults(
  defineProps<{
    /** 附件 URL 数组；兼容旧数据里的单个字符串。 */
    modelValue?: string[] | string | null;
    /** 上传接口需要 app_id。 */
    appId?: number | string;
    /** input[type=file] 的 accept，例如 image/*,.pdf。 */
    accept?: string;
    /** 最多附件数（后端上限 20）。 */
    max?: number;
    disabled?: boolean;
  }>(),
  {
    modelValue: () => [],
    appId: 0,
    accept: "",
    max: MAX_ATTACHMENTS,
    disabled: false,
  }
);

const emit = defineEmits<{
  (e: "update:modelValue", value: string[]): void;
}>();

const inputRef = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const progress = ref(0);

const maxCount = computed(() => {
  const value = Math.floor(Number(props.max) || MAX_ATTACHMENTS);
  return Math.max(1, Math.min(MAX_ATTACHMENTS, value));
});

const files = computed<string[]>(() => {
  const value = props.modelValue;
  if (Array.isArray(value)) {
    return value.filter((item): item is string => typeof item === "string" && item.length > 0);
  }
  if (typeof value === "string" && value) return [value];
  return [];
});

function commit(next: string[]) {
  emit("update:modelValue", next.slice(0, maxCount.value));
}

function pickFiles() {
  if (props.disabled || uploading.value) return;
  inputRef.value?.click();
}

function removeAt(index: number) {
  commit(files.value.filter((_url, i) => i !== index));
}

function displayName(url: string): string {
  try {
    const path = url.split("?")[0].split("#")[0];
    const raw = decodeURIComponent(path.substring(path.lastIndexOf("/") + 1));
    // 上传接口生成的存储名为 <uuid12>-<uuid4>-<原始文件名>，展示时去掉前缀。
    return raw.replace(/^[0-9a-f]{8,}-[0-9a-f]{4}-/i, "") || url;
  } catch {
    return url;
  }
}

async function onFilesChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const picked = Array.from(input.files || []);
  input.value = "";
  if (!picked.length || props.disabled) return;

  const appId = Number(props.appId);
  if (!appId) {
    ElMessage.warning("缺少应用 ID，无法上传附件");
    return;
  }

  let remaining = maxCount.value - files.value.length;
  if (remaining <= 0) {
    ElMessage.warning(`最多上传 ${maxCount.value} 个附件`);
    return;
  }
  if (picked.length > remaining) {
    ElMessage.warning(`最多还能上传 ${remaining} 个附件，多余的已忽略`);
  }
  const batch = picked.slice(0, remaining);

  uploading.value = true;
  progress.value = 0;
  const next = [...files.value];
  let uploaded = 0;
  let failed = 0;

  // 顺序上传，避免并发打满；每成功一个立即回写 URL 数组。
  for (let i = 0; i < batch.length; i += 1) {
    try {
      const asset = await api.upload<{ url?: string }>(`/assets/?app_id=${appId}`, batch[i]);
      const url = String(asset?.url || "");
      if (url && url.length > MAX_URL_LENGTH) {
        failed += 1;
      } else if (url) {
        next.push(url);
        uploaded += 1;
        commit(next);
      } else {
        failed += 1;
      }
    } catch {
      failed += 1;
    }
    progress.value = Math.round(((i + 1) / batch.length) * 100);
  }

  uploading.value = false;
  if (uploaded > 0 && failed === 0) {
    ElMessage.success(`已上传 ${uploaded} 个附件`);
  } else if (failed > 0) {
    ElMessage.warning(`${failed} 个附件上传失败，已成功上传 ${uploaded} 个`);
  }
}
</script>

<style scoped>
.wp-attachment-field {
  width: 100%;
}
.wp-attachment-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 6px;
}
.wp-attachment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.wp-attachment-badge {
  flex: none;
}
.wp-attachment-link {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-attachment-remove {
  flex: none;
}
.wp-attachment-empty {
  margin-bottom: 6px;
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.wp-attachment-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.wp-attachment-count {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-attachment-hint {
  color: var(--el-text-color-placeholder);
  font-size: 12px;
}
.wp-attachment-progress {
  margin-top: 6px;
}
</style>
