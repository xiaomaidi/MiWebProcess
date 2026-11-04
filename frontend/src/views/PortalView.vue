<template>
  <div class="wp-portal">
    <header class="portal-nav">
      <a class="portal-brand" href="/portal">
        <span class="portal-mark">M</span>
        <span><strong>MiWebProcess</strong><small>ENTERPRISE PLATFORM</small></span>
      </a>
      <nav class="portal-links">
        <a href="#capabilities">平台能力</a>
        <a href="#delivery">交付方式</a>
        <a href="#security">安全</a>
      </nav>
      <div class="portal-actions">
        <el-button text @click="go('/login')">登录</el-button>
        <el-button type="primary" @click="go('/admin/apps')">进入工作台</el-button>
      </div>
    </header>

    <main>
      <section class="portal-hero">
        <div class="portal-hero-copy">
          <span class="portal-eyebrow">LOW-CODE · ENTERPRISE READY</span>
          <h1>把业务想法<br />变成可运行的企业应用</h1>
          <p>页面设计、数据模型、流程审批、权限与 AI 辅助构建，统一在一个平台内完成。</p>
          <div class="portal-hero-actions">
            <el-button type="primary" size="large" @click="go('/admin/apps')">开始搭建</el-button>
            <el-button size="large" @click="go('/auth/mi-admin/login')">应用登录</el-button>
          </div>
          <div class="portal-trust">
            <span>Apache-2.0</span><span>私有部署</span><span>OIDC SSO</span><span>数据留在企业</span>
          </div>
        </div>
        <div class="portal-hero-panel">
          <div class="portal-panel-head"><span>今日运行概览</span><i class="portal-live" /></div>
          <div class="portal-metrics">
            <div><strong>52</strong><span>业务应用</span></div>
            <div><strong>94</strong><span>平台用户</span></div>
            <div><strong>177</strong><span>数据记录</span></div>
          </div>
          <div class="portal-bars">
            <div><span>流程审批</span><b style="width: 84%" /></div>
            <div><span>数据服务</span><b style="width: 68%" /></div>
            <div><span>AI 辅助</span><b style="width: 52%" /></div>
          </div>
          <div class="portal-panel-foot"><span>企业运维控制台</span><b>健康</b></div>
        </div>
      </section>

      <section id="capabilities" class="portal-section">
        <div class="portal-section-head">
          <span class="portal-eyebrow">CAPABILITIES</span>
          <h2>一个平台，覆盖应用全生命周期</h2>
        </div>
        <div class="portal-grid">
          <article v-for="item in features" :key="item.title" class="portal-card">
            <span class="portal-card-icon">{{ item.icon }}</span>
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
          </article>
        </div>
      </section>

      <section id="delivery" class="portal-section portal-delivery">
        <div>
          <span class="portal-eyebrow">DELIVERY</span>
          <h2>从内部台账到客户门户</h2>
          <p>同一套数据模型和权限体系，既可以内部使用，也可以面向外部客户交付。</p>
        </div>
        <div class="portal-steps">
          <div><i>01</i><strong>配置</strong><span>页面、字段、流程可视化配置</span></div>
          <div><i>02</i><strong>发布</strong><span>草稿、预览、版本、灰度发布</span></div>
          <div><i>03</i><strong>运营</strong><span>权限、审计、监控、备份</span></div>
        </div>
      </section>

      <section id="security" class="portal-security">
        <div>
          <span class="portal-eyebrow">ENTERPRISE SECURITY</span>
          <h2>企业级访问与运维</h2>
        </div>
        <div class="portal-security-grid">
          <span>OIDC 单点登录</span><span>应用级角色权限</span><span>字段级脱敏</span>
          <span>操作审计</span><span>数据库备份</span><span>健康监控</span>
        </div>
      </section>

      <section class="portal-cta">
        <h2>准备好把下一个业务搬到线上了吗？</h2>
        <p>使用平台账号进入工作台，或联系管理员开通企业 SSO。</p>
        <el-button type="primary" size="large" @click="go('/admin/apps')">进入 MiWebProcess</el-button>
      </section>
    </main>

    <footer class="portal-footer">
      <span>MiWebProcess · Apache-2.0</span>
      <span>企业低代码与数据平台</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from "vue-router";

const router = useRouter();
const features = [
  { icon: "◇", title: "可视化页面", desc: "拖拽搭建表单、列表、详情和仪表盘，发布即用。" },
  { icon: "▦", title: "数据模型", desc: "30+ 字段类型、关联、附件、公式和权限一次配置。" },
  { icon: "⌁", title: "流程与审批", desc: "应用级工作流、待办、审批中心和消息通知。" },
  { icon: "✦", title: "AI 辅助", desc: "AI 建站、生成模型、写内容和修改页面提案。" },
  { icon: "◎", title: "企业 SSO", desc: "应用级 OIDC 登录，支持自动建用户和默认角色。" },
  { icon: "▣", title: "运维控制台", desc: "健康检查、审计、失败任务和数据库备份。" },
];
function go(path: string) { router.push(path); }
</script>

