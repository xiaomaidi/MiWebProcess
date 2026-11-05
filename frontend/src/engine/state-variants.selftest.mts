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
import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  buildStateCss,
  escapeAttrValue,
  findActiveVariant,
  hasAnyState,
  hasStateOverride,
  isBindingLikeValue,
  mergeVariantProps,
  mergeVariantStyle,
  overrideSummary,
  resolveDesignProps,
  resolveInteractionState,
  splitVariantStyleBindings,
  statePropsFor,
  stateStyleFor,
  variantBindingEntries,
  variantStyleBindingKeys,
} from "./state-variants.ts";
import type { SchemaNode } from "../types.ts";

// state-variants.ts 自身保持零运行时依赖；这里通过 Node 解析钩子加载真实
// engine/binding.ts（把 @/ 别名与无扩展名相对导入映射到 src/*.ts），
// 用与运行态完全相同的 resolveProps 验证变体绑定解析形状。
const SRC_DIR = fileURLToPath(new URL("../", import.meta.url));
registerHooks({
  resolve(specifier, context, nextResolve) {
    let target: string | null = null;
    if (specifier.startsWith("@/")) {
      target = SRC_DIR + specifier.slice(2);
    } else if (
      specifier.startsWith("./") &&
      !/\.(m?[jt]s|json)$/.test(specifier) &&
      context.parentURL?.startsWith("file:")
    ) {
      try {
        target = fileURLToPath(new URL(specifier, context.parentURL));
      } catch {
        target = null;
      }
    }
    if (target) {
      for (const candidate of [`${target}.ts`, `${target}/index.ts`, target]) {
        if (existsSync(candidate)) return { url: pathToFileURL(candidate).href, shortCircuit: true };
      }
    }
    return nextResolve(specifier, context);
  },
});
const { resolveProps } = await import("./binding.ts");

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

// ---------- 变体绑定：合并优先级 / 解析形状 / 设计态预览 / 不改入参 ----------
const scope = {
  variables: { title: "主标题", subtitle: "副标题" },
  routeParams: {},
  routePath: "",
  setVariable() {},
  datasourceResults: {},
  modelResults: {},
  formValues: {},
  loopVars: {},
  callDatasource: async () => undefined,
  navigate() {},
  openModal() {},
  closeModal() {},
  modalNodeIds: new Set<string>(),
  message() {},
  record: {
    list: async () => undefined,
    get: async () => undefined,
    create: async () => undefined,
    update: async () => undefined,
    remove: async () => undefined,
  },
};

const boundNode: SchemaNode = {
  id: "n-bound",
  type: "ElButton",
  componentVersion: "1.0.0",
  props: {
    text: { __binding__: { source: "variable", ref: "title" } },
    type: "default",
    disabled: false,
    icon: "Star",
  },
  variants: [
    {
      id: "v-bound",
      name: "绑定变体",
      props: {
        text: { __binding__: { source: "variable", ref: "subtitle" } },
        type: { __binding__: { source: "variable", ref: "title" } },
        disabled: true,
      },
      style: { color: "#ffffff", width: "{{missing}}" },
    },
    { id: "v-static", name: "静态变体", props: { text: "静态" } },
    {
      id: "v-mixed",
      name: "混合变体",
      props: {
        label: "{{title}}",
        text: { __binding__: { source: "variable", ref: "title" } },
        disabled: false,
      },
    },
  ],
  activeVariant: "v-bound",
};
const boundSnapshot = JSON.stringify(boundNode);

const mergedBound = mergeVariantProps(boundNode);
assert.deepEqual(
  mergedBound.text,
  { __binding__: { source: "variable", ref: "subtitle" } },
  "变体绑定对象应覆盖基础绑定对象"
);
assert.deepEqual(
  mergedBound.type,
  { __binding__: { source: "variable", ref: "title" } },
  "变体绑定覆盖基础字面量"
);
assert.equal(mergedBound.disabled, true);
assert.equal(mergedBound.icon, "Star", "未覆盖的基础 props 保留");

