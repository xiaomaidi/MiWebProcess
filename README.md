# MiWebProcess

> 一个可视化、多应用的低代码建站与业务平台：拖拽页面、配置数据模型、连接工作流，再用 AI Agent 辅助修改。
>
> 目标：**平台内核开发一次，应用只配置，不重复写代码。**

---

## 1. 项目简介

MiWebProcess 是一个面向内部管理系统、客户门户、数据看板和表单应用的开发平台。

核心能力：

- 页面可视化搭建；
- 数据模型与动态记录 CRUD；
- 应用级登录、注册、成员和权限；
- 应用级工作流、审批面板和审批中心；
- ECharts 图表、WebSocket 实时数据；
- 应用级文件、通知、API Token、Webhook 和定时任务；
- AI Agent 读取页面、生成修改提案、创建模型和流程；
- 应用蓝图导出、导入和克隆。

一个平台可以承载多个独立应用。每个应用拥有自己的：

```text
页面
数据模型
成员与角色
登录配置
工作流
文件目录
通知模板
API Token
Webhook
定时任务
```

---

## 2. 技术栈

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
```

---

## 3. 快速启动

### 3.0 一键启动

Windows 双击：

```text
start.bat
```

会启动：

```text
DSH 真实服务 9000
Django 后端 8000
Vite 前端 5173
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

### 3.1 后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt

python manage.py migrate
python manage.py seed_builtin_components

python -m daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

默认接口地址：

```text
http://127.0.0.1:8000
```

### 3.2 前端

```bash
cd frontend
npm install
npm run dev
```

默认页面地址：

```text
http://127.0.0.1:5173
```

### 3.3 可选服务

```bash
# Celery Worker
celery -A config worker -l info

# Celery Beat（定时任务）
celery -A config beat -l info
```

没有 Redis 时，Celery 会使用 eager 模式，Beat 不会作为独立进程运行。

---

## 4. 默认入口

```text
平台登录：       http://127.0.0.1:5173/login
管理后台：       http://127.0.0.1:5173/admin
应用运行：       http://127.0.0.1:5173/run/{appCode}/...
应用登录：       http://127.0.0.1:5173/auth/{appCode}/login
应用注册：       http://127.0.0.1:5173/auth/{appCode}/register
工作流设计器：   http://127.0.0.1:5173/workflow/design/{appId}
应用设置：       http://127.0.0.1:5173/admin/apps/{appId}/settings
应用服务：       http://127.0.0.1:5173/admin/apps/{appId}/services
```

演示账号：

```text
用户名：admin
密码：admin123
```

演示应用：

```text
应用名：MiWebProcess 企业管理后台
应用编码：mi-admin
应用 ID：112
```

---

## 5. 平台核心概念

### 5.1 App

一个 App 是一个独立业务应用。

主要配置：

```text
名称
编码
主题
设计 Token
登录配置
模块开关
成员角色
```

### 5.2 页面

页面由 Schema 描述：

```json
{
  "schemaVersion": 2,
  "rootId": "root",
  "nodes": {},
  "variables": {},
  "layout": {},
  "meta": {},
  "state": {},
  "events": {},
  "lifecycle": {}
}
```

页面支持：

- 草稿与发布版本；
- 页面级路由参数；
- 页面生命周期；
- 页面状态；
- 组件事件；
- 设计 Token；
- 响应式断点。

### 5.3 数据模型

数据模型使用逻辑字段 + JSONB 记录：

```text
DataModel
DataRecord
```

支持：

- 字段类型与校验；
- 行级权限；
- 数据范围；
- 审核流程；
- 工作流绑定；
- 动态查询；
- 导入导出。

### 5.4 工作流

应用级工作流：

```text
WorkflowDefinition
WorkflowInstance
WorkflowTask
```

支持：

- 发起节点；
- 审批节点；
- 条件节点；
- 结束节点；
- 审批通过/驳回；
- 超时提醒；
- 业务记录状态回写；
- 真实审批中心。

数据模型可以绑定流程，绑定后通用记录详情页会自动显示审批面板。

### 5.5 认证

平台账号与应用成员分离。

每个应用可以配置：

```text
是否启用登录
是否要求登录
是否允许注册
是否自动加入
默认角色
邀请码
登录页标题
登录页副标题
Logo
主题色
登录后跳转
允许域名
```

