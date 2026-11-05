# MiWebProcess

[中文](#中文) | [English](#english)

> 可视化、多应用的低代码建站与业务平台：拖拽页面、配置数据模型、连接工作流，再用 AI Agent 辅助修改。
>
> A visual, multi-application low-code platform: build pages by dragging, configure data models, connect workflows, and let AI Agents help you iterate.

**平台内核开发一次，应用只配置，不重复写代码。**
**Build the platform core once; configure applications instead of writing the same code again.**

- Gitee: <https://gitee.com/xiaomi517/mi-web-process>
- 设计器文档 / Designer docs: [docs/DESIGNER.md](docs/DESIGNER.md)
- 企业能力 / Enterprise docs: [docs/ENTERPRISE.md](docs/ENTERPRISE.md)
- API 文档 / API docs: [docs/API.md](docs/API.md)
- Redis / 多 worker 部署 / deployment: [docs/deployment/Redis.md](docs/deployment/Redis.md)

---

# 中文

## 1. 项目简介

MiWebProcess 是面向内部管理系统、客户门户、数据看板和表单应用的开发平台。

一个平台可以承载多个独立应用，每个应用拥有自己的：

```text
页面
数据模型
成员与角色
登录 / 注册配置
工作流与审批
文件目录
通知模板
API Token
Webhook
定时任务
```

## 2. 核心能力

### 页面设计器

- 流式 / 自由布局，网格吸附、拖动、缩放。
- 智能参考线、对齐 / 分布、组合 / 锁定 / 隐藏、框选。
- 桌面 / 平板 / 手机响应式布局。
- 可复用区块、区块版本、区块市场、视觉 diff。
- 组件状态与变体、变体数据绑定。
- 页面变量、数据源、数据模型、表单字段可视化绑定。
- 素材库、组件库、大纲树、实时评论。
- 发布前质量与可访问性检查。

### 实时协作

- 在线成员、光标、选区。
- 服务端强制节点锁，TTL 90 秒，心跳续期。
- 锁等待队列、排队位置、超时提示、取消。
- schema 操作日志与节点级 CRDT-style 合并。
- 保存冲突检测与「重新加载 / 覆盖保存」。
- Redis Channel Layer 支持多 ASGI worker。

### 数据与应用

- 数据模型、字段、动态记录 CRUD。
- 应用级登录、注册、成员、角色、权限。
- 工作流、审批面板、审批中心。
- 应用级文件、通知、API Token、Webhook、定时任务。
- PostgreSQL，开发可降级 SQLite。

### AI Agent

- 读取页面、生成修改提案。
- 创建 / 修改数据模型与工作流。
- 提案 diff、审批、应用、验证、回滚。
- 页面助手与高级 Agent 分离。

### 企业与交付

- 企业控制台、备份、审计、OIDC SSO。
- 页面 / 表单导入导出，PDF / Excel / CSV。
- 模板市场、组件市场、区块市场。
- 应用蓝图导出、导入、克隆。
- PWA、通知中心、双语文档。

## 3. 技术栈

### 后端

```text
Django 5
Django REST Framework
Channels / Daphne
Celery
PostgreSQL（可降级 SQLite）
Redis（可选）
MinIO / S3（可选）
```

### 前端

```text
Vue 3
TypeScript
Vite
Pinia
Vue Router
Element Plus
Monaco Editor
ECharts
Playwright
```

## 4. 快速启动

### 一键启动

Windows 双击：

```text
start.bat
```

会启动：

```text
DSH 真实服务   9000
Django 后端    8000
Vite 前端      5173
```

停止：

```text
stop.bat
```

强制重启：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Restart
```

日志：

```text
.runtime/logs/
```

### 手动启动

后端：

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

### 可选服务

```bash
docker compose up -d
```

包含 PostgreSQL、Redis、MinIO。

## 5. 默认入口

```text
平台登录：      http://127.0.0.1:5173/login
管理后台：      http://127.0.0.1:5173/admin
应用运行：      http://127.0.0.1:5173/run/{appCode}/...
应用登录：      http://127.0.0.1:5173/auth/{appCode}/login
应用注册：      http://127.0.0.1:5173/auth/{appCode}/register
工作流设计器：  http://127.0.0.1:5173/workflow/design/{appId}
应用设置：      http://127.0.0.1:5173/admin/apps/{appId}/settings
应用服务：      http://127.0.0.1:5173/admin/apps/{appId}/services
```

演示账号：

```text
用户名：admin
密码：  admin123
```

> 生产部署前必须修改默认账号和密码。

演示应用：

```text
名称：MiWebProcess 企业管理后台
编码：mi-admin
ID：  112
```

## 6. 构建与检查

前端：

```bash
cd frontend
pnpm typecheck
pnpm build
npm run test:e2e
```

后端：

```bash
cd backend
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

Playwright 端到端覆盖：

```text
登录 / 应用列表 / 应用详情
通知中心
组件市场签名与沙箱
设计器加载 / 属性面板
录制回放
区块库
移动端面板
锁冲突
双用户 schema 同步
```

## 7. 目录结构

```text
backend/
  appcore/        应用、成员、通知、模板
  pages/          页面、设计器 schema、区块、版本、操作日志
  components/     组件注册表
  workflows/      工作流与审批
  enterprise/     企业控制台、备份、审计
  collab/         评论、节点锁、锁队列
  market/         组件 / 区块市场、签名
  realtime/       WebSocket、Channel Layer
  runtime/        应用运行时
frontend/
  src/designer/   设计器
  src/engine/     渲染引擎、绑定、状态
  src/builtin/    内置组件
  src/views/      管理后台与运行时页面
  e2e/            Playwright
docs/
```

## 8. 已知边界

- CRDT 为节点级 LWW，不是字段级 CRDT。
- 操作日志 append-only，暂不自动归档。
- Redis 5 需 `?protocol=2`，生产建议 Redis 7。
- 区块回滚只恢复草稿，不自动重发已发布页面。
- 沙箱组件仅支持 custom element ESM，需 CORS。
- 市场签名覆盖元数据 / URL / schema，不覆盖远端 ESM 字节。
- 变体 style 数据绑定不支持。

## 9. License

Apache License 2.0，见 [LICENSE](LICENSE) 与 [NOTICE](NOTICE)。

---

# English

## 1. Overview

MiWebProcess is a development platform for internal management systems, customer portals, dashboards, and form-driven applications.

One deployment can host multiple independent applications. Each application owns its own:

```text
pages
data models
members and roles
login / registration configuration
workflows and approvals
file storage
notification templates
API tokens
webhooks
scheduled jobs
```

## 2. Highlights

### Page designer

- Flow and free-form layouts, grid snapping, drag and resize.
- Smart guides, align / distribute, group / lock / hide, marquee selection.
- Desktop / tablet / phone responsive layouts.
- Reusable blocks, block versions, block marketplace, visual diff.
- Component states and variants, variant-level data binding.
- Visual binding for page variables, data sources, models, and form fields.
- Media library, component library, outline tree, realtime comments.
- Pre-publish quality and accessibility checks.

### Realtime collaboration

- Online members, cursors, selections.
- Server-authoritative node locks with a 90-second TTL and heartbeats.
- Lock wait queue, queue position, timeout, cancellation.
- Schema operation log with node-level CRDT-style merge.
- Save conflict detection with reload / overwrite options.
- Redis Channel Layer for multi-worker ASGI deployments.

### Data and applications

- Data models, fields, and dynamic record CRUD.
- App-level login, registration, members, roles, permissions.
- Workflows, approval panels, approval center.
- App files, notifications, API tokens, webhooks, scheduled jobs.
- PostgreSQL; SQLite fallback for development.

### AI Agents

- Read pages and generate change proposals.
- Create or modify data models and workflows.
- Proposal diff, approval, apply, verification, rollback.
- Separate page assistant and advanced Agent.

### Enterprise and delivery

- Enterprise console, backups, audit, OIDC SSO.
- Page / form import and export, PDF / Excel / CSV.
- Template, component, and block marketplaces.
- App blueprint export, import, and clone.
- PWA, notification center, bilingual documentation.

## 3. Tech stack

### Backend

```text
Django 5
Django REST Framework
Channels / Daphne
Celery
PostgreSQL (SQLite fallback)
Redis (optional)
MinIO / S3 (optional)
```

### Frontend

```text
Vue 3
TypeScript
Vite
Pinia
Vue Router
Element Plus
Monaco Editor
ECharts
Playwright
```

## 4. Quick start

### One-click start (Windows)

```text
start.bat
```

Starts:

```text
DSH real service   9000
Django backend     8000
Vite frontend      5173
```

Stop:

```text
stop.bat
```

Restart:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -Restart
```

Logs:

```text
.runtime/logs/
```

### Manual start

Backend:

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
python manage.py migrate
python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

Frontend:

```bash
cd frontend
pnpm install
pnpm dev
```

### Optional services

```bash
docker compose up -d
```

Includes PostgreSQL, Redis, and MinIO.

## 5. Default entry points

```text
Platform login:     http://127.0.0.1:5173/login
Admin console:      http://127.0.0.1:5173/admin
Runtime:            http://127.0.0.1:5173/run/{appCode}/...
App login:          http://127.0.0.1:5173/auth/{appCode}/login
App registration:   http://127.0.0.1:5173/auth/{appCode}/register
Workflow designer:  http://127.0.0.1:5173/workflow/design/{appId}
App settings:       http://127.0.0.1:5173/admin/apps/{appId}/settings
App services:       http://127.0.0.1:5173/admin/apps/{appId}/services
```

Demo account:

```text
username: admin
password: admin123
```

> Change the default credentials before production deployment.

Demo application:

```text
name: MiWebProcess Enterprise Admin
code: mi-admin
id:   112
```

## 6. Build and checks

Frontend:

```bash
cd frontend
pnpm typecheck
pnpm build
npm run test:e2e
```

Backend:

```bash
cd backend
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

Playwright end-to-end coverage:

```text
login / app list / app detail
notification center
marketplace signing and sandbox badges
designer load / property panel
recorder and replay
block library
mobile panels
lock conflict
two-user schema sync
```

## 7. Repository layout

```text
backend/
  appcore/        apps, members, notifications, templates
  pages/          pages, schema, blocks, versions, operation log
  components/     component registry
  workflows/      workflows and approvals
  enterprise/     enterprise console, backups, audit
  collab/         comments, node locks, lock queue
  market/         component / block marketplace, signing
  realtime/       WebSocket, channel layer
  runtime/        application runtime
frontend/
  src/designer/   page designer
  src/engine/     renderer, bindings, states
  src/builtin/    built-in components
  src/views/      admin and runtime pages
  e2e/            Playwright
docs/
```

## 8. Known limitations

- CRDT is node-level LWW, not field-level CRDT.
- Operation log is append-only and not auto-archived.
- Redis 5 requires `?protocol=2`; Redis 7 is recommended.
- Block rollback restores drafts only; it does not republish pages.
- Sandbox components support custom-element ESM only and require CORS.
- Signing covers metadata / URL / schema, not remote ESM bytes.
- Variant style data binding is not supported.

## 9. License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
