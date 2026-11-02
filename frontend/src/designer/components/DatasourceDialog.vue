<template>
  <el-dialog
    :model-value="modelValue"
    :title="editing ? `编辑数据源：${editing.name}` : '新建数据源'"
    width="520px"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="onClosed"
  >
    <el-form label-position="top">
      <el-form-item label="名称">
        <el-input v-model="form.name" placeholder="例如：用户列表" />
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.type" style="width: 100%">
          <el-option label="HTTP 数据源（rest）" value="rest" />
          <el-option label="系统内置 SQL（sql）" value="sql" />
          <el-option label="MySQL（外部）" value="mysql" />
          <el-option label="PostgreSQL（外部）" value="postgres" />
          <el-option label="SQL Server（外部）" value="sqlserver" />
          <el-option label="静态数据（static）" value="static" />
          <el-option label="WebSocket 实时数据" value="websocket" />
        </el-select>
      </el-form-item>

      <template v-if="form.type === 'websocket'">
        <el-form-item label="WebSocket 地址">
          <el-input v-model="ws.url" placeholder="wss://example.com/live" />
        </el-form-item>
        <el-form-item label="订阅消息（JSON，可选）">
          <el-input v-model="ws.subscribe" type="textarea" :rows="3" class="wp-mono" placeholder='{"type":"subscribe","channel":"ticker"}' />
        </el-form-item>
        <el-form-item label="数据路径（可选）">
          <el-input v-model="ws.dataPath" placeholder="例如 data、data.list" />
        </el-form-item>
        <el-form-item label="断线重连毫秒">
          <el-input-number v-model="ws.reconnectMs" :min="0" :max="60000" style="width: 100%" />
        </el-form-item>
        <el-alert
          title="WebSocket 由浏览器运行时连接，服务端不保存连接。适合实时行情、看板、告警推送。"
          type="info"
          :closable="false"
          show-icon
          class="wp-ds-note"
        />
      </template>
      <template v-if="form.type === 'rest'">
        <el-form-item label="请求地址 URL">
          <el-input v-model="rest.url" placeholder="https://api.example.com/users/{id}" />
        </el-form-item>
        <el-form-item label="请求方法">
          <el-select v-model="rest.method" style="width: 100%">
            <el-option label="GET" value="GET" />
            <el-option label="POST" value="POST" />
            <el-option label="PUT" value="PUT" />
          </el-select>
        </el-form-item>
        <el-form-item label="数据路径（可选）">
          <el-input v-model="rest.dataPath" placeholder="例如 data.list、data.items[*]、$.data.rows" />
          <div class="wp-form-tip">用于从 {code,data:{list:[]}} 这类外层结构中取出数组。</div>
        </el-form-item>
        <el-form-item label="扁平化嵌套对象">
          <el-switch v-model="rest.flatten" />
          <span class="wp-form-tip" style="margin-left: 8px">嵌套对象会变成 a_b_c 列，数组保持原值</span>
        </el-form-item>
        <el-form-item label="认证方式">
          <el-select v-model="rest.authType" clearable style="width: 100%">
            <el-option label="无" value="" />
            <el-option label="Bearer Token" value="bearer" />
            <el-option label="Basic" value="basic" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="rest.authType === 'bearer'" label="Token">
          <el-input v-model="rest.token" type="password" show-password />
        </el-form-item>
        <template v-if="rest.authType === 'basic'">
          <el-form-item label="用户名"><el-input v-model="rest.username" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="rest.password" type="password" show-password /></el-form-item>
        </template>
        <el-form-item label="请求头（JSON，可选）">
          <el-input v-model="rest.headers" type="textarea" :rows="3" class="wp-mono" placeholder='{"X-Api-Version":"1"}' />
        </el-form-item>
        <el-form-item label="请求体（JSON，可选）">
          <el-input v-model="rest.body" type="textarea" :rows="3" class="wp-mono" placeholder='{"name":"{{form.name}}"}' />
        </el-form-item>
        <el-form-item label="响应字段映射（JSON，可选）">
          <el-input v-model="rest.responseMap" type="textarea" :rows="3" class="wp-mono" placeholder='{"items":"data.list","total":"data.total"}' />
        </el-form-item>
        <el-form-item label="超时秒数">
          <el-input-number v-model="rest.timeout" :min="1" :max="60" style="width: 100%" />
        </el-form-item>
      </template>

      <el-form-item v-else-if="form.type === 'sql'" label="SELECT 查询">
        <el-input
          v-model="sqlQuery"
          type="textarea"
          :rows="6"
          class="wp-mono"
          placeholder="SELECT id, name FROM table WHERE status = {status}"
        />
      </el-form-item>

      <el-form-item v-else-if="form.type === 'static'" label="静态数据（JSON）">
        <el-input v-model="staticData" type="textarea" :rows="6" class="wp-mono" placeholder='[{"name":"A","value":1}]' />
      </el-form-item>

      <template v-else>
        <el-alert
          title="外部数据库只允许 SELECT 查询；连接信息在服务端使用，不会下发到浏览器。"
          type="info"
          :closable="false"
          show-icon
          class="wp-ds-note"
        />
        <el-form-item label="主机">
          <el-input v-model="external.host" placeholder="db.example.com 或 10.0.0.12" />
        </el-form-item>
        <el-form-item label="端口">
          <el-input-number v-model="external.port" :min="1" :max="65535" style="width: 100%" />
        </el-form-item>
        <el-form-item label="数据库名">
          <el-input v-model="external.database" placeholder="analytics" />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="external.username" autocomplete="off" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="external.password" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-form-item label="SELECT 查询">
          <el-input
            v-model="external.query"
            type="textarea"
            :rows="6"
            class="wp-mono"
            placeholder="SELECT id, name FROM users WHERE status = {status} LIMIT 100"
          />
        </el-form-item>
        <el-form-item v-if="form.type === 'postgres'" label="SSL 模式">
          <el-select v-model="external.ssl" style="width: 100%">
            <el-option label="prefer" value="prefer" />
            <el-option label="require" value="require" />
            <el-option label="disable" value="disable" />
          </el-select>
        </el-form-item>
        <el-form-item label="超时秒数">
          <el-input-number v-model="external.timeout" :min="1" :max="60" style="width: 100%" />
        </el-form-item>
        <el-form-item label="最大返回行数">
          <el-input-number v-model="external.maxRows" :min="1" :max="5000" style="width: 100%" />
        </el-form-item>
      </template>

      <el-form-item label="结果转换 transform（表达式，可选）">
        <el-input v-model="form.transform" placeholder="例如：data.items" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="$emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="onSave">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import type { DataSourceDef } from "@/types";
