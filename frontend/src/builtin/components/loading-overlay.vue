<template>
  <div class="wp-loading-host" :class="{ 'is-fullscreen': fullscreen }">
    <slot />
    <div v-if="loading" class="wp-loading-mask" :style="{ background }">
      <span class="wp-loading-spinner" />
      <span v-if="text" class="wp-loading-text">{{ text }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    loading?: boolean;
    text?: string;
    fullscreen?: boolean;
    background?: string;
  }>(),
  {
    loading: true,
    text: "加载中…",
    fullscreen: false,
    background: "rgba(255,255,255,.75)",
  }
);
void props;
</script>

<style scoped>
.wp-loading-host {
  position: relative;
  min-height: 40px;
}
.wp-loading-host.is-fullscreen {
  min-height: 120px;
}
.wp-loading-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: center;
  justify-content: center;
  z-index: 10;
  backdrop-filter: blur(1px);
}
.wp-loading-spinner {
  width: 22px;
  height: 22px;
  border: 2px solid var(--el-color-primary-light-7);
  border-top-color: var(--el-color-primary);
  border-radius: 50%;
  animation: wp-spin 0.8s linear infinite;
}
.wp-loading-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
@keyframes wp-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
