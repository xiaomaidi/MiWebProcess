<template>
  <el-dialog
    :model-value="modelValue"
    title="AI 全自动建站"
    width="860px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
    @close="onClose"
  >
    <template v-if="!job">
      <div v-if="planVisible" class="wp-ab-plan">
        <el-alert
          :title="planSourceMode ? '数据表页会自动生成；下面可调整附加页面。' : '取消勾选可去掉附加页；home/list/detail/about/contact/search 等核心页会自动补齐。'"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 12px"
        />
        <div class="wp-ab-plan-list">
          <div v-for="(page, index) in planPages" :key="index" class="wp-ab-plan-row">
            <el-checkbox v-model="page.enabled" />
            <el-input v-model="page.name" size="small" placeholder="页面名" style="width: 150px" />
            <el-input v-model="page.path" size="small" placeholder="路径" :disabled="planSourceMode" style="flex: 1" />
            <el-tag size="small" type="info">{{ page.kind }}</el-tag>
          </div>
        </div>
        <div class="wp-ab-plan-actions">
          <el-button @click="planVisible = false">返回修改</el-button>
          <el-button type="primary" :loading="starting" @click="confirmPlan">确认并开始</el-button>
        </div>
      </div>
      <div v-show="!planVisible">
      <div class="wp-ab-wizard-entry">
        <el-button type="primary" plain @click="wizardOpen = true">🧭 使用结构化向导</el-button>
        <span>选模板、勾页面，不用自己写提示词。</span>
      </div>
      <el-alert
        title="一句话生成完整站点：应用 + 内容模型 + 示例内容 + 页面 + 发布 + 搜索索引"
        description="创意模式用示例内容；PostgreSQL 模式直接读取数据库表，导入为公开数据模型并生成页面。"
        type="info"
        :closable="false"
        show-icon
        class="wp-ab-note"
      />
      <div class="wp-ab-mode-bar">
        <el-button size="small" text @click="wizardOpen = true">🧭 重新选择建站方式</el-button>
        <span>当前：{{ mode === "postgres" ? "PostgreSQL 数据建站" : "AI 创意建站" }}</span>
      </div>

      <el-form v-if="mode === 'creative'" label-position="top">
        <el-form-item label="你希望建一个什么站点？">
          <el-input
            v-model="prompt"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="例如：做一个深色数据大屏站，包含首页、数据大屏、在线表单、关于我们和站内搜索；大屏要 KPI、柱状图、饼图和明细表。"
          />
        </el-form-item>
      </el-form>

      <template v-else>
        <div class="wp-ab-existing">
          <span>复用已有数据源：</span>
          <el-select
            v-model="existingDatasourceId"
            clearable
            filterable
            placeholder="不使用，手动填写连接"
            style="flex: 1"
            @change="onExistingChange"
          >
            <el-option
              v-for="item in existingDatasources"
              :key="item.id"
              :label="`${item.app_name} / ${item.name}（${item.database || item.type}）`"
              :value="item.id"
            />
          </el-select>
          <el-button size="small" text @click="loadExisting">刷新</el-button>
        </div>
        <el-alert
          v-if="existingDatasourceId"
          type="success"
          :closable="false"
          show-icon
          title="已选择已有数据源：无需填写密码，建站时会复制该连接配置。"
          style="margin-bottom: 10px"
        />
        <el-form :model="pg" label-width="92px" class="wp-ab-pg">
          <el-row :gutter="10">
            <el-col :span="14">
              <el-form-item label="主机">
                <el-input v-model="pg.host" placeholder="127.0.0.1" />
              </el-form-item>
            </el-col>
            <el-col :span="10">
              <el-form-item label="端口">
                <el-input-number v-model="pg.port" :min="1" :max="65535" controls-position="right" style="width: 100%" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="12">
              <el-form-item label="数据库">
                <el-input v-model="pg.database" placeholder="db_stock" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Schema">
                <el-input v-model="pg.schema" placeholder="public" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-row :gutter="10">
            <el-col :span="12">
              <el-form-item label="用户名">
                <el-input v-model="pg.username" placeholder="postgres" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="密码">
                <el-input v-model="pg.password" type="password" show-password />
              </el-form-item>
            </el-col>
          </el-row>
          <div class="wp-ab-conn-actions">
            <el-button size="small" :loading="pgInspectLoading" @click="inspectDatasource">🔌 测试连接并读取表</el-button>
            <span v-if="pgInspectMessage" class="wp-ab-conn-msg">{{ pgInspectMessage }}</span>
          </div>
          <div class="wp-ab-tables">
            <div class="wp-ab-table-head">
              <span class="wp-ab-col-table">表名</span>
              <span class="wp-ab-col-limit">行数</span>
              <span class="wp-ab-col-label">栏目名</span>
              <span class="wp-ab-col-action"></span>
            </div>
            <div v-for="(item, index) in pgTables" :key="index" class="wp-ab-table-row">
              <el-select
                v-model="item.table"
                class="wp-ab-col-table"
                filterable
                allow-create
                default-first-option
                placeholder="选择或输入表名"
                @change="onTableChange(item)"
              >
                <el-option
                  v-for="table in pgCatalog"
                  :key="`${table.schema}.${table.name}`"
                  :label="`${table.schema}.${table.name}`"
                  :value="table.name"
                />
              </el-select>
              <el-input-number v-model="item.limit" :min="1" :max="500" controls-position="right" class="wp-ab-col-limit" />
              <el-input v-model="item.label" placeholder="行情" class="wp-ab-col-label" />
              <span class="wp-ab-col-action">
                <el-button text type="danger" :disabled="pgTables.length === 1" @click="removeTable(index)">删除</el-button>
              </span>
            </div>
            <el-button size="small" text type="primary" @click="addTable">+ 添加数据表（一表一模型）</el-button>
          </div>
          <el-row :gutter="10">
            <el-col :span="12">
              <el-form-item label="站点名（可选）">
                <el-input v-model="prompt" placeholder="股市前线" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="主题提示（可选）">
                <el-input v-model="themeHint" placeholder="深色红黑、简洁蓝色…" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="连接信息只用于本次建站：会创建只读数据源（密码加密存储），并把表数据导入为公开模型；请确保表是只读/可信数据。"
        />
      </template>
      <div class="wp-ab-examples">
        <span>示例：</span>
        <el-button size="small" text @click="fill('做一个独立游戏评测站，包含首页、评测列表、文章详情、关于我们和站内搜索，清爽浅色风')">独立游戏评测站</el-button>
        <el-button size="small" text @click="fill('做一个深色运营数据大屏站，包含首页、数据大屏、在线表单、关于我们和站内搜索；大屏有 4 个 KPI、柱状图、饼图和明细表。')">数据大屏 + 表单</el-button>
        <el-button size="small" text @click="fill('做一个企业官网，包含首页、产品列表、产品详情、关于我们和站内搜索，蓝色简洁风')">企业官网</el-button>
        <el-button size="small" text @click="fill('做一个游戏资讯门户，首页、资讯列表、文章详情、关于我们，深色科技风')">游戏资讯门户</el-button>
      </div>

      <el-divider content-position="left">生成选项</el-divider>
      <div class="wp-ab-options">
        <el-checkbox v-model="options.use_llm">调用大模型生成蓝图（关闭则用本地规则）</el-checkbox>
        <el-checkbox v-if="mode === 'creative'" v-model="options.sample_content">生成示例内容</el-checkbox>
        <el-checkbox v-model="options.create_workflow">创建发布审批工作流</el-checkbox>
        <el-checkbox v-model="options.create_realtime">创建实时通知通道</el-checkbox>
        <el-checkbox v-model="options.generate_ssr">生成 SSR 快照</el-checkbox>
        <el-checkbox v-model="options.publish">自动发布</el-checkbox>
        <el-checkbox v-model="options.enable_review">开启内容审核</el-checkbox>
      </div>
      </div>
    </template>

    <template v-else>
      <div class="wp-ab-head">
        <div>
          <strong>{{ job.blueprint?.site?.name || "正在规划站点" }}</strong>
          <el-tag size="small" :type="statusType" style="margin-left: 8px">{{ statusText }}</el-tag>
          <el-tag v-if="job.provider" size="small" effect="plain" style="margin-left: 6px">{{ job.provider }}</el-tag>
        </div>
        <span class="wp-ab-progress-text">{{ job.progress }}%</span>
      </div>
      <el-progress :percentage="job.progress" :status="job.status === 'failed' ? 'exception' : job.status === 'success' ? 'success' : undefined" :stroke-width="10" />

      <div class="wp-ab-body">
        <div class="wp-ab-steps">
          <div v-for="step in job.steps" :key="step.key" class="wp-ab-step" :class="`is-${step.status}`">
            <span class="wp-ab-dot" />
            <div class="wp-ab-step-main">
              <div class="wp-ab-step-label">{{ step.label }}</div>
              <div v-if="step.message" class="wp-ab-step-msg">{{ step.message }}</div>
            </div>
            <el-tag size="small" :type="stepType(step.status)">{{ stepText(step.status) }}</el-tag>
          </div>
        </div>

        <div class="wp-ab-side">
          <template v-if="job.blueprint?.site">
            <div class="wp-ab-card">
              <div class="wp-ab-card-title">站点蓝图</div>
              <div class="wp-ab-kv"><span>名称</span><b>{{ job.blueprint.site.name }}</b></div>
              <div class="wp-ab-kv"><span>主题</span><b>{{ job.blueprint.site.theme }}</b></div>
              <div class="wp-ab-kv"><span>内容模型</span><b>{{ job.result?.model_name || job.blueprint.content?.model }}</b></div>
              <div class="wp-ab-kv"><span>数据行</span><b>{{ job.result?.records ?? (job.blueprint.content?.items?.length || 0) }}</b></div>
              <div class="wp-ab-kv"><span>页面</span><b>{{ pageSummary }}</b></div>
            </div>
          </template>
          <el-collapse v-model="logOpen">
            <el-collapse-item title="执行日志" name="logs">
              <pre class="wp-ab-logs">{{ job.logs || "等待日志…" }}</pre>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>

      <el-alert v-if="job.status === 'failed'" type="error" :closable="false" show-icon :title="job.error || '建站失败'" style="margin-top: 12px" />

      <div v-if="job.status === 'success' && job.result" class="wp-ab-result">
        <el-alert type="success" :closable="false" show-icon title="站点已生成并发布" />
        <div class="wp-ab-links">
          <a :href="job.result.links.runtime" target="_blank" class="wp-ab-link">🌐 打开站点</a>
          <a v-if="job.result.links.list" :href="job.result.links.list" target="_blank" class="wp-ab-link">📋 数据列表</a>
          <a v-if="hasLivePage" :href="job.result.links.live" target="_blank" class="wp-ab-link">⚡ 实时数据</a>
          <a v-if="dashboardPage" :href="`/run/${job.result.app_code}/${dashboardPage.path}`" target="_blank" class="wp-ab-link">📊 数据大屏</a>
          <a v-if="formPage" :href="`/run/${job.result.app_code}/${formPage.path}`" target="_blank" class="wp-ab-link">📝 在线表单</a>
          <a :href="job.result.links.search" target="_blank" class="wp-ab-link">🔍 站内搜索</a>
          <a :href="job.result.links.designer" target="_blank" class="wp-ab-link">🎨 进入设计器</a>
          <a :href="job.result.links.admin" target="_blank" class="wp-ab-link">⚙️ 应用管理</a>
          <a :href="job.result.links.review" target="_blank" class="wp-ab-link">✅ 内容审核</a>
        </div>
        <div class="wp-ab-summary">
          应用 <b>{{ job.result.app_name }}</b>（{{ job.result.app_code }}） ·
          {{ job.result.pages.length }} 个页面 · {{ job.result.records }} 条内容 ·
          索引 {{ job.result.index_docs }} 条 · SSR {{ job.result.ssr_pages }} 页
          <template v-if="job.result.review?.structure">
            · 结构评审 {{ job.result.review.structure.after }} 分
            <template v-if="job.result.review.visual?.score != null"> / 视觉 {{ job.result.review.visual.score }} 分</template>
            <template v-if="job.result.review.fixed_pages?.length"> / 自动修复 {{ job.result.review.fixed_pages.length }} 页</template>
          </template>
        </div>
      </div>
    </template>

    <template #footer>
      <el-button @click="close">{{ job && isRunning ? "后台继续执行" : "关闭" }}</el-button>
      <el-button v-if="job && isRunning" type="danger" plain :loading="cancelling" @click="cancel">取消任务</el-button>
      <el-button v-if="!job && !planVisible" type="primary" :loading="starting || planning" :disabled="!prompt.trim() && mode !== 'postgres'" @click="start">预览页面计划</el-button>
      <el-button v-if="job && !isRunning" type="primary" @click="reset">再建一个</el-button>
    </template>

    <AutoBuildWizard v-model="wizardOpen" @apply="applyWizard" />
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/api";
import AutoBuildWizard from "./AutoBuildWizard.vue";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ (e: "update:modelValue", v: boolean): void; (e: "created"): void }>();