import { parseJson, prettyJson } from "../util";

const props = defineProps<{
  modelValue: boolean;
  appId: number;
  editing: DataSourceDef | null;
}>();
const emit = defineEmits<{
  (e: "update:modelValue", v: boolean): void;
  (e: "saved"): void;
}>();

const saving = ref(false);
const form = reactive({
  name: "",
  type: "rest",
  transform: "",
});
const rest = reactive({
  url: "",
  method: "GET",
  dataPath: "",
  flatten: false,
  authType: "",
  token: "",
  username: "",
  password: "",
  headers: "{}",
  body: "",
  responseMap: "{}",
  timeout: 5,
});
const sqlQuery = ref("");
const staticData = ref("[]");
const ws = reactive({
  url: "",
  subscribe: '{"type":"subscribe"}',
  dataPath: "",
  reconnectMs: 3000,
});
const external = reactive({
  host: "",
  port: 3306,
  database: "",
  username: "",
  password: "",
  query: "",
  ssl: "prefer",
  timeout: 8,
  maxRows: 500,
});

function loadConfig(type: string, cfg: Record<string, any>) {
  if (type === "rest") {
    rest.url = String(cfg.url || "");
    rest.method = String(cfg.method || "GET");
    rest.dataPath = String(cfg.data_path || "");
    rest.flatten = !!cfg.flatten;
    rest.authType = String(cfg.auth_type || "");
    rest.token = String(cfg.token || cfg.api_key || "");
    rest.username = String(cfg.username || "");
    rest.password = String(cfg.password || "");
    rest.headers = prettyJson(cfg.headers || {});
    rest.body = typeof cfg.body === "string" ? cfg.body : cfg.body ? prettyJson(cfg.body) : "";
    rest.responseMap = prettyJson(cfg.response_map || {});
    rest.timeout = Number(cfg.timeout) || 5;
  } else if (type === "sql") {
    sqlQuery.value = String(cfg.query || cfg.sql || "");
  } else if (type === "websocket") {
    ws.url = String(cfg.url || "");
    ws.subscribe = typeof cfg.subscribe === "string" ? cfg.subscribe : prettyJson(cfg.subscribe || { type: "subscribe" });
    ws.dataPath = String(cfg.data_path || "");
    ws.reconnectMs = Number(cfg.reconnect_ms) || 3000;
  } else if (type === "mysql" || type === "postgres" || type === "sqlserver") {
    external.host = String(cfg.host || "");
    external.port = Number(cfg.port) || (type === "mysql" ? 3306 : type === "postgres" ? 5432 : 1433);
    external.database = String(cfg.database || "");
    external.username = String(cfg.username || "");
    external.password = String(cfg.password || "");
    external.query = String(cfg.query || "");
    external.ssl = String(cfg.ssl || "prefer");
    external.timeout = Number(cfg.timeout) || 8;
    external.maxRows = Number(cfg.max_rows) || 500;
  } else {
    staticData.value = prettyJson(cfg.data ?? []);
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    if (props.editing) {
      form.name = props.editing.name;
      form.type = props.editing.type;
      loadConfig(props.editing.type, props.editing.config ?? {});
      const t = props.editing.transform as unknown as string | Record<string, any> | undefined;
      form.transform = t == null ? "" : typeof t === "string" ? t : prettyJson(t);
    } else {
      form.name = "";
      form.type = "rest";
      loadConfig("rest", {});
      form.transform = "";
    }
  }
);

