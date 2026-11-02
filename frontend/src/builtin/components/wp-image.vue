<template>
  <div class="wp-image" :style="box" @click="on_click">
    <el-image :src="src" :alt="alt" :fit="fit" class="wp-image-img" />
  </div>
</template>

<script setup lang="ts">
import { computed, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    src?: string;
    alt?: string;
    width?: number;
    height?: number;
    fit?: "cover" | "contain" | "fill";
    borderRadius?: number;
  }>(),
  {
    src: "",
    alt: "",
    width: 200,
    height: 120,
    fit: "cover",
    borderRadius: 4,
  }
);

const emit = defineEmits<{ (e: "click", payload: MouseEvent): void }>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

const box = computed(() => ({
  width: `${props.width}px`,
  height: `${props.height}px`,
  borderRadius: `${props.borderRadius}px`,
}));

function on_click(e: MouseEvent) {
  emit("click", e);
}
</script>

<style scoped>
.wp-image {
  overflow: hidden;
  display: inline-block;
}
.wp-image-img {
  width: 100%;
  height: 100%;
  display: block;
}
</style>