const prompt = ref("");
const wizardOpen = ref(false);
const starting = ref(false);
const cancelling = ref(false);
const job = ref<any>(null);
const logOpen = ref<string[]>([]);
const mode = ref<"creative" | "postgres">("creative");
let timer: number | null = null;

const pg = reactive({
  host: "127.0.0.1",
  port: 5432,
  database: "",
  username: "postgres",
  password: "",
  schema: "public",
});
const pgTables = reactive([{ table: "", limit: 100, label: "数据", schema: "" }]);
const pgCatalog = ref<any[]>([]);
const pgInspectLoading = ref(false);
const pgInspectMessage = ref("");
const existingDatasources = ref<any[]>([]);
const existingDatasourceId = ref<number | null>(null);
const themeHint = ref("");

const options = reactive({
  use_dsh: true,
  use_llm: true,
  sample_content: true,
  create_workflow: true,
  create_realtime: true,
  generate_ssr: true,
  publish: true,
  enable_review: false,
});

const isRunning = computed(() => job.value && ["pending", "running"].includes(job.value.status));
const hasLivePage = computed(() => (job.value?.result?.pages || []).some((page: any) => page.path === "live"));
const dashboardPage = computed(() => (job.value?.result?.pages || []).find((page: any) => page.kind === "dashboard"));
const formPage = computed(() => (job.value?.result?.pages || []).find((page: any) => page.kind === "form"));
const pageSummary = computed(() => {
  const pages = job.value?.result?.pages || [];
  return pages.length ? pages.map((page: any) => page.path).join(" / ") : "首页 / 列表 / 详情 / 关于 / 搜索";
});
const statusText = computed(() => ({ pending: "排队中", running: "执行中", success: "已完成", failed: "失败", cancelled: "已取消" }[job.value?.status as string] || job.value?.status));
const statusType = computed(() => (job.value?.status === "success" ? "success" : job.value?.status === "failed" ? "danger" : job.value?.status === "cancelled" ? "info" : "warning"));

