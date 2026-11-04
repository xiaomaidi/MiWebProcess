# MiWebProcess 企业版

Apache-2.0 企业能力扩展。核心平台保持开源，企业能力按应用隔离。

## 已交付

### 数据与表单
- 35+ 字段类型：文本、富文本、邮箱、手机号、URL、单选/多选、标签、整数、小数、金额、百分比、日期时间、时长、引用/多引用、用户、部门、图片、附件、多附件、签名、地理位置、条码、评分、颜色、JSON、自动编号、公式、创建/更新时间。
- 多附件：`attachments` 字段保存 URL 数组，单记录最多 20 个；表单支持多选上传、进度、删除，表格显示前 3 个附件。
- 关联记录：`reference` / `references` 使用远程搜索、分页加载和已选标签保留。
- 用户/部门选择器：从组织目录加载。
- 地图选点：Leaflet + OpenStreetMap，保存 `{lat, lng}`。
- 签名板：Canvas 手写，保存 PNG Data URL。
- 公式字段：安全 AST 求值，支持算术、比较、逻辑、`round/min/max/abs/len/sum`。
- 公式聚合：`sum_related` / `count_related` / `avg_related` / `min_related` / `max_related`，限定当前应用内，最多 5000 行。

### 导入导出
- CSV / XLSX 导入：表头支持字段名或中文 label，`append` / `upsert`，最多 20MB / 5000 行，逐行错误报告。
- CSV / XLSX 导出：UTF-8 BOM，字段中文表头。
- 打印 / PDF：打印友好 HTML，浏览器另存 PDF。

### 运维
- 企业运维控制台：数据库/缓存/Broker 健康、应用/用户/记录/存储 KPI、审计、失败任务/Webhook、发布失败、备份。
- 数据库备份：列表与创建，支持包含媒体；仅平台管理员。
- 通知：站内信、邮件、Webhook；通知模板/日志/消息中心。
- 定时任务：Cron 到期执行、手动执行、Payload、失败状态；通知模板和 Webhook 广播处理器。
- Webhook 投递记录。
- API Token。

### 企业登录
- 应用级 OpenID Connect SSO Provider 配置。
- OAuth2 Authorization Code + PKCE、state、nonce、ID Token 校验、issuer/邮箱域名限制。
- 自动创建用户与默认角色；平台 JWT 与现有登录兼容。
- 登录页 SSO 按钮与 `/sso/callback` 回调页。
- client_secret 加密落库，API 永不回显。

### 移动端与品牌
- PWA manifest / 主题色 / 图标。
- 管理后台移动端抽屉导航。
- Apache-2.0 许可证与 NOTICE。

## 配置入口

- 企业运维：`/admin/enterprise`
- 应用认证 / SSO：`/admin/apps/{id}/auth`
- 应用服务：`/admin/apps/{id}/services`
- 导入导出：`/admin/models/{id}`
- 备份 API：`/api/enterprise/backups/`
- SSO 公开流程：`/api/auth/sso/{appCode}/{providerSlug}/start/`

## 环境变量

- `FRONTEND_URL`：SSO 回跳的前端地址，例如 `http://127.0.0.1:5173`。
- `ENTERPRISE_BACKUP_MAX_DB_BYTES` / `ENTERPRISE_BACKUP_MAX_MEDIA_BYTES`：备份体积上限。

## 已知边界

- 文件存储默认本地 `media/`；生产建议切换到 S3/MinIO。
- SSO 目前为通用 OIDC；企业微信/钉钉需再加适配层。
- 公式聚合在应用内内存计算，适合常规业务规模。
- PDF 走浏览器打印，不生成二进制 PDF。
- 导入在单事务内逐行校验，超大文件请拆分。
