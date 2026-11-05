/**
 * canvasVirtualization.ts 的最小自测（无测试框架，Node 原生类型剥离即可运行）。
 *
 * 运行（Windows，仓库根目录）：
 *   node frontend/src/designer/utils/canvasVirtualization.selftest.mts
 *
 * 说明：本文件是 .mts，不在 frontend/tsconfig.json 的 include（src/**\/*.ts）里，
 * 不参与 vue-tsc / vite 构建；仅作为纯函数回归用例。
 */
import assert from "node:assert/strict";
import type { SchemaNode } from "../../types.ts";
import {
  DEFAULT_OVERSCAN,
  FREE_LAYOUT_VIRTUALIZE_THRESHOLD,
  FLOW_LAYOUT_CONTAINMENT_THRESHOLD,
  VIEWPORT_CELL,
  computeVisibleNodeIds,
  planVirtualization,
  quantizeViewport,
  type NodeMap,
  type VisibleNodeResult,
} from "./canvasVirtualization.ts";

function node(id: string, extra: Partial<SchemaNode> = {}): SchemaNode {
  return { id, type: "div", componentVersion: "2.0.0", props: {}, ...extra };
}

function map(...nodes: SchemaNode[]): NodeMap {
  const out: NodeMap = {};
  for (const n of nodes) out[n.id] = n;
  return out;
}

function viewport(x: number, y: number, width: number, height: number) {
  return { x, y, width, height };
}

function visibleIds(result: VisibleNodeResult): string[] {
  return [...result.visible].sort();
}