function stepText(status: string): string {
  return { pending: "等待", running: "进行中", done: "完成", skipped: "跳过", failed: "失败" }[status] || status;
}
function stepType(status: string): "success" | "warning" | "danger" | "info" {
  return status === "done" ? "success" : status === "running" ? "warning" : status === "failed" ? "danger" : "info";
}

function fill(text: string) {
  prompt.value = text;
}

function applyWizard(payload: { prompt: string; mode: string; options: Record<string, any> }) {
  if (payload.mode === "postgres") {
    mode.value = "postgres";
    prompt.value = "";
    wizardOpen.value = false;
    ElMessage.info("请继续填写 PostgreSQL 连接和表");
    return;
  }
  mode.value = "creative";
  prompt.value = payload.prompt;
  Object.assign(options, payload.options || {});
  wizardOpen.value = false;
}

watch(
  () => props.modelValue,
  (open) => {
    if (open && !prompt.value && !job.value) wizardOpen.value = true;
  }
);

function addTable() {
  pgTables.push({ table: "", limit: 100, label: `数据${pgTables.length + 1}`, schema: "" });
}

function onTableChange(item: any) {
  const hit = pgCatalog.value.find((table: any) => table.name === item.table);
  if (hit) item.schema = hit.schema;
}

async function loadExisting() {
  try {
    const result = await api.get<any>("/ai/datasources/existing/");
    existingDatasources.value = result.results || [];
  } catch {
    existingDatasources.value = [];
  }
}

