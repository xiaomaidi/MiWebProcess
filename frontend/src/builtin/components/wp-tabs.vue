<template>
  <el-tabs v-model="active" :tab-position="tabAlign" class="wp-tabs">
    <slot />
  </el-tabs>
</template>

<script setup lang="ts">
import { ref, inject } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(defineProps<{ tabAlign?: "top" | "bottom" }>(), { tabAlign: "top" });

const scope = inject<RuntimeScope | null>("wp.scope", null);

const active = ref("");
</script>
