<template>
  <el-dialog
    :model-value="modelValue"
    title="AI 建站向导"
    width="860px"
    :close-on-click-modal="false"
    append-to-body
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="wp-wiz">
      <div class="wp-wiz-intro">
        先选建站方式，再选模板、页面和内容。系统会自动拼装需求，不需要你写提示词。
      </div>

      <div class="wp-wiz-section-title">1. 建站方式</div>
      <div class="wp-wiz-modes">
        <button type="button" class="wp-wiz-mode" :class="{ 'is-active': dataMode === 'creative' }" @click="dataMode = 'creative'">
          <strong>AI 创意建站</strong>
          <span>用示例内容生成完整站点，适合官网、媒体站和展示站。</span>
        </button>
        <button type="button" class="wp-wiz-mode" :class="{ 'is-active': dataMode === 'postgres' }" @click="dataMode = 'postgres'">
          <strong>PostgreSQL 数据建站</strong>
          <span>连接业务库、选择表，导入为公开数据模型并生成页面。</span>
        </button>
      </div>

      <div v-if="dataMode === 'postgres'" class="wp-wiz-pg">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="下一步填写 PostgreSQL 连接、选择数据表，再生成页面计划。"
        />
        <el-button type="primary" @click="submitDatabase">继续配置数据库</el-button>
      </div>

      <template v-if="dataMode === 'creative'">
        <div class="wp-wiz-section-title">2. 选择模板</div>
        <div class="wp-wiz-templates">
          <button
            v-for="item in templates"
            :key="item.key"
            type="button"
            class="wp-wiz-template"
            :class="{ 'is-active': form.template === item.key }"
            @click="selectTemplate(item.key)"
          >
            <span class="wp-wiz-template-icon">{{ item.icon }}</span>
            <span class="wp-wiz-template-name">{{ item.label }}</span>
            <span class="wp-wiz-template-desc">{{ item.desc }}</span>
          </button>
        </div>

        <div class="wp-wiz-section-title">3. 基础信息</div>
        <el-form label-position="top" size="small">
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="站点名称">
                <el-input v-model="form.name" placeholder="例如：玩家星图" maxlength="30" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="单位 / 品牌（可选）">
                <el-input v-model="form.brand" placeholder="例如：某某单位" maxlength="30" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="一句话定位">
            <el-input v-model="form.positioning" maxlength="100" placeholder="例如：面向 PC 和主机玩家的游戏资讯、评测与攻略" />
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="目标用户">
                <el-input v-model="form.audience" maxlength="50" placeholder="例如：硬核玩家、游戏爱好者" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="内容方向">
                <el-input v-model="form.contentDirection" maxlength="60" placeholder="例如：PC / 主机 / 独立游戏" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <div class="wp-wiz-section-title">4. 页面</div>
        <el-checkbox-group v-model="form.pages" class="wp-wiz-checks">
          <el-checkbox v-for="page in pageOptions" :key="page.key" :value="page.key">
            <span class="wp-wiz-check-title">{{ page.label }}</span>
            <span class="wp-wiz-check-desc">{{ page.desc }}</span>
          </el-checkbox>
        </el-checkbox-group>

        <div class="wp-wiz-section-title">5. 首页模块</div>
        <el-checkbox-group v-model="form.modules" class="wp-wiz-checks">
          <el-checkbox v-for="module in moduleOptions" :key="module.key" :value="module.key">
            <span class="wp-wiz-check-title">{{ module.label }}</span>
            <span class="wp-wiz-check-desc">{{ module.desc }}</span>
          </el-checkbox>
        </el-checkbox-group>

        <el-form label-position="top" size="small" class="wp-wiz-module-note">
          <el-form-item label="首页重点想突出什么？（可选）">
            <el-input
              v-model="form.heroIdea"
              type="textarea"
              :rows="2"
              maxlength="160"
              placeholder="例如：本周新作、国产 3A、独立游戏；不填则使用默认焦点推荐。"
            />
          </el-form-item>
        </el-form>

        <div class="wp-wiz-section-title">6. 内容与图片</div>
        <el-form label-position="top" size="small">
          <el-row :gutter="12">
            <el-col :span="8">
              <el-form-item label="文章数量">
                <el-input-number v-model="form.articleCount" :min="0" :max="50" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="游戏数量">
                <el-input-number v-model="form.gameCount" :min="0" :max="50" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="生成示例内容">
                <el-switch v-model="form.sampleContent" />
              </el-form-item>
            </el-col>
          </el-row>
          <el-form-item label="内容分类">
            <el-input v-model="form.categories" maxlength="80" placeholder="例如：资讯、评测、攻略" />
          </el-form-item>
          <el-form-item label="图片要求">
            <el-input
              v-model="form.imageNote"
              type="textarea"
              :rows="2"
              maxlength="180"
              placeholder="例如：每篇文章、每个游戏必须有封面；详情页至少 2 张配图；不要空图。"
            />
          </el-form-item>
        </el-form>

        <div class="wp-wiz-section-title">7. 风格</div>
        <el-form label-position="top" size="small">
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="主题预设">
                <el-select v-model="form.theme" style="width: 100%" @change="applyTheme">
                  <el-option label="深色游戏媒体（红黑）" value="dark-game" />
                  <el-option label="浅色资讯站" value="light-news" />
                  <el-option label="企业蓝" value="corporate-blue" />
                  <el-option label="数据大屏（深蓝）" value="dashboard-dark" />
                  <el-option label="暖色内容站" value="warm" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="强调色">
                <el-input v-model="form.accent" placeholder="#e11d48" />
              </el-form-item>
            </el-col>
          </el-row>
        </el-form>

        <div class="wp-wiz-section-title">8. 高级自由补充（可选）</div>
        <el-form label-position="top" size="small">
          <el-form-item label="还有哪些特别要求？">
            <el-input
              v-model="form.extra"
              type="textarea"
              :rows="3"
              maxlength="500"
              placeholder="例如：不要使用真实媒体图片；导航要吸顶；移动端单列；首页要像游戏媒体门户。"
            />
          </el-form-item>
        </el-form>
      </template>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button v-if="dataMode === 'creative'" type="primary" @click="submit">生成页面计划</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "apply", payload: { prompt: string; mode: string; options: Record<string, any> }): void;
}>();

