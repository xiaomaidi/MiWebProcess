/** 自由布局几何工具：矩形、吸附、命中测试（纯函数，便于复用与测试）。 */
import type { SchemaNode } from "@/types";

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface SnapTargets {
  /** 竖向参考线（x 坐标）。 */
  vertical: number[];
  /** 横向参考线（y 坐标）。 */
  horizontal: number[];
}

export interface SnapResult {
  x: number;
  y: number;
  /** 吸附后仍然对齐的竖向参考线（用于画辅助线）。 */
  v: number[];
  /** 吸附后仍然对齐的横向参考线。 */
  h: number[];
}

/** 节点 layout → 矩形；无 layout 返回 null。 */
export function layoutRect(node: SchemaNode | null | undefined): Rect | null {
  const l = node?.layout;
  if (!l) return null;
  return { x: l.x, y: l.y, width: l.width, height: l.height };
}

/** 合并多个矩形（空数组返回 null）。 */
export function unionRect(rects: Rect[]): Rect | null {
  if (!rects.length) return null;
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const r of rects) {
    minX = Math.min(minX, r.x);
    minY = Math.min(minY, r.y);
    maxX = Math.max(maxX, r.x + r.width);
    maxY = Math.max(maxY, r.y + r.height);
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minY)) return null;
  return { x: minX, y: minY, width: Math.max(1, maxX - minX), height: Math.max(1, maxY - minY) };
}

/** 两矩形是否相交（tolerance 用于轻微容差；为 0 时接触边也算相交）。 */
export function intersectsRect(a: Rect, b: Rect, tolerance = 0): boolean {
  return (
    a.x <= b.x + b.width + tolerance &&
    a.x + a.width >= b.x - tolerance &&
    a.y <= b.y + b.height + tolerance &&
    a.y + a.height >= b.y - tolerance
  );
}

function bestDelta(edges: number[], lines: number[], threshold: number): number | null {
  let delta = 0;
  let dist = Infinity;
  for (const edge of edges) {
    for (const line of lines) {
      const d = line - edge;
      const ad = Math.abs(d);
      if (ad < dist) {
        dist = ad;
        delta = d;
      }
    }
  }
  return dist <= threshold ? delta : null;
}

/**
 * 让矩形边缘 / 中心吸附到参考线：返回吸附后的左上角坐标和仍然命中的参考线。
 * 每个轴最多吸附一次，阈值默认 6px（缩放后的逻辑像素）。
 */
export function snapRect(rect: Rect, targets: SnapTargets, threshold = 6): SnapResult {
  const vEdges = [rect.x, rect.x + rect.width / 2, rect.x + rect.width];
  const hEdges = [rect.y, rect.y + rect.height / 2, rect.y + rect.height];
  const vDelta = bestDelta(vEdges, targets.vertical, threshold);
  const hDelta = bestDelta(hEdges, targets.horizontal, threshold);
  const x = rect.x + (vDelta ?? 0);
  const y = rect.y + (hDelta ?? 0);
  const vx = vEdges.map((e) => e + (vDelta ?? 0));
  const hy = hEdges.map((e) => e + (hDelta ?? 0));
  const near = (a: number, b: number) => Math.abs(a - b) < 0.5;
  return {
    x,
    y,
    v: vDelta === null ? [] : [...new Set(targets.vertical.filter((line) => vx.some((e) => near(e, line))))],
    h: hDelta === null ? [] : [...new Set(targets.horizontal.filter((line) => hy.some((e) => near(e, line))))],
  };
}

/**
 * 节点在页面坐标系中的绝对矩形：累加祖先 layout 偏移（组合 / 嵌套容器）。
 * parentOf 由 schema store 提供，避免 util 直接依赖 Pinia。
 */
export function absoluteRect(
  id: string,
  nodes: Record<string, SchemaNode>,
  parentOf: (nodeId: string) => string | null
): Rect | null {
  const node = nodes[id];
  const own = layoutRect(node);
  if (!own) return null;
  let x = own.x;
  let y = own.y;
  let cur = parentOf(id);
  const seen = new Set<string>([id]);
  while (cur && !seen.has(cur)) {
    seen.add(cur);
    const parent = nodes[cur];
    if (parent?.layout) {
      x += parent.layout.x;
      y += parent.layout.y;
    }
    cur = parentOf(cur);
  }
  return { x, y, width: own.width, height: own.height };
}

/** 元素矩形（页面坐标）是否与选择框相交。 */
export function rectIntersectsSelection(rect: Rect, selection: Rect, tolerance = 0): boolean {
  return intersectsRect(rect, selection, tolerance);
}
