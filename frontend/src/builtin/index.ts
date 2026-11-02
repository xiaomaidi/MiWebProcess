/** 内置组件注册表：组件类型键 / 运行时 element 名 → Vue 组件。 */
import type { Component } from "vue";

import WpContainer from "./components/wp-container.vue";
import WpRow from "./components/wp-row.vue";
import WpColumn from "./components/wp-column.vue";
import WpCard from "./components/wp-card.vue";
import WpTabs from "./components/wp-tabs.vue";
import WpTabItem from "./components/wp-tab-item.vue";
import WpGrid from "./components/wp-grid.vue";
import WpSpace from "./components/wp-space.vue";
import WpDivider from "./components/wp-divider.vue";
import WpFreebox from "./components/wp-freebox.vue";
import WpText from "./components/wp-text.vue";
import WpHeading from "./components/wp-heading.vue";
import WpImage from "./components/wp-image.vue";
import WpButton from "./components/wp-button.vue";
import WpLink from "./components/wp-link.vue";
import WpTag from "./components/wp-tag.vue";
import WpAlert from "./components/wp-alert.vue";
import WpModal from "./components/wp-modal.vue";
import WpBadge from "./components/wp-badge.vue";
import WpForm from "./components/wp-form.vue";
import WpInput from "./components/wp-input.vue";
import WpTextarea from "./components/wp-textarea.vue";
import WpSelect from "./components/wp-select.vue";
import WpCheckbox from "./components/wp-checkbox.vue";
import WpRadio from "./components/wp-radio.vue";
import WpSwitch from "./components/wp-switch.vue";
import WpNumber from "./components/wp-number.vue";
import WpDate from "./components/wp-date.vue";
import WpTable from "./components/wp-table.vue";
import WpList from "./components/wp-list.vue";
import WpStatcard from "./components/wp-statcard.vue";
import WpProgress from "./components/wp-progress.vue";
import WpBarchart from "./components/wp-barchart.vue";
import WpPiechart from "./components/wp-piechart.vue";
import WpEcharts from "./components/wp-echarts.vue";
import WpWsLive from "./components/wp-ws-live.vue";
import WorkflowTaskCenter from "./components/workflow-task-center.vue";
import NotificationInbox from "./components/notification-inbox.vue";

import DataTable from "./components/data-table.vue";
import CardRenderer from "./components/card-renderer.vue";
import CompositeRenderer from "./components/composite-renderer.vue";
import SelectField from "./components/select-field.vue";
import ChoiceGroup from "./components/choice-group.vue";
import AutoForm from "./components/auto-form.vue";
import ContentList from "./components/content-list.vue";
import ArticleDetail from "./components/article-detail.vue";
import SiteNav from "./components/site-nav.vue";
import SiteSearch from "./components/site-search.vue";
import RelationTable from "./components/relation-table.vue";
import PublicMasterDetail from "./components/public-master-detail.vue";
import PublicJoinTable from "./components/public-join-table.vue";
import ApprovalPanel from "./components/approval-panel.vue";
import ReportTable from "./components/report-table.vue";
import RichText from "./components/rich-text.vue";
import MarkdownRenderer from "./components/markdown-renderer.vue";
import CodeBlock from "./components/code-block.vue";
import ChartRenderer from "./components/chart-renderer.vue";
import HtmlBlock from "./components/html-block.vue";
import SvgBlock from "./components/svg-block.vue";
import CanvasBlock from "./components/canvas-block.vue";
import ComponentSlot from "./components/component-slot.vue";
import LoadingOverlay from "./components/loading-overlay.vue";
import PortalBlock from "./components/portal-block.vue";

export const builtinComponents: Record<string, Component> = {
  "wp-container": WpContainer,
  "wp-row": WpRow,
  "wp-column": WpColumn,
  "wp-card": WpCard,
  "wp-tabs": WpTabs,
  "wp-tab-item": WpTabItem,
  "wp-grid": WpGrid,
  "wp-space": WpSpace,
  "wp-divider": WpDivider,
  "wp-freebox": WpFreebox,
  "wp-text": WpText,
  "wp-heading": WpHeading,
  "wp-image": WpImage,
  "wp-button": WpButton,
  "wp-link": WpLink,
  "wp-tag": WpTag,
  "wp-alert": WpAlert,
  "wp-modal": WpModal,
  "wp-badge": WpBadge,
  "wp-form": WpForm,
  "wp-input": WpInput,
  "wp-textarea": WpTextarea,
  "wp-select": WpSelect,
  "wp-checkbox": WpCheckbox,
  "wp-radio": WpRadio,
  "wp-switch": WpSwitch,
  "wp-number": WpNumber,
  "wp-date": WpDate,
  "wp-table": WpTable,
  "wp-list": WpList,
  "wp-statcard": WpStatcard,
  "wp-progress": WpProgress,
  "wp-barchart": WpBarchart,
  "wp-piechart": WpPiechart,
  "wp-echarts": WpEcharts,
  "wp-ws-live": WpWsLive,
  "workflow-task-center": WorkflowTaskCenter,
  "notification-inbox": NotificationInbox,

  // v2 运行时特殊组件（registry.element 指向这些名字）
  DataTable,
  CardRenderer,
  CompositeRenderer,
  SelectField,
  ChoiceGroup,
  AutoForm,
  ContentList,
  ArticleDetail,
  SiteNav,
  SiteSearch,
  RelationTable,
  PublicMasterDetail,
  PublicJoinTable,
  ApprovalPanel,
  ReportTable,
  RichText,
  MarkdownRenderer,
  CodeBlock,
  ChartRenderer,
  HtmlBlock,
  SvgBlock,
  CanvasBlock,
  ComponentSlot,
  LoadingOverlay,
  PortalBlock,
};

export {
  DataTable,
  CardRenderer,
  CompositeRenderer,
  SelectField,
  ChoiceGroup,
  AutoForm,
  ContentList,
  ArticleDetail,
  SiteNav,
  SiteSearch,
  RelationTable,
  PublicMasterDetail,
  PublicJoinTable,
  ApprovalPanel,
  ReportTable,
  RichText,
  MarkdownRenderer,
  CodeBlock,
  ChartRenderer,
  HtmlBlock,
  SvgBlock,
  CanvasBlock,
  ComponentSlot,
  LoadingOverlay,
  PortalBlock,
};