通用路由：

```text
/auth/{appCode}/login
/auth/{appCode}/register
```

### 5.6 应用模块

模块是**能力开关**，不是单纯的菜单开关。

当前模块：

```text
auth
workflow
cms
crm
members
files
notifications
audit
search
reports
api
ai
```

模块关闭后：

- 对应页面返回 403；
- 对应数据模型 API 返回 403；
- 对应服务 API 返回 403；
- 标准 `ElMenuItem` 菜单会过滤。

没有菜单的单页、门户、API 应用，仍然可以通过页面和 API 门禁生效。

### 5.7 应用服务

应用级服务包括：

```text
文件
通知模板
API Token
Webhook
定时任务
```

入口：

```text
/admin/apps/{appId}/services
```

---

## 6. AI Agent

AI Agent 绑定应用和当前页面。

### 6.1 已有工具

```text
get_page
list_components
list_models
search_records
review_page
list_pages
list_datasources
inspect_datasource
preview_datasource
propose_page_patch
propose_page_schema
propose_datasource_import
create_page
create_model
publish_page
publish_app
bind_datasource
rollback_page
create_workflow
```

### 6.2 写操作原则

所有写操作先生成提案：

```text
读取页面
→ 生成修改提案
→ 用户确认
→ 平台校验
→ 写入草稿
→ 发布
```

支持：

- 提案应用；
- 撤销上一次应用；
- 流式输出；
- 停止生成；
- 工具轨迹。

### 6.3 图表规则

图表统一使用 `wp-echarts`。

`props.option` 是完整 ECharts 配置。

`props.chartType` 只是没有 `option` 时的示例类型。

切换图表类型时必须同时修改：

```text
series[].type
xAxis
yAxis
series[].data
```

不能只改 `chartType`。

`props.height` 必须是数字：

```json
{ "height": 300 }
```

不要写：

```json
{ "height": "300px" }
```

AI 提案会做兼容归一化，前端也会兼容字符串高度。

### 6.4 当前限制

```text
单轮最多 5 个 Agent 步骤
长任务可能中断
多提案目前只保留第一个
没有自动截图验证
没有多 Agent 分工
```

下一步重点：

```text
任务规划
多提案与原子应用
变更 diff
应用后自动验证
评估集
应用级记忆
长任务队列
```

---

## 7. 应用蓝图

导出内容包含：

```text
页面
数据模型
示例数据
工作流
数据模型流程绑定
审批面板流程绑定
认证配置
模块开关
设计 Token
通知模板
Webhook
定时任务
成员
```

不导出：

```text
API Token 明文
Token 哈希
Webhook 签名密钥
```

应用设置入口：

```text
/admin/apps/{appId}/settings
```

---

## 8. 目录结构

```text
webprocess/
├─ shared/
│  └─ component-registry.json      # 前后端共享组件注册表
├─ docs/
│  └─ API.md                       # API 约定
├─ backend/
│  ├─ config/                      # settings / urls / asgi / celery
│  ├─ core/                        # 审计、存储、安全、权限
│  ├─ accounts/                    # 用户与 JWT
│  ├─ appcore/                     # 应用、成员、认证、模块、服务
│  ├─ pages/                       # 页面、版本、资产
│  ├─ components/                  # 组件元数据
│  ├─ datasources/                 # 数据源
│  ├─ datamodels/                  # 数据模型与记录
│  ├─ releases/                    # 发布、灰度、回滚
│  ├─ runtime/                     # 运行时页面接口
│  ├─ realtime/                    # WebSocket
│  ├─ workflow/                    # 工作流
│  └─ ai/                          # AI Agent
├─ frontend/
│  └─ src/
│     ├─ api/
│     ├─ engine/
│     ├─ builtin/
│     ├─ designer/
│     ├─ runtime/
│     ├─ views/
│     └─ admin/
└─ README.md
```

---

## 9. 构建与检查

前端：

```bash
cd frontend
npm run build
```

类型检查：

```bash
npx vue-tsc --noEmit
```

后端语法检查：

```bash
cd backend
python -m compileall .
```

迁移：

```bash
python manage.py makemigrations
python manage.py migrate
```

---

