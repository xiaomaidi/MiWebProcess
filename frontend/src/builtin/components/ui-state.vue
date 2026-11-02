<template>
  <div class="wp-ui-state" :class="state">
    <div class="wp-ui-state-icon">
      <span v-if="state === 'loading'" class="wp-ui-state-spinner" />
      <span v-else-if="state === 'error'">!</span>
      <span v-else-if="state === 'forbidden'">×</span>
      <span v-else>○</span>
    </div>
    <div class="wp-ui-state-title">{{ title || defaultTitle }}</div>
    <p v-if="description">{{ description }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = withDefaults(
  defineProps<{
    state?: "loading" | "empty" | "error" | "forbidden" | "success";
    title?: string;
    description?: string;
  }>(),
  { state: "empty", title: "", description: "" }
);

const defaultTitle = computed(
  () =>
    ({
      loading: "加载中…",
      empty: "暂无数据",
      error: "加载失败",
      forbidden: "无访问权限",
      success: "操作成功",
    }[props.state] || "暂无数据")
);
</script>

<style scoped>
.wp-ui-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 150px;
  padding: 24px;
  color: var(--wp-muted, #909399);
  text-align: center;
}
.wp-ui-state-icon {
  font-size: 28px;
  color: var(--wp-muted, #c0c4cc);
}
.wp-ui-state.error .wp-ui-state-icon {
  color: var(--wp-color-danger, #f56c6c);
}
.wp-ui-state.forbidden .wp-ui-state-icon {
  color: var(--wp-color-warning, #e6a23c);
}
.wp-ui-state-title {
  color: var(--wp-text, #303133);
  font-size: 14px;
  font-weight: 600;
}
.wp-ui-state p {
  margin: 0;
  font-size: 12px;
}
.wp-ui-state-spinner {
  display: inline-block;
  width: 24px;
  height: 24px;
  border: 2px solid var(--wp-border, #dcdfe6);
  border-top-color: var(--wp-accent, #409eff);
  border-radius: 50%;
  animation: wp-ui-spin 0.8s linear infinite;
}
@keyframes wp-ui-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