// ---------- 1. 绝对坐标 = 自身 layout + 祖先偏移 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["a"] }),
    node("a", { layout: { x: 100, y: 50, width: 300, height: 200 }, children: ["b"] }),
    node("b", { layout: { x: 20, y: 10, width: 50, height: 50 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(119, 59, 2, 2), 0);
  assert.deepEqual(visibleIds(result), ["a", "b", "root"], "b 的绝对位置应为 (120,60)");
  assert.equal(result.culledCount, 0);
  assert.equal(result.hitCount, 2, "root 无 layout，不参与几何命中");
  assert.equal(result.total, 3);
}

// ---------- 2. 视口外叶子被裁 + 顶层容器整棵子树计数 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["group"] }),
    node("group", { layout: { x: 500, y: 500, width: 100, height: 100 }, children: ["leaf", "deep"] }),
    node("leaf", { layout: { x: 10, y: 10, width: 20, height: 20 } }),
    node("deep", { layout: { x: 20, y: 20, width: 30, height: 30 }, children: ["deepLeaf"] }),
    node("deepLeaf", { layout: { x: 5, y: 5, width: 10, height: 10 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(visibleIds(result), ["root"]);
  assert.deepEqual(result.culledIds, ["deep", "deepLeaf", "group", "leaf"]);
  assert.equal(result.culledCount, 4, "被裁容器的整棵子树都要计入裁剪数");
}

// ---------- 3. 非顶层容器永不裁撤，只裁其视口外叶子 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["outer"] }),
    node("outer", {
      layout: { x: 100, y: 50, width: 300, height: 200 },
      children: ["inner"],
    }),
    node("inner", { layout: { x: 500, y: 500, width: 100, height: 100 }, children: ["leaf"] }),
    node("leaf", { layout: { x: 510, y: 510, width: 20, height: 20 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(visibleIds(result), ["inner", "outer", "root"]);
  assert.deepEqual(result.culledIds, ["leaf"]);
}

// ---------- 4. 选中节点即使完全在视口外也保留 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["a", "b"] }),
    node("a", { layout: { x: 1000, y: 1000, width: 50, height: 50 } }),
    node("b", { layout: { x: 1100, y: 1100, width: 50, height: 50 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0, ["b"]);
  assert.deepEqual(visibleIds(result), ["b", "root"]);
  assert.deepEqual(result.culledIds, ["a"]);
}

// ---------- 5. overscan：刚好在扩展视口内 / 外 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["a"] }),
    node("a", { layout: { x: 200, y: 0, width: 50, height: 50 } })
  );
  const hidden = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 50);
  assert.deepEqual(hidden.culledIds, ["a"]);
  const near = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 120);
  assert.deepEqual(near.culledIds, []);
  assert.deepEqual(visibleIds(near), ["a", "root"]);
}

// ---------- 6. 视口未测量（宽/高为 0）时不裁剪 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["a"] }),
    node("a", { layout: { x: 5000, y: 5000, width: 10, height: 10 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 0, 0), 0);
  assert.deepEqual(result.culledIds, []);
  assert.equal(result.visible.size, 2);
}

// ---------- 7. 无 layout 的节点保留（位置无法证明在视口外） ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["positioned", "flowChild"] }),
    node("positioned", { layout: { x: 900, y: 900, width: 10, height: 10 } }),
    node("flowChild", { children: [] })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(visibleIds(result), ["flowChild", "root"]);
  assert.deepEqual(result.culledIds, ["positioned"]);
}

// ---------- 8. 命名插槽子节点（表格列 / 标签页等）不裁剪 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["card"] }),
    node("card", {
      layout: { x: 500, y: 500, width: 100, height: 100 },
      slots: { header: ["title"] },
    }),
    node("title", { layout: { x: 5, y: 5, width: 50, height: 20 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(result.culledIds, []);
  assert.ok(result.visible.has("title"), "命名插槽子节点必须保留");
}

// ---------- 9. 子节点溢出父容器：命中子节点会保护整条祖先链 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["box"] }),
    node("box", { layout: { x: 500, y: 500, width: 100, height: 100 }, children: ["probe"] }),
    node("probe", { layout: { x: -450, y: -450, width: 20, height: 20 } })
  );
  // probe 绝对位置 (50,50)，在视口内；box 自身在视口外，但作为祖先必须保留。
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(visibleIds(result), ["box", "probe", "root"]);
  assert.deepEqual(result.culledIds, []);
}

// ---------- 10. 选中后代阻止顶层容器整棵裁撤 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["group"] }),
    node("group", { layout: { x: 500, y: 500, width: 100, height: 100 }, children: ["leaf"] }),
    node("leaf", { layout: { x: 510, y: 510, width: 20, height: 20 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0, ["leaf"]);
  assert.deepEqual(result.culledIds, []);
  assert.deepEqual(visibleIds(result), ["group", "leaf", "root"]);
}

// ---------- 11. 画布根永不裁撤（根 layout 不参与页面坐标，子节点仍按自身 layout 判定） ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", layout: { x: 900, y: 900, width: 100, height: 100 }, children: ["a"] }),
    node("a", { layout: { x: 5000, y: 5000, width: 20, height: 20 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.ok(result.visible.has("root"));
  assert.deepEqual(result.culledIds, ["a"]);
}

// ---------- 12. malformed 环引用不死循环 ----------
{
  const nodes: NodeMap = {
    a: { type: "div", layout: { x: 0, y: 0, width: 10, height: 10 }, children: ["b"] },
    b: { type: "div", layout: { x: 0, y: 0, width: 10, height: 10 }, children: ["a"] },
  };
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.equal(result.total, 2);
  assert.equal(result.culledCount, 0, "环引用应被 seen 集合截断，不得无限递归");
}

// ---------- 13. 祖先处于文档流（无 layout）时位置不可推断 → 保守保留 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["flowParent"] }),
    node("flowParent", { children: ["positioned"] }),
    node("positioned", { layout: { x: 5000, y: 5000, width: 20, height: 20 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(result.culledIds, [], "祖先无 layout 时无法计算绝对位置，不得裁撤");
  assert.deepEqual(visibleIds(result), ["flowParent", "positioned", "root"]);
}

// ---------- 14. 阈值 / 策略：free 布局 > 300，flow 布局 > 500 ----------
{
  assert.equal(FREE_LAYOUT_VIRTUALIZE_THRESHOLD, 300);
  assert.equal(FLOW_LAYOUT_CONTAINMENT_THRESHOLD, 500);

  const freeSmall = planVirtualization(FREE_LAYOUT_VIRTUALIZE_THRESHOLD, "free");
  assert.deepEqual([freeSmall.active, freeSmall.strategy, freeSmall.threshold], [false, "none", 300]);
  const freeLarge = planVirtualization(FREE_LAYOUT_VIRTUALIZE_THRESHOLD + 1, "free");
  assert.deepEqual([freeLarge.active, freeLarge.strategy, freeLarge.threshold], [true, "cull", 300]);

  const flowSmall = planVirtualization(FLOW_LAYOUT_CONTAINMENT_THRESHOLD, "flow");
  assert.deepEqual([flowSmall.active, flowSmall.strategy, flowSmall.threshold], [false, "none", 500]);
  assert.equal(
    planVirtualization(FREE_LAYOUT_VIRTUALIZE_THRESHOLD + 1, "flow").active,
    false,
    "flow 布局使用 500 阈值，301 节点不启用 CSS 隔离"
  );
  const flowLarge = planVirtualization(FLOW_LAYOUT_CONTAINMENT_THRESHOLD + 1, "flow");
  assert.deepEqual([flowLarge.active, flowLarge.strategy, flowLarge.threshold], [true, "contain", 500]);

  assert.equal(planVirtualization(Number.NaN, "free").nodeCount, 0);
}

// ---------- 15. 视口量化：向外取整且完整包含原视口 ----------
{
  const original = viewport(-10, 20, 100, 100);
  const quantized = quantizeViewport(original, VIEWPORT_CELL);
  assert.deepEqual(quantized, { x: -256, y: 0, width: 512, height: 256 });
  assert.ok(quantized.x <= original.x && quantized.y <= original.y);
  assert.ok(quantized.x + quantized.width >= original.x + original.width);
  assert.ok(quantized.y + quantized.height >= original.y + original.height);
  assert.equal(quantizeViewport(original, 0).width >= original.width, true, "非法 cell 回退默认值");
}

// ---------- 16. 默认 overscan 常量可用 ----------
{
  assert.equal(DEFAULT_OVERSCAN, 480);
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["a"] }),
    node("a", { layout: { x: 470, y: 0, width: 10, height: 10 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100));
  assert.deepEqual(result.culledIds, [], "默认 480 预渲染范围内不应裁撤");
}

// ---------- 17. conditional 没有定位 wrapper：自身与后代都不参与裁剪 ----------
{
  const nodes = map(
    node("root", { type: "wp-canvas", children: ["conditional"] }),
    node("conditional", {
      type: "conditional",
      layout: { x: 5000, y: 5000, width: 100, height: 100 },
      children: ["inside"],
    }),
    node("inside", { layout: { x: 5000, y: 5000, width: 20, height: 20 } })
  );
  const result = computeVisibleNodeIds(nodes, viewport(0, 0, 100, 100), 0);
  assert.deepEqual(result.culledIds, []);
  assert.deepEqual(visibleIds(result), ["conditional", "inside", "root"]);
}

console.log("canvasVirtualization.selftest: OK");
