/**
 * 运行时作用域：为 NodeRenderer 与内置组件提供变量、数据源/模型查询、
 * 模态框/抽屉、消息、确认、表单、事件与页面跳转能力。所有状态为 reactive。
 */
import { reactive } from "vue";
import { ElMessage, ElMessageBox, ElNotification } from "element-plus";
import { api } from "@/api";
import type {
  AppInfo,
  DataModelInfo,
  DataSourceDef,
  FormSubmitResult,
  Paged,
  RuntimeScope,
} from "@/types";

export interface RuntimeScopeOptions {
  app: AppInfo;
  pageId: number;
  pageVersion: number;
  datasources: DataSourceDef[];
  models: DataModelInfo[];
  variables: Record<string, any>;
  routeParams?: Record<string, string>;
  routePath?: string;
  navigate(path: string): void;
  setNodeStyle?: (nodeId: string, style: Record<string, any>) => void;
  emit?: (event: string, payload?: unknown) => void;
  stateDefs?: Record<string, any>;
  eventSchemas?: Record<string, any>;
  modules?: Record<string, boolean>;
}

function valueType(value: any): string {
  if (Array.isArray(value)) return "array";
  if (value === null) return "null";
  return typeof value;
}

function checkStateType(expected: string | undefined, value: any): boolean {
  if (!expected || expected === "any" || value === null || value === undefined) return true;
  return valueType(value) === expected;
}

export interface ModelRecord {
  id: number;
  data: Record<string, any>;
}

