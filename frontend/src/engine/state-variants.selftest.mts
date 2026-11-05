/**
 * state-variants.ts 的最小自测（无测试框架，Node 原生类型剥离即可运行）。
 *
 * 运行（frontend 目录）：
 *   node src/engine/state-variants.selftest.mts
 *
 * 说明：本文件是 .mts，不在 tsconfig 的 include（src/**\/*.ts）内，不参与
 * vue-tsc / vite 构建；仅作为回归用例。
 */
import assert from "node:assert/strict";
import {
  buildStateCss,
  escapeAttrValue,
  findActiveVariant,
  hasAnyState,
  hasStateOverride,
  mergeVariantProps,
  mergeVariantStyle,
  overrideSummary,
  resolveInteractionState,
  statePropsFor,
  stateStyleFor,
} from "./state-variants.ts";
import type { SchemaNode } from "../types.ts";

const node: SchemaNode = {
  id: "n1",
  type: "ElButton",
  componentVersion: "1.0.0",
  props: { type: "default", text: "保存", disabled: false },
  style: { color: "#111111" },
  variants: [
    {
      id: "v1",
      name: "主按钮",
      props: { type: "primary", disabled: true },
      style: { backgroundColor: "#409eff", borderRadius: "6px" },
    },
    { id: "v2", name: "次按钮" },
  ],
  activeVariant: "v1",
  states: {
    hover: { style: { backgroundColor: "#66b1ff", color: "#ffffff" } },
    active: { style: { transform: "translateY(1px)" } },
    focus: { props: { loading: true } },
    disabled: { style: { opacity: "0.6", cursor: "not-allowed" } },
  },
};

const snapshot = JSON.stringify(node);

// ---------- 变体 ----------
assert.equal(findActiveVariant(node)?.name, "主按钮");
assert.equal(findActiveVariant({ ...node, activeVariant: "missing" }), null);
assert.equal(findActiveVariant({ ...node, activeVariant: undefined }), null);

assert.deepEqual(mergeVariantProps(node), {
  type: "primary",
  text: "保存",
  disabled: true,
});
assert.deepEqual(mergeVariantStyle(node), { backgroundColor: "#409eff", borderRadius: "6px" });
assert.equal(node.props.type, "default", "合并不应修改节点 props");
assert.equal(node.props.disabled, false, "合并不应修改节点 props");
assert.equal(node.style?.backgroundColor, undefined, "合并不应修改节点 style");

const noVariant = { ...node, activeVariant: "missing" };
assert.deepEqual(mergeVariantProps(noVariant), { type: "default", text: "保存", disabled: false });
assert.deepEqual(mergeVariantStyle(noVariant), {});
assert.deepEqual(mergeVariantProps({ ...node, variants: undefined }), {
  type: "default",
  text: "保存",
  disabled: false,
});

// ---------- 状态 ----------
assert.deepEqual(stateStyleFor(node, "hover"), { backgroundColor: "#66b1ff", color: "#ffffff" });
assert.deepEqual(stateStyleFor(node, "focus"), {}, "只有 props 的状态没有 style");
assert.deepEqual(stateStyleFor(node, null), {});
assert.deepEqual(statePropsFor(node, "focus"), { loading: true });
assert.deepEqual(statePropsFor(node, "hover"), {});

assert.equal(hasStateOverride(node, "active"), true);
assert.equal(hasStateOverride(node, "disabled"), true);
assert.equal(hasAnyState(node), true);
assert.equal(hasAnyState({ ...node, states: {} }), false);
assert.equal(hasAnyState({ ...node, states: { hover: {} } }), false);

// 优先级：disabled > active > hover > focus
assert.equal(
  resolveInteractionState(node, { disabled: true, hovered: true, pressed: true, focused: true }),
  "disabled"
);
assert.equal(resolveInteractionState(node, { hovered: true, pressed: true, focused: true }), "active");
assert.equal(resolveInteractionState(node, { hovered: true, focused: true }), "hover");
assert.equal(resolveInteractionState(node, { focused: true }), "focus");
assert.equal(resolveInteractionState(node, {}), null);
assert.equal(resolveInteractionState({ ...node, states: undefined }, { hovered: true }), null);

// ---------- CSS ----------
const css = buildStateCss(node);
assert.match(css, /\[data-wp-node="n1"\]:hover\{background-color: #66b1ff !important; color: #ffffff !important;\}/);
assert.match(css, /\[data-wp-node="n1"\]:active\{transform: translateY\(1px\) !important;\}/);
assert.match(css, /\[data-wp-node="n1"\]:disabled, \[data-wp-node="n1"\]\[aria-disabled="true"\], \[data-wp-node="n1"\]\.is-disabled\{opacity: 0\.6 !important; cursor: not-allowed !important;\}/);
assert.equal(buildStateCss({ ...node, states: { focus: { props: { loading: true } } } }), "", "纯 props 状态不生成 CSS");
assert.equal(buildStateCss({ ...node, states: undefined }), "");

assert.equal(escapeAttrValue('a"b\\c'), 'a\\"b\\\\c');
const escaped = buildStateCss({
  id: 'a"b',
  type: "div",
  componentVersion: "1.0.0",
  props: {},
  states: { hover: { style: { color: "red" } } },
});
assert.ok(escaped.startsWith('[data-wp-node="a\\"b"]:hover'), escaped);

// ---------- 摘要 ----------
assert.equal(overrideSummary(node.states?.hover), "样式 2");
assert.equal(overrideSummary(node.states?.focus), "props 1");
assert.equal(overrideSummary(node.variants?.[0]), "样式 2 · props 2");
assert.equal(overrideSummary(null), "未设置");

assert.equal(JSON.stringify(node), snapshot, "纯函数不应修改节点");
console.log("state-variants.selftest: OK");
