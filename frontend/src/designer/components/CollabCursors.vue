<template>
  <div class="wp-collab-cursors" aria-hidden="true">
    <div
      v-for="peer in cursors"
      :key="peer.username"
      class="wp-collab-cursor"
      :style="{ left: `${peer.cursor!.x}px`, top: `${peer.cursor!.y}px`, color: peer.color }"
    >
      <span class="wp-collab-arrow" :style="{ background: peer.color }" />
      <span class="wp-collab-name" :style="{ background: peer.color }">{{ peer.username }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useDesignerCollab } from "../collab";

const { peers } = useDesignerCollab();
const cursors = computed(() => peers.value.filter((peer) => peer.cursor));
</script>

<style scoped>
.wp-collab-cursors { position: absolute; inset: 0; z-index: 40; overflow: hidden; pointer-events: none; }
.wp-collab-cursor { position: absolute; transform: translate(-2px, -2px); transition: left 0.06s linear, top 0.06s linear; }
.wp-collab-arrow { display: block; width: 0; height: 0; border-top: 10px solid currentColor; border-right: 7px solid transparent; filter: drop-shadow(0 1px 1px rgba(15, 23, 42, 0.2)); }
.wp-collab-name { position: absolute; top: 10px; left: 5px; padding: 1px 4px; border-radius: 3px; color: #fff; font-size: 9px; white-space: nowrap; }
</style>
