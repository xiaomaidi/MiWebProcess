/**
 * 页面质量 / 可访问性预发布检查（纯函数，无外部依赖）。
 *
 * 只读取 PageSchema，不修改、不依赖 Pinia / DOM / 网络，可在设计器、发布前钩子
 * 或脚本中直接调用：
 *
 *   import { auditPage, auditSummary } from "@/designer/quality";
 *   const issues = auditPage(schema);
 *   const summary = auditSummary(issues); // { total, error, warn, info, ... }
 *
 * 设计原则：
 * - 静态可判定的问题才报；值可能来自数据绑定 / 表达式时跳过，避免“假阳性”。
 * - 对比度、自由布局重叠属于启发式检查：只在节点自身同时声明了文字色与背景色
 *   时计算，结果以 warn 为主，并在 detail 里注明局限。
 * - 组件能力（是否容器 / 是否表单字段）可用 AuditOptions 注入（设计器里接
 *   component store 的 meta），不注入时使用内置类型集合兜底。
 */
import type { PageSchema, SchemaNode } from "@/types";

/** 手机画布宽度：固定宽度超过该值的组件在移动端会溢出。 */
export const PHONE_CANVAS_WIDTH = 375;
/** 超过该嵌套深度开始提示性能风险。 */
export const DEFAULT_MAX_DEPTH = 14;
/** 超过该节点数开始提示性能风险。 */
export const DEFAULT_MAX_NODES = 600;

const BREAKPOINTS = ["xs", "sm", "md", "lg", "xl"] as const;

export type QualitySeverity = "error" | "warn" | "info";

export type QualityCode =
  | "empty-container"
  | "empty-page"
  | "image-missing-src"
  | "link-empty-href"
  | "control-no-text"
  | "form-field-no-label"
  | "duplicate-element-id"
  | "dangling-reference"
  | "node-id-mismatch"
  | "node-cycle"
  | "unreachable-node"
  | "low-contrast"
  | "fixed-width-overflow"
  | "page-title-missing"
  | "page-description-missing"
  | "hidden-required-field"
  | "deep-tree"
  | "too-many-nodes"
  | "free-layout-out-of-bounds"
  | "free-layout-overlap"
  | "root-missing";

/** 单条检查结果。 */
export interface QualityIssue {
  /** 严重级别：error 建议发布前修复；warn 应该修复；info 提示性建议。 */
  severity: QualitySeverity;
  code: QualityCode;
  /** 面向用户的中文问题描述。 */
  message: string;
  /** 关联节点；页面级问题（标题 / 页面规模）可能没有。 */
  nodeId?: string;
  /** 节点类型，便于面板展示。 */
  nodeType?: string;
  /** 节点显示名：label / title / text / content 的截断。 */
  nodeLabel?: string;
  /** 修复建议（一句话、可操作）。 */
  fix: string;
  /** 补充说明 / 计算依据（如对比度数值、启发式局限）。 */
  detail?: string;
}

/** 页面级汇总。 */
export interface QualitySummary {
  total: number;
  error: number;
  warn: number;
  info: number;
  /** 是否存在 error 级问题（可用于发布前阻断）。 */
  passed: boolean;
  /** code → 数量，便于做统计或埋点。 */
  byCode: Partial<Record<QualityCode, number>>;
}

/** 可选检查参数；不传时使用内置规则。 */
export interface AuditOptions {
  /** 组件是否为容器（接 component store 的 meta.is_container）。 */
  isContainer?: (type: string) => boolean;
  /** 组件是否为表单字段（接 component store 的 meta.is_form_field）。 */
  isFormField?: (type: string) => boolean;
  /** 手机画布宽度，默认 375。 */
  phoneWidth?: number;
  /** 深度告警阈值，默认 14。 */
  maxDepth?: number;
  /** 节点数告警阈值，默认 600。 */
  maxNodeCount?: number;
}

// ===================== 组件类型知识（兜底，不依赖注册表） =====================

/** 内置容器类型；注册表 meta.is_container 优先。 */
const CONTAINER_TYPES = new Set<string>([
  "wp-canvas",
  "wp-container",
  "wp-row",
  "wp-column",
  "wp-card",
  "wp-tabs",
  "wp-tab-item",
  "wp-grid",
  "wp-space",
  "wp-modal",
  "wp-form",
  "wp-list",
  "wp-freebox",
  "ElCard",
  "ElContainer",
  "ElHeader",
  "ElAside",
  "ElMain",
  "ElFooter",
  "ElRow",
  "ElCol",
  "ElSpace",
  "ElSplitter",
  "ElSplitterPanel",
  "ElTabs",
  "ElTabPane",
  "ElForm",
  "ElFormItem",
  "ElDialog",
  "ElDrawer",
  "ElCollapse",
  "ElCollapseItem",
  "div",
  "section",
  "flex-box",
  "grid-box",
]);

