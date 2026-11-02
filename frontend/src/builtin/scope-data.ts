import type { RuntimeScope } from "@/types";

/** 单条数据行。 */
export type Row = Record<string, unknown>;

/** 从任意查询结果中提取行数组：数组本身、Paged.results 或常见字段名。 */
function asRows(value: unknown): Row[] | null {
  if (Array.isArray(value)) return value as Row[];
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    for (const key of ["results", "rows", "items", "data", "records"]) {
      if (Array.isArray(o[key])) return o[key] as Row[];
    }
  }
  return null;
}

/**
 * wp-table/wp-list/wp-barchart/wp-piechart 的数据约定：
 * 组件注册表未为这四个组件提供数据源类型 props，故它们从运行时 scope
 * 读取最新查询结果，优先级：
 * 1. modelResults（模型记录查询，Paged，按 modelId 键控）
 * 2. datasourceResults（数据源调用结果，按 datasourceId 键控）
 * 3. variables / loopVars 中第一个对象数组。
 * scope 为 null 时返回空数组（组件仅渲染空态）。
 */
export function rowsFromScope(scope: RuntimeScope | null): Row[] {
  if (!scope) return [];
  for (const v of Object.values(scope.modelResults)) {
    const rows = asRows(v);
    if (rows) return rows;
  }
  for (const v of Object.values(scope.datasourceResults)) {
    const rows = asRows(v);
    if (rows) return rows;
  }
  for (const v of Object.values(scope.variables)) {
    const rows = asRows(v);
    if (rows) return rows;
  }
  return [];
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "boolean") return value ? 1 : 0;
  if (typeof value === "string") {
    const t = value.trim();
    if (t !== "" && !Number.isNaN(Number(t))) return Number(t);
  }
  return null;
}

/**
 * wp-statcard 的取值约定（注册表未提供 value prop）：
 * 1. 与 label 同名的变量
 * 2. variables 中第一个数值
 * 3. modelResults 中第一个 Paged.count
 * 4. datasourceResults 中第一个结果的行数
 * 均无则返回 null（组件显示 "--"）。
 */
export function metricFromScope(scope: RuntimeScope | null, label?: string): number | null {
  if (!scope) return null;
  if (label && label in scope.variables) {
    const n = toNumber(scope.variables[label]);
    if (n !== null) return n;
  }
  for (const v of Object.values(scope.variables)) {
    const n = toNumber(v);
    if (n !== null) return n;
  }
  for (const v of Object.values(scope.modelResults)) {
    if (v && typeof v === "object" && typeof (v as Record<string, unknown>).count === "number") {
      return (v as { count: number }).count;
    }
  }
  for (const v of Object.values(scope.datasourceResults)) {
    const rows = asRows(v);
    if (rows) return rows.length;
  }
  return null;
}
