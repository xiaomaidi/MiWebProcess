/** 响应式断点工具：优先读取页面 Token，回退默认值。 */

export type Breakpoint = "xs" | "sm" | "md" | "lg" | "xl";

const DEFAULTS: Record<Exclude<Breakpoint, "xs">, number> = {
  sm: 640,
  md: 768,
  lg: 1024,
  xl: 1280,
};

function readPx(name: string, fallback: number): number {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function getBreakpoint(): Breakpoint {
  if (typeof window === "undefined") return "lg";
  const width = window.innerWidth;
  const sm = readPx("--wp-breakpoint-sm", DEFAULTS.sm);
  const md = readPx("--wp-breakpoint-md", DEFAULTS.md);
  const lg = readPx("--wp-breakpoint-lg", DEFAULTS.lg);
  const xl = readPx("--wp-breakpoint-xl", DEFAULTS.xl);
  if (width >= xl) return "xl";
  if (width >= lg) return "lg";
  if (width >= md) return "md";
  if (width >= sm) return "sm";
  return "xs";
}

export function onBreakpoint(handler: (value: Breakpoint) => void): () => void {
  if (typeof window === "undefined") return () => undefined;
  let last = getBreakpoint();
  handler(last);
  const listener = () => {
    const next = getBreakpoint();
    if (next !== last) {
      last = next;
      handler(next);
    }
  };
  window.addEventListener("resize", listener);
  return () => window.removeEventListener("resize", listener);
}
