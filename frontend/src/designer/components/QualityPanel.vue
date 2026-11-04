<template>
  <div class="wp-quality">
    <div class="wp-quality-head">
      <div class="wp-quality-title">
        <strong>发布前质检</strong>
        <span class="wp-quality-time">{{ lastRunText }}</span>
      </div>
      <el-button size="small" type="primary" plain :loading="running" @click="runAudit">重新检查</el-button>
    </div>

    <div class="wp-quality-summary" role="status" aria-live="polite">
      <span class="wp-quality-pill is-error">错误 {{ summary.error }}</span>
      <span class="wp-quality-pill is-warn">警告 {{ summary.warn }}</span>
      <span class="wp-quality-pill is-info">提示 {{ summary.info }}</span>
      <span v-if="hasRun" class="wp-quality-duration">共 {{ summary.total }} 项 · {{ durationMs }}ms</span>
    </div>

    <el-radio-group v-model="filter" size="small" class="wp-quality-filter">
      <el-radio-button value="all">全部 {{ summary.total }}</el-radio-button>
      <el-radio-button value="error">错误 {{ summary.error }}</el-radio-button>
      <el-radio-button value="warn">警告 {{ summary.warn }}</el-radio-button>
      <el-radio-button value="info">提示 {{ summary.info }}</el-radio-button>
    </el-radio-group>

    <div v-if="!hasRun" class="wp-quality-empty">
      <el-empty description="尚未检查，点击「重新检查」开始" :image-size="48" />
    </div>
    <div v-else-if="!visibleIssues.length" class="wp-quality-empty">
      <el-empty
        :description="issues.length ? '当前筛选没有结果' : '未发现问题，可以发布'"
        :image-size="48"
      />
    </div>
    <ul v-else class="wp-quality-list">
      <li
        v-for="(issue, index) in visibleIssues"
        :key="`${issue.code}-${issue.nodeId || 'page'}-${index}`"
        class="wp-quality-item"
        :class="{ 'is-static': !issue.nodeId }"
        @click="focusIssue(issue)"
      >
        <el-tag size="small" :type="tagType(issue.severity)" effect="light" class="wp-quality-tag">
          {{ severityLabel(issue.severity) }}
        </el-tag>
        <div class="wp-quality-body">
          <div class="wp-quality-msg">{{ issue.message }}</div>
          <div class="wp-quality-meta">
            <span v-if="issue.nodeType" class="wp-quality-node">
              {{ issue.nodeType }}<template v-if="issue.nodeLabel && issue.nodeLabel !== issue.nodeType"> · {{ issue.nodeLabel }}</template>
            </span>
            <span class="wp-quality-code">{{ issue.code }}</span>
          </div>
          <div class="wp-quality-fix">修复：{{ issue.fix }}</div>
          <div v-if="issue.detail" class="wp-quality-detail">{{ issue.detail }}</div>
        </div>
        <button
          v-if="issue.nodeId"
          type="button"
          class="wp-quality-locate"
          :aria-label="`定位到节点 ${issue.nodeLabel || issue.nodeId}`"
          @click.stop="focusIssue(issue)"
        >
          定位
        </button>
      </li>
    </ul>

    <div v-if="hasRun" class="wp-quality-foot">
      <span class="wp-quality-hint">点击问题可选中并定位画布节点；对比度 / 重叠为启发式检查。</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 页面质量 / 可访问性检查面板（预发布自检）。
 *
 * 自成一体：直接注入 schema store 与 component store，不依赖 DesignerView 的 props。
 * 接入方式（不改本文件）：
 *   - 抽屉：<el-drawer v-model="qualityOpen"><QualityPanel /></el-drawer>
 *   - 标签页：leftTab 增加 <el-tab-pane label="质检" name="quality"><QualityPanel /></el-tab-pane>
 * 也可通过 ref 调用面板的 runAudit() 在打开前刷新。
 */
import { computed, onMounted, ref, watch } from "vue";
import { useSchemaStore } from "@/store/schema";
import { useComponentStore } from "@/store/component";
import {
  auditPage,
  auditSummary,
  type QualityIssue,
  type QualitySeverity,
  type QualitySummary,
} from "../quality";

type Filter = "all" | QualitySeverity;

const schema = useSchemaStore();
const components = useComponentStore();

const filter = ref<Filter>("all");
const issues = ref<QualityIssue[]>([]);
const summary = ref<QualitySummary>(auditSummary([]));
const lastRunAt = ref<Date | null>(null);
const durationMs = ref(0);
const hasRun = ref(false);
const running = ref(false);

const visibleIssues = computed<QualityIssue[]>(() =>
  filter.value === "all" ? issues.value : issues.value.filter((issue) => issue.severity === filter.value)
);

const lastRunText = computed(() => {
  if (!lastRunAt.value) return "尚未检查";
  return `上次检查 ${lastRunAt.value.toLocaleTimeString("zh-CN", { hour12: false })}`;
});

