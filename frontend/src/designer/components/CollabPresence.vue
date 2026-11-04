<template>
  <div class="wp-collab-presence" :title="connected ? '实时协作已连接' : '实时协作未连接'">
    <span class="wp-collab-dot" :class="{ online: connected }" />
    <span class="wp-collab-count">{{ peers.length + 1 }} 在线</span>
    <span class="wp-collab-avatars">
      <i class="wp-collab-me">我</i>
      <i v-for="peer in peers.slice(0, 4)" :key="peer.username" :style="{ background: peer.color }" :title="peer.username">
        {{ peer.username.slice(0, 1).toUpperCase() }}
      </i>
      <i v-if="peers.length > 4" class="wp-collab-more">+{{ peers.length - 4 }}</i>
    </span>
    <span v-if="lockCount" class="wp-collab-locks">{{ lockCount }} 处锁定</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useDesignerCollab } from "../collab";

const { peers, connected, remoteLocks } = useDesignerCollab();
const lockCount = computed(() => Object.keys(remoteLocks.value).length);
</script>

<style scoped>
.wp-collab-presence { display: inline-flex; align-items: center; gap: 6px; padding: 3px 7px; border: 1px solid #e8edf5; border-radius: 999px; background: #fff; color: #64748b; font-size: 10px; }
.wp-collab-dot { width: 6px; height: 6px; border-radius: 50%; background: #cbd5e1; }
.wp-collab-dot.online { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12); }
.wp-collab-count { white-space: nowrap; }
.wp-collab-avatars { display: inline-flex; align-items: center; margin-left: 2px; }
.wp-collab-avatars i { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; margin-left: -4px; border: 2px solid #fff; border-radius: 50%; color: #fff; font-size: 8px; font-style: normal; font-weight: 700; }
.wp-collab-me { background: #0f172a; }
.wp-collab-more { background: #e2e8f0 !important; color: #475569 !important; }
.wp-collab-locks { color: #d97706; white-space: nowrap; }
</style>
