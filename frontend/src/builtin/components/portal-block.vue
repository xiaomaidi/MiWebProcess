<template>
  <template v-if="mode === 'design'">
    <div class="wp-portal-design">传送门 → {{ target || "body" }}<slot /></div>
  </template>
  <Teleport v-else :to="target || 'body'">
    <slot />
  </Teleport>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    target?: string;
    mode?: "design" | "runtime";
  }>(),
  {
    target: "body",
    mode: "runtime",
  }
);
void props;
</script>

<style scoped>
.wp-portal-design {
  border: 1px dashed var(--el-border-color);
  border-radius: 4px;
  padding: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
