<template>
  <div class="wp-signature">
    <div class="wp-signature-head">
      <span>在下方签名</span>
      <button type="button" @click="clear">清除</button>
    </div>
    <canvas
      ref="canvasEl"
      class="wp-signature-canvas"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointerleave="onPointerUp"
    />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = withDefaults(defineProps<{ modelValue?: string }>(), { modelValue: "" });
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const canvasEl = ref<HTMLCanvasElement | null>(null);
let ctx: CanvasRenderingContext2D | null = null;
let drawing = false;

function setupCanvas() {
  const canvas = canvasEl.value;
  if (!canvas) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(rect.height * dpr));
  ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.strokeStyle = "#0f172a";
  if (props.modelValue) drawDataUrl(props.modelValue);
}

function drawDataUrl(url: string) {
  if (!ctx || !canvasEl.value) return;
  const img = new Image();
  img.onload = () => {
    const canvas = canvasEl.value;
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.clientWidth, canvas.clientHeight);
  };
  img.src = url;
}
function point(e: PointerEvent) {
  const canvas = canvasEl.value!;
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}
function onPointerDown(e: PointerEvent) {
  if (!ctx) return;
  drawing = true;
  canvasEl.value?.setPointerCapture?.(e.pointerId);
  const p = point(e);
  ctx.beginPath();
  ctx.moveTo(p.x, p.y);
}
function onPointerMove(e: PointerEvent) {
  if (!drawing || !ctx) return;
  const p = point(e);
  ctx.lineTo(p.x, p.y);
  ctx.stroke();
}
function onPointerUp() {
  if (!drawing || !ctx || !canvasEl.value) return;
  drawing = false;
  emit("update:modelValue", canvasEl.value.toDataURL("image/png"));
}
function clear() {
  const canvas = canvasEl.value;
  if (!canvas || !ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  emit("update:modelValue", "");
}
watch(
  () => props.modelValue,
  (value) => { if (value) drawDataUrl(value); }
);
onMounted(() => {
  setupCanvas();
  window.addEventListener("resize", setupCanvas);
});
onBeforeUnmount(() => window.removeEventListener("resize", setupCanvas));
</script>

<style scoped>
.wp-signature { width: 100%; border: 1px solid #dbe3ef; border-radius: 8px; overflow: hidden; background: #fff; }
.wp-signature-head { display: flex; align-items: center; justify-content: space-between; padding: 6px 9px; border-bottom: 1px solid #eef2f8; color: #64748b; font-size: 11px; }
.wp-signature-head button { border: none; background: transparent; color: #2563eb; font-size: 11px; cursor: pointer; }
.wp-signature-canvas { display: block; width: 100%; height: 160px; touch-action: none; cursor: crosshair; }
</style>
