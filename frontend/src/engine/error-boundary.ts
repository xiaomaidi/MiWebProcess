/** 运行态错误边界：捕获组件渲染异常，降级为提示卡片并上报。 */
import { defineComponent, getCurrentInstance, h, ref, type Component } from "vue";
import type { RuntimeScope } from "@/types";

declare global {
  interface Window {
    __WP_ERROR_REPORT__?: (payload: { nodeId?: string; message: string; stack?: string; url: string }) => void;
  }
}

export function reportError(nodeId: string | undefined, error: unknown) {
  const msg = error instanceof Error ? `${error.message}\n${error.stack || ""}` : String(error);
  try {
    window.__WP_ERROR_REPORT__?.({ nodeId, message: msg, url: location.href });
  } catch {
    /* ignore */
  }
  console.error("[MiWebProcess] 节点渲染错误", nodeId, error);
}

export function createErrorBoundary(scope: RuntimeScope | undefined, nodeId: string): Component {
  const failed = ref(false);
  const error = ref("");
  return defineComponent({
    name: "WpErrorBoundary",
    setup(_, { slots }) {
      return () =>
        failed.value
          ? h(
              "div",
              { class: "wp-error-boundary" },
              [
                h("div", `组件渲染失败：${nodeId}`),
                error.value ? h("code", error.value.split("\n")[0]) : null,
              ]
            )
          : slots.default?.();
    },
    errorCaptured(err) {
      failed.value = true;
      error.value = err instanceof Error ? err.message : String(err);
      reportError(nodeId, err);
      scope?.onNodeError?.(nodeId, err);
      return false;
    },
  });
}
