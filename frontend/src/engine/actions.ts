/** 动作流执行器（运行态）。支持顺序/条件/循环/并行/异常捕获五种编排。 */
import { ElMessage, ElMessageBox, ElNotification } from "element-plus";
import { api } from "@/api";
import type { ActionStep, RuntimeScope } from "@/types";
import { evaluateExpression, interpolate, checkExpression } from "./expr";
import { buildScope } from "./binding";

function looksLikeExpr(v: string): boolean {
  return /[\w$.]+(\s*\+|==|===|!=|!==|<|>|&&|\|\||\(|\[|\?)/.test(v);
}

/** 动作参数求值：支持 {{expr}}、表达式字符串、普通字面量。 */
function evalValue(v: any, vars: Record<string, any>, expression = true): any {
  if (typeof v !== "string") return v;
  if (v.includes("{{")) return interpolate(v, vars);
  if (expression) {
    const direct = v.trim();
    // 裸变量/路径（如 users、user.name）也应求值，而不是当字符串。
    if (/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/.test(direct) && (direct in vars || direct.includes("."))) {
      const value = evaluateExpression(direct, vars);
      if (value !== undefined) return value;
    }
    if (looksLikeExpr(v)) return evaluateExpression(v, vars);
  }
  return v;
}

function evalObject(obj: any, vars: Record<string, any>): any {
  if (typeof obj === "string") return evalValue(obj, vars);
  if (Array.isArray(obj)) return obj.map((v) => evalObject(v, vars));
  if (obj && typeof obj === "object") {
    const out: Record<string, any> = {};
    for (const [k, v] of Object.entries(obj)) out[k] = evalObject(v, vars);
    return out;
  }
  return obj;
}

function errorText(e: any): string {
  return e?.message || e?.detail || String(e ?? "未知错误");
}

function payloadMatches(schema: Record<string, string> | undefined, payload: any): boolean {
  if (!schema || !Object.keys(schema).length) return true;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  for (const [key, type] of Object.entries(schema)) {
    if (!(key in payload)) return false;
    const value = payload[key];
    const actual = Array.isArray(value) ? "array" : value === null ? "null" : typeof value;
    if (type !== "any" && actual !== type) return false;
  }
  return true;
}

export async function runSteps(
  steps: ActionStep[],
  scope: RuntimeScope,
  extra?: Record<string, any>,
  depth = 0,
  propagate = false
): Promise<void> {
  if (depth > 12) {
    scope.message("动作嵌套过深，已停止执行", "error");
    return;
  }
  for (const step of steps || []) {
    if (!step || !step.kind) continue;
    const vars = buildScope(scope, extra);
    const p = step.params || {};
    try {
      switch (step.kind) {
        case "setVariable": {
          if (p.name) scope.setVariable(p.name, evalValue(p.value, vars));
          break;
        }
        case "callDatasource": {
          const ref = p.ref || p.id;
          const id = Number(String(ref).replace(/^ds_/, ""));
          const params: Record<string, any> = {};
          for (const [k, v] of Object.entries(p.params || {})) params[k] = evalValue(v, vars);
          try {
            await scope.callDatasource(id, params);
          } catch (e: any) {
            scope.message(`数据源调用失败：${errorText(e)}`, "error");
          }
          break;
        }
        case "navigate": {
          scope.navigate(String(evalValue(p.path || "/", vars, false)), p.target);
          break;
        }
        case "openModal": {
          if (p.nodeId) scope.openModal(String(p.nodeId));
          break;
        }
        case "closeModal": {
          if (p.nodeId) scope.closeModal(String(p.nodeId));
          break;
        }
        case "openDrawer": {
          if (p.nodeId) {
            if (scope.openDrawer) scope.openDrawer(String(p.nodeId));
            else scope.openModal(String(p.nodeId));
          }
          break;
        }
        case "closeDrawer": {
          if (p.nodeId) {
            if (scope.closeDrawer) scope.closeDrawer(String(p.nodeId));
            else scope.closeModal(String(p.nodeId));
          }
          break;
        }
        case "message": {
          scope.message(String(evalValue(p.text ?? "", vars, true)), p.type || "info");
          break;
        }
        case "notification": {
          const text = String(evalValue(p.text ?? "", vars, true));
          const type = p.type || "info";
          if (scope.notification) scope.notification(text, type, p.title);
          else ElNotification({ title: p.title || "通知", message: text, type });
          break;
        }
        case "confirm": {
          const text = String(evalValue(p.text || "确认执行该操作？", vars, true));
          const title = p.title || "确认";
          let ok = false;
          if (scope.confirm) {
            ok = await scope.confirm(text, title);
          } else {
            try {
              await ElMessageBox.confirm(text, title, { type: "warning" });
              ok = true;
            } catch {
              ok = false;
            }
          }
          if (ok) await runSteps(step.then || [], scope, extra, depth + 1);
          else await runSteps(step.else || [], scope, extra, depth + 1);
          break;
        }
        case "record": {
          const modelId = Number(p.modelId || String(p.ref || "").replace(/^model_/, ""));
          if (p.op === "list") {
            const res = await scope.record.list(modelId, evalObject(p.params, vars));
            if (p.varName) scope.setVariable(p.varName, res);
          } else if (p.op === "create") {
            await scope.record.create(modelId, evalObject(p.data || {}, vars));
          } else if (p.op === "update") {
            await scope.record.update(modelId, Number(evalValue(p.id, vars)), evalObject(p.data || {}, vars));
          } else if (p.op === "remove") {
            await scope.record.remove(modelId, Number(evalValue(p.id, vars)));
          }
          break;
        }
        case "condition": {
          const cond = evaluateExpression(p.expr, vars);
          await runSteps(cond ? step.then || [] : step.else || [], scope, extra, depth + 1);
          break;
        }
        case "loop": {
          let list = evalValue(p.list, vars);
          if (list && typeof list === "object" && !Array.isArray(list) && Array.isArray((list as any).results)) {
            list = (list as any).results;
          }
          if (!Array.isArray(list)) list = [];
          const itemVar = p.itemVar || "item";
          const indexVar = p.indexVar || "index";
          for (let i = 0; i < list.length; i++) {
            await runSteps(step.then || [], scope, { ...(extra || {}), [itemVar]: list[i], [indexVar]: i }, depth + 1);
          }
          break;
        }
        case "parallel": {
          await Promise.all((step.then || []).map((s) => runSteps([s], scope, extra, depth + 1)));
          break;
        }
        case "tryCatch": {
          try {
            await runSteps(step.then || [], scope, extra, depth + 1, true);
          } catch (e: any) {
            const catchSteps = step.catch || step.else || [];
            await runSteps(catchSteps, scope, { ...(extra || {}), error: { message: errorText(e) } }, depth + 1);
          }
          break;
        }
        case "delay": {
          const ms = Math.max(0, Math.min(60000, Number(evalValue(p.ms ?? p.duration ?? 300, vars)) || 0));
          await new Promise((resolve) => setTimeout(resolve, ms));
          break;
        }
        case "setStyle": {
          const nodeId = String(p.nodeId || "");
          if (nodeId && scope.setNodeStyle) {
            scope.setNodeStyle(nodeId, evalObject(p.style || {}, vars));
          }
          break;
        }
        case "emit": {
          const eventName = String(p.event || "custom");
          const payload = evalObject(p.payload ?? p.data, vars);
          const schema = scope.eventSchemas?.[eventName]?.payload;
          if (schema && !payloadMatches(schema, payload)) {
            const message = `事件 ${eventName} 的 payload 不符合契约`;
            scope.message(message, "warning");
            scope.coordinationErrors?.push(message);
            if ((scope.coordinationErrors?.length || 0) > 50) scope.coordinationErrors?.shift();
            break;
          }
          scope.emit?.(eventName, payload);
          break;
        }
        case "submitForm": {
          const formId = p.formId ? String(evalValue(p.formId, vars)).replace(/^form_/, "") : undefined;
          if (scope.submitForm) {
            const result = await scope.submitForm(formId);
            if (!result.valid) {
              scope.message(result.values?.__error__ || "表单校验未通过", "warning");
              break;
            }
            if (p.varName) scope.setVariable(p.varName, result.values);
            if (p.modelId) {
              const modelId = Number(evalValue(p.modelId, vars));
              const data = { ...result.values };
              delete data.__error__;
              if ((p.op || "create") === "update") {
                const recordId = Number(evalValue(p.recordId, vars));
                if (!recordId) {
                  scope.message("更新记录缺少 recordId", "error");
                  break;
                }
                await scope.record.update(modelId, recordId, data);
              } else {
                await scope.record.create(modelId, data);
              }
            }
            scope.message(String(p.successText || "提交成功"), "success");
          } else {
            const values = formId ? scope.formValues[formId] || {} : Object.assign({}, ...Object.values(scope.formValues));
            if (p.varName) scope.setVariable(p.varName, values);
            scope.message(String(p.successText || "已收集表单数据"), "success");
          }
          break;
        }
        case "resetForm": {
          const formId = p.formId ? String(evalValue(p.formId, vars)).replace(/^form_/, "") : undefined;
          if (scope.resetForm) scope.resetForm(formId);
          else if (formId && scope.formValues[formId]) scope.formValues[formId] = {};
          break;
        }
        case "download": {
          const content = String(evalValue(p.content ?? p.text ?? "", vars, false));
          const filename = String(p.filename || "download.txt");
          const blob = new Blob([content], { type: String(p.mime || "text/plain;charset=utf-8") });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = filename;
          a.click();
          URL.revokeObjectURL(url);
          break;
        }
        case "copy": {
          const text = String(evalValue(p.text ?? "", vars, false));
          if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(text);
          scope.message(String(p.successText || "已复制"), "success");
          break;
        }
        case "print": {
          window.print();
          break;
        }
        case "http": {
          const method = String(p.method || "POST").toUpperCase();
          const path = String(evalValue(p.path || "", vars, false));
          const body = evalObject(p.body || {}, vars);
          const res =
            method === "GET"
              ? await api.get<any>(path, { silent: true })
              : method === "PUT"
                ? await api.put<any>(path, body, { silent: true })
                : method === "DELETE"
                  ? await api.del<any>(path, { silent: true })
                  : await api.post<any>(path, body, { silent: true });
          if (p.varName) scope.setVariable(p.varName, res);
          break;
        }
        case "js": {
          const code = String(p.code || p.expr || "").trim();
          if (!code) break;
          if (/\b(eval|Function|window|document|fetch|XMLHttpRequest|localStorage|sessionStorage)\b|=>|;/.test(code)) {
            scope.message("JS 动作仅允许受限表达式，禁止语句/DOM/网络 API", "error");
            break;
          }
          const checked = checkExpression(code);
          if (!checked.ok) {
            scope.message(`JS 动作仅允许受限表达式：${checked.error || "语法错误"}`, "error");
            break;
          }
          const value = evaluateExpression(code, vars);
          if (p.varName) scope.setVariable(p.varName, value);
          break;
        }
        default:
          break;
      }
    } catch (e: any) {
      if (propagate) throw e;
      scope.message(`动作 ${step.kind} 执行失败：${errorText(e)}`, "error");
    }
  }
}

/** 供 RuntimeScope.message 使用。 */
export function defaultMessage(text: string, type: "success" | "info" | "warning" | "error" = "info") {
  const map = { success: ElMessage.success, info: ElMessage.info, warning: ElMessage.warning, error: ElMessage.error };
  map[type](text);
}