/** 表单字段类型（注册表里 wp-input 等旧组件没有 form 标记，需要兜底）。 */
const FORM_FIELD_TYPES = new Set<string>([
  "ElInput",
  "ElInputNumber",
  "ElSelect",
  "ElRadioGroup",
  "ElCheckboxGroup",
  "ElSwitch",
  "ElSlider",
  "ElRate",
  "ElColorPicker",
  "ElDatePicker",
  "ElTimePicker",
  "ElTimeSelect",
  "ElCascader",
  "ElTransfer",
  "ElUpload",
  "ElAutocomplete",
  "ElMention",
  "ElSegmented",
  "ElTreeSelect",
  "wp-input",
  "wp-textarea",
  "wp-select",
  "wp-checkbox",
  "wp-radio",
  "wp-switch",
  "wp-number",
  "wp-date",
]);

const IMAGE_TYPES = new Set(["ElImage", "wp-image", "img"]);
const LINK_TYPES = new Set(["ElLink", "wp-link", "a"]);
const BUTTON_TYPES = new Set(["ElButton", "wp-button"]);
/** 弹窗 / 抽屉的宽度是遮罩层尺寸，与手机画布溢出无关。 */
const OVERLAY_TYPES = new Set(["ElDialog", "ElDrawer", "wp-modal", "ElModal"]);

/** 这些类型自身就能显示文字，文字色/背景色检查才有意义。 */
const TEXT_PROP_KEYS = ["text", "label", "content", "title", "description"] as const;

const COLOR_NAMES: Record<string, string> = {
  white: "#ffffff",
  black: "#000000",
  red: "#ff0000",
  green: "#008000",
  blue: "#0000ff",
  gray: "#808080",
  grey: "#808080",
  silver: "#c0c0c0",
  yellow: "#ffff00",
};

// ===================== 通用小工具 =====================

function clip(text: string, max = 26): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function isBinding(value: any): boolean {
  return !!value && typeof value === "object" && !Array.isArray(value) && "__binding__" in value;
}

/** 静态文本：绑定 / 含 {{ }} 的表达式返回 null（动态，无法静态判定）。 */
function staticText(value: any): string | null {
  if (typeof value !== "string") return null;
  if (/\{\{[\s\S]*\}\}/.test(value)) return null;
  return value.trim();
}

type TextProbe = { state: "empty" | "text" | "dynamic"; text: string };

/** 依次检查 props 上的文本字段；任一动态即视为动态。 */
function probeText(node: SchemaNode, keys: readonly string[]): TextProbe {
  let dynamic = false;
  for (const key of keys) {
    const raw = node.props?.[key];
    if (isBinding(raw)) {
      dynamic = true;
      continue;
    }
    if (typeof raw !== "string") continue;
    const text = staticText(raw);
    if (text === null) {
      dynamic = true;
      continue;
    }
    if (text) return { state: "text", text };
  }
  return { state: dynamic ? "dynamic" : "empty", text: "" };
}

function ariaLabel(node: SchemaNode): string {
  const props = node.props || {};
  const raw = props["aria-label"] ?? props.ariaLabel;
  if (isBinding(raw)) return "dynamic";
  return typeof raw === "string" ? raw.trim() : "";
}

function nodeLabel(node: SchemaNode): string {
  const probe = probeText(node, TEXT_PROP_KEYS);
  if (probe.state === "text") return clip(probe.text);
  return node.type;
}

function childIdsOf(node: SchemaNode): string[] {
  const ids: string[] = [];
  if (Array.isArray(node.children)) ids.push(...node.children);
  for (const list of Object.values(node.slots || {})) {
    if (Array.isArray(list)) ids.push(...list);
  }
  return ids.filter((id): id is string => typeof id === "string");
}

function hasRenderedChild(node: SchemaNode, nodes: Record<string, SchemaNode>): boolean {
  return childIdsOf(node).some((id) => !!nodes[id]);
}

function hasTextChild(node: SchemaNode, nodes: Record<string, SchemaNode>): boolean {
  const ids = [...(node.children || []), ...(node.slots?.default || [])];
  return ids.some((id) => {
    const child = nodes[id];
    return !!child && child.type !== "ElIcon";
  });
}

function isContainerNode(node: SchemaNode, options: AuditOptions): boolean {
  if (options.isContainer?.(node.type)) return true;
  return CONTAINER_TYPES.has(node.type);
}

function isFormFieldNode(node: SchemaNode, options: AuditOptions): boolean {
  if (options.isFormField?.(node.type)) return true;
  if (FORM_FIELD_TYPES.has(node.type)) return true;
  // 旧版自定义组件：声明了 field prop 即按表单字段对待。
  return typeof node.props?.field === "string" && node.props.field.trim() !== "";
}

function isRequiredNode(node: SchemaNode): boolean {
  if (node.props?.required === true) return true;
  const rules = node.props?.rules;
  return Array.isArray(rules) && rules.some((r: any) => r && typeof r === "object" && r.required === true);
}

function parsePx(value: any): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!text) return null;
  const px = text.match(/^(-?\d+(?:\.\d+)?)px$/i);
  if (px) return Number(px[1]);
  if (/^-?\d+(?:\.\d+)?$/.test(text)) return Number(text);
  return null;
}

