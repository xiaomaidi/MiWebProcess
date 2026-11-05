<template>
  <div class="wp-sandbox-host" :style="{ height: `${height}px` }" data-wp-component-sandbox>
    <div v-if="configError" class="wp-sandbox-overlay is-error">
      <span>{{ configError }}</span>
    </div>
    <template v-else>
      <iframe
        ref="frameRef"
        class="wp-sandbox-frame"
        :title="title"
        sandbox="allow-scripts"
        referrerpolicy="no-referrer"
        :srcdoc="iframeDoc"
        @load="onFrameLoad"
      />
      <div v-if="status !== 'ready'" class="wp-sandbox-overlay" :class="{ 'is-error': status === 'error' }">
        <span>{{ status === "error" ? error : "沙箱组件加载中…" }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
/**
 * SandboxedComponent
 * ------------------
 * 在 `sandbox="allow-scripts"`（无 allow-same-origin）的 iframe 中加载已构建的
 * 自定义元素 ESM。父页面绝不 import/eval 远端代码，只通过 postMessage 传递 props。
 *
 * 约束/限制：
 * - 仅支持注册了自定义元素（customElements.define）的 ESM；React/Vue 组件需自行
 *   打包成 custom element。
 * - 不支持插槽/子节点；props 通过 DOM property（失败时 primitive 走 attribute）传递。
 * - 事件通过 postMessage 回传，父页面用 @event 接收，不提供同步返回值。
 * - 由于 iframe 是 opaque origin，srcdoc 内动态 import 跨源模块要求源站允许 CORS；
 *   绝对 URL 请使用带 CORS 头的 CDN/媒体地址。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

interface SandboxPolicy {
  network?: string;
  allowed_origins?: string[];
  timeout_ms?: number;
  allow_same_origin?: boolean;
  allow_forms?: boolean;
  allow_popups?: boolean;
  [key: string]: unknown;
}

const props = withDefaults(
  defineProps<{
    sourceUrl: string;
    element?: string;
    componentProps?: Record<string, unknown>;
    events?: string[];
    policy?: SandboxPolicy;
    title?: string;
    minHeight?: number;
  }>(),
  {
    element: "",
    componentProps: () => ({}),
    events: () => [],
    policy: () => ({}),
    title: "沙箱组件",
    minHeight: 240,
  },
);

const emit = defineEmits<{
  (event: "ready", payload: { tag: string }): void;
  (event: "error", payload: { message: string }): void;
  (event: "event", payload: { name: string; detail: unknown }): void;
}>();

const ELEMENT_RE = /^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$/;
const frameRef = ref<HTMLIFrameElement | null>(null);
const status = ref<"loading" | "ready" | "error">("loading");
const error = ref("");
const height = ref(Math.max(props.minHeight, 120));
let bridgeReady = false;
let loadTimer: ReturnType<typeof setTimeout> | undefined;

const elementName = computed(() => (props.element || "").trim());
const configError = computed(() => {
  if (!props.sourceUrl || !String(props.sourceUrl).trim()) return "缺少组件 source_url，无法加载沙箱组件";
  if (/[\\\u0000-\u001f]/.test(props.sourceUrl)) return "source_url 含非法字符";
  if (!ELEMENT_RE.test(elementName.value)) return "缺少合法的自定义元素名（element）";
  if (!elementName.value.startsWith("wp-")) return "element 必须以 wp- 开头";
  return "";
});

const timeoutMs = computed(() => {
  const raw = Number(props.policy?.timeout_ms ?? 10000);
  if (!Number.isFinite(raw)) return 10000;
  return Math.min(Math.max(raw, 1000), 30000);
});

const sourceOrigin = computed(() => {
  try {
    const origin = new URL(props.sourceUrl, window.location.href).origin;
    return /^https?:\/\/[a-z0-9.:\[\]-]+$/i.test(origin) ? origin : "";
  } catch {
    return "";
  }
});

function safeOrigin(value: unknown): string {
  try {
    const origin = new URL(String(value)).origin;
    return /^https?:\/\/[a-z0-9.:\[\]-]+$/i.test(origin) ? origin : "";
  } catch {
    return "";
  }
}

const csp = computed(() => {
  const scriptSrc = ["'unsafe-inline'", sourceOrigin.value].filter(Boolean).join(" ");
  const allowed = Array.isArray(props.policy?.allowed_origins)
    ? props.policy!.allowed_origins!.map(safeOrigin).filter(Boolean)
    : [];
  const network = String(props.policy?.network || "none").toLowerCase();
  const connectSrc = network === "allowlist" && allowed.length ? Array.from(new Set(allowed)).join(" ") : "'none'";
  return [
    "default-src 'none'",
    `script-src ${scriptSrc}`,
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "font-src data:",
    `connect-src ${connectSrc}`,
    "form-action 'none'",
    "base-uri 'none'",
    "object-src 'none'",
  ].join("; ");
});

/** JSON 嵌入 <script> 时转义 < / > / & 与 JS 行分隔符，避免提前闭合标签。 */
function jsLiteral(value: unknown): string {
  return JSON.stringify(value ?? null)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

const iframeDoc = computed(() => {
  const events = Array.isArray(props.events) ? props.events.map(String).slice(0, 50) : [];
  const cspValue = csp.value.replace(/"/g, "&quot;");
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${cspValue}">
<meta name="referrer" content="no-referrer">
<style>
  html,body{margin:0;padding:0;background:transparent;color:#0f172a;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:13px;line-height:1.6}
  #wp-market-root{min-height:1px}
  .wp-sandbox-error{margin:12px;padding:12px;border:1px solid #fecaca;border-radius:8px;background:#fef2f2;color:#b91c1c;font-size:12px;white-space:pre-wrap;word-break:break-word}
</style>
</head>
<body>
<div id="wp-market-root"></div>
<script type="module">
const SOURCE_URL = ${jsLiteral(props.sourceUrl)};
const ELEMENT = ${jsLiteral(elementName.value)};
const EVENT_NAMES = ${jsLiteral(events)};
let mounted = null;
let currentProps = {};
let finished = false;

function post(type, payload) {
  try {
    window.parent.postMessage({ type, ...(payload || {}) }, "*");
  } catch (_error) {
    /* ignore */
  }
}

function toAttr(name) {
  return String(name).replace(/[A-Z]/g, function (match) { return "-" + match.toLowerCase(); });
}

function applyProps(next) {
  currentProps = next && typeof next === "object" ? next : {};
  if (!mounted) return;
  for (const key of Object.keys(currentProps)) {
    if (!key || key === "children") continue;
    const value = currentProps[key];
    let applied = false;
    try {
      if (key in mounted) {
        mounted[key] = value;
        applied = true;
      }
    } catch (_error) {
      applied = false;
    }
    if (!applied) {
      const attr = toAttr(key);
      if (value === null || value === undefined) mounted.removeAttribute(attr);
      else if (typeof value !== "object") mounted.setAttribute(attr, String(value));
    }
  }
}

function fail(reason) {
  if (finished) return;
  finished = true;
  const message = reason && reason.message ? reason.message : String(reason || "未知错误");
  const root = document.getElementById("wp-market-root");
  if (root) {
    const box = document.createElement("div");
    box.className = "wp-sandbox-error";
    box.textContent = "沙箱组件加载失败：" + message;
    root.replaceChildren(box);
  }
  post("wp:sandbox:error", { message });
}

window.addEventListener("message", function (event) {
  if (event.source !== window.parent) return;
  const data = event.data;
  if (!data || data.type !== "wp:sandbox:props") return;
  applyProps(data.props || {});
});

post("wp:sandbox:hello");

(async function boot() {
  try {
    if (!SOURCE_URL) throw new Error("缺少 source_url");
    if (!ELEMENT) throw new Error("缺少 element");
    await import(SOURCE_URL);
    if (!customElements.get(ELEMENT)) {
      await Promise.race([
        customElements.whenDefined(ELEMENT),
        new Promise(function (_, reject) {
          setTimeout(function () { reject(new Error("自定义元素 " + ELEMENT + " 未注册")); }, ${Math.round(timeoutMs.value)});
        }),
      ]);
    }
    const root = document.getElementById("wp-market-root");
    if (!root) throw new Error("沙箱容器不存在");
    mounted = document.createElement(ELEMENT);
    root.replaceChildren(mounted);
    for (const name of EVENT_NAMES) {
      mounted.addEventListener(name, function (event) {
        let detail = null;
        try { detail = event instanceof CustomEvent ? event.detail : null; } catch (_error) { detail = null; }
        post("wp:sandbox:event", { name: name, detail: detail });
      });
    }
    applyProps(currentProps);
    finished = true;
    post("wp:sandbox:ready", { tag: ELEMENT });

    function reportHeight() {
      const value = Math.ceil(document.documentElement.scrollHeight || document.body.scrollHeight || 0);
      post("wp:sandbox:height", { height: value });
    }
    if (typeof ResizeObserver !== "undefined") {
      new ResizeObserver(reportHeight).observe(document.body);
    }
    reportHeight();
  } catch (error) {
    fail(error);
  }
})();
<\/script>
</body>
</html>`;
});

function postToFrame(type: string, payload: Record<string, unknown> = {}) {
  const frame = frameRef.value;
  if (!frame?.contentWindow) return;
  try {
    // iframe 为 opaque origin，targetOrigin 只能是 "*"；父页面通过 event.source 校验来源。
    frame.contentWindow.postMessage({ type, ...payload }, "*");
  } catch {
    status.value = "error";
    error.value = "组件 props 无法通过 postMessage 序列化";
  }
}

function sendProps() {
  postToFrame("wp:sandbox:props", { props: props.componentProps || {} });
}

function clearLoadTimer() {
  if (loadTimer !== undefined) {
    clearTimeout(loadTimer);
    loadTimer = undefined;
  }
}

function armLoadTimer() {
  clearLoadTimer();
  loadTimer = setTimeout(() => {
    if (status.value === "ready") return;
    status.value = "error";
    error.value = `沙箱组件加载超时（${timeoutMs.value}ms）`;
    emit("error", { message: error.value });
  }, timeoutMs.value);
}

function onFrameLoad() {
  bridgeReady = false;
  if (configError.value) {
    status.value = "error";
    error.value = configError.value;
    return;
  }
  status.value = "loading";
  error.value = "";
  armLoadTimer();
  // 双重握手：hello 消息可能早于父监听器注册，load 后再补发一次当前 props。
  sendProps();
}

function onMessage(event: MessageEvent) {
  const frame = frameRef.value;
  if (!frame || event.source !== frame.contentWindow) return;
  const data = event.data as any;
  if (!data || typeof data.type !== "string" || !data.type.startsWith("wp:sandbox:")) return;

  if (data.type === "wp:sandbox:hello") {
    bridgeReady = true;
    sendProps();
    return;
  }
  if (data.type === "wp:sandbox:ready") {
    clearLoadTimer();
    status.value = "ready";
    emit("ready", { tag: String(data.tag || elementName.value) });
    return;
  }
  if (data.type === "wp:sandbox:error") {
    clearLoadTimer();
    status.value = "error";
    error.value = String(data.message || "沙箱组件加载失败");
    emit("error", { message: error.value });
    return;
  }
  if (data.type === "wp:sandbox:event") {
    emit("event", { name: String(data.name || ""), detail: data.detail });
    return;
  }
  if (data.type === "wp:sandbox:height") {
    const next = Number(data.height);
    if (Number.isFinite(next)) {
      height.value = Math.min(Math.max(Math.ceil(next), Math.max(props.minHeight, 120)), 4000);
    }
  }
}

function reload() {
  clearLoadTimer();
  bridgeReady = false;
  status.value = "loading";
  error.value = "";
  const frame = frameRef.value;
  if (!frame) return;
  frame.srcdoc = iframeDoc.value;
}

watch(
  () => [props.sourceUrl, props.element, props.policy, props.events],
  () => reload(),
  { deep: true },
);

watch(
  () => props.componentProps,
  () => {
    if (bridgeReady) sendProps();
  },
  { deep: true },
);

onMounted(() => {
  window.addEventListener("message", onMessage);
  if (configError.value) {
    status.value = "error";
    error.value = configError.value;
    emit("error", { message: error.value });
  }
});

onBeforeUnmount(() => {
  clearLoadTimer();
  window.removeEventListener("message", onMessage);
});
</script>

<style scoped>
.wp-sandbox-host {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 10px;
  background: #f8fafc;
}
.wp-sandbox-frame {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: transparent;
}
.wp-sandbox-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  color: #64748b;
  font-size: 12px;
  text-align: center;
  background: #f8fafc;
}
.wp-sandbox-overlay.is-error {
  color: #b91c1c;
  background: #fef2f2;
}
</style>
