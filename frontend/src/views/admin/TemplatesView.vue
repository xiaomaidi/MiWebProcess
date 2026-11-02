<template>
  <div class="wp-admin-page">
    <div class="wp-page-header">
      <div class="wp-page-title-block">
        <h2>模板中心</h2>
        <p class="wp-page-desc">选一个业务模板，输入名称即可创建应用；创建后可继续在设计器里修改。</p>
      </div>
      <div class="wp-page-actions">
        <el-button @click="fileInput?.click()">导入模板 JSON</el-button>
        <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="importFile" />
      </div>
    </div>

    <div class="wp-template-grid">
      <el-card v-for="item in templates" :key="item.key" shadow="hover" class="wp-template-card">
        <div class="wp-template-icon" :style="{ background: item.accent }">{{ item.icon }}</div>
        <div class="wp-template-body">
          <div class="wp-template-head">
            <h3>{{ item.name }}</h3>
            <el-tag size="small" effect="plain">{{ item.category }}</el-tag>
          </div>
          <p>{{ item.description }}</p>
          <div class="wp-template-tags">
            <el-tag v-for="tag in item.tags" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
          </div>
          <div class="wp-template-actions">
            <el-button type="primary" plain @click="openCreate(item)">使用模板</el-button>
            <el-button size="small" @click="openEdit(item)">编辑</el-button>
            <el-button size="small" @click="openHistory(item)">版本</el-button>
          </div>
        </div>
      </el-card>
    </div>

    <el-dialog v-model="dialogVisible" title="使用模板创建应用" width="520px" :close-on-click-modal="false">
      <el-form v-if="selected" label-width="90px">
        <el-form-item label="模板">
          <el-input :model-value="selected.name" disabled />
        </el-form-item>
        <el-form-item label="应用名称" required>
          <el-input v-model="form.name" :placeholder="selected.name" />
        </el-form-item>
        <el-form-item label="应用标识" required>
          <el-input v-model="form.code" placeholder="inventory-demo" />
        </el-form-item>
        <el-form-item label="额外成员">
          <el-select v-model="form.members" multiple filterable placeholder="可选，添加为只读成员" style="width: 100%">
            <el-option v-for="u in users" :key="u.id" :label="`${u.username}（${u.email || '无邮箱'}）`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="将创建一个首页草稿；数据模型、接口和权限可后续在应用内补充。"
        />
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="createApp">创建并进入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editVisible" title="编辑模板 JSON" width="820px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" show-icon title="保存后仅影响当前浏览器中的模板副本；导出/导入可跨机器共享。" />
      <el-input v-model="editJson" type="textarea" :rows="22" class="wp-template-json" />
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存模板</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="模板版本" width="620px">
      <el-table :data="historyRows" size="small" border>
        <el-table-column label="时间" width="190">
          <template #default="{ row }">{{ new Date(row.at).toLocaleString() }}</template>
        </el-table-column>
        <el-table-column label="说明" min-width="220">
          <template #default="{ row }">{{ row.note || "手动保存" }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="restoreVersion(row)">恢复</el-button>
          </template>
        </el-table-column>
        <template #empty><el-empty description="还没有模板版本" :image-size="50" /></template>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/api";

interface TemplateDef {
  key: string;
  name: string;
  category: string;
  icon: string;
  accent: string;
  description: string;
  tags: string[];
  schema: (name: string) => any;
  model?: any;
  records?: any[];
  workflow?: any;
}

const router = useRouter();
const dialogVisible = ref(false);
const creating = ref(false);
const selected = ref<TemplateDef | null>(null);
const fileInput = ref<HTMLInputElement | null>(null);
const users = ref<any[]>([]);
const form = reactive({ name: "", code: "", members: [] as number[] });
const editVisible = ref(false);
const editJson = ref("");
const editingTemplate = ref<TemplateDef | null>(null);
const historyVisible = ref(false);
const historyRows = ref<any[]>([]);
const historyTemplate = ref<TemplateDef | null>(null);

const OVERRIDE_KEY = "wp-template-overrides-v1";
const VERSION_KEY = "wp-template-versions-v1";
const overrides = ref<Record<string, any>>(loadJson(OVERRIDE_KEY, {}));
const versions = ref<Record<string, any[]>>(loadJson(VERSION_KEY, {}));

function loadJson(key: string, fallback: any) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null") ?? fallback;
  } catch {
    return fallback;
  }
}