function buildConfig(): Record<string, any> {
  if (form.type === "rest") {
    const headers = parseJson(rest.headers.trim() || "{}");
    if (headers === undefined || headers === null || typeof headers !== "object" || Array.isArray(headers)) {
      throw new Error("请求头必须是 JSON 对象");
    }
    const responseMap = parseJson(rest.responseMap.trim() || "{}");
    if (responseMap && (typeof responseMap !== "object" || Array.isArray(responseMap))) {
      throw new Error("响应字段映射必须是 JSON 对象");
    }
    const config: Record<string, any> = {
      url: rest.url.trim(),
      method: rest.method,
      headers,
      data_path: rest.dataPath.trim(),
      flatten: rest.flatten,
      response_map: responseMap || {},
      timeout: rest.timeout,
    };
    if (rest.authType) {
      config.auth_type = rest.authType;
      if (rest.authType === "bearer") config.token = rest.token;
      if (rest.authType === "basic") {
        config.username = rest.username;
        config.password = rest.password;
      }
    }
    if (rest.body.trim()) {
      const body = parseJson(rest.body.trim());
      config.body = body === undefined ? rest.body : body;
    }
    return config;
  }
  if (form.type === "websocket") {
    if (!ws.url.trim().startsWith("ws://") && !ws.url.trim().startsWith("wss://")) {
      throw new Error("WebSocket 地址必须以 ws:// 或 wss:// 开头");
    }
    let subscribe: any = parseJson(ws.subscribe.trim() || "{}");
    if (subscribe === undefined) subscribe = ws.subscribe.trim();
    return {
      url: ws.url.trim(),
      subscribe,
      data_path: ws.dataPath.trim(),
      reconnect_ms: ws.reconnectMs,
    };
  }
  if (form.type === "sql") return { query: sqlQuery.value.trim() };
  if (form.type === "mysql" || form.type === "postgres" || form.type === "sqlserver") {
    if (!external.host.trim() || !external.database.trim()) throw new Error("请填写主机和数据库名");
    return {
      host: external.host.trim(),
      port: external.port,
      database: external.database.trim(),
      username: external.username,
      password: external.password,
      query: external.query.trim(),
      ssl: external.ssl,
      timeout: external.timeout,
      max_rows: external.maxRows,
    };
  }
  const data = parseJson(staticData.value.trim() || "[]");
  if (data === undefined) throw new Error("静态数据必须是合法 JSON");
  return { data };
}

watch(
  () => form.type,
  (type) => {
    if (type === "mysql") external.port = 3306;
    else if (type === "postgres") external.port = 5432;
    else if (type === "sqlserver") external.port = 1433;
  }
);

function onClosed() {
  // el-dialog closed：无需额外清理
}

async function onSave() {
  if (!form.name.trim()) {
    ElMessage.warning("请填写名称");
    return;
  }
  let config: Record<string, any>;
  try {
    config = buildConfig();
  } catch (e: any) {
    ElMessage.error(e?.message || "数据源配置不合法");
    return;
  }
  if (form.type === "rest" && !rest.url.trim()) {
    ElMessage.warning("请填写请求地址 URL");
    return;
  }
  if (form.type === "websocket" && !ws.url.trim()) {
    ElMessage.warning("请填写 WebSocket 地址");
    return;
  }
  if (form.type === "sql" && !sqlQuery.value.trim()) {
    ElMessage.warning("请填写 SELECT 查询");
    return;
  }
  if (["mysql", "postgres", "sqlserver"].includes(form.type) && !external.query.trim()) {
    ElMessage.warning("请填写 SELECT 查询");
    return;
  }
  const transformText = form.transform.trim();
  const transform = transformText ? (parseJson(transformText) ?? transformText) : {};
  const body = {
    name: form.name.trim(),
    type: form.type,
    config,
    transform,
  };
  saving.value = true;
  try {
    if (props.editing) {
      await api.put(`/datasources/${props.editing.id}/`, body);
      ElMessage.success("数据源已更新");
    } else {
      await api.post(`/apps/${props.appId}/datasources/`, body);
      ElMessage.success("数据源已创建");
    }
    emit("update:modelValue", false);
    emit("saved");
  } catch {
    /* api 客户端已提示错误 */
  } finally {
    saving.value = false;
  }
}
</script>

<style scoped>
.wp-form-tip {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
}
</style>
