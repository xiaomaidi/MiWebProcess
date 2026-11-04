/**
 * quality.ts 的最小自测（无测试框架，Node 原生类型剥离即可运行）。
 *
 * 运行（Windows，仓库根目录）：
 *   "C:\Users\27606\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" \
 *     frontend/src/designer/components/quality.selftest.mts
 *
 * 说明：本文件是 .mts，不在 frontend/tsconfig.json 的 include（src/**\/*.ts）里，
 * 不参与 vue-tsc / vite 构建；仅作为可执行的示例与回归用例。
 */
import assert from "node:assert/strict";
import { auditPage, auditSummary, type QualityIssue } from "../quality.ts";
import type { PageSchema, SchemaNode } from "../../types.ts";

function node(
  id: string,
  type: string,
  props: Record<string, any> = {},
  extra: Partial<SchemaNode> = {}
): SchemaNode {
  return { id, type, componentVersion: "2.0.0", props, children: [], ...extra };
}

function codes(issues: QualityIssue[]): Set<string> {
  return new Set(issues.map((issue) => issue.code));
}

function expectIssue(issues: QualityIssue[], code: string, nodeId?: string): void {
  const found = issues.find((issue) => issue.code === code && (nodeId === undefined || issue.nodeId === nodeId));
  assert.ok(found, `缺少预期问题 ${code}${nodeId ? ` (${nodeId})` : ""}，实际：${issues.map((i) => i.code).join(", ")}`);
}

// ---------- 1. 覆盖全部规则的示例页面 ----------
const chain: Record<string, SchemaNode> = {};
let previous: SchemaNode | null = null;
for (let depth = 0; depth < 16; depth += 1) {
  const id = `deep-${depth}`;
  chain[id] = node(id, "wp-text", { content: `第 ${depth} 层` });
  if (previous) previous.children = [...(previous.children || []), id];
  previous = chain[id];
}

const nodes: Record<string, SchemaNode> = {
  root: node("root", "wp-canvas", {}, {
    children: [
      "emptyBox",
      "lonelyBox",
      "brokenBox",
      "wide",
      "img",
      "link",
      "btn",
      "input",
      "lowContrast",
      "hidden",
      "freeA",
      "freeB",
      "outside",
      "dup",
      "dup",
      "shared",
      "deep-0",
    ],
  }),
  emptyBox: node("emptyBox", "wp-container", {}, { children: [] }),
  lonelyBox: node("lonelyBox", "wp-row", {}, { children: [] }),
  brokenBox: node("brokenBox", "wp-container", {}, { children: ["ghost"] }),
  wide: node("wide", "wp-container", {}, { children: ["wideText"], style: { width: "640px" } }),
  wideText: node("wideText", "wp-text", { content: "宽容器" }),
  img: node("img", "ElImage", { src: "" }),
  link: node("link", "wp-link", { label: "官网", href: "#" }),
  btn: node("btn", "ElButton", { text: "" }),
  input: node("input", "ElInput", { field: "name", label: "" }),
  lowContrast: node(
    "lowContrast",
    "wp-text",
    { content: "浅灰文字", color: "#e5e5e5" },
    { style: { backgroundColor: "#ffffff" } }
  ),
  hidden: node("hidden", "wp-container", {}, {
    hideOn: ["xs", "sm", "md", "lg", "xl"],
    children: ["hiddenInput"],
  }),
  hiddenInput: node("hiddenInput", "ElInput", { field: "phone", label: "手机号", required: true }),
  freeA: node("freeA", "wp-text", { content: "A" }, { layout: { x: 20, y: 20, width: 200, height: 80 } }),
  freeB: node("freeB", "wp-text", { content: "B" }, { layout: { x: 40, y: 40, width: 200, height: 80 } }),
  outside: node("outside", "wp-text", { content: "C" }, { layout: { x: 1100, y: 760, width: 300, height: 120 } }),
  dup: node("dup", "wp-text", { content: "重复引用" }),
  shared: node("shared", "wp-text", { content: "多父引用" }, {}),
  emptyBoxChild: node("emptyBoxChild", "wp-text", { content: "占位" }),
  orphan: node("orphan", "wp-text", { content: "游离节点" }),
  ...chain,
};
// 多父引用：shared 同时挂在 root 与 emptyBox 下。
nodes.emptyBox.children = ["emptyBoxChild", "shared"];

const schema: PageSchema = {
  schemaVersion: 2,
  rootId: "root",
  nodes,
  meta: { title: "", seo: {} },
  layout: { mode: "free", width: 1200, height: 800 },
};

const snapshot = JSON.stringify(schema);
const issues = auditPage(schema);
assert.equal(JSON.stringify(schema), snapshot, "auditPage 不应修改 schema");