function persistTemplates() {
  localStorage.setItem(OVERRIDE_KEY, JSON.stringify(overrides.value));
  localStorage.setItem(VERSION_KEY, JSON.stringify(versions.value));
}

function bundleOf(item: TemplateDef, name: string) {
  const schema = item.schema(name);
  return {
    name,
    description: item.description,
    design_tokens: schema.meta?.designTokens || {},
    pages: [{ name: "首页", path: "home", type: "page", schema, schemaVersion: schema.schemaVersion || 2 }],
    models: item.model
      ? [{ ...item.model, records: item.records || item.model.records || [] }]
      : [],
    workflow: item.workflow || {},
  };
}

function activeBundle(item: TemplateDef, name: string) {
  const custom = overrides.value[item.key];
  return custom ? JSON.parse(JSON.stringify(custom)) : bundleOf(item, name);
}

function openEdit(item: TemplateDef) {
  editingTemplate.value = item;
  editJson.value = JSON.stringify(activeBundle(item, item.name), null, 2);
  editVisible.value = true;
}

function saveEdit() {
  if (!editingTemplate.value) return;
  let parsed: any;
  try {
    parsed = JSON.parse(editJson.value);
  } catch {
    ElMessage.error("模板 JSON 格式不正确");
    return;
  }
  if (!Array.isArray(parsed?.pages) || !parsed.pages.length) {
    ElMessage.error("模板必须包含 pages");
    return;
  }
  overrides.value[editingTemplate.value.key] = parsed;
  versions.value[editingTemplate.value.key] = [
    { at: Date.now(), note: "手动保存", bundle: JSON.parse(JSON.stringify(parsed)) },
    ...(versions.value[editingTemplate.value.key] || []),
  ].slice(0, 20);
  persistTemplates();
  editVisible.value = false;
  ElMessage.success("模板已保存");
}

function openHistory(item: TemplateDef) {
  historyTemplate.value = item;
  historyRows.value = versions.value[item.key] || [];
  historyVisible.value = true;
}

function restoreVersion(row: any) {
  if (!historyTemplate.value) return;
  overrides.value[historyTemplate.value.key] = JSON.parse(JSON.stringify(row.bundle));
  persistTemplates();
  historyVisible.value = false;
  ElMessage.success("模板版本已恢复");
}

function node(id: string, type: string, props: any, children: string[] = [], style: any = {}) {
  return { id, type, props, children, style };
}

function baseNodes(extra: Record<string, any>, brand: string, title: string, background = "#f5f7fa") {
  const nodes: Record<string, any> = {
    root: node("root", "wp-canvas", {}, ["main"], { minHeight: "100vh", background }),
    main: node("main", "ElContainer", { direction: "vertical", padding: 0, background }, ["nav", ...Object.keys(extra), "footer"], { width: "100%" }),
    nav: node("nav", "site-nav", { brand, dark: false, homePath: "home", showSearch: false, links: [{ label: "首页", path: "home" }] }),
    footer: node("footer", "ElContainer", { direction: "vertical", padding: 20, background: "#ffffff" }, ["footerText"], { borderTop: "1px solid #e4e7ed", marginTop: "24px" }),
    footerText: node("footerText", "wp-text", { content: `${title} · 由模板中心创建`, align: "center", color: "#909399", fontSize: 12 }),
  };
  return Object.assign(nodes, extra);
}

function makeSchema(nodes: Record<string, any>, title: string, preset = "light-admin") {
  return {
    schemaVersion: 2,
    rootId: "root",
    nodes,
    meta: {
      title,
      lang: "zh-CN",
      designTokens: { preset },
      seo: { description: `${title}模板` },
    },
    layout: { mode: "flow", width: 1200, height: 900 },
  };
}

