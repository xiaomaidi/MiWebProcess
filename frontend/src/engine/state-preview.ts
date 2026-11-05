/**
 * 设计器「状态预览」临时状态。
 *
 * 只影响设计画布渲染，不写入 schema / 不进入撤销历史；选中其他节点或
 * 点击「重置预览」时清除。NodeRenderer 通过 `previewedStateOf(node.id)`
 * 读取，PropertyPanel 的「状态」页签负责写入。
 */
import { reactive } from "vue";
import type { ComponentStateName } from "@/types";

export interface StatePreviewState {
  nodeId: string | null;
  state: ComponentStateName | null;
}

export const statePreview = reactive<StatePreviewState>({
  nodeId: null,
  state: null,
});

/** 设置某节点的预览状态；state=null 表示退出预览。 */
export function setStatePreview(nodeId: string | null, state: ComponentStateName | null): void {
  if (!nodeId || !state) {
    statePreview.nodeId = null;
    statePreview.state = null;
    return;
  }
  statePreview.nodeId = nodeId;
  statePreview.state = state;
}

/** 清除预览；传 nodeId 时仅在预览目标匹配时清除。 */
export function clearStatePreview(nodeId?: string): void {
  if (nodeId && statePreview.nodeId !== nodeId) return;
  statePreview.nodeId = null;
  statePreview.state = null;
}

/** 某节点当前被预览的状态（未预览返回 null）。 */
export function previewedStateOf(nodeId: string): ComponentStateName | null {
  return statePreview.nodeId === nodeId ? statePreview.state : null;
}
