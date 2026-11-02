<template>
  <el-dialog
    :model-value="open"
    :title="title"
    :width="width"
    :show-close="showClose"
    :close-on-click-modal="closeOnClickMask"
    :close-on-press-escape="true"
    append-to-body
    class="wp-modal"
    @update:model-value="onDialogChange"
    @open="on_open"
    @close="on_close"
  >
    <slot />
    <template v-if="showFooter" #footer>
      <slot name="footer">
        <el-button @click="close">取消</el-button>
        <el-button type="primary" @click="confirm">确定</el-button>
      </slot>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import type { RuntimeScope } from "@/types";

const props = withDefaults(
  defineProps<{
    title?: string;
    visible?: boolean;
    width?: number;
    showClose?: boolean;
    closeOnClickMask?: boolean;
    showFooter?: boolean;
    /** 节点 id：由 NodeRenderer 注入，供 openModal/closeModal 动作联动可见性 */
    wpNodeId?: string;
  }>(),
  {
    title: "弹窗标题",
    visible: false,
    width: 520,
    showClose: true,
    closeOnClickMask: true,
    showFooter: true,
    wpNodeId: "",
  }
);

const emit = defineEmits<{
  (e: "open", payload?: undefined): void;
  (e: "close", payload?: undefined): void;
}>();

const scope = inject<RuntimeScope | null>("wp.scope", null);

/**
 * 打开/关闭由 visible prop 或 scope.modalNodeIds（openModal/closeModal 动作）驱动。
 */
const localOpen = ref(props.visible);

watch(
  () => props.visible,
  (v) => {
    if (v !== localOpen.value) localOpen.value = v;
  }
);

const inModalSet = computed(() => {
  if (!scope || !props.wpNodeId) return false;
  return scope.modalNodeIds.has(props.wpNodeId);
});

const open = computed(() => localOpen.value || inModalSet.value);

function onDialogChange(v: boolean | string | number) {
  const next = !!v;
  if (next !== localOpen.value) localOpen.value = next;
  if (props.wpNodeId) scope?.closeModal(props.wpNodeId);
}

function on_open() {
  emit("open");
}

function on_close() {
  emit("close");
}

function close() {
  localOpen.value = false;
  if (props.wpNodeId) scope?.closeModal(props.wpNodeId);
}

function confirm() {
  localOpen.value = false;
  if (props.wpNodeId) scope?.closeModal(props.wpNodeId);
}
</script>