function inventorySchema(name: string) {
  const nodes = baseNodes({
    hero: node("hero", "ElContainer", { direction: "vertical", padding: 28, background: "#ffffff" }, ["title", "desc"], { maxWidth: "1120px", margin: "0 auto", width: "100%" }),
    title: node("title", "wp-heading", { content: name || "库存台账", level: 1, color: "#303133", marginBottom: 6 }),
    desc: node("desc", "wp-text", { content: "物料库存、批次、预警和出入库记录。", color: "#909399", fontSize: 14 }),
    filters: node("filters", "common-filter-bar", {
      title: "筛选库存",
      fields: [
        { key: "keyword", label: "物料", placeholder: "名称 / SKU" },
        { key: "status", label: "状态", type: "select", options: [{ label: "正常", value: "normal" }, { label: "低库存", value: "low" }, { label: "缺货", value: "out" }] },
      ],
    }, [], { maxWidth: "1120px", margin: "0 auto 14px", width: "100%" }),
    table: node("table", "data-table", {
      title: "库存明细",
      dataModelId: "__TEMPLATE_MODEL__",
      dataModelKey: "inventory_item",
      remote: true,
      autoColumns: true,
      showPagination: true,
      pageSize: 10,
      showSearch: true,
      exportable: true,
      emptyText: "暂无库存数据",
    }, [], { maxWidth: "1120px", margin: "0 auto", width: "100%" }),
  }, name || "库存台账", "库存台账", "#f5f7fa");
  return makeSchema(nodes, name || "库存台账", "light-admin");
}

function approvalSchema(name: string) {
  const nodes = baseNodes({
    hero: node("hero", "ElContainer", { direction: "vertical", padding: 28, background: "#ffffff" }, ["title", "desc"], { maxWidth: "1000px", margin: "0 auto", width: "100%" }),
    title: node("title", "wp-heading", { content: name || "审批流程", level: 1, color: "#303133", marginBottom: 6 }),
    desc: node("desc", "wp-text", { content: "申请、审核、驳回和流程记录。", color: "#909399", fontSize: 14 }),
    flow: node("flow", "common-approval-flow", {
      title: "采购申请审批",
      current: 1,
      steps: [
        { title: "提交申请", approver: "申请人", status: "approved", comment: "采购 20 台电机", time: "2026-01-01 10:00" },
        { title: "部门审核", approver: "部门负责人", status: "pending" },
        { title: "财务审核", approver: "财务", status: "pending" },
      ],
    }, [], { maxWidth: "1000px", margin: "0 auto 14px", width: "100%" }),
    timeline: node("timeline", "common-timeline", {
      title: "流程动态",
      items: [
        { time: "10:00", title: "创建申请", desc: "采购申请已提交", color: "#409eff" },
        { time: "10:10", title: "部门待审", desc: "等待负责人处理", color: "#e6a23c" },
      ],
    }, [], { maxWidth: "1000px", margin: "0 auto", width: "100%" }),
  }, name || "审批流程", "审批中心", "#f5f7fa");
  return makeSchema(nodes, name || "审批流程", "corporate-blue");
}

function customerSchema(name: string) {
  const nodes = baseNodes({
    hero: node("hero", "ElContainer", { direction: "vertical", padding: 28, background: "#ffffff" }, ["title", "desc"], { maxWidth: "1120px", margin: "0 auto", width: "100%" }),
    title: node("title", "wp-heading", { content: name || "客户管理", level: 1, color: "#303133", marginBottom: 6 }),
    desc: node("desc", "wp-text", { content: "客户档案、联系人和跟进状态。", color: "#909399", fontSize: 14 }),
    table: node("table", "data-table", {
      title: "客户列表",
      dataModelId: "__TEMPLATE_MODEL__",
      dataModelKey: "customer",
      remote: true,
      autoColumns: true,
      showPagination: true,
      pageSize: 10,
      showSearch: true,
      exportable: true,
      emptyText: "暂无客户数据",
    }, [], { maxWidth: "1120px", margin: "0 auto", width: "100%" }),
  }, name || "客户管理", "客户管理", "#f5f7fa");
  return makeSchema(nodes, name || "客户管理", "light-admin");
}

