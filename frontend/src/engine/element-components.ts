/**
 * Element Plus 全量组件/图标索引。
 *
 * 使用命名空间导入而不是逐个具名导入：注册表里的 element 是字符串，
 * 运行时按需取组件；打包器仍可静态分析 element-plus 的导出。
 * 对未安装/版本不匹配的组件返回 null，由 NodeRenderer 降级为占位。
 */
import * as ElementPlus from "element-plus";
import * as ElementPlusIcons from "@element-plus/icons-vue";

const components = ElementPlus as unknown as Record<string, any>;
const icons = ElementPlusIcons as unknown as Record<string, any>;

export function getElementComponent(name: string | undefined | null): any {
  if (!name) return null;
  return components[name] || null;
}

export function getElementIcon(name: string | undefined | null): any {
  if (!name) return null;
  return icons[name] || null;
}

export function hasElementComponent(name: string): boolean {
  return !!getElementComponent(name);
}

/** 结构化组件：在运行态不包一层 div，避免破坏 Element 的父子插槽协议。 */
export const STRUCTURAL_ELEMENTS = new Set([
  "ElOption",
  "ElTableColumn",
  "ElTabPane",
  "ElStep",
  "ElMenuItem",
  "ElSubMenu",
  "ElBreadcrumbItem",
  "ElCarouselItem",
  "ElTimelineItem",
  "ElCollapseItem",
  "ElDescriptionsItem",
  "ElDropdownMenu",
  "ElDropdownItem",
  "ElAnchorLink",
  "ElSplitterPanel",
  "ElTourStep",
]);

/**
 * 使用 useOrderedChildren 收集直接子组件的复合组件：
 * type → 子组件 Element 名。运行时由 CompositeRenderer 直接生成真实 VNode。
 */
export const COMPOSITE_CHILDREN: Record<string, string> = {
  ElTabs: "ElTabPane",
  ElSteps: "ElStep",
  ElCarousel: "ElCarouselItem",
  ElSplitter: "ElSplitterPanel",
  ElTour: "ElTourStep",
  ElMenu: "ElMenuItem",
  ElCollapse: "ElCollapseItem",
  ElTimeline: "ElTimelineItem",
  ElDescriptions: "ElDescriptionsItem",
  ElBreadcrumb: "ElBreadcrumbItem",
  ElAnchor: "ElAnchorLink",
};

/** 这些组件必须直接拿到默认插槽文本，而不是把 label 当 prop。 */
export const TEXT_SLOT_ELEMENTS = new Set([
  "ElButton",
  "ElLink",
  "ElText",
  "ElTag",
  "ElCheckbox",
  "ElRadio",
  "ElBreadcrumbItem",
  "ElDropdownItem",
  "ElMenuItem",
  "ElStep",
  "ElTimelineItem",
  "ElPageHeader",
]);