<style scoped>
.wp-portal { min-height: 100vh; background: #f8fafc; color: #0f172a; }
.portal-nav { display: flex; align-items: center; justify-content: space-between; gap: 24px; max-width: 1240px; margin: 0 auto; padding: 22px 28px; }
.portal-brand { display: flex; align-items: center; gap: 9px; color: #0f172a; text-decoration: none; }
.portal-mark { display: flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 10px; background: linear-gradient(135deg, #2563eb, #38bdf8); color: #fff; font-weight: 800; }
.portal-brand span:last-child { display: flex; flex-direction: column; gap: 1px; }
.portal-brand strong { font-size: 14px; }
.portal-brand small { color: #94a3b8; font-size: 7px; letter-spacing: 1.4px; }
.portal-links { display: flex; gap: 24px; }
.portal-links a { color: #64748b; font-size: 12px; text-decoration: none; }
.portal-links a:hover { color: #2563eb; }
.portal-actions { display: flex; align-items: center; gap: 4px; }
.portal-hero { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 48px; align-items: center; max-width: 1240px; margin: 0 auto; padding: 70px 28px 84px; }
.portal-eyebrow { display: inline-block; margin-bottom: 14px; color: #2563eb; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
.portal-hero h1 { margin: 0 0 18px; font-size: 52px; line-height: 1.18; letter-spacing: -2px; }
.portal-hero-copy p { max-width: 520px; margin: 0 0 26px; color: #64748b; font-size: 15px; line-height: 1.8; }
.portal-hero-actions { display: flex; gap: 10px; }
.portal-trust { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 28px; color: #94a3b8; font-size: 10px; }
.portal-trust span { padding: 4px 8px; border: 1px solid #e2e8f0; border-radius: 999px; background: #fff; }
.portal-hero-panel { padding: 22px; border: 1px solid #e2e8f0; border-radius: 18px; background: #0f172a; color: #cbd5e1; box-shadow: 0 30px 80px rgba(15, 23, 42, 0.2); }
.portal-panel-head { display: flex; justify-content: space-between; align-items: center; color: #94a3b8; font-size: 11px; }
.portal-live { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 5px rgba(34, 197, 94, 0.12); }
.portal-metrics { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 22px 0; }
.portal-metrics div { padding: 12px; border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 10px; background: rgba(148, 163, 184, 0.06); }
.portal-metrics strong { display: block; color: #f8fafc; font-size: 22px; }
.portal-metrics span { color: #64748b; font-size: 10px; }
.portal-bars { display: flex; flex-direction: column; gap: 12px; }
.portal-bars div { display: grid; grid-template-columns: 74px 1fr; align-items: center; gap: 10px; color: #94a3b8; font-size: 10px; }
.portal-bars div::after { grid-column: 2; height: 5px; border-radius: 999px; background: rgba(148, 163, 184, 0.16); content: ""; }
.portal-bars b { height: 5px; margin-bottom: -15px; border-radius: 999px; background: linear-gradient(90deg, #2563eb, #38bdf8); }
.portal-panel-foot { display: flex; justify-content: space-between; margin-top: 22px; padding-top: 14px; border-top: 1px solid rgba(148, 163, 184, 0.12); color: #64748b; font-size: 10px; }
.portal-panel-foot b { color: #4ade80; }
.portal-section { max-width: 1240px; margin: 0 auto; padding: 60px 28px; }
.portal-section-head { max-width: 620px; margin-bottom: 26px; }
.portal-section h2 { margin: 0 0 10px; font-size: 32px; letter-spacing: -1px; }
.portal-section p { color: #64748b; font-size: 13px; line-height: 1.8; }
.portal-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.portal-card { padding: 22px; border: 1px solid #e8edf5; border-radius: 14px; background: #fff; transition: transform 0.16s ease, box-shadow 0.16s ease; }
.portal-card:hover { transform: translateY(-2px); box-shadow: 0 14px 30px rgba(15, 23, 42, 0.07); }
.portal-card-icon { display: flex; align-items: center; justify-content: center; width: 34px; height: 34px; border-radius: 9px; background: #eff6ff; color: #2563eb; font-size: 17px; }
.portal-card h3 { margin: 15px 0 7px; font-size: 14px; }
.portal-card p { margin: 0; font-size: 12px; line-height: 1.7; }
.portal-delivery { display: grid; grid-template-columns: 0.9fr 1.1fr; gap: 40px; align-items: center; padding-top: 40px; }
.portal-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.portal-steps div { display: flex; flex-direction: column; gap: 6px; padding: 16px; border: 1px solid #e8edf5; border-radius: 12px; background: #fff; }
.portal-steps i { color: #2563eb; font-size: 10px; font-style: normal; font-weight: 700; }
.portal-steps strong { font-size: 13px; }
.portal-steps span { color: #94a3b8; font-size: 10px; line-height: 1.6; }
.portal-security { max-width: 1240px; margin: 0 auto; padding: 28px; border-radius: 18px; background: #0f172a; color: #e2e8f0; }
.portal-security h2 { color: #f8fafc; font-size: 24px; }
.portal-security-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-top: 20px; }
.portal-security-grid span { padding: 10px 12px; border: 1px solid rgba(148, 163, 184, 0.16); border-radius: 8px; color: #cbd5e1; font-size: 11px; }
.portal-cta { max-width: 1240px; margin: 30px auto 0; padding: 56px 28px; text-align: center; }
.portal-cta h2 { margin: 0 0 10px; font-size: 28px; }
.portal-cta p { margin: 0 0 20px; color: #64748b; font-size: 12px; }
.portal-footer { display: flex; justify-content: space-between; max-width: 1240px; margin: 0 auto; padding: 22px 28px 28px; color: #94a3b8; font-size: 10px; }
@media (max-width: 900px) { .portal-links { display: none; } .portal-hero { grid-template-columns: 1fr; padding-top: 36px; } .portal-hero h1 { font-size: 38px; } .portal-grid, .portal-delivery, .portal-security-grid { grid-template-columns: 1fr; } .portal-actions .el-button:first-child { display: none; } }
@media (max-width: 520px) { .portal-nav { padding: 16px; } .portal-section { padding: 40px 18px; } .portal-hero { padding: 28px 18px 50px; } .portal-hero h1 { font-size: 32px; } .portal-security { margin: 0 18px; padding: 20px; } .portal-cta { padding: 40px 18px; } .portal-steps { grid-template-columns: 1fr; } }
</style>
