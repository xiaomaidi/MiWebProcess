<template>
  <div class="wp-slot" :class="{ 'wp-slot-design': mode === 'design' }">
    <slot>
      <span v-if="mode === 'design'" class="wp-slot-placeholder">插槽「{{ name || "default" }}」{{ fallback }}</span>
      <span v-else>{{ fallback }}</span>
    </slot>
  </div>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    name?: string;
    fallback?: string;
    mode?: "design" | "runtime";
  }>(),
  {
    name: "default",
    fallback: "",
    mode: "runtime",
  }
);
void props;
</script>

<style scoped>
.wp-slot {
  min-height: 1px;
}
.wp-slot-design {
  min-height: 36px;
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
}
.wp-slot-placeholder {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
