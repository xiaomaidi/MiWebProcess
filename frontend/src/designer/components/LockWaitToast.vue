<template>
  <!--
    服务端锁等待队列的轻量提示。
    - 自包含：直接读取 lock-session 的响应式 state.queues，不依赖 DesignerView/CanvasArea 传参；
    - 由 designer/lock-wait-toast.ts 自动挂载到 body（也可手动 <LockWaitToast /> 使用）；
    - 只展示 waiting/reconnecting 项；超时/被拒/授权通过 onLockWait 事件转成一次性提示。
  -->
  <div
    v-if="visibleItems.length || hiddenCount || notice"
    class="wp-lock-wait-layer"
    role="status"
    aria-live="polite"
  >
    <TransitionGroup name="wp-lock-wait" tag="div" class="wp-lock-wait-list">
      <div
        v-for="item in visibleItems"
        :key="item.nodeId"
        class="wp-lock-wait-toast"
        :class="{ 'is-reconnecting': item.status === 'reconnecting' }"
      >
        <span class="wp-lock-wait-icon" aria-hidden="true">
          <svg v-if="item.status === 'reconnecting'" viewBox="0 0 24 24">
            <path
              d="M20 11a8 8 0 0 0-14.9-3M4 5v4h4M4 13a8 8 0 0 0 14.9 3M20 19v-4h-4"
              fill="none"
              stroke="currentColor"
              stroke-width="2.2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <svg v-else viewBox="0 0 24 24">
            <path
              d="M7.5 10V7.6a4.5 4.5 0 0 1 9 0V10"
              fill="none"
              stroke="currentColor"
              stroke-width="2.4"
              stroke-linecap="round"
            />
            <rect x="4.5" y="10" width="15" height="10.4" rx="2.4" fill="currentColor" />
          </svg>
        </span>

        <div class="wp-lock-wait-body">
          <div class="wp-lock-wait-title">
            <template v-if="item.status === 'reconnecting'">连接已断开，正在重连…</template>
            <template v-else>
              等待
              <b class="wp-lock-wait-owner">{{ ownerName(item) }}</b>
              释放「<b class="wp-lock-wait-node">{{ labelFor(item.nodeId) }}</b>」…
            </template>
          </div>
          <div class="wp-lock-wait-meta">
            <template v-if="item.status === 'reconnecting'">
              <span>重连后将按剩余时间自动重新排队</span>
            </template>
            <template v-else>
              <span v-if="item.position > 0">位置 {{ item.position }}</span>
              <span v-if="item.position > 0 && remainingSeconds(item) > 0" class="wp-lock-wait-dot">·</span>
              <span v-if="remainingSeconds(item) > 0" class="wp-lock-wait-countdown">
                {{ remainingSeconds(item) }}s
              </span>
              <span v-if="item.queueLength > 1" class="wp-lock-wait-dot">·</span>
              <span v-if="item.queueLength > 1">{{ item.queueLength }} 人排队</span>
            </template>
          </div>
        </div>

        <button
          type="button"
          class="wp-lock-wait-cancel"
          :aria-label="`取消等待节点 ${labelFor(item.nodeId)}`"
          @click="cancelWait(item.nodeId)"
        >
          取消
        </button>
      </div>
    </TransitionGroup>

    <div v-if="hiddenCount" class="wp-lock-wait-more">
      <span>另有 {{ hiddenCount }} 个节点在等待…</span>
      <button type="button" class="wp-lock-wait-cancel-all" @click="cancelAllWaits">全部取消</button>
    </div>

    <Transition name="wp-lock-wait-notice">
      <div v-if="notice" class="wp-lock-wait-notice" :class="`is-${notice.kind}`" role="status">
        {{ notice.text }}
      </div>
    </Transition>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useComponentStore } from "@/store/component";
import { useSchemaStore } from "@/store/schema";
import {
  cancelAllWaits,
  cancelWait,
  onLockWait,
  useLockSession,
  type LockQueueState,
  type LockWaitEvent,
} from "../lock-session";

interface Notice {
  kind: "ok" | "warn" | "error";
  text: string;
}

const MAX_VISIBLE = 3;
const NOTICE_MS = 4_000;