/** 宽度是否被断点覆盖 / 自适应“缓解”（此时不报固定宽度溢出）。 */
function widthMitigated(node: SchemaNode, phoneWidth: number): boolean {
  if (Array.isArray(node.hideOn) && node.hideOn.includes("xs")) return true;
  const responsive = node.responsive || {};
  for (const bp of ["xs", "sm"]) {
    const style = responsive[bp] || {};
    const width = style.width;
    const px = parsePx(width);
    if (px !== null && px <= phoneWidth) return true;
    if (typeof width === "string" && /^(100%|100vw|auto)$/i.test(width.trim())) return true;
    const responsiveMax = parsePx(style.maxWidth);
    if (responsiveMax !== null && responsiveMax <= phoneWidth) return true;
  }
  const maxWidth = node.style?.maxWidth;
  if (typeof maxWidth === "string" && /^(100%|100vw)$/i.test(maxWidth.trim())) return true;
  return false;
}

// ===================== 颜色 / 对比度 =====================

interface Rgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

function parseColor(input: any): Rgba | null {
  if (typeof input !== "string") return null;
  const raw = input.trim().toLowerCase();
  if (!raw || raw.startsWith("var(") || raw.startsWith("linear-gradient")) return null;
  const named = COLOR_NAMES[raw];
  if (named) return parseColor(named);
  const hex = raw.match(/^#([0-9a-f]{3,8})$/);
  if (hex) {
    let digits = hex[1];
    if (digits.length === 3 || digits.length === 4) {
      digits = digits
        .split("")
        .map((d) => d + d)
        .join("");
    }
    if (digits.length !== 6 && digits.length !== 8) return null;
    const r = Number.parseInt(digits.slice(0, 2), 16);
    const g = Number.parseInt(digits.slice(2, 4), 16);
    const b = Number.parseInt(digits.slice(4, 6), 16);
    const a = digits.length === 8 ? Number.parseInt(digits.slice(6, 8), 16) / 255 : 1;
    return { r, g, b, a };
  }
  const rgb = raw.match(/^rgba?\(([^)]+)\)$/);
  if (rgb) {
    const parts = rgb[1]
      .split(/[,/\s]+/)
      .map((p) => p.trim())
      .filter(Boolean);
    if (parts.length < 3) return null;
    const channel = (part: string): number => {
      if (part.endsWith("%")) return Math.round((Number.parseFloat(part) / 100) * 255);
      return Math.round(Number.parseFloat(part));
    };
    const r = channel(parts[0]);
    const g = channel(parts[1]);
    const b = channel(parts[2]);
    const a = parts[3] === undefined ? 1 : Math.max(0, Math.min(1, Number.parseFloat(parts[3])));
    if ([r, g, b, a].some((n) => !Number.isFinite(n))) return null;
    return { r, g, b, a };
  }
  return null;
}