## 10. README 编码说明

本项目 README 必须使用 **UTF-8** 保存。

Windows PowerShell 5 的 `Get-Content` / `Set-Content` 默认可能按 ANSI/GBK 处理中文，容易把 UTF-8 中文二次编码成：

```text
鈥? 鍏嶄唬鐮? 锟?
```

这类乱码不是浏览器问题，而是文件编码被错误转换。

正确处理：

- 用 VS Code / Notepad++ 打开并另存为 UTF-8；
- 或使用 PowerShell 7：
  ```powershell
  Get-Content README.md -Encoding utf8 | Set-Content README.md -Encoding utf8
  ```
- 不要用 Windows PowerShell 5 默认编码批量改写中文文件；
- Git 建议配置：
  ```bash
  git config --global core.autocrlf false
  ```

当前 README 已重新以 UTF-8 保存。

---

## 11. 常见问题

### 页面 403

检查应用模块是否关闭：

```text
/admin/apps/{appId}/settings
→ 应用模块
```

### 登录后跳转异常

检查应用认证配置：

```text
/admin/apps/{appId}/auth
```

### 页面显示旧版本

发布后需要刷新，必要时：

```text
Ctrl + F5
```

### 工作流任务为空

确认：

- 流程已发布；
- 数据模型已绑定流程；
- 审批节点角色正确；
- 当前用户属于对应应用。

### 定时任务不执行

确认 Celery Worker 和 Beat 都在运行，且有 Redis。

手动执行：

```bash
cd backend
python manage.py run_app_jobs --force
```

---

## 12. 当前状态

已完成：

```text
页面搭建
数据模型
工作流
应用认证
应用模块
文件 / 通知 / API Token / Webhook / 定时任务
应用蓝图
AI Agent 提案与撤销
```

下一阶段：

```text
Agent 任务规划
多提案与原子应用
变更 diff
应用后自动验证
Agent 评估集
站内信与事件闭环完善
```

---

## 13. 高级 Agent Gateway

高级 Agent 与普通页面助手分开：

```text
普通助手：快速页面编辑
高级 Agent：任务队列、提案、Diff、审批、应用、验证、回滚
```

入口：

```text
/admin/agent
```

### API

```http
GET  /api/ai/agent/tasks/?app_id=112
POST /api/ai/agent/tasks/
GET  /api/ai/agent/tasks/{id}/
POST /api/ai/agent/tasks/{id}/cancel/
POST /api/ai/agent/tasks/{id}/retry/
POST /api/ai/agent/proposals/{id}/apply/
POST /api/ai/agent/proposals/{id}/reject/
POST /api/ai/agent/proposals/{id}/rollback/
```

### 执行器

默认使用平台内置 Agent。

配置外部 DSH 执行器：

```bash
DSH_AGENT_URL=http://127.0.0.1:9000
DSH_AGENT_TOKEN=your-token
DSH_AGENT_TIMEOUT=300
```

DSH 可执行器约定：

```text
POST {DSH_AGENT_URL}/tasks
{
  "task_id": 1,
  "goal": "页面目标",
  "app": {...},
  "page": {"id": 1, "schema": {...}}
}
```

返回：

```json
{
  "proposals": [
    {
      "kind": "page_patch",
      "summary": "修改说明",
      "ops": [
        {"op": "update_node", "node_id": "x", "props": {}}
      ]
    }
  ]
}
```

没有 `DSH_AGENT_URL` 时自动回退到平台内置 Agent。

---

## 14. 高级 Agent 能力状态

已实现：

```text
任务队列
提案中心
Diff 预览
三向 Diff 冲突检测
多提案原子应用
应用草稿 / 应用并发布
拒绝
回滚
重跑
取消
基础审计
每日任务 / Token 配额
Webhook 事件推送
```

本轮新增：

```text
三向 Diff
多提案跨页面原子应用
应用后自动截图
验证失败自动回滚
控制台错误检查
Agent 评估集
Token / 费用配额
Webhook 事件推送
DSH 沙箱状态与容器命令生成
```

自动验证配置：

```text
AGENT_AUTO_VERIFY=1
AGENT_BROWSER_PATH=
AGENT_FRONTEND_URL=http://127.0.0.1:5173
```

自动验证使用草稿预览，不依赖发布 release：