function runAudit() {
  const started = Date.now();
  running.value = true;
  try {
    if (!schema.schema) {
      // 页面 schema 尚未加载：保持“尚未检查”，避免误报“未发现问题”。
      issues.value = [];
      summary.value = auditSummary([]);
      hasRun.value = false;
      return;
    }
    issues.value = auditPage(schema.schema, {
      isContainer: (type) => !!components.meta(type)?.is_container,
      isFormField: (type) => !!components.meta(type)?.is_form_field,
    });
    summary.value = auditSummary(issues.value);
    lastRunAt.value = new Date();
    durationMs.value = Math.max(0, Date.now() - started);
    hasRun.value = true;
    // 当前筛选结果为空时回到“全部”，避免看起来像没检查。
    if (filter.value !== "all" && !visibleIssues.value.length) filter.value = "all";
  } finally {
    running.value = false;
  }
}

function focusIssue(issue: QualityIssue) {
  if (!issue.nodeId) return;
  if (!schema.schema?.nodes[issue.nodeId]) return;
  schema.select(issue.nodeId);
  if (typeof document === "undefined") return;
  const nodeId = issue.nodeId;
  requestAnimationFrame(() => {
    const selector = `[data-wp-node="${nodeId.replace(/["\\]/g, "\\$&")}"]`;
    const el = document.querySelector(selector);
    el?.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
  });
}

function tagType(severity: QualitySeverity): "danger" | "warning" | "info" {
  if (severity === "error") return "danger";
  if (severity === "warn") return "warning";
  return "info";
}

function severityLabel(severity: QualitySeverity): string {
  if (severity === "error") return "错误";
  if (severity === "warn") return "警告";
  return "提示";
}

// 页面加载 / 切换时自动重跑；同一页面的编辑保留手动刷新。
watch(
  () => [schema.pageId, schema.schema?.rootId] as const,
  () => runAudit()
);

onMounted(runAudit);

defineExpose({ runAudit, issues, summary });
</script>

<style scoped>
.wp-quality {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px;
  min-width: 0;
  font-size: 13px;
  box-sizing: border-box;
}
.wp-quality-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.wp-quality-title {
  display: flex;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}
.wp-quality-time {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wp-quality-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-quality-pill {
  padding: 0 6px;
  border-radius: 9px;
  font-size: 11px;
  line-height: 18px;
  white-space: nowrap;
}
.wp-quality-pill.is-error {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}
.wp-quality-pill.is-warn {
  color: var(--el-color-warning);
  background: var(--el-color-warning-light-9);
}
.wp-quality-pill.is-info {
  color: var(--el-color-info);
  background: var(--el-color-info-light-9);
}
.wp-quality-duration {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-quality-filter {
  display: flex;
  flex-wrap: wrap;
  row-gap: 4px;
  max-width: 100%;
}
.wp-quality-filter :deep(.el-radio-button__inner) {
  padding: 5px 8px;
  font-size: 12px;
}
.wp-quality-empty {
  padding: 4px 0;
}
.wp-quality-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.wp-quality-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 6px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-bg-color);
  transition: background-color 0.15s ease, border-color 0.15s ease;
  min-width: 0;
}
.wp-quality-item:not(.is-static) {
  cursor: pointer;
}
.wp-quality-item:not(.is-static):hover {
  background: var(--el-fill-color-light);
  border-color: var(--el-color-primary-light-7);
}
.wp-quality-item.is-static {
  cursor: default;
}
.wp-quality-tag {
  flex: 0 0 auto;
  margin-top: 1px;
}
.wp-quality-body {
  flex: 1;
  min-width: 0;
}
.wp-quality-msg {
  font-size: 13px;
  line-height: 1.45;
  color: var(--el-text-color-primary);
  word-break: break-word;
}
.wp-quality-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
}
.wp-quality-node {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wp-quality-code {
  padding: 0 4px;
  border-radius: 2px;
  background: var(--el-fill-color);
  font-family: ui-monospace, Consolas, monospace;
  font-size: 10px;
}
.wp-quality-fix {
  margin-top: 3px;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}
.wp-quality-detail {
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.4;
  word-break: break-word;
}
.wp-quality-locate {
  flex: 0 0 auto;
  align-self: center;
  padding: 2px 6px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 3px;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 11px;
  line-height: 1.4;
  cursor: pointer;
}
.wp-quality-locate:hover,
.wp-quality-locate:focus-visible {
  background: var(--el-color-primary-light-8);
  outline: none;
}
.wp-quality-foot {
  padding-top: 2px;
}
.wp-quality-hint {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  line-height: 1.4;
}

@media (max-width: 640px) {
  .wp-quality {
    padding: 6px;
    gap: 6px;
  }
  .wp-quality-head {
    align-items: flex-start;
  }
  .wp-quality-item {
    padding: 5px 6px;
  }
  .wp-quality-msg {
    font-size: 12px;
  }
}
</style>
