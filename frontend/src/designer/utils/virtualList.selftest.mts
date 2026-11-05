/**
 * virtualList.ts 的最小自测（无测试框架，Node 原生类型剥离即可运行）。
 *
 * 运行（Windows，仓库根目录）：
 *   "C:\Users\27606\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" \
 *     frontend/src/designer/utils/virtualList.selftest.mts
 *
 * 说明：本文件是 .mts，不在 frontend/tsconfig.json 的 include（src/**\/*.ts）里，
 * 不参与 vue-tsc / vite 构建；仅作为纯函数回归用例。
 */
import assert from "node:assert/strict";
import {
  OUTLINE_OVERSCAN,
  clampScrollTop,
  computeVirtualRange,
  type VirtualRange,
} from "./virtualList.ts";

const ROW = 30;

function range(total: number, scrollTop: number, viewportHeight = 600, overscan = OUTLINE_OVERSCAN): VirtualRange {
  return computeVirtualRange({ total, rowHeight: ROW, scrollTop, viewportHeight, overscan });
}

// 1. 空列表：全 0
assert.deepEqual(range(0, 0), {
  start: 0,
  end: 0,
  padTop: 0,
  padBottom: 0,
  totalHeight: 0,
  visibleCount: 0,
});

// 2. 顶部：可见 20 行 + 下方 overscan
const top = range(1000, 0);
assert.equal(top.start, 0);
assert.equal(top.end, 20 + OUTLINE_OVERSCAN);
assert.equal(top.padTop, 0);
assert.equal(top.padBottom, (1000 - top.end) * ROW);

// 3. 中部：区间包含可见部分，占位精确
const mid = range(1000, 3000);
assert.ok(mid.start <= 100, `中部 start=${mid.start} 应覆盖首行 100`);
assert.ok(mid.end >= 121, `中部 end=${mid.end} 应覆盖末行 120`);
assert.ok(mid.start >= 100 - OUTLINE_OVERSCAN && mid.end <= 120 + OUTLINE_OVERSCAN);
assert.equal(mid.padTop, mid.start * ROW);
assert.equal(mid.padBottom, (1000 - mid.end) * ROW);

// 4. 底部 / 越界滚动：夹取后最后一行可见
const bottom = range(1000, 999999);
assert.equal(bottom.end, 1000);
assert.equal(bottom.padBottom, 0);
assert.ok(bottom.start <= 980, `底部 start=${bottom.start} 应覆盖首行 980`);

// 5. 短列表：全部渲染，无占位
const short = range(3, 0);
assert.deepEqual([short.start, short.end, short.padTop, short.padBottom, short.visibleCount], [0, 3, 0, 0, 3]);

// 6. 任意滚动位置：占位 + 渲染高度 == 总高度，且区间合法
for (const scrollTop of [-50, -1, 0, 1, 29, 30, 450, 12345, 30000]) {
  const r = range(1000, scrollTop);
  assert.equal(r.padTop + r.visibleCount * ROW + r.padBottom, r.totalHeight);
  assert.ok(r.start >= 0 && r.end <= 1000 && r.start < r.end, `非法区间 ${r.start}-${r.end}`);
}

// 7. overscan=0 时只渲染可见行
const noOverscan = range(1000, 0, 600, 0);
assert.deepEqual([noOverscan.start, noOverscan.end, noOverscan.visibleCount], [0, 20, 20]);

// 8. 视口高度为 0（布局测量前）时仍渲染一行 + overscan
const zeroViewport = range(10, 0, 0);
assert.equal(zeroViewport.visibleCount, 1 + OUTLINE_OVERSCAN);

// 9. 非法输入归一化
const weird = computeVirtualRange({
  total: Number.NaN,
  rowHeight: 0,
  scrollTop: Number.NaN,
  viewportHeight: -1,
  overscan: -3,
});
assert.deepEqual(weird, {
  start: 0,
  end: 0,
  padTop: 0,
  padBottom: 0,
  totalHeight: 0,
  visibleCount: 0,
});

// 10. clampScrollTop 边界
assert.equal(clampScrollTop(-5, 1000, ROW, 600), 0);
assert.equal(clampScrollTop(120, 1000, ROW, 600), 120);
assert.equal(clampScrollTop(999999, 1000, ROW, 600), 1000 * ROW - 600);
assert.equal(clampScrollTop(100, 0, ROW, 600), 0);

console.log("virtualList.selftest: OK");
