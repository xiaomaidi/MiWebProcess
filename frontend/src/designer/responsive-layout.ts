import type { SchemaNode } from "@/types";

export type DeviceKey = "desktop" | "tablet" | "phone";
export type LayoutBox = { x: number; y: number; width?: number; height?: number };

/**
 * Per-device free-layout overrides live in `node.responsiveLayout`.
 * The schema remains backward compatible: desktop uses node.layout.
 */
export function deviceKey(device: string): DeviceKey {
  return device === "tablet" || device === "phone" ? device : "desktop";
}

export function layoutFor(node: SchemaNode | undefined, device: string): LayoutBox | undefined {
  if (!node) return undefined;
  const key = deviceKey(device);
  if (key !== "desktop") {
    const override = (node as any).responsiveLayout?.[key];
    if (override) return { ...node.layout, ...override } as LayoutBox;
  }
  return node.layout as LayoutBox | undefined;
}

export function writeLayout(node: SchemaNode, device: string, box: LayoutBox): void {
  const key = deviceKey(device);
  if (key === "desktop") {
    node.layout = { ...(node.layout || { x: 0, y: 0, width: 200, height: 80 }), ...box } as any;
    return;
  }
  const container = ((node as any).responsiveLayout ||= {});
  container[key] = { ...(container[key] || {}), ...box };
}

export function clearDeviceLayout(node: SchemaNode, device: string): void {
  const key = deviceKey(device);
  if (key === "desktop") return;
  const container = (node as any).responsiveLayout;
  if (!container) return;
  delete container[key];
  if (!Object.keys(container).length) delete (node as any).responsiveLayout;
}

export function hasDeviceLayout(node: SchemaNode | undefined, device: string): boolean {
  if (!node || deviceKey(device) === "desktop") return false;
  return !!(node as any).responsiveLayout?.[deviceKey(device)];
}

/** Clone the node map with device overrides applied for rendering only. */
export function displayNodes(nodes: Record<string, SchemaNode>, device: string): Record<string, SchemaNode> {
  if (deviceKey(device) === "desktop") return nodes;
  const out: Record<string, SchemaNode> = {};
  for (const [id, node] of Object.entries(nodes)) {
    const override = (node as any).responsiveLayout?.[deviceKey(device)];
    out[id] = override ? { ...node, layout: { ...(node.layout || {}), ...override } } : node;
  }
  return out;
}