function luminance(color: Rgba): number {
  const channel = (value: number): number => {
    const v = value / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
}

function contrastRatio(a: Rgba, b: Rgba): number {
  const la = luminance(a);
  const lb = luminance(b);
  const light = Math.max(la, lb);
  const dark = Math.min(la, lb);
  return (light + 0.05) / (dark + 0.05);
}

function findFontSize(node: SchemaNode): number | null {
  const fromProps = parsePx(node.props?.fontSize);
  if (fromProps !== null) return fromProps;
  return parsePx(node.style?.fontSize);
}

function isBold(node: SchemaNode): boolean {
  const weight = node.props?.fontWeight ?? node.style?.fontWeight;
  if (weight === "bold" || weight === "bolder") return true;
  const numeric = Number(weight);
  return Number.isFinite(numeric) && numeric >= 700;
}

// ===================== 树遍历 =====================

interface WalkResult {
  order: SchemaNode[];
  depthOf: Map<string, number>;
  parentOf: Map<string, string>;
  maxDepth: number;
}

/**
 * 从 rootId 深度优先遍历；同时产出重复引用 / 环 / 断链信息。
 * 重复引用追加到 issues（nodeId 指向被重复引用的节点）。
 */
function walkTree(schema: PageSchema, nodes: Record<string, SchemaNode>, issues: QualityIssue[]): WalkResult {
  const order: SchemaNode[] = [];
  const depthOf = new Map<string, number>();
  const parentOf = new Map<string, string>();
  const path = new Set<string>();
  const referenced = new Set<string>();
  const reportedDuplicate = new Set<string>();
  const reportedDangling = new Set<string>();
  let maxDepth = 0;

  const visit = (id: string, depth: number): void => {
    const node = nodes[id];
    if (!node) return;
    if (path.has(id)) {
      issues.push({
        severity: "error",
        code: "node-cycle",
        message: `节点 «${nodeLabel(node)}» 的父子引用形成环，页面渲染可能卡死`,
        nodeId: id,
        nodeType: node.type,
        nodeLabel: nodeLabel(node),
        fix: "检查该节点的 children / slots 引用，移除回指自身的 id。",
      });
      return;
    }
    if (referenced.has(id)) return;
    referenced.add(id);
    order.push(node);
    depthOf.set(id, depth);
    maxDepth = Math.max(maxDepth, depth);
    path.add(id);
    for (const childId of childIdsOf(node)) {
      if (!nodes[childId]) {
        const key = `${node.id}->${childId}`;
        if (reportedDangling.has(key)) continue;
        reportedDangling.add(key);
        issues.push({
          severity: "error",
          code: "dangling-reference",
          message: `节点 «${nodeLabel(node)}» 引用了不存在的子节点 id «${childId}»`,
          nodeId: node.id,
          nodeType: node.type,
          nodeLabel: nodeLabel(node),
          fix: "删除该引用，或在 nodes 中恢复对应节点；不要手改 id。",
        });
        continue;
      }
      const existing = parentOf.get(childId);
      if (existing) {
        const child = nodes[childId];
        if (reportedDuplicate.has(childId)) continue;
        reportedDuplicate.add(childId);
        issues.push({
          severity: "error",
          code: "duplicate-element-id",
          message: `元素 id «${childId}» 被多个父节点引用（${existing} 与 ${id}），渲染与选中会错乱`,
          nodeId: childId,
          nodeType: child.type,
          nodeLabel: nodeLabel(child),
          fix: "删除重复引用；需要复用组件时复制节点（会生成新 id），不要共享同一 id。",
        });
        continue;
      }
      parentOf.set(childId, id);
      visit(childId, depth + 1);
    }
    path.delete(id);
  };

  // 同一父节点内重复 id 也要报（父节点 children 数组里出现两次）。
  for (const node of Object.values(nodes)) {
    const ids = childIdsOf(node);
    const seen = new Set<string>();
    const dup = new Set<string>();
    for (const id of ids) {
      if (seen.has(id)) dup.add(id);
      seen.add(id);
    }
    for (const id of dup) {
      const child = nodes[id];
      if (reportedDuplicate.has(id)) continue;
      reportedDuplicate.add(id);
      issues.push({
        severity: "error",
        code: "duplicate-element-id",
        message: `父节点 «${nodeLabel(node)}» 的子列表里重复引用 id «${id}»`,
        nodeId: id,
        nodeType: child?.type,
        nodeLabel: child ? nodeLabel(child) : undefined,
        fix: "在该节点的 children / slots 中只保留一份引用。",
      });
    }
  }

  if (nodes[schema.rootId]) visit(schema.rootId, 0);

  // 多个节点声明了同一个 node.id（映射键不同）：DOM id / 选中定位会冲突。
  const idOwners = new Map<string, string[]>();
  for (const [key, node] of Object.entries(nodes)) {
    if (!node.id) continue;
    const list = idOwners.get(node.id) || [];
    list.push(key);
    idOwners.set(node.id, list);
  }
  const duplicatedIds = new Set<string>();
  for (const [id, keys] of idOwners) {
    if (keys.length < 2) continue;
    duplicatedIds.add(id);
    issues.push({
      severity: "error",
      code: "duplicate-element-id",
      message: `多个节点声明了相同的 id «${id}»（映射键：${keys.join("、")}），选中与 DOM 定位会冲突`,
      nodeId: keys[0],
      nodeType: nodes[keys[0]]?.type,
      nodeLabel: nodes[keys[0]] ? nodeLabel(nodes[keys[0]]) : undefined,
      fix: "为每个节点生成唯一 id；复制节点请使用设计器的「复制」而不是手工改 id。",
    });
  }

  // 节点映射键与 node.id 不一致：选中 / 定位会失效。
  for (const [key, node] of Object.entries(nodes)) {
    if (node.id && node.id !== key && !duplicatedIds.has(node.id)) {
      issues.push({
        severity: "error",
        code: "node-id-mismatch",
        message: `节点映射键 «${key}» 与节点自身 id «${node.id}» 不一致`,
        nodeId: key,
        nodeType: node.type,
        nodeLabel: nodeLabel(node),
        fix: "把 node.id 改为与 nodes 的键一致，或重新插入该组件。",
      });
    }
  }

  return { order, depthOf, parentOf, maxDepth };
}

// ===================== 各项检查 =====================

function checkPageMeta(schema: PageSchema, issues: QualityIssue[]): void {
  const meta = schema.meta || {};
  const title = typeof meta.title === "string" ? meta.title.trim() : "";
  if (!title) {
    issues.push({
      severity: "warn",
      code: "page-title-missing",
      message: "页面缺少标题（meta.title），浏览器标签页与搜索结果会显示为空",
      fix: "在属性面板的「页面」设置里填写标题，或调用 schemaStore.setPageMeta({ title })。",
    });
  }
  const descriptionRaw = [meta.seo?.description, meta.description].find(
    (item): item is string => typeof item === "string" && item.trim() !== ""
  );
  const description = descriptionRaw ? descriptionRaw.trim() : "";
  if (!description) {
    issues.push({
      severity: "info",
      code: "page-description-missing",
      message: "页面缺少 meta description，分享与搜索摘要会退化为抓取正文",
      fix: "在 meta.seo.description 写 60–160 字的页面摘要。",
    });
  }
}

function checkRoot(schema: PageSchema, nodes: Record<string, SchemaNode>, issues: QualityIssue[]): void {
  const root = nodes[schema.rootId];
  if (!root) {
    issues.push({
      severity: "error",
      code: "root-missing",
      message: "页面结构缺少根节点（rootId 指向的节点不存在），无法渲染",
      fix: "重新创建页面，或把 rootId 指向一个存在的 wp-canvas 节点。",
    });
    return;
  }
  if (!hasRenderedChild(root, nodes)) {
    issues.push({
      severity: "warn",
      code: "empty-page",
      message: "画布是空的，页面没有任何组件",
      nodeId: root.id,
      nodeType: root.type,
      nodeLabel: nodeLabel(root),
      fix: "从左侧组件库拖入组件，或使用 AI 生成页面结构。",
    });
  }
}

function checkContainers(
  order: SchemaNode[],
  nodes: Record<string, SchemaNode>,
  options: AuditOptions,
  issues: QualityIssue[]
): void {
  for (const node of order) {
    if (node.type === "wp-canvas") continue;
    if (!isContainerNode(node, options)) continue;
    if (hasRenderedChild(node, nodes)) continue;
    issues.push({
      severity: "warn",
      code: "empty-container",
      message: `容器 «${nodeLabel(node)}»（${node.type}）内没有子组件`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "放入子组件，或删除该空容器；表单容器至少需要一个字段。",
    });
  }
}

function checkImagesAndLinks(
  order: SchemaNode[],
  nodes: Record<string, SchemaNode>,
  issues: QualityIssue[]
): void {
  for (const node of order) {
    if (node.type === "wp-canvas") continue;
    if (IMAGE_TYPES.has(node.type)) {
      const src = node.props?.src;
      if (isBinding(src)) continue;
      const text = typeof src === "string" ? src.trim() : "";
      const broken = !text || text === "#" || /^javascript:/i.test(text) || text === "about:blank";
      if (broken) {
        issues.push({
          severity: "error",
          code: "image-missing-src",
          message: `图片 «${nodeLabel(node)}» 没有有效地址（src 为空或为占位链接）`,
          nodeId: node.id,
          nodeType: node.type,
          nodeLabel: nodeLabel(node),
          fix: "在属性面板选择图片或填写图片 URL；运行态由数据绑定提供时可忽略本项。",
        });
      }
    }

    if (LINK_TYPES.has(node.type)) {
      const hrefRaw = node.props?.href;
      if (!isBinding(hrefRaw)) {
        const href = typeof hrefRaw === "string" ? hrefRaw.trim() : "";
        const broken = !href || href === "#" || /^javascript:/i.test(href);
        if (broken) {
          issues.push({
            severity: "error",
            code: "link-empty-href",
            message: `链接 «${nodeLabel(node)}» 的跳转地址为空（${href || "空"}）`,
            nodeId: node.id,
            nodeType: node.type,
            nodeLabel: nodeLabel(node),
            fix: "填写 href，或改用按钮 + navigate 动作；占位链接发布前应移除。",
          });
        }
      }
      checkControlText(node, nodes, "链接", issues);
    }

    if (BUTTON_TYPES.has(node.type)) {
      checkControlText(node, nodes, "按钮", issues);
    }
  }
}

function checkControlText(node: SchemaNode, nodes: Record<string, SchemaNode>, kind: string, issues: QualityIssue[]): void {
  if (hasTextChild(node, nodes)) return; // 子节点提供文案
  const probe = probeText(node, ["text", "label", "content"]);
  if (probe.state === "dynamic") return;
  if (probe.state === "text") return;
  const aria = ariaLabel(node);
  if (aria === "dynamic") return;
  if (aria) return;
  const iconOnly = !!node.props?.icon || node.type === "ElIcon";
  issues.push({
    severity: "error",
    code: "control-no-text",
    message: `${kind} «${node.type}» 没有可见文案或 aria-label，读屏用户无法识别${iconOnly ? "（纯图标）" : ""}`,
    nodeId: node.id,
    nodeType: node.type,
    nodeLabel: nodeLabel(node),
    fix: "补充 text/label 文案；纯图标按钮请加 aria-label（或 title）描述动作。",
  });
}

/** 向上找 ElFormItem 的 label（最多 3 层）。 */
function formItemLabel(nodeId: string, nodes: Record<string, SchemaNode>, parentOf: Map<string, string>): string {
  let current = parentOf.get(nodeId);
  let hops = 0;
  while (current && hops < 3) {
    const parent = nodes[current];
    if (!parent) break;
    if (parent.type === "ElFormItem" || parent.type === "wp-form-item") {
      const label = typeof parent.props?.label === "string" ? parent.props.label.trim() : "";
      if (label) return label;
    }
    current = parentOf.get(current);
    hops += 1;
  }
  return "";
}

function checkFormLabels(
  order: SchemaNode[],
  nodes: Record<string, SchemaNode>,
  parentOf: Map<string, string>,
  options: AuditOptions,
  issues: QualityIssue[]
): void {
  for (const node of order) {
    if (node.type === "wp-canvas") continue;
    if (!isFormFieldNode(node, options)) continue;
    const labelRaw = node.props?.label;
    if (isBinding(labelRaw)) continue;
    const ownLabel = typeof labelRaw === "string" ? labelRaw.trim() : "";
    if (ownLabel) continue;
    const aria = ariaLabel(node);
    if (aria === "dynamic" || aria) continue;
    const inherited = formItemLabel(node.id, nodes, parentOf);
    if (inherited) continue;

    const placeholderRaw = node.props?.placeholder;
    const placeholder = isBinding(placeholderRaw) ? "" : typeof placeholderRaw === "string" ? placeholderRaw.trim() : "";
    if (placeholder) {
      issues.push({
        severity: "warn",
        code: "form-field-no-label",
        message: `表单字段 «${nodeLabel(node)}» 只有占位符 «${clip(placeholder, 18)}»，没有 label`,
        nodeId: node.id,
        nodeType: node.type,
        nodeLabel: nodeLabel(node),
        fix: "补充 label（或 aria-label）；placeholder 在输入后会消失，不能替代标签。",
      });
      continue;
    }
    issues.push({
      severity: "error",
      code: "form-field-no-label",
      message: `表单字段 «${nodeLabel(node)}» 没有 label / aria-label，读屏用户无法知道要填什么`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "填写字段 label，或放进带 label 的 ElFormItem / wp-form 中。",
    });
  }
}

function checkFixedWidth(order: SchemaNode[], options: AuditOptions, issues: QualityIssue[]): void {
  const phoneWidth = options.phoneWidth ?? PHONE_CANVAS_WIDTH;
  for (const node of order) {
    if (node.type === "wp-canvas" || OVERLAY_TYPES.has(node.type)) continue;
    if (widthMitigated(node, phoneWidth)) continue;
    const candidates: { key: string; value: number }[] = [];
    const layoutWidth = parsePx(node.layout?.width);
    if (layoutWidth !== null) candidates.push({ key: "layout.width", value: layoutWidth });
    const propWidth = parsePx(node.props?.width);
    if (propWidth !== null) candidates.push({ key: "props.width", value: propWidth });
    const styleWidth = parsePx(node.style?.width);
    if (styleWidth !== null) candidates.push({ key: "style.width", value: styleWidth });
    const minWidth = parsePx(node.style?.minWidth);
    if (minWidth !== null) candidates.push({ key: "style.minWidth", value: minWidth });
    const widest = candidates.reduce<{ key: string; value: number } | null>(
      (acc, item) => (!acc || item.value > acc.value ? item : acc),
      null
    );
    if (!widest || widest.value <= phoneWidth) continue;
    issues.push({
      severity: "warn",
      code: "fixed-width-overflow",
      message: `节点 «${nodeLabel(node)}» 固定宽度 ${Math.round(widest.value)}px，超过手机画布 ${phoneWidth}px`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "改用百分比 / max-width:100%，或在 xs/sm 断点覆盖宽度。",
      detail: `来源：${widest.key}`,
    });
  }
}

function checkContrast(order: SchemaNode[], issues: QualityIssue[]): void {
  for (const node of order) {
    const backgroundColor = node.style?.backgroundColor ?? node.props?.background;
    const textColor = node.style?.color ?? node.props?.color;
    if (typeof backgroundColor !== "string" || typeof textColor !== "string") continue;
    const bg = parseColor(backgroundColor);
    const fg = parseColor(textColor);
    if (!bg || !fg || bg.a < 1 || fg.a < 1) continue; // 半透明 / 渐变背景：叠加结果未知，跳过
    const probe = probeText(node, TEXT_PROP_KEYS);
    if (probe.state !== "text") continue;
    const fontSize = findFontSize(node);
    const large = fontSize !== null && (fontSize >= 24 || (fontSize >= 18.66 && isBold(node)));
    const threshold = large ? 3 : 4.5;
    const ratio = contrastRatio(fg, bg);
    if (ratio >= threshold) continue;
    issues.push({
      severity: ratio < 2 ? "error" : "warn",
      code: "low-contrast",
      message: `文字与背景对比度约 ${ratio.toFixed(2)}:1，低于 ${threshold}:1（WCAG AA）`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "调整文字色 color 或背景色 backgroundColor，使对比度达标。",
      detail: `启发式：只比较节点自身声明的 color=${textColor} 与 background=${backgroundColor}，继承样式/主题/图片背景未参与计算。`,
    });
  }
}

function descendantsOf(nodeId: string, nodes: Record<string, SchemaNode>): SchemaNode[] {
  const out: SchemaNode[] = [];
  const stack = [...childIdsOf(nodes[nodeId] || ({} as SchemaNode))];
  const visited = new Set<string>();
  while (stack.length) {
    const id = stack.pop() as string;
    if (visited.has(id)) continue;
    visited.add(id);
    const node = nodes[id];
    if (!node) continue;
    out.push(node);
    stack.push(...childIdsOf(node));
  }
  return out;
}

function hiddenMode(node: SchemaNode): { hidden: boolean; blocking: boolean; reason: string } {
  const hideOn = Array.isArray(node.hideOn) ? node.hideOn : [];
  const hideAll = BREAKPOINTS.every((bp) => hideOn.includes(bp));
  if (hideAll) return { hidden: true, blocking: true, reason: "hideOn 覆盖了所有断点" };
  if (node.style?.display === "none") return { hidden: true, blocking: true, reason: "style.display=none" };
  const expr = node.condition?.expr?.trim();
  if (expr && /^(false|0|null|undefined)$/i.test(expr)) {
    return { hidden: true, blocking: false, reason: `condition = ${expr}` };
  }
  return { hidden: false, blocking: false, reason: "" };
}

function checkHiddenRequired(
  order: SchemaNode[],
  nodes: Record<string, SchemaNode>,
  options: AuditOptions,
  issues: QualityIssue[]
): void {
  for (const node of order) {
    const state = hiddenMode(node);
    if (!state.hidden) continue;
    const required = descendantsOf(node.id, nodes).filter(
      (child) => isRequiredNode(child) && (isFormFieldNode(child, options) || child.type === "ElFormItem")
    );
    if (!required.length) continue;
    const names = required
      .slice(0, 3)
      .map((child) => nodeLabel(child))
      .join("、");
    const more = required.length > 3 ? ` 等 ${required.length} 个` : "";
    issues.push({
      severity: state.blocking ? "error" : "warn",
      code: "hidden-required-field",
      message: state.blocking
        ? `节点 «${nodeLabel(node)}» 永久隐藏（${state.reason}），但内部包含必填字段 «${names}»${more}，用户无法填写却会被校验阻塞`
        : `节点 «${nodeLabel(node)}» 被条件隐藏（${state.reason}），内部必填字段 «${names}»${more} 永远不会渲染`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "把必填字段移出隐藏节点；若整块都该隐藏，同时移除其 required 校验。",
    });
  }
}

function checkFreeLayout(
  order: SchemaNode[],
  parentOf: Map<string, string>,
  nodes: Record<string, SchemaNode>,
  schema: PageSchema,
  issues: QualityIssue[]
): void {
  if (schema.layout?.mode !== "free") return;
  const canvasWidth = Number(schema.layout.width) || 1200;
  const canvasHeight = Number(schema.layout.height) || 800;
  const placed = order.filter(
    (node) =>
      node.type !== "wp-canvas" &&
      !!node.layout &&
      Number.isFinite(node.layout.x) &&
      Number.isFinite(node.layout.y) &&
      Number.isFinite(node.layout.width) &&
      Number.isFinite(node.layout.height)
  );

  for (const node of placed) {
    const layout = node.layout as NonNullable<SchemaNode["layout"]>;
    const out =
      layout.x < 0 ||
      layout.y < 0 ||
      layout.x + layout.width > canvasWidth + 1 ||
      layout.y + layout.height > canvasHeight + 1;
    if (!out) continue;
    issues.push({
      severity: "warn",
      code: "free-layout-out-of-bounds",
      message: `自由布局节点 «${nodeLabel(node)}» 超出画布范围（x=${Math.round(layout.x)}, y=${Math.round(layout.y)}, ${Math.round(
        layout.width
      )}×${Math.round(layout.height)}；画布 ${canvasWidth}×${canvasHeight}）`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "拖动回画布内，或缩小尺寸；也可改为流式布局。",
    });
  }

  const byParent = new Map<string, SchemaNode[]>();
  for (const node of placed) {
    const parent = parentOf.get(node.id) || schema.rootId;
    const list = byParent.get(parent) || [];
    list.push(node);
    byParent.set(parent, list);
  }
  let reported = 0;
  for (const siblings of byParent.values()) {
    for (let i = 0; i < siblings.length && reported < 10; i += 1) {
      for (let j = i + 1; j < siblings.length && reported < 10; j += 1) {
        const a = siblings[i].layout as NonNullable<SchemaNode["layout"]>;
        const b = siblings[j].layout as NonNullable<SchemaNode["layout"]>;
        const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
        const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
        if (overlapX <= 0 || overlapY <= 0) continue;
        const overlap = overlapX * overlapY;
        const minArea = Math.min(a.width * a.height, b.width * b.height);
        if (minArea <= 0) continue;
        const ratio = overlap / minArea;
        if (ratio < 0.5) continue;
        issues.push({
          severity: "warn",
          code: "free-layout-overlap",
          message: `节点 «${nodeLabel(siblings[i])}» 与 «${nodeLabel(siblings[j])}» 重叠约 ${Math.round(ratio * 100)}%`,
          nodeId: siblings[i].id,
          nodeType: siblings[i].type,
          nodeLabel: nodeLabel(siblings[i]),
          fix: "用对齐/分布工具拉开位置，或改用流式布局避免遮挡。",
          detail: `仅比较同一父节点下的同级自由布局节点（${nodes[siblings[i].id]?.type} / ${nodes[siblings[j].id]?.type}）。`,
        });
        reported += 1;
      }
    }
  }
}

function checkScale(
  walk: WalkResult,
  nodes: Record<string, SchemaNode>,
  issues: QualityIssue[],
  options: AuditOptions
): void {
  const maxDepthLimit = options.maxDepth ?? DEFAULT_MAX_DEPTH;
  const maxNodeLimit = options.maxNodeCount ?? DEFAULT_MAX_NODES;
  if (walk.maxDepth > maxDepthLimit) {
    issues.push({
      severity: walk.maxDepth > maxDepthLimit + 6 ? "error" : "warn",
      code: "deep-tree",
      message: `组件树嵌套 ${walk.maxDepth} 层（建议 ≤ ${maxDepthLimit} 层），渲染与维护成本偏高`,
      fix: "拆分为单独页面/复用组件，或减少无意义的布局容器嵌套。",
    });
  }
  const count = Object.keys(nodes).length;
  if (count > maxNodeLimit) {
    issues.push({
      severity: count > maxNodeLimit * 1.5 ? "error" : "warn",
      code: "too-many-nodes",
      message: `页面共有 ${count} 个节点（建议 ≤ ${maxNodeLimit}），编辑与发布可能变慢`,
      fix: "把长页面拆分为多个页面，复用组件，或删除无用节点。",
    });
  }
}

function checkUnreachable(
  nodes: Record<string, SchemaNode>,
  walk: WalkResult,
  issues: QualityIssue[],
  rootExists: boolean
): void {
  if (!rootExists) return; // 根节点缺失时整页都不可达，已由 root-missing 报过，避免刷屏
  const reachable = new Set(walk.order.map((node) => node.id));
  let reported = 0;
  let extra = 0;
  for (const node of Object.values(nodes)) {
    if (reachable.has(node.id)) continue;
    if (reported >= 10) {
      extra += 1;
      continue;
    }
    issues.push({
      severity: "warn",
      code: "unreachable-node",
      message: `节点 «${nodeLabel(node)}»（${node.type}）没有挂到页面树上，发布后不会渲染`,
      nodeId: node.id,
      nodeType: node.type,
      nodeLabel: nodeLabel(node),
      fix: "删除该节点，或把它重新挂到某个容器的 children / slots 中。",
    });
    reported += 1;
  }
  if (extra > 0) {
    issues.push({
      severity: "warn",
      code: "unreachable-node",
      message: `还有 ${extra} 个节点未挂到页面树上`,
      fix: "在大纲面板检查游离节点并清理。",
    });
  }
}

// ===================== 排序 / 汇总 =====================

const SEVERITY_RANK: Record<QualitySeverity, number> = { error: 0, warn: 1, info: 2 };

/** 错误优先、同级按 code 稳定排序（便于面板稳定展示）。 */
export function sortQualityIssues(issues: QualityIssue[]): QualityIssue[] {
  return [...issues].sort((a, b) => {
    const bySeverity = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
    if (bySeverity !== 0) return bySeverity;
    return a.code.localeCompare(b.code);
  });
}

/**
 * 页面审计入口。纯函数：同样的 schema 得到同样的问题列表（顺序稳定）。
 * 传入 null / 空结构返回空数组。
 */
export function auditPage(schema: PageSchema | null | undefined, options: AuditOptions = {}): QualityIssue[] {
  if (!schema || !schema.nodes || typeof schema.nodes !== "object") return [];
  const nodes = schema.nodes as Record<string, SchemaNode>;
  const issues: QualityIssue[] = [];

  checkPageMeta(schema, issues);
  checkRoot(schema, nodes, issues);

  const walk = walkTree(schema, nodes, issues);
  const order = walk.order.filter((node) => node.type !== "wp-canvas");

  checkContainers(order, nodes, options, issues);
  checkImagesAndLinks(order, nodes, issues);
  checkFormLabels(order, nodes, walk.parentOf, options, issues);
  checkContrast(order, issues);
  checkFixedWidth(order, options, issues);
  checkHiddenRequired(order, nodes, options, issues);
  checkFreeLayout(order, walk.parentOf, nodes, schema, issues);
  checkScale(walk, nodes, issues, options);
  checkUnreachable(nodes, walk, issues, !!nodes[schema.rootId]);

  return sortQualityIssues(issues);
}

/** 汇总问题数量；passed 为 true 表示没有 error 级问题。 */
export function auditSummary(issues: QualityIssue[]): QualitySummary {
  const summary: QualitySummary = {
    total: issues.length,
    error: 0,
    warn: 0,
    info: 0,
    passed: true,
    byCode: {},
  };
  for (const issue of issues) {
    summary[issue.severity] += 1;
    summary.byCode[issue.code] = (summary.byCode[issue.code] || 0) + 1;
  }
  summary.passed = summary.error === 0;
  return summary;
}