function onExistingChange(value: number | null) {
  const ds = existingDatasources.value.find((item: any) => item.id === value);
  if (!ds) return;
  pg.host = ds.host || "127.0.0.1";
  pg.port = Number(ds.port) || 5432;
  pg.database = ds.database || "";
  pg.username = ds.username || "";
  pg.schema = ds.schema || "public";
  pg.password = "";
  pgCatalog.value = [];
  pgInspectMessage.value = "";
}

async function inspectDatasource() {
  if (!pg.database.trim() && !existingDatasourceId.value) {
    ElMessage.warning("请先填写数据库名");
    return;
  }
  pgInspectLoading.value = true;
  try {
    const result = existingDatasourceId.value
      ? await api.post<any>("/ai/datasources/inspect-existing/", { datasource_id: existingDatasourceId.value })
      : await api.post<any>("/ai/datasources/inspect/", {
          type: "postgres",
          host: pg.host.trim(),
          port: pg.port,
          database: pg.database.trim(),
          username: pg.username.trim(),
          password: pg.password,
          schema: pg.schema.trim() || "public",
        });
    pgCatalog.value = result.tables || [];
    pgInspectMessage.value = `连接成功：${result.count} 张表`;
    if (!pgTables[0].table && pgCatalog.value[0]) {
      pgTables[0].table = pgCatalog.value[0].name;
      pgTables[0].schema = pgCatalog.value[0].schema;
    }
    ElMessage.success(`连接成功，读取到 ${result.count} 张表`);
  } catch (error: any) {
    pgInspectMessage.value = "";
    ElMessage.error(error?.message || "连接失败");
  } finally {
    pgInspectLoading.value = false;
  }
}

