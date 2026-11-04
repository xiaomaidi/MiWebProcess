import type { PageSchema, SchemaNode } from "@/types";

export type AuditSeverity = "error" | "warning" | "info";

export interface AuditIssue {
  code: string;
  severity: AuditSeverity;
  message: string;
  nodeId?: string;
  hint?: string;
}

const CONTAINER_TYPES = new Set([
  "wp-container", "wp-row", "wp-column", "wp-card", "wp-tabs", "wp-tab-item",
  "wp-grid", "wp-space", "wp-freebox", "wp-canvas",
]);

function textOf(node: SchemaNode): string {
  const props = node.props || {};
  return String(props.content ?? props.text ?? props.label ?? props.title ?? props.value ?? "").trim();
}

function hasChild(node: SchemaNode | undefined): boolean {
  if (!node) return false;
  return (node.children || []).length > 0 || Object.values(node.slots || {}).some((list) => list.length > 0);
}

export function auditPage(schema: PageSchema | null): AuditIssue[] {
  if (!schema?.rootId || !schema.nodes) {
    return [{ code: "empty-schema", severity: "error", message: "页面没有可用的画布结构。" }];
  }
  const issues: AuditIssue[] = [];
  const seen = new Set<string>();
  const nodes = Object.values(schema.nodes);
  const ids = new Set<string>();

  if (!schema.meta?.title?.trim()) {
    issues.push({ code: "meta-title", severity: "warning", message: "页面缺少浏览器标题（Meta title）。" });
  }
  if (!schema.meta?.description?.trim()) {
    issues.push({ code: "meta-description", severity: "info", message: "页面缺少 Meta description。" });
  }

  for (const node of nodes) {
    if (ids.has(node.id)) {
      issues.push({ code: "duplicate-id", severity: "error", message: `节点 ID 重复：${node.id}`, nodeId: node.id });
    }
    ids.add(node.id);
    seen.add(node.id);
    const props = node.props || {};
    const type = node.type;

    if (CONTAINER_TYPES.has(type) && !hasChild(node)) {
      issues.push({ code: "empty-container", severity: "warning", message: "容器内没有子组件。", nodeId: node.id });
    }
    if ((type === "wp-image" || type === "ElImage") && !String(props.src || "").trim()) {
      issues.push({ code: "image-src", severity: "error", message: "图片没有设置地址。", nodeId: node.id });
    }
    if (type === "wp-link" && !String(props.href || "").trim()) {
      issues.push({ code: "link-href", severity: "warning", message: "链接没有设置目标地址。", nodeId: node.id });
    }
    if ((type === "wp-button" || type === "ElButton") && !textOf(node)) {
      issues.push({ code: "button-label", severity: "error", message: "按钮缺少可见文字或无障碍名称。", nodeId: node.id });
    }
    if ((type === "wp-input" || type === "wp-select" || type === "ElInput") && !String(props.label || props.placeholder || "").trim()) {
      issues.push({ code: "input-label", severity: "warning", message: "输入控件缺少 label 或 placeholder。", nodeId: node.id });
    }
    if (typeof node.style?.width === "string" && /^(\d{3,})px$/.test(node.style.width)) {
      const width = Number(node.style.width.replace("px", ""));
      if (width > 375) {
        issues.push({ code: "phone-width", severity: "info", message: `固定宽度 ${width}px 可能超出手机画布。`, nodeId: node.id });
      }
    }
    if (node.layout && schema.layout?.mode === "free") {
      const x = Number(node.layout.x || 0);
      const y = Number(node.layout.y || 0);
      const w = Number(node.layout.width || 0);
      if (x < 0 || y < 0 || x + w > 1400) {
        issues.push({ code: "layout-bounds", severity: "warning", message: "自由布局节点超出画布范围。", nodeId: node.id });
      }
    }
  }

  const total = Object.keys(schema.nodes).length;
  if (total > 300) {
    issues.push({ code: "node-count", severity: "warning", message: `页面节点较多（${total}），建议拆分页面或复用区块。` });
  }
  return issues;
}

export function auditSummary(issues: AuditIssue[]) {
  return {
    total: issues.length,
    error: issues.filter((item) => item.severity === "error").length,
    warning: issues.filter((item) => item.severity === "warning").length,
    info: issues.filter((item) => item.severity === "info").length,
  };
}
