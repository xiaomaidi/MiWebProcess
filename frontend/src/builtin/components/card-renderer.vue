<template>
  <el-card :shadow="shadow" :body-style="{ padding: padding + 'px' }" class="wp-card-renderer">
    <template #header v-if="title || $slots.header">
      <slot name="header">{{ title }}</slot>
    </template>
    <slot />
    <template #footer v-if="$slots.footer">
      <slot name="footer" />
    </template>
  </el-card>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    title?: string;
    shadow?: "always" | "never" | "hover";
    padding?: number;
    rounded?: boolean;
  }>(),
  {
    title: "",
    shadow: "always",
    padding: 16,
    rounded: true,
  }
);
void props;
</script>

<style scoped>
.wp-card-renderer {
  width: 100%;
  box-sizing: border-box;
}
</style>