for (const code of [
  "page-title-missing",
  "page-description-missing",
  "empty-container",
  "image-missing-src",
  "link-empty-href",
  "control-no-text",
  "form-field-no-label",
  "duplicate-element-id",
  "dangling-reference",
  "low-contrast",
  "fixed-width-overflow",
  "hidden-required-field",
  "deep-tree",
  "free-layout-out-of-bounds",
  "free-layout-overlap",
  "unreachable-node",
]) {
  expectIssue(issues, code);
}

assert.equal(issues.find((i) => i.code === "control-no-text")?.severity, "error", "无文案按钮应为 error");
assert.equal(issues.find((i) => i.code === "image-missing-src")?.nodeId, "img", "图片问题应带 nodeId");
assert.equal(issues.find((i) => i.code === "low-contrast")?.severity, "error", "对比度 < 2:1 应为 error");
assert.ok(
  issues.find((i) => i.code === "low-contrast")?.detail?.includes("启发式"),
  "对比度问题应注明启发式局限"
);

// 阈值参数可调（节点数刚好超过上限 → too-many-nodes，warn）
const nodeCount = Object.keys(nodes).length;
const strict = auditPage(schema, { maxNodeCount: nodeCount - 1, maxDepth: 100 });
expectIssue(strict, "too-many-nodes");
assert.equal(strict.find((i) => i.code === "too-many-nodes")?.severity, "warn");

// 汇总
const summary = auditSummary(issues);
assert.equal(summary.total, issues.length);
assert.equal(summary.error + summary.warn + summary.info, summary.total);
assert.equal(summary.passed, false);
assert.equal(summary.byCode["duplicate-element-id"], 2, "重复引用应各报一次（父列表重复 + 多父引用）");

// 稳定排序：同样输入两次结果一致
assert.deepEqual(auditPage(schema), auditPage(schema));

// ---------- 2. 干净页面不应产生 error ----------
const cleanNodes: Record<string, SchemaNode> = {
  root: node("root", "wp-canvas", {}, { children: ["card"] }),
  card: node("card", "ElCard", {}, {
    children: ["title", "form"],
    slots: { header: [] },
  }),
  title: node("title", "ElText", { text: "欢迎" }, { style: { color: "#1f2329", backgroundColor: "#ffffff" } }),
  form: node("form", "ElForm", {}, { children: ["item"] }),
  item: node("item", "ElFormItem", { label: "姓名" }, { children: ["name"] }),
  name: node("name", "ElInput", { field: "name", label: "姓名" }),
};
const clean: PageSchema = {
  schemaVersion: 2,
  rootId: "root",
  nodes: cleanNodes,
  meta: { title: "欢迎页", seo: { description: "这是一个用于自测的干净页面。" } },
  layout: { mode: "flow", width: 1200, height: 800 },
};
const cleanIssues = auditPage(clean);
assert.equal(cleanIssues.filter((issue) => issue.severity === "error").length, 0, `干净页面不应有 error：${JSON.stringify(cleanIssues)}`);
assert.equal(auditSummary(cleanIssues).passed, true);

// ---------- 3. 空输入不报错 ----------
assert.deepEqual(auditPage(null), []);
assert.deepEqual(auditPage(undefined), []);
assert.equal(auditSummary([]).passed, true);
assert.equal(auditSummary([]).total, 0);

// ---------- 4. 重复 node.id / 根节点缺失 ----------
const duplicateIdSchema: PageSchema = {
  schemaVersion: 2,
  rootId: "root",
  nodes: {
    root: node("root", "wp-canvas", {}, { children: ["a", "b"] }),
    a: node("same", "wp-text", { content: "A" }),
    b: node("same", "wp-text", { content: "B" }),
  },
  meta: { title: "重复 id", seo: { description: "用于验证重复 id 的页面。" } },
};
const duplicateIdIssues = auditPage(duplicateIdSchema);
expectIssue(duplicateIdIssues, "duplicate-element-id");
assert.equal(
  duplicateIdIssues.filter((issue) => issue.code === "node-id-mismatch").length,
  0,
  "重复 id 已按重复报，不应再叠加映射键不一致"
);

const brokenRootSchema: PageSchema = {
  schemaVersion: 2,
  rootId: "nope",
  nodes: { a: node("a", "wp-text", { content: "孤立节点" }) },
  meta: { title: "坏页面", seo: { description: "用于验证根节点缺失。" } },
};
const brokenRootIssues = auditPage(brokenRootSchema);
expectIssue(brokenRootIssues, "root-missing");
assert.equal(
  brokenRootIssues.some((issue) => issue.code === "unreachable-node"),
  false,
  "根节点缺失时不应刷屏式报 unreachable"
);

void codes;
console.log(`quality.selftest: OK（示例页面 ${issues.length} 项问题；干净页面 ${cleanIssues.length} 项）`);