```text
/run/{appCode}/{pagePath}?draft=1
```

DSH 沙箱配置：

```text
DSH_SANDBOX_MODE=http
DSH_SANDBOX_IMAGE=
DSH_SANDBOX_COMMAND=
DSH_SANDBOX_NETWORK=none
DSH_SANDBOX_MEMORY=1g
DSH_SANDBOX_CPUS=1
DSH_SANDBOX_TIMEOUT=300
```

模式：

```text
http    外部 DSH HTTP
process 本地进程沙箱（临时工作区 + 超时 + 精简环境）
docker  容器沙箱
```

进程沙箱样例：

```bash
DSH_SANDBOX_MODE=process
DSH_SANDBOX_COMMAND=python services/dsh_service.py --task-file
```

评估集批量接口：

```http
POST /api/ai/agent/evals/run-all/
POST /api/ai/agent/evals/score-all/
```

当前机器没有 Docker，因此沙箱状态为：

```text
builtin
```

配置 Docker 镜像后自动切换为：

```text
container
```

DSH 执行器目前也可以是外部 HTTP 适配器：


```text
DSH_AGENT_URL
DSH_AGENT_TOKEN
DSH_AGENT_TIMEOUT
```

没有配置时使用平台内置 Agent。

---

## 15. DSH 全自动建站

全自动建站默认优先使用 DSH：

```json
{
  "use_dsh": true
}
```

流程：

```text
用户描述站点
→ DSH 生成 MiWebProcess 蓝图
→ 平台创建应用/模型/内容/页面/工作流
→ 发布
```

DSH 接口：

```http
POST {DSH_AGENT_URL}/build
```

请求：

```json
{
  "prompt": "建一个内容站点",
  "options": {},
  "schema": "miwebprocess-blueprint-v1"
}
```

返回：

```json
{
  "blueprint": {
    "site": {},
    "content": {},
    "pages": []
  },
  "provider": "dsh",
  "model": "dsh-agent",
  "warnings": []
}
```

DSH 不可用时自动回退内置蓝图。

## 真实 DSH Headless

```bash
# 需要 DEEPSEEK_API_KEY
python services/dsh_service.py --port 9000 --real
```

它会调用：

```bash
dsh --profile headless -
```

而不是固定蓝图。

空提案自动重试：

```bash
DSH_AGENT_RETRIES=2
```

## 容器

```bash
docker build -f services/Dockerfile.dsh -t miwebprocess-dsh .
```

或：

```bash
DEEPSEEK_API_KEY=... docker compose -f services/docker-compose.dsh.yml up -d
```

容器内暴露：

```text
http://dsh:9000
```

平台配置：

```bash
DSH_AGENT_URL=http://127.0.0.1:9000
```

## DSH 兼容样例

本地 DSH 兼容样例：

```bash
python services/dsh_service.py --port 9000
```

```bash
DSH_AGENT_URL=http://127.0.0.1:9000
```

样例实现：

```text
GET  /health
POST /build
POST /tasks
```

`/tasks` 用于页面级高级 Agent：

```json
{
  "task_id": 1,
  "goal": "把图表改成柱状图",
  "app": {},
  "page": {"id": 973, "schema": {}}
}
```

返回：

```json
{
  "proposals": [
    {"kind": "page_patch", "summary": "修改说明", "ops": []}
  ],
  "provider": "dsh",
  "model": "dsh-agent"
}
```

它返回与 DSH 相同的蓝图结构，用于验证：

```text
平台全自动建站
→ DSH 蓝图
→ 创建应用/模型/页面
→ 发布
```

生产环境把样例替换成真实 DSH Agent 即可。

AI 助手面板新增“高级 Agent”入口：

```text
AI 页面助手
→ 高级 Agent
→ /admin/agent?app_id=...&page_id=...
```

---

## 16. License

内部项目，未声明开源协议。

---

## License

This project is licensed under the **Apache License, Version 2.0**.

```text
Copyright 2026 MiWebProcess contributors
SPDX-License-Identifier: Apache-2.0
```

You may obtain a copy of the License at:

```text
http://www.apache.org/licenses/LICENSE-2.0
```

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the full text and
attribution information. Third-party dependencies retain their own
copyright notices and licenses.
