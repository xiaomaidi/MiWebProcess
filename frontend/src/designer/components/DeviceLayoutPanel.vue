<template>
  <div class="wp-device-layout">
    <el-alert
      title="桌面布局作为默认；平板/手机仅保存自己的覆盖值。"
      type="info"
      :closable="false"
      show-icon
    />
    <div class="wp-device-tabs">
      <el-radio-group v-model="device" size="small" @change="sync">
        <el-radio-button value="desktop">桌面</el-radio-button>
        <el-radio-button value="tablet">平板</el-radio-button>
        <el-radio-button value="phone">手机</el-radio-button>
      </el-radio-group>
      <el-tag v-if="isOverride" size="small" type="warning">覆盖</el-tag>
    </div>
    <div v-if="layout" class="wp-device-grid">
      <label>X<el-input-number v-model="form.x" :min="0" :controls="false" size="small" style="width:100%" /></label>
      <label>Y<el-input-number v-model="form.y" :min="0" :controls="false" size="small" style="width:100%" /></label>
      <label>宽<el-input-number v-model="form.width" :min="24" :controls="false" size="small" style="width:100%" /></label>
      <label>高<el-input-number v-model="form.height" :min="24" :controls="false" size="small" style="width:100%" /></label>
    </div>
    <div class="wp-device-actions">
      <el-button size="small" :disabled="device === 'desktop'" @click="copyDesktop">复制桌面</el-button>
      <el-button size="small" type="primary" :disabled="!isOverride" @click="apply">应用</el-button>
      <el-button size="small" type="danger" plain :disabled="!isOverride" @click="clear">清除覆盖</el-button>
    </div>
    <p v-if="device === 'desktop'" class="wp-device-hint">桌面端直接编辑画布节点位置。</p>
    <p v-else class="wp-device-hint">切换顶部设备后，在画布拖动节点会写入 {{ device === "phone" ? "手机" : "平板" }} 布局。</p>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from "vue";
import { ElMessage } from "element-plus";
import { useSchemaStore } from "@/store/schema";
import { useEditorStore } from "@/store/editor";
import { clearDeviceLayout, hasDeviceLayout, layoutFor, writeLayout } from "../responsive-layout";
import { commit } from "../util";

const props = defineProps<{ nodeId: string }>();
const schema = useSchemaStore();
const editor = useEditorStore();
const node = computed(() => schema.node(props.nodeId));
const device = computed({
  get: () => editor.device,
  set: (value: string) => { if (value === "desktop" || value === "tablet" || value === "phone") editor.setDevice(value); },
});
const form = reactive({ x: 0, y: 0, width: 200, height: 80 });

const layout = computed(() => layoutFor(node.value, device.value));
const isOverride = computed(() => hasDeviceLayout(node.value, device.value));

function sync() {
  const value = layout.value;
  if (!value) return;
  Object.assign(form, {
    x: Number(value.x || 0), y: Number(value.y || 0),
    width: Number(value.width || 200), height: Number(value.height || 80),
  });
}
function apply() {
  if (!node.value) return;
  commit("应用设备布局", () => writeLayout(node.value!, device.value, { ...form }));
  ElMessage.success("设备布局已应用");
}
function copyDesktop() {
  if (!node.value?.layout) return;
  Object.assign(form, {
    x: node.value.layout.x, y: node.value.layout.y,
    width: node.value.layout.width || 200, height: node.value.layout.height || 80,
  });
}
function clear() {
  if (!node.value) return;
  commit("清除设备布局", () => clearDeviceLayout(node.value!, device.value));
  sync();
}
watch(node, sync, { immediate: true });
watch(() => device.value, sync);
</script>

<style scoped>
.wp-device-layout { display: flex; flex-direction: column; gap: 9px; }
.wp-device-tabs { display: flex; align-items: center; justify-content: space-between; }
.wp-device-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
.wp-device-grid label { color: #64748b; font-size: 10px; }
.wp-device-actions { display: flex; gap: 5px; flex-wrap: wrap; }
.wp-device-hint { margin: 0; color: #94a3b8; font-size: 10px; line-height: 1.6; }
</style>