type TemplateKey = "game" | "corporate" | "dashboard" | "master-detail" | "blank";

interface Template {
  key: TemplateKey;
  icon: string;
  label: string;
  desc: string;
  name: string;
  positioning: string;
  audience: string;
  contentDirection: string;
  pages: string[];
  modules: string[];
  categories: string;
  theme: string;
  accent: string;
  articleCount: number;
  gameCount: number;
}

const templates: Template[] = [
  {
    key: "game", icon: "🎮", label: "游戏媒体站", desc: "资讯 / 评测 / 攻略 / 游戏库",
    name: "玩家星图", positioning: "面向 PC 和主机玩家的游戏资讯、评测与攻略",
    audience: "硬核玩家、游戏爱好者", contentDirection: "PC / 主机 / 独立游戏",
    pages: ["home", "news", "reviews", "guides", "games", "about", "search"],
    modules: ["hero", "latest", "ranking", "reviews", "guides", "game-grid"],
    categories: "资讯、评测、攻略", theme: "dark-game", accent: "#e11d48",
    articleCount: 16, gameCount: 6,
  },
  {
    key: "corporate", icon: "🏢", label: "企业官网", desc: "首页 / 产品 / 关于 / 联系",
    name: "企业官网", positioning: "展示单位业务、产品与联系方式的官方网站",
    audience: "客户、合作伙伴、访客", contentDirection: "产品与服务",
    pages: ["home", "products", "about", "contact", "search"],
    modules: ["hero", "features", "products", "about", "contact"],
    categories: "产品、新闻", theme: "corporate-blue", accent: "#2563eb",
    articleCount: 6, gameCount: 0,
  },
  {
    key: "dashboard", icon: "📊", label: "数据大屏站", desc: "KPI / 图表 / 明细 / 表单",
    name: "数据运营大屏", positioning: "面向管理者的数据看板与运营监控站",
    audience: "管理者、运营人员", contentDirection: "业务数据",
    pages: ["home", "dashboard", "form", "about", "search"],
    modules: ["hero", "kpis", "charts", "table", "form"],
    categories: "运营数据", theme: "dashboard-dark", accent: "#22d3ee",
    articleCount: 4, gameCount: 0,
  },
  {
    key: "master-detail", icon: "🗂️", label: "主从数据站", desc: "主表 / 明细 / JOIN 汇总",
    name: "主从数据站", positioning: "展示主表、明细与跨表汇总的数据站点",
    audience: "业务人员、数据使用方", contentDirection: "业务数据",
    pages: ["home", "list", "detail", "join", "about", "search"],
    modules: ["hero", "data-overview", "list", "join"],
    categories: "业务数据", theme: "dashboard-dark", accent: "#38bdf8",
    articleCount: 0, gameCount: 0,
  },
  {
    key: "blank", icon: "✨", label: "空白站点", desc: "只生成基础页面，后续再扩展",
    name: "新站点", positioning: "一个简洁的网站",
    audience: "访客", contentDirection: "综合内容",
    pages: ["home", "about", "search"],
    modules: ["hero", "latest"],
    categories: "综合", theme: "light-news", accent: "#409eff",
    articleCount: 6, gameCount: 0,
  },
];