// 与运行态完全一致的 resolveProps：变体绑定按作用域解析为普通值。
const resolvedBound = resolveProps(mergedBound, scope);
assert.deepEqual(resolvedBound, {
  text: "副标题",
  type: "主标题",
  disabled: true,
  icon: "Star",
});
assert.equal(
  Object.values(resolvedBound).some(
    (v) => !!v && typeof v === "object" && !Array.isArray(v) && "__binding__" in (v as object)
  ),
  false,
  "解析后不应残留 __binding__ 结构"
);

// 无激活变体时回退基础绑定。
const inactive = { ...boundNode, activeVariant: "missing" };
assert.equal(resolveProps(mergeVariantProps(inactive), scope).text, "主标题");

// 设计态：有预览作用域 → 显示绑定值；无预览数据 → 类型安全占位值。
const designWithPreview = resolveDesignProps(mergedBound, scope, (key) => `<${key}>`, resolveProps);
assert.equal(designWithPreview.props.text, "副标题");
assert.equal(designWithPreview.props.type, "主标题");
assert.deepEqual(designWithPreview.unresolved, []);

const designWithoutPreview = resolveDesignProps(mergedBound, null, (key) => `<${key}>`);
assert.equal(designWithoutPreview.props.text, "<text>");
assert.equal(designWithoutPreview.props.type, "<type>");
assert.deepEqual([...designWithoutPreview.unresolved].sort(), ["text", "type"]);

// 绑定未命中且无 defaultValue → 占位；有 defaultValue → 回退默认值。
const missingVariant = {
  ...boundNode,
  variants: [{ id: "v-bound", name: "缺字段", props: { text: { __binding__: { source: "variable", ref: "nope" } } } }],
};
const missingDesign = resolveDesignProps(mergeVariantProps(missingVariant), scope, (key) => `<${key}>`, resolveProps);
assert.equal(missingDesign.props.text, "<text>");
assert.deepEqual(missingDesign.unresolved, ["text"]);

const defaultDesign = resolveDesignProps(
  { text: { __binding__: { source: "variable", ref: "nope", defaultValue: "兜底" } } },
  null,
  () => "<placeholder>"
);
assert.equal(defaultDesign.props.text, "兜底");
assert.deepEqual(defaultDesign.resolved, ["text"]);

// 变体绑定 / 表达式条目与 style 绑定提示。
const mixedEntries = variantBindingEntries(boundNode.variants?.[2]);
assert.deepEqual(
  mixedEntries.map((entry) => [entry.key, entry.kind]),
  [
    ["label", "expression"],
    ["text", "binding"],
  ]
);
assert.deepEqual(variantBindingEntries(boundNode.variants?.[1]), []);
assert.deepEqual(variantStyleBindingKeys(boundNode.variants?.[0]?.style), ["width"]);
const splitStyle = splitVariantStyleBindings(boundNode.variants?.[0]?.style);
assert.deepEqual(splitStyle.style, { color: "#ffffff" });
assert.deepEqual(splitStyle.bindingKeys, ["width"]);
assert.equal(isBindingLikeValue({ __binding__: { source: "variable", ref: "x" } }), true);
assert.equal(isBindingLikeValue("{{ title }}"), true);
assert.equal(isBindingLikeValue("#409eff"), false);
assert.equal(isBindingLikeValue(12), false);

assert.equal(boundNode.props.text.__binding__.ref, "title", "合并 / 解析不应修改基础绑定");
assert.equal(boundNode.variants?.[0]?.props?.text.__binding__.ref, "subtitle", "合并 / 解析不应修改变体绑定");
assert.equal(JSON.stringify(boundNode), boundSnapshot, "绑定合并 / 解析不应修改节点");

assert.equal(JSON.stringify(node), snapshot, "纯函数不应修改节点");
console.log("state-variants.selftest: OK");