export function createRuntimeScope(opts: RuntimeScopeOptions): RuntimeScope {
  const variables: Record<string, any> = reactive<Record<string, any>>({ ...opts.variables });
  const datasourceResults: Record<number, any> = reactive<Record<number, any>>({});
  const modelResults: Record<number, any> = reactive<Record<number, any>>({});
  const formValues: Record<string, Record<string, any>> = reactive<Record<string, Record<string, any>>>({});
  const formValidators: Record<string, () => Promise<boolean>> = reactive<Record<string, () => Promise<boolean>>>({});
  const loopVars: Record<string, any> = reactive<Record<string, any>>({});
  const coordinationErrors = reactive<string[]>([]);
  const modalNodeIds = reactive(new Set<string>());
  const drawerNodeIds = reactive(new Set<string>());

  variables.app = opts.app;
  const datasources = opts.datasources || [];

  function datasourceConfig(id: number): { ds: any; cfg: Record<string, any> } | null {
    const list = (scope as any)?.datasources || datasources;
    const ds = list.find((item: any) => Number(item.id) === Number(id));
    if (!ds) return null;
    return { ds, cfg: { ...(ds.public_config || ds.config || {}) } };
  }

  function renderTemplate(text: string, params: Record<string, any>): string {
    let out = String(text || "");
    for (const [key, value] of Object.entries(params || {})) {
      const replacement = typeof value === "object" ? JSON.stringify(value) : String(value);
      out = out.replaceAll(`{{${key}}}`, replacement);
    }
    return out;
  }

  function jsonPath(value: any, path: string): any {
    if (!path) return value;
    let current = value;
    for (const part of path.split(".").filter(Boolean)) {
      if (current == null) return undefined;
      current = current[part];
    }
    return current;
  }

  function subscribeDatasource(
    id: number,
    params: Record<string, any>,
    handler: (data: any, raw?: any) => void
  ): () => void {
    const found = datasourceConfig(id);
    if (!found || found.ds.type !== "websocket") {
      throw new Error("WebSocket 数据源不存在");
    }
    if (typeof window === "undefined" || !("WebSocket" in window)) {
      throw new Error("当前浏览器不支持 WebSocket");
    }
    const { cfg } = found;
    const url = renderTemplate(String(cfg.url || ""), params);
    if (!url) throw new Error("WebSocket 数据源缺少 url");
    let closed = false;
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (closed) return;
      socket = new WebSocket(url);
      socket.onopen = () => {
        const subscribe = cfg.subscribe;
        if (subscribe !== undefined && subscribe !== null && subscribe !== "") {
          const text = typeof subscribe === "string" ? renderTemplate(subscribe, params) : renderTemplate(JSON.stringify(subscribe), params);
          try {
            socket?.send(text);
          } catch {
            /* ignore */
          }
        }
      };
      socket.onmessage = (event) => {
        let payload: any = event.data;
        try {
          payload = JSON.parse(event.data);
        } catch {
          /* keep raw text */
        }
        const data = jsonPath(payload, String(cfg.data_path || ""));
        datasourceResults[id] = data;
        variables[`ds_${id}`] = data;
        handler(data, payload);
      };
      socket.onerror = () => {
        coordinationErrors.push(`WebSocket 数据源 ${id} 连接错误`);
        if (coordinationErrors.length > 50) coordinationErrors.shift();
      };
      socket.onclose = () => {
        if (closed) return;
        const delay = Number(cfg.reconnect_ms) || 0;
        if (delay > 0) retryTimer = setTimeout(connect, Math.min(delay, 60000));
      };
    };
    connect();
    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
      socket = null;
    };
  }

  async function callDatasource(id: number, params?: Record<string, any>): Promise<any> {
    const found = datasourceConfig(id);
    if (found?.ds.type === "websocket") {
      return new Promise((resolve, reject) => {
        let unsubscribe: (() => void) | null = null;
        const timer = setTimeout(() => {
          unsubscribe?.();
          reject(new Error("WebSocket 等待数据超时"));
        }, 10000);
        unsubscribe = subscribeDatasource(id, params || {}, (data) => {
          clearTimeout(timer);
          unsubscribe?.();
          resolve(data);
        });
      });
    }
    const res = await api.post(`/datasources/${id}/query/`, { params: params ?? {} });
    datasourceResults[id] = res;
    variables[`ds_${id}`] = res && typeof res === "object" && "data" in res ? (res as { data: any }).data : res;
    return res;
  }

  function recordList(modelId: number, params?: Record<string, any>): Promise<Paged<ModelRecord>> {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params ?? {})) {
      if (v === null || v === undefined || v === "") continue;
      qs.set(k, typeof v === "object" ? JSON.stringify(v) : String(v));
    }
    return api.get<Paged<ModelRecord>>(`/models/${modelId}/records/?${qs.toString()}`)
      .then((data) => {
        modelResults[modelId] = data;
        return data;
      });
  }

  const scope: RuntimeScope = {
    variables,
    routeParams: { ...(opts.routeParams || {}) },
    routePath: opts.routePath || "",
    setVariable(name: string, value: any) {
      const def = opts.stateDefs?.[name];
      if (def && !checkStateType(def.type, value)) {
        const message = `状态 ${name} 需要 ${def.type}，收到 ${valueType(value)}`;
        ElMessage.warning(message);
        coordinationErrors.push(message);
        if (coordinationErrors.length > 50) coordinationErrors.shift();
        return;
      }
      variables[name] = value;
    },
    datasourceResults,
    modelResults,
    formValues,
    formValidators,
    loopVars,
    coordinationErrors,
    datasources,
    modules: opts.modules || {},
    subscribeDatasource,
    callDatasource,
    navigate(path: string, target?: string) {
      if (target === "_blank") {
        window.open(path, "_blank");
        return;
      }
      opts.navigate(path);
    },
    openModal(nodeId: string) {
      modalNodeIds.add(nodeId);
    },
    closeModal(nodeId: string) {
      modalNodeIds.delete(nodeId);
    },
    modalNodeIds,
    drawerNodeIds,
    openDrawer(nodeId: string) {
      drawerNodeIds.add(nodeId);
    },
    closeDrawer(nodeId: string) {
      drawerNodeIds.delete(nodeId);
    },
    message(text: string, type?: "success" | "info" | "warning" | "error") {
      if (type === "success") ElMessage.success(text);
      else if (type === "warning") ElMessage.warning(text);
      else if (type === "error") ElMessage.error(text);
      else ElMessage.info(text);
    },
    notification(text: string, type?: "success" | "info" | "warning" | "error", title?: string) {
      ElNotification({ title: title || "通知", message: text, type: type || "info" });
    },
    async confirm(text: string, title?: string) {
      try {
        await ElMessageBox.confirm(text, title || "确认", { type: "warning" });
        return true;
      } catch {
        return false;
      }
    },
    async submitForm(formId?: string): Promise<FormSubmitResult> {
      const ids = formId ? [formId] : Object.keys(formValidators);
      for (const id of ids) {
        const validate = formValidators[id];
        if (validate) {
          try {
            const ok = await validate();
            if (!ok) {
              return { valid: false, values: { ...(formValues[id] || {}), __error__: "表单校验未通过" } };
            }
          } catch {
            return { valid: false, values: { ...(formValues[id] || {}), __error__: "表单校验未通过" } };
          }
        }
      }
      const values = formId
        ? { ...(formValues[formId] || {}) }
        : Object.assign({}, ...Object.values(formValues).map((v) => ({ ...v })));
      return { valid: !values.__error__, values };
    },
    resetForm(formId?: string) {
      if (formId) formValues[formId] = {};
      else for (const key of Object.keys(formValues)) formValues[key] = {};
    },
    setNodeStyle: opts.setNodeStyle,
    record: {
      list: recordList,
      async get(modelId: number, id: number) {
        return await api.get(`/models/${modelId}/records/${id}/`);
      },
      async create(modelId: number, data: Record<string, any>) {
        return await api.post<ModelRecord>(`/models/${modelId}/records/`, { data });
      },
      async update(modelId: number, id: number, data: Record<string, any>) {
        return await api.put<ModelRecord>(`/models/${modelId}/records/${id}/`, { data });
      },
      async remove(modelId: number, id: number) {
        await api.del(`/models/${modelId}/records/${id}/`);
      },
    },
    emit(event: string, payload?: unknown) {
      if (opts.emit) opts.emit(event, payload);
      else window.dispatchEvent(new CustomEvent(`wp:${event}`, { detail: payload }));
    },
  };
  return scope;
}
