<template>
  <div v-if="node?.layout" class="wp-layout-tab">
    <el-form label-position="top" size="small">
      <div class="wp-layout-grid">
        <el-form-item label="X">
          <el-input-number v-model="pos.x" :min="0" controls-position="right" @change="apply" />
        </el-form-item>
        <el-form-item label="Y">
          <el-input-number v-model="pos.y" :min="0" controls-position="right" @change="apply" />
        </el-form-item>
        <el-form-item label="宽度">
          <el-input-number v-model="pos.w" :min="24" controls-position="right" @change="apply" />
        </el-form-item>
        <el-form-item label="高度">
          <el-input-number v-model="pos.h" :min="24" controls-position="right" @change="apply" />
        </el-form-item>
      </div>
      <el-form-item label="水平对齐">
        <el-button-group>
          <el-button size="small" @click="alignTo('left')">左对齐</el-button>
          <el-button size="small" @click="alignTo('center')">居中</el-button>
          <el-button size="small" @click="alignTo('right')">右对齐</el-button>
        </el-button-group>
      </el-form-item>
      <div class="wp-layout-tip">对齐相对画布宽度计算；也可在画布上直接拖动节点移动、拖右下角手柄调整大小。</div>
    </el-form>
  </div>
  <div v-else class="wp-pp-empty">
    流式布局下组件位置由文档流决定。在右侧画布设置中切换为自由布局后，可手动设置位置、大小并对齐。
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import { useSchemaStore } from "@/store/schema";
import { commit } from "../util";

const props = defineProps<{ nodeId: string }>();
const schema = useSchemaStore();
const node = computed(() => schema.node(props.nodeId));

const pos = reactive({ x: 0, y: 0, w: 100, h: 60 });
function sync() {
  const l = node.value?.layout;
  if (l) Object.assign(pos, { x: l.x, y: l.y, w: l.width, h: l.height });
}
watch(() => props.nodeId, sync, { immediate: true });
watch(() => node.value?.layout, sync, { deep: true });

function apply() {
  commit("布局", () => {
    const n = node.value;
    if (!n?.layout) return;
    n.layout = { ...n.layout, x: pos.x, y: pos.y, width: pos.w, height: pos.h };
  });
}

/** 水平对齐：left=0、center=(画布宽-节点宽)/2、right=画布宽-节点宽。 */
function alignTo(which: "left" | "center" | "right") {
  const n = node.value;
  if (!n?.layout) return;
  const canvasW = schema.schema?.layout?.width ?? 1200;
  const x =
    which === "left"
      ? 0
      : which === "center"
        ? Math.max(0, Math.round((canvasW - n.layout.width) / 2))
        : Math.max(0, canvasW - n.layout.width);
  commit("对齐", () => {
    const m = node.value;
    if (m?.layout) m.layout = { ...m.layout, x };
  });
}
</script>

<style scoped>
.wp-layout-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  column-gap: 8px;
}
.wp-layout-tip {
  font-size: 12px;
  color: var(--el-color-secondary, #909399);
  line-height: 1.5;
}
</style>