const { queues } = useLockSession();
const now = ref(Date.now());
const notice = ref<Notice | null>(null);

let ticker: number | undefined;
let noticeTimer: number | undefined;
let unsubscribe: (() => void) | undefined;

const ordered = computed<LockQueueState[]>(() =>
  Object.values(queues.value)
    .filter((item) => item.status === "waiting" || item.status === "reconnecting")
    .sort((a, b) => a.enqueuedAt - b.enqueuedAt)
);

const visibleItems = computed(() => ordered.value.slice(0, MAX_VISIBLE));
const hiddenCount = computed(() => Math.max(0, ordered.value.length - MAX_VISIBLE));

function syncTicker(): void {
  const shouldTick = ordered.value.length > 0;
  if (shouldTick && !ticker) {
    ticker = window.setInterval(() => {
      now.value = Date.now();
    }, 500);
  } else if (!shouldTick && ticker) {
    window.clearInterval(ticker);
    ticker = undefined;
  }
}

function remainingSeconds(item: LockQueueState): number {
  const deadline = Date.parse(item.timeoutAt || "");
  if (!Number.isFinite(deadline)) return 0;
  return Math.max(0, Math.ceil((deadline - now.value) / 1000));
}

function truncate(text: string, max = 18): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** 节点标题优先取 props.title/label/text，再退回组件注册表标签；任何异常都退回 nodeId。 */
function labelFor(nodeId: string): string {
  try {
    const node = useSchemaStore().node(nodeId);
    if (!node) return nodeId;
    const props = (node.props || {}) as Record<string, unknown>;
    for (const key of ["title", "label", "text", "name", "placeholder"]) {
      const value = props[key];
      if (typeof value === "string" && value.trim()) return truncate(value.trim());
    }
    try {
      const meta = useComponentStore().meta(node.type);
      if (meta?.label) return String(meta.label);
    } catch {
      /* 组件注册表未就绪时忽略 */
    }
    return node.type || nodeId;
  } catch {
    return nodeId;
  }
}

function ownerName(item: LockQueueState): string {
  return String(item.owner?.username || "").trim() || "其他成员";
}

function showNotice(next: Notice): void {
  notice.value = next;
  if (noticeTimer) window.clearTimeout(noticeTimer);
  noticeTimer = window.setTimeout(() => {
    notice.value = null;
    noticeTimer = undefined;
  }, NOTICE_MS);
}

function deniedText(event: LockWaitEvent, label: string): string {
  const owner = String(event.owner?.username || "").trim();
  if (event.reason === "queue-full") return `「${label}」等待队列已满（最多 50 人），请稍后重试`;
  if (event.reason === "queue-busy") return "锁服务繁忙，请稍后重试";
  if (event.reason === "forbidden") return `没有编辑权限，无法锁定「${label}」`;
  if (owner) return `节点「${label}」已被 ${owner} 锁定，暂时无法获取`;
  return `暂时无法获取「${label}」的锁`;
}

function handleEvent(event: LockWaitEvent): void {
  const label = labelFor(event.nodeId);
  if (event.type === "timeout") {
    showNotice({ kind: "warn", text: `等待「${label}」超时，请稍后重试` });
    return;
  }
  if (event.type === "denied") {
    showNotice({ kind: event.reason === "forbidden" ? "error" : "warn", text: deniedText(event, label) });
    return;
  }
  if (event.type === "granted" && event.result?.queued) {
    showNotice({ kind: "ok", text: `已获得「${label}」的锁` });
  }
}

onMounted(() => {
  unsubscribe = onLockWait(handleEvent);
  syncTicker();
});

onBeforeUnmount(() => {
  unsubscribe?.();
  if (ticker) window.clearInterval(ticker);
  if (noticeTimer) window.clearTimeout(noticeTimer);
  ticker = undefined;
  noticeTimer = undefined;
});

// 等待项增删时开关倒计时；Vue 的 computed 依赖足够细，不需要 deep watch。
watch(ordered, syncTicker, { flush: "post" });
</script>

<style scoped>
.wp-lock-wait-layer {
  position: fixed;
  right: max(16px, env(safe-area-inset-right));
  bottom: max(16px, env(safe-area-inset-bottom));
  z-index: 4000;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  max-width: min(380px, calc(100vw - 24px));
  pointer-events: none;
}