const pageOptions = [
  { key: "home", label: "首页", desc: "站点主入口" },
  { key: "news", label: "资讯列表", desc: "新闻与动态" },
  { key: "reviews", label: "评测列表", desc: "评测文章" },
  { key: "guides", label: "攻略列表", desc: "实用攻略" },
  { key: "games", label: "游戏库", desc: "封面卡片与详情" },
  { key: "products", label: "产品列表", desc: "产品/服务展示" },
  { key: "list", label: "数据列表", desc: "业务数据列表" },
  { key: "detail", label: "数据详情", desc: "单条数据详情" },
  { key: "dashboard", label: "数据大屏", desc: "KPI 与图表" },
  { key: "form", label: "在线表单", desc: "公开提交表单" },
  { key: "join", label: "汇总页", desc: "多表 JOIN 宽表" },
  { key: "about", label: "关于我们", desc: "单位/站点介绍" },
  { key: "contact", label: "联系我们", desc: "联系方式" },
  { key: "search", label: "站内搜索", desc: "标题/摘要/标签搜索" },
];

const moduleOptions = [
  { key: "hero", label: "焦点推荐", desc: "大标题、副标题、入口按钮" },
  { key: "latest", label: "最新资讯", desc: "图文列表" },
  { key: "ranking", label: "热门排行", desc: "编号排行" },
  { key: "reviews", label: "评测精选", desc: "卡片网格" },
  { key: "guides", label: "攻略精选", desc: "图文列表" },
  { key: "game-grid", label: "游戏库推荐", desc: "封面卡片" },
  { key: "features", label: "优势/能力", desc: "图标 + 说明" },
  { key: "products", label: "产品展示", desc: "产品卡片" },
  { key: "about", label: "关于简介", desc: "单位介绍" },
  { key: "contact", label: "联系方式", desc: "电话/地址/表单" },
  { key: "kpis", label: "KPI 指标", desc: "关键数字卡片" },
  { key: "charts", label: "图表", desc: "柱状图/饼图/趋势" },
  { key: "table", label: "明细表", desc: "数据表格" },
  { key: "form", label: "在线表单", desc: "收集信息" },
  { key: "data-overview", label: "数据总览", desc: "数据模型概览" },
  { key: "list", label: "数据列表", desc: "业务数据列表" },
  { key: "join", label: "JOIN 汇总", desc: "多表宽表" },
];

const dataMode = ref<"creative" | "postgres">("creative");

const form = reactive({
  template: "game" as TemplateKey,
  name: "",
  brand: "",
  positioning: "",
  audience: "",
  contentDirection: "",
  pages: [] as string[],
  modules: [] as string[],
  heroIdea: "",
  articleCount: 16,
  gameCount: 6,
  sampleContent: true,
  categories: "",
  imageNote: "每篇文章、每个游戏必须有独立封面；文章详情页至少 2 张内配图；不要空图、破图或只有色块。",
  theme: "dark-game",
  accent: "#e11d48",
  extra: "",
});

function applyTemplate(template: Template) {
  form.name = template.name;
  form.positioning = template.positioning;
  form.audience = template.audience;
  form.contentDirection = template.contentDirection;
  form.pages = [...template.pages];
  form.modules = [...template.modules];
  form.categories = template.categories;
  form.theme = template.theme;
  form.accent = template.accent;
  form.articleCount = template.articleCount;
  form.gameCount = template.gameCount;
}

function selectTemplate(key: TemplateKey) {
  form.template = key;
  const template = templates.find((item) => item.key === key);
  if (template) applyTemplate(template);
}

function applyTheme(theme: string) {
  const colors: Record<string, string> = {
    "dark-game": "#e11d48",
    "light-news": "#2563eb",
    "corporate-blue": "#2563eb",
    "dashboard-dark": "#22d3ee",
    warm: "#f59e0b",
  };
  form.accent = colors[theme] || form.accent;
}

function pageLabel(key: string): string {
  return pageOptions.find((item) => item.key === key)?.label || key;
}

function moduleLabel(key: string): string {
  return moduleOptions.find((item) => item.key === key)?.label || key;
}

function themeLabel(theme: string): string {
  const labels: Record<string, string> = {
    "dark-game": "深色游戏媒体风，背景 #0b0f14，卡片 #121820，红黑强调",
    "light-news": "浅色资讯风，白色背景，清晰卡片和蓝色强调",
    "corporate-blue": "企业蓝简洁风，专业、可信",
    "dashboard-dark": "深色数据大屏风，深蓝背景，青色数据强调",
    warm: "暖色内容风，米白背景，橙色强调",
  };
  return labels[theme] || theme;
}