function dashboardSchema(name: string) {
  const nodes = baseNodes({
    hero: node("hero", "ElContainer", { direction: "vertical", padding: 28, background: "#07111f" }, ["title", "desc"], { maxWidth: "1120px", margin: "0 auto", width: "100%" }),
    title: node("title", "wp-heading", { content: name || "数据看板", level: 1, color: "#e5e7eb", marginBottom: 6 }),
    desc: node("desc", "wp-text", { content: "核心指标、趋势和明细。", color: "#94a3b8", fontSize: 14 }),
    stats: node("stats", "ElContainer", { direction: "horizontal", padding: 12, background: "#07111f" }, ["s1", "s2", "s3"], { gap: "14px", maxWidth: "1120px", margin: "0 auto 14px", width: "100%" }),
    s1: node("s1", "wp-statcard", { label: "今日订单", color: "#22d3ee", background: "#0d1b2f", border: "1px solid #1e3a5f" }),
    s2: node("s2", "wp-statcard", { label: "销售额", color: "#22c55e", background: "#0d1b2f", border: "1px solid #1e3a5f" }),
    s3: node("s3", "wp-statcard", { label: "库存预警", color: "#f59e0b", background: "#0d1b2f", border: "1px solid #1e3a5f" }),
    table: node("table", "data-table", {
      title: "业务明细",
      dataModelId: "__TEMPLATE_MODEL__",
      dataModelKey: "order",
      remote: true,
      autoColumns: true,
      showPagination: true,
      pageSize: 10,
      showSearch: true,
      exportable: true,
      emptyText: "暂无业务数据",
    }, [], { maxWidth: "1120px", margin: "0 auto", width: "100%" }),
  }, name || "数据看板", "数据看板", "#07111f");
  return makeSchema(nodes, name || "数据看板", "dashboard-dark");
}

function corporateSchema(name: string) {
  const nodes = baseNodes({
    hero: node("hero", "ElContainer", { direction: "vertical", padding: 48, background: "#0b0f14" }, ["title", "desc", "cta"], { textAlign: "center", background: "linear-gradient(120deg,#0b0f14,#16202e)" }),
    title: node("title", "wp-heading", { content: name || "企业官网", level: 1, align: "center", color: "#f8fafc", marginBottom: 10 }),
    desc: node("desc", "wp-text", { content: "把产品、方案和联系信息放在一个页面里。", align: "center", color: "#a9b4c0", fontSize: 16 }),
    cta: node("cta", "ElButton", { text: "联系我们", type: "primary" }, [], { marginTop: "10px" }),
    features: node("features", "ElContainer", { direction: "horizontal", padding: 24, background: "#ffffff" }, ["f1", "f2", "f3"], { gap: "18px", justifyContent: "center", flexWrap: "wrap" }),
    f1: node("f1", "ElContainer", { direction: "vertical", padding: 20, background: "#ffffff" }, ["f1t", "f1d"], { width: "280px", border: "1px solid #e4e7ed", borderRadius: "10px" }),
    f1t: node("f1t", "wp-heading", { content: "产品能力", level: 3, color: "#303133" }),
    f1d: node("f1d", "wp-text", { content: "稳定、可扩展的业务基础能力。", color: "#606266", fontSize: 14 }),
    f2: node("f2", "ElContainer", { direction: "vertical", padding: 20, background: "#ffffff" }, ["f2t", "f2d"], { width: "280px", border: "1px solid #e4e7ed", borderRadius: "10px" }),
    f2t: node("f2t", "wp-heading", { content: "行业方案", level: 3, color: "#303133" }),
    f2d: node("f2d", "wp-text", { content: "按业务场景组合页面和数据。", color: "#606266", fontSize: 14 }),
    f3: node("f3", "ElContainer", { direction: "vertical", padding: 20, background: "#ffffff" }, ["f3t", "f3d"], { width: "280px", border: "1px solid #e4e7ed", borderRadius: "10px" }),
    f3t: node("f3t", "wp-heading", { content: "服务支持", level: 3, color: "#303133" }),
    f3d: node("f3d", "wp-text", { content: "从搭建到上线的一站式支持。", color: "#606266", fontSize: 14 }),
  }, name || "企业官网", "企业官网", "#0b0f14");
  return makeSchema(nodes, name || "企业官网", "dark-game");
}