.wp-lock-wait-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.wp-lock-wait-toast {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  width: 100%;
  box-sizing: border-box;
  padding: 10px 10px 10px 12px;
  border: 1px solid #dbe3ef;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.97);
  color: #0f172a;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14), 0 1px 3px rgba(15, 23, 42, 0.08);
  pointer-events: auto;
  backdrop-filter: blur(6px);
}

.wp-lock-wait-toast.is-reconnecting {
  border-color: #cbd5e1;
  background: rgba(248, 250, 252, 0.97);
}

.wp-lock-wait-icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  margin-top: 1px;
  border-radius: 8px;
  background: #eff6ff;
  color: #2563eb;
}

.wp-lock-wait-icon svg {
  width: 15px;
  height: 15px;
}

.wp-lock-wait-toast:not(.is-reconnecting) .wp-lock-wait-icon svg {
  animation: wp-lock-wait-pulse 1.6s ease-in-out infinite;
}

.wp-lock-wait-body {
  flex: 1;
  min-width: 0;
  padding-top: 1px;
}

.wp-lock-wait-title {
  font-size: 12px;
  line-height: 17px;
  color: #334155;
  overflow-wrap: anywhere;
}

.wp-lock-wait-owner,
.wp-lock-wait-node {
  color: #0f172a;
  font-weight: 700;
}

.wp-lock-wait-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
  color: #64748b;
  font-size: 11px;
  line-height: 15px;
  font-variant-numeric: tabular-nums;
}

.wp-lock-wait-dot {
  color: #cbd5e1;
}

.wp-lock-wait-countdown {
  color: #b45309;
  font-weight: 600;
}

.wp-lock-wait-cancel {
  flex: none;
  align-self: center;
  margin-left: 2px;
  padding: 4px 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  color: #475569;
  font-size: 11px;
  line-height: 16px;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.wp-lock-wait-cancel:hover {
  border-color: #bfdbfe;
  background: #eff6ff;
  color: #1d4ed8;
}

.wp-lock-wait-cancel:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 1px;
}

.wp-lock-wait-more {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 4px;
  color: #64748b;
  font-size: 11px;
}

.wp-lock-wait-cancel-all {
  padding: 2px 6px;
  border: 1px solid #e2e8f0;
  border-radius: 5px;
  background: #fff;
  color: #475569;
  font-size: 11px;
  line-height: 15px;
  cursor: pointer;
  pointer-events: auto;
}

.wp-lock-wait-cancel-all:hover {
  border-color: #fecaca;
  color: #b91c1c;
}

.wp-lock-wait-notice {
  box-sizing: border-box;
  max-width: 100%;
  padding: 7px 10px;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #fff;
  color: #475569;
  font-size: 11px;
  line-height: 16px;
  box-shadow: 0 4px 14px rgba(15, 23, 42, 0.1);
  pointer-events: auto;
}

.wp-lock-wait-notice.is-ok {
  border-color: #bbf7d0;
  background: #f0fdf4;
  color: #166534;
}

.wp-lock-wait-notice.is-warn {
  border-color: #fde68a;
  background: #fffbeb;
  color: #92400e;
}

.wp-lock-wait-notice.is-error {
  border-color: #fecaca;
  background: #fef2f2;
  color: #991b1b;
}

@keyframes wp-lock-wait-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

.wp-lock-wait-enter-active,
.wp-lock-wait-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.wp-lock-wait-enter-from,
.wp-lock-wait-leave-to {
  opacity: 0;
  transform: translateY(6px);
}

.wp-lock-wait-notice-enter-active,
.wp-lock-wait-notice-leave-active {
  transition: opacity 0.16s ease;
}

.wp-lock-wait-notice-enter-from,
.wp-lock-wait-notice-leave-to {
  opacity: 0;
}

@media (prefers-reduced-motion: reduce) {
  .wp-lock-wait-toast:not(.is-reconnecting) .wp-lock-wait-icon svg {
    animation: none;
  }
  .wp-lock-wait-enter-active,
  .wp-lock-wait-leave-active,
  .wp-lock-wait-notice-enter-active,
  .wp-lock-wait-notice-leave-active {
    transition: none;
  }
}
</style>