onMounted(loadExisting);

function removeTable(index: number) {
  if (pgTables.length > 1) pgTables.splice(index, 1);
}

const planVisible = ref(false);
const planning = ref(false);
const planPages = ref<any[]>([]);
const planSourceMode = ref(false);
const planConfirmed = ref(false);

function validateInputs(): boolean {
  if (mode.value === "postgres") {
    if (!pg.database.trim() || pgTables.some((item) => !item.table.trim())) {
      ElMessage.warning("请填写数据库名和表名");
      return false;
    }
  } else if (!prompt.value.trim()) {
    return false;
  }
  return true;
}

function buildPayloadOptions(): { prompt: string; options: Record<string, any> } {
  const payloadOptions: Record<string, any> = { ...options };
  if (mode.value === "postgres") {
    payloadOptions.sources = pgTables.map((item) => ({
      host: pg.host.trim(),
      port: pg.port,
      database: pg.database.trim(),
      username: pg.username.trim(),
      password: pg.password,
      schema: item.schema || pg.schema.trim() || "public",
      table: item.table.trim(),
      limit: item.limit,
      label: item.label.trim() || "数据",
      ...(existingDatasourceId.value ? { datasource_id: existingDatasourceId.value } : {}),
    }));
    payloadOptions.sample_content = false;
  }
  const finalPrompt = (prompt.value.trim() || (mode.value === "postgres" ? `根据 PostgreSQL 表 ${pgTables[0]?.table} 建站` : ""))
    + (mode.value === "postgres" && themeHint.value.trim() ? `，${themeHint.value.trim()}` : "");
  return { prompt: finalPrompt, options: payloadOptions };
}

async function start() {
  if (!validateInputs()) return;
  planning.value = true;
  try {
    const payload = buildPayloadOptions();
    const result = await api.post<any>("/ai/autobuild/plan/", payload);
    planPages.value = (result.pages || []).map((page: any) => ({ ...page, enabled: page.enabled !== false }));
    planSourceMode.value = !!result.source_mode;
    planVisible.value = true;
  } catch (error: any) {
    ElMessage.error(error?.message || "页面计划生成失败");
  } finally {
    planning.value = false;
  }
}

async function confirmPlan() {
  const enabled = planPages.value.filter((page) => page.enabled !== false);
  if (!enabled.length) {
    ElMessage.warning("至少保留一个页面");
    return;
  }
  if (enabled.some((page) => !String(page.path || "").trim())) {
    ElMessage.warning("页面路径不能为空");
    return;
  }
  planVisible.value = false;
  planConfirmed.value = true;
  await startBuild(enabled);
}

async function startBuild(pages?: any[]) {
  starting.value = true;
  try {
    const payload = buildPayloadOptions();
    if (pages && pages.length) {
      payload.options.pages_override = pages.map((page) => ({
        kind: page.kind,
        name: page.name,
        path: page.path,
        title: page.title || page.name,
        category: page.category || "",
        list_path: page.list_path || "",
        brief: page.brief || "",
        enabled: true,
      }));
    }
    const created = await api.post<any>("/ai/autobuild/", payload);
    job.value = created;
    if (["pending", "running"].includes(created.status)) startPolling();
    else finish(created);
  } catch (error: any) {
    ElMessage.error(error?.message || "启动建站失败");
  } finally {
    starting.value = false;
  }
}

function startPolling() {
  stopPolling();
  timer = window.setInterval(poll, 1500);
}