function contentSchema(name: string) {
  const nodes = baseNodes({
    hero: node("hero", "ElContainer", { direction: "vertical", padding: 32, background: "#ffffff" }, ["title", "desc"], { maxWidth: "1000px", margin: "0 auto", width: "100%" }),
    title: node("title", "wp-heading", { content: name || "内容站", level: 1, color: "#303133", marginBottom: 6 }),
    desc: node("desc", "wp-text", { content: "文章、专题和最新动态。", color: "#909399", fontSize: 14 }),
    list: node("list", "ElContainer", { direction: "vertical", padding: 12, background: "#ffffff" }, ["a1", "a2", "a3"], { maxWidth: "1000px", margin: "0 auto", gap: "12px", width: "100%" }),
    a1: node("a1", "ElContainer", { direction: "vertical", padding: 16, background: "#ffffff" }, ["a1t", "a1d"], { borderBottom: "1px solid #ebeef5", width: "100%" }),
    a1t: node("a1t", "wp-heading", { content: "第一篇文章标题", level: 2, color: "#303133", marginBottom: 4 }),
    a1d: node("a1d", "wp-text", { content: "文章摘要内容，点击进入详情页继续阅读。", color: "#909399", fontSize: 14 }),
    a2: node("a2", "ElContainer", { direction: "vertical", padding: 16, background: "#ffffff" }, ["a2t", "a2d"], { borderBottom: "1px solid #ebeef5", width: "100%" }),
    a2t: node("a2t", "wp-heading", { content: "第二篇文章标题", level: 2, color: "#303133", marginBottom: 4 }),
    a2d: node("a2d", "wp-text", { content: "文章摘要内容，点击进入详情页继续阅读。", color: "#909399", fontSize: 14 }),
    a3: node("a3", "ElContainer", { direction: "vertical", padding: 16, background: "#ffffff" }, ["a3t", "a3d"], { width: "100%" }),
    a3t: node("a3t", "wp-heading", { content: "第三篇文章标题", level: 2, color: "#303133", marginBottom: 4 }),
    a3d: node("a3d", "wp-text", { content: "文章摘要内容，点击进入详情页继续阅读。", color: "#909399", fontSize: 14 }),
  }, name || "内容站", "内容站", "#ffffff");
  return makeSchema(nodes, name || "内容站", "warm");
}

const workflows = {
  approval: {
    name: "采购申请审批",
    code: "purchase_approval",
    description: "部门审批后进入结束节点",
    publish: true,
    nodes: [
      { id: "start", name: "发起", type: "start" },
      { id: "dept", name: "部门审批", type: "approval", assignee_role: "editor", mode: "all" },
      { id: "end", name: "结束", type: "end", on_approve: { status: "已审批" }, on_reject: { status: "已驳回" } },
    ],
  },
};

const models = {
  inventory: {
    name: "inventory_item",
    fields: [
      { name: "sku", label: "SKU", type: "string", required: true },
      { name: "name", label: "物料", type: "string", required: true },
      { name: "warehouse", label: "仓库", type: "string" },
      { name: "stock", label: "库存", type: "number" },
      { name: "unit", label: "单位", type: "string" },
    ],
    records: [
      { sku: "M-1001", name: "螺丝 M6", warehouse: "主仓", stock: 1280, unit: "个" },
      { sku: "M-1002", name: "电机", warehouse: "主仓", stock: 36, unit: "台" },
      { sku: "M-1003", name: "包装箱", warehouse: "辅仓", stock: 8, unit: "个" },
    ],
  },
  customer: {
    name: "customer",
    fields: [
      { name: "name", label: "客户", type: "string", required: true },
      { name: "contact", label: "联系人", type: "string" },
      { name: "phone", label: "电话", type: "string" },
      { name: "level", label: "等级", type: "string" },
    ],
    records: [
      { name: "华东制造", contact: "张经理", phone: "13800000001", level: "A" },
      { name: "南方物流", contact: "李经理", phone: "13800000002", level: "B" },
    ],
  },
  order: {
    name: "order",
    fields: [
      { name: "date", label: "日期", type: "date" },
      { name: "order_no", label: "订单", type: "string" },
      { name: "amount", label: "金额", type: "number" },
      { name: "status", label: "状态", type: "string" },
    ],
    records: [
      { date: "2026-01-01", order_no: "SO-001", amount: 12800, status: "已完成" },
      { date: "2026-01-02", order_no: "SO-002", amount: 8600, status: "进行中" },
    ],
  },
  approval: {
    name: "approval_request",
    fields: [
      { name: "title", label: "申请标题", type: "string", required: true },
      { name: "amount", label: "金额", type: "number" },
      { name: "status", label: "状态", type: "string" },
    ],
    records: [
      { title: "采购 20 台电机", amount: 36000, status: "待审批" },
    ],
  },
};

