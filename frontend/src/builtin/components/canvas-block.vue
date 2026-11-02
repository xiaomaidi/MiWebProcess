<template>
  <div class="wp-canvas-block">
    <canvas ref="canvasRef" :width="width" :height="height" :style="{ background }" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

interface DrawCommand {
  type: "rect" | "circle" | "line" | "text" | "ellipse";
  x?: number;
  y?: number;
  w?: number;
  h?: number;
  r?: number;
  x1?: number;
  y1?: number;
  x2?: number;
  y2?: number;
  text?: string;
  fill?: string;
  stroke?: string;
  lineWidth?: number;
  fontSize?: number;
}

const props = withDefaults(
  defineProps<{
    width?: number;
    height?: number;
    draw?: string;
    background?: string;
  }>(),
  {
    width: 320,
    height: 200,
    draw: "[]",
    background: "transparent",
  }
);

const canvasRef = ref<HTMLCanvasElement | null>(null);

function parseCommands(): DrawCommand[] {
  try {
    const v = JSON.parse(props.draw || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function render() {
  const el = canvasRef.value;
  if (!el) return;
  const ctx = el.getContext("2d");
  if (!ctx) return;
  ctx.clearRect(0, 0, props.width, props.height);
  if (props.background && props.background !== "transparent") {
    ctx.fillStyle = props.background;
    ctx.fillRect(0, 0, props.width, props.height);
  }
  for (const c of parseCommands()) {
    ctx.save();
    ctx.fillStyle = c.fill || "#409eff";
    ctx.strokeStyle = c.stroke || "#409eff";
    ctx.lineWidth = c.lineWidth || 2;
    if (c.type === "rect") ctx.fillRect(c.x || 0, c.y || 0, c.w || 40, c.h || 40);
    else if (c.type === "circle") {
      ctx.beginPath();
      ctx.arc(c.x || 0, c.y || 0, c.r || 20, 0, Math.PI * 2);
      c.fill ? ctx.fill() : ctx.stroke();
    } else if (c.type === "ellipse") {
      ctx.beginPath();
      ctx.ellipse(c.x || 0, c.y || 0, c.r || 30, c.r || 18, 0, 0, Math.PI * 2);
      c.fill ? ctx.fill() : ctx.stroke();
    } else if (c.type === "line") {
      ctx.beginPath();
      ctx.moveTo(c.x1 || 0, c.y1 || 0);
      ctx.lineTo(c.x2 || 100, c.y2 || 0);
      ctx.stroke();
    } else if (c.type === "text") {
      ctx.fillStyle = c.fill || "#303133";
      ctx.font = `${c.fontSize || 14}px sans-serif`;
      ctx.fillText(c.text || "", c.x || 0, c.y || 16);
    }
    ctx.restore();
  }
}

onMounted(render);
watch(() => [props.width, props.height, props.draw, props.background], render);
</script>

<style scoped>
.wp-canvas-block {
  max-width: 100%;
  overflow: auto;
}
</style>