function buildPrompt(): string {
  const name = form.name.trim() || "新站点";
  const brand = form.brand.trim();
  const pages = form.pages.map(pageLabel).join("、") || "首页、关于我们、站内搜索";
  const modules = form.modules.map(moduleLabel).join("、") || "焦点推荐、最新资讯";
  const lines = [
    `请为${brand || "单位"}搭建一个网站，站点名称「${name}」。`,
    `一句话定位：${form.positioning.trim() || "一个简洁实用的网站"}。`,
    `目标用户：${form.audience.trim() || "普通访客"}。`,
    `内容方向：${form.contentDirection.trim() || "综合内容"}。`,
    `页面必须包含：${pages}。`,
    `首页模块：${modules}。`,
  ];
  if (form.heroIdea.trim()) lines.push(`首页重点突出：${form.heroIdea.trim()}。`);
  if (form.articleCount > 0) lines.push(`生成约 ${form.articleCount} 篇示例内容，分类为${form.categories || "综合"}，每篇必须有标题、摘要、正文、封面、作者、分类、标签和发布时间。`);
  if (form.gameCount > 0) lines.push(`生成 ${form.gameCount} 个游戏条目，每个必须有封面、名称、简介、平台、类型、评分和发售日期。`);
  if (form.imageNote.trim()) lines.push(`图片要求：${form.imageNote.trim()}`);
  lines.push(`视觉风格：${themeLabel(form.theme)}，强调色 ${form.accent}，桌面端内容宽度约 1240px，移动端单列自适应。`);
  lines.push("参考同类网站的信息架构，但不要使用游民星空或其他站点的名称、Logo、文章和图片。");
  lines.push("公开访问，不需要登录；不生成支付、会员、评论、投稿功能。");
  if (form.extra.trim()) lines.push(`高级补充：${form.extra.trim()}`);
  lines.push("生成示例内容并发布页面和应用，完成后给出首页、各频道和后台地址。");
  return lines.join("\n");
}

function submit() {
  if (!form.name.trim()) {
    ElMessage.warning("请填写站点名称");
    return;
  }
  emit("apply", {
    prompt: buildPrompt(),
    mode: "creative",
    options: {
      use_llm: true,
      sample_content: form.sampleContent,
      create_workflow: false,
      create_realtime: false,
      generate_ssr: false,
      publish: true,
      enable_review: false,
    },
  });
  emit("update:modelValue", false);
  ElMessage.success("已生成结构化需求，请预览页面计划");
}

function submitDatabase() {
  emit("apply", { prompt: "", mode: "postgres", options: {} });
  emit("update:modelValue", false);
}

onMounted(() => {
  const template = templates.find((item) => item.key === form.template);
  if (template) applyTemplate(template);
});
</script>

<style scoped>
.wp-wiz {
  max-height: 68vh;
  overflow: auto;
  padding-right: 6px;
}
.wp-wiz-intro {
  margin-bottom: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f5f7fa;
  color: #606266;
  font-size: 13px;
}
.wp-wiz-section-title {
  margin: 18px 0 10px;
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.wp-wiz-section-title:first-of-type {
  margin-top: 0;
}
.wp-wiz-modes {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.wp-wiz-mode {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}
.wp-wiz-mode:hover,
.wp-wiz-mode.is-active {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.12);
}
.wp-wiz-mode strong {
  color: #303133;
}
.wp-wiz-mode span {
  color: #909399;
  font-size: 12px;
}
.wp-wiz-pg {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  background: #fafafa;
}
.wp-wiz-pg .el-button {
  margin-top: 10px;
}
.wp-wiz-templates {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.wp-wiz-template {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  text-align: left;
}
.wp-wiz-template:hover,
.wp-wiz-template.is-active {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.12);
}
.wp-wiz-template-icon {
  font-size: 20px;
}
.wp-wiz-template-name {
  font-weight: 600;
  color: #303133;
}
.wp-wiz-template-desc {
  font-size: 12px;
  color: #909399;
}
.wp-wiz-checks {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 14px;
}
.wp-wiz-checks :deep(.el-checkbox) {
  height: auto;
  margin-right: 0;
  align-items: flex-start;
}
.wp-wiz-check-title {
  display: block;
  line-height: 1.4;
}
.wp-wiz-check-desc {
  display: block;
  color: #909399;
  font-size: 11px;
  line-height: 1.4;
}
.wp-wiz-module-note {
  margin-top: 10px;
}
@media (max-width: 760px) {
  .wp-wiz-templates,
  .wp-wiz-checks,
  .wp-wiz-modes {
    grid-template-columns: 1fr;
  }
}
</style>
