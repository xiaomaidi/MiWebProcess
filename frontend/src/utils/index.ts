import { toRaw } from "vue";

export function uid(): string {
  return "n" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function formatTime(iso: string | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 找出无法序列化/克隆的字段路径（函数、DOM 节点等），仅用于诊断。 */
function findUncloneable(raw: unknown): string[] {
  const bad: string[] = [];
  const seen = new WeakSet<object>();
  const walk = (obj: object, p = "") => {
    if (seen.has(obj)) return;
    seen.add(obj);
    for (const [k, val] of Object.entries(obj)) {
      const np = p ? `${p}.${k}` : k;
      if (typeof val === "function" || val instanceof HTMLElement || val instanceof Window) bad.push(np);
      else if (val && typeof val === "object") walk(val, np);
    }
  };
  try {
    walk((raw as object) || {});
  } catch {
    /* ignore */
  }
  return bad;
}

/**
 * 深拷贝（可安全用于响应式对象：先 toRaw 解除 Vue 代理再 structuredClone）。
 * 若 structuredClone 仍失败（数据里混入了函数/DOM 对象等），降级为手工递归克隆：
 * 丢弃不可序列化字段、处理循环引用，绝不抛错（schema 本身必须可 JSON 序列化，降级不影响持久化）。
 */
export function deepClone<T>(v: T): T {
  const raw = toRaw(v);
  try {
    return structuredClone(raw);
  } catch (e) {
    if (import.meta.env.DEV) {
      const bad = findUncloneable(raw);
      console.warn(
        "[deepClone] structuredClone 失败，已降级为递归克隆（丢弃的不可序列化字段: " +
          (bad.length ? bad.slice(0, 15).join(", ") : "未知（可能是代理/跨域对象）") +
          "）"
      );
    }
    const cache = new WeakMap<object, unknown>();
    const walk = (val: unknown): unknown => {
      if (val === null || typeof val !== "object") return val;
      if (cache.has(val)) return cache.get(val);
      if (typeof val === "function" || val instanceof HTMLElement || val instanceof Window) return undefined;
      if (Array.isArray(val)) {
        const out: unknown[] = [];
        cache.set(val, out);
        for (const x of val) out.push(walk(x));
        return out;
      }
      const out: Record<string, unknown> = {};
      cache.set(val, out);
      for (const [k, x] of Object.entries(val as object)) out[k] = walk(x);
      return out;
    };
    return walk(raw) as T;
  }
}

export function isPlainObject(v: unknown): v is Record<string, any> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** 解析 "a.b[2].c" / "a[*].c" 形式字段路径。 */
export function splitFieldPath(path: string): (string | number | "*")[] {
  return path
    .replace(/\[(\d+)\]/g, ".$1")
    .replace(/\[\*\]/g, ".*")
    .split(".")
    .filter(Boolean)
    .map((seg) => (seg === "*" ? "*" : /^\d+$/.test(seg) ? Number(seg) : seg));
}

export function getPathValue(obj: any, path: string): { found: boolean; value: any } {
  const parts = splitFieldPath(path);
  let cur: any = obj;
  let i = 0;
  while (i < parts.length) {
    const p = parts[i];
    if (p === "*") {
      if (!Array.isArray(cur)) return { found: false, value: undefined };
      if (i === parts.length - 1) return { found: true, value: [...cur] };
      const rest = parts.slice(i + 1).join(".");
      return { found: true, value: cur.map((el) => getPathValue(el, rest).value) };
    }
    if (cur == null || typeof cur !== "object") return { found: false, value: undefined };
    cur = cur[p as any];
    i++;
  }
  return { found: cur !== undefined, value: cur };
}

export function styleObjectToCss(style: Record<string, any> | undefined): string {
  if (!style) return "";
  return Object.entries(style)
    .filter(([, v]) => v !== undefined && v !== null)
    .map(([k, v]) => `${k.replace(/[A-Z]/g, (m) => "-" + m.toLowerCase())}: ${v}`)
    .join("; ");
}