function stopPolling() {
  if (timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}

async function poll() {
  if (!job.value) return;
  try {
    const latest = await api.get<any>(`/ai/autobuild/${job.value.id}/`, { silent: true });
    job.value = latest;
    if (!["pending", "running"].includes(latest.status)) finish(latest);
  } catch {
    /* 轮询失败时继续下一次 */
  }
}

function finish(latest: any) {
  stopPolling();
  if (latest.status === "success") {
    if (latest.result?.warnings?.length) ElMessage.warning(latest.result.warnings.join("；"));
    else ElMessage.success(`站点「${latest.result?.app_name || ""}」已生成`);
    emit("created");
  } else if (latest.status === "failed") {
    ElMessage.error(latest.error || "建站失败");
  }
}

async function cancel() {
  if (!job.value) return;
  cancelling.value = true;
  try {
    job.value = await api.post(`/ai/autobuild/${job.value.id}/cancel/`, {});
    ElMessage.info("已请求取消");
  } finally {
    cancelling.value = false;
  }
}

function reset() {
  stopPolling();
  job.value = null;
  prompt.value = "";
  mode.value = "creative";
  planVisible.value = false;
  planPages.value = [];
  planConfirmed.value = false;
}

function close() {
  stopPolling();
  emit("update:modelValue", false);
}

function onClose() {
  stopPolling();
}

onBeforeUnmount(stopPolling);
</script>

<style scoped>
.wp-ab-wizard-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px dashed var(--el-color-primary);
  border-radius: 8px;
  background: var(--el-color-primary-light-9);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-ab-mode-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wp-ab-note {
  margin-bottom: 14px;
}
.wp-ab-examples {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: -6px;
}
.wp-ab-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 18px;
}
.wp-ab-pg {
  margin-top: 4px;
}
.wp-ab-pg :deep(.el-form-item) {
  margin-bottom: 12px;
}
.wp-ab-conn-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.wp-ab-existing {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
}
.wp-ab-conn-msg {
  font-size: 12px;
  color: var(--el-color-success);
}
.wp-ab-tables {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 14px;
}
.wp-ab-table-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.wp-ab-table-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.wp-ab-col-table {
  flex: 1.4;
}
.wp-ab-col-limit {
  width: 110px;
  flex: none;
}
.wp-ab-col-label {
  width: 100px;
  flex: none;
}
.wp-ab-col-action {
  width: 52px;
  flex: none;
  text-align: center;
}
.wp-ab-plan-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 52vh;
  overflow: auto;
}
.wp-ab-plan-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.wp-ab-plan-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 14px;
}
.wp-ab-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.wp-ab-progress-text {
  font-weight: 600;
  color: var(--el-color-primary);
}
.wp-ab-body {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 16px;
  margin-top: 16px;
}
.wp-ab-steps {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wp-ab-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
}
.wp-ab-step.is-running {
  background: var(--el-color-warning-light-9);
}
.wp-ab-step.is-failed {
  background: var(--el-color-danger-light-9);
}
.wp-ab-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-top: 6px;
  background: var(--el-color-info-light-3);
  flex: none;
}
.wp-ab-step.is-done .wp-ab-dot {
  background: var(--el-color-success);
}
.wp-ab-step.is-running .wp-ab-dot {
  background: var(--el-color-warning);
}
.wp-ab-step.is-failed .wp-ab-dot {
  background: var(--el-color-danger);
}
.wp-ab-step-main {
  flex: 1;
}
.wp-ab-step-label {
  font-size: 13px;
}
.wp-ab-step-msg {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
}
.wp-ab-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
}
.wp-ab-card-title {
  font-weight: 600;
  font-size: 13px;
  margin-bottom: 6px;
}
.wp-ab-kv {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  padding: 2px 0;
  color: var(--el-text-color-secondary);
}
.wp-ab-kv b {
  color: var(--el-text-color-primary);
  font-weight: 500;
}
.wp-ab-logs {
  max-height: 220px;
  overflow: auto;
  font-size: 11px;
  line-height: 1.6;
  background: #0f172a;
  color: #cbd5e1;
  padding: 10px;
  border-radius: 6px;
  white-space: pre-wrap;
}
.wp-ab-result {
  margin-top: 12px;
}
.wp-ab-links {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 10px 0;
}
.wp-ab-link {
  font-size: 13px;
  padding: 6px 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 6px;
  color: var(--el-color-primary);
  text-decoration: none;
}
.wp-ab-link:hover {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.wp-ab-summary {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