const templates: TemplateDef[] = [
  { key: "inventory", name: "库管台账", category: "业务管理", icon: "▦", accent: "#409eff", description: "库存明细、筛选、预警和出入库入口。", tags: ["台账", "库存", "表格"], schema: inventorySchema, model: models.inventory },
  { key: "approval", name: "审批流程", category: "流程协作", icon: "✓", accent: "#e6a23c", description: "申请、审核、驳回和流程动态。", tags: ["审批", "流程", "时间线"], schema: approvalSchema, model: models.approval, workflow: workflows.approval },
  { key: "customer", name: "客户管理", category: "业务管理", icon: "◎", accent: "#67c23a", description: "客户档案、联系人和跟进状态。", tags: ["CRM", "客户", "表格"], schema: customerSchema, model: models.customer },
  { key: "dashboard", name: "数据看板", category: "数据分析", icon: "◫", accent: "#22d3ee", description: "核心指标、趋势和业务明细。", tags: ["看板", "指标", "深色"], schema: dashboardSchema, model: models.order },
  { key: "corporate", name: "企业官网", category: "网站", icon: "◇", accent: "#94a3b8", description: "品牌首页、产品能力和联系入口。", tags: ["官网", "品牌", "深色"], schema: corporateSchema },
  { key: "content", name: "内容站", category: "网站", icon: "≡", accent: "#d97706", description: "文章列表、专题和最新内容。", tags: ["内容", "文章", "列表"], schema: contentSchema },
];

function openCreate(item: TemplateDef) {
  selected.value = item;
  form.name = item.name;
  form.code = `${item.key}-${Date.now().toString(36)}`;
  form.members = [];
  dialogVisible.value = true;
}

async function loadUsers() {
  try {
    const data = await api.get<any>("/auth/users/?page=1&size=100");
    users.value = data?.results || [];
  } catch {
    users.value = [];
  }
}

async function importFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  let template: any;
  try {
    template = JSON.parse(await file.text());
  } catch {
    ElMessage.error("JSON 文件格式不正确");
    input.value = "";
    return;
  }
  if (!Array.isArray(template?.pages) || !template.pages.length) {
    ElMessage.error("模板缺少 pages");
    input.value = "";
    return;
  }
  let name = "";
  try {
    const result = await ElMessageBox.prompt("导入后应用名称", "导入模板", {
      inputValue: template.name || file.name.replace(/\.json$/i, ""),
      confirmButtonText: "创建",
      cancelButtonText: "取消",
    });
    name = String(result.value || "").trim();
  } catch {
    input.value = "";
    return;
  }
  if (!name) {
    input.value = "";
    return;
  }
  try {
    const result = await api.post<any>("/templates/import/", {
      name,
      code: `import-${Date.now().toString(36)}`,
      template,
    });
    ElMessage.success("模板已导入");
    router.push(`/admin/apps/${result.app.id}`);
  } catch (error: any) {
    ElMessage.error(error?.message || "导入失败");
  } finally {
    input.value = "";
  }
}

async function createApp() {  if (!selected.value) return;
  if (!form.name.trim() || !form.code.trim()) {
    ElMessage.warning("请填写应用名称和标识");
    return;
  }
  creating.value = true;
  try {
    const bundle = activeBundle(selected.value, form.name.trim());
    const result = await api.post<any>("/templates/apply/", {
      ...bundle,
      name: form.name.trim(),
      code: form.code.trim(),
      members: form.members.map((user_id) => ({ user_id, role: "viewer" })),
    });
    ElMessage.success(
      result?.models?.length || result?.workflow
        ? "应用、数据模型、示例数据和流程已创建"
        : "应用已创建"
    );
    dialogVisible.value = false;
    router.push(`/admin/apps/${result.app.id}`);
  } catch (error: any) {
    ElMessage.error(error?.message || "创建模板应用失败");
  } finally {
    creating.value = false;
  }
}

onMounted(loadUsers);
</script>

<style scoped>
.wp-template-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}
.wp-template-card :deep(.el-card__body) {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}
.wp-template-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 46px;
  height: 46px;
  border-radius: 12px;
  color: #fff;
  font-size: 24px;
}
.wp-template-body {
  min-width: 0;
  flex: 1;
}
.wp-template-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.wp-template-head h3 {
  margin: 0;
  font-size: 16px;
}
.wp-template-body p {
  margin: 8px 0;
  min-height: 40px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}
.wp-template-tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.wp-template-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.wp-template-json {
  margin-top: 12px;
}
.wp-template-json :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 12px;
}
@media (max-width: 1100px) {
  .wp-template-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .wp-template-grid { grid-template-columns: 1fr; }
}
</style>
