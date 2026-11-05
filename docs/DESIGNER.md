# 页面设计器（企业版）

## 能力总览

### 画布与布局
- 流式 / 自由布局；网格吸附、拖动、缩放。
- 智能参考线：页面边缘、中心、兄弟节点对齐。
- 多选框选、多节点整体移动。
- 左 / 中 / 右、上 / 中 / 下对齐；水平 / 垂直等距分布。
- 组合 / 取消组合；锁定 / 隐藏；大纲拖拽排序与移入容器。
- 快捷键：保存、撤销、重做、删除、复制、粘贴、快捷复制。

### 响应式
- 桌面 1200 / 平板 768 / 手机 375。
- `node.responsiveLayout` 保存平板 / 手机独立位置和尺寸。
- 运行时按视口宽度应用设备布局。
- 断点样式覆盖、设备隐藏、入场动画。
- 平板 / 手机布局面板：复制桌面、应用、清除覆盖。

### 复用区块 / 共享布局
- `PageBlock` 可复用区块；承载页面类型 `fragment`。
- 从当前选区创建区块，插入 `wp-block` 引用。
- 区块 ID 前缀隔离，避免节点 ID / CSS 冲突。
- 区块递归深度限制 8 层，检测循环。
- fragment 页面从发布包、sitemap、普通页面列表排除。

### 区块版本与市场流水线
- `PageBlockVersion` 保存 schema 快照；区块创建 / 更新自动生成版本。
- fragment 页面在设计器保存时自动补版本（跳过无变化）。
- `GET/POST /api/blocks/{id}/versions/`、版本详情、草稿回滚。
- `GET /api/blocks/{id}/versions/diff/?from=&to=` 结构化版本差异。
- `POST /api/blocks/{id}/publish-market/` 发布 / 更新市场条目。
- 区块库提供「版本」「发布市场」「对比」「回滚」。

### 数据与交互
- 可视化绑定：页面变量、数据源、数据模型、表单字段。
- 字段形状、类型兼容提示、真实 / 模拟预览、表达式模式。
- 结构化绑定与模板表达式兼容。
- 事件动作摘要、条件、动作排序、目标校验。
- 组件状态：hover / active / focus / disabled 样式与 props 覆盖。
- 组件变体：新增、复制、删除、启用；变体 props / style 覆盖基础值。

### schema 操作日志 / CRDT-style 合并
- `PageSchemaOperation` append-only：node.upsert / node.delete / schema.meta。
- 每节点 Lamport clock；counter 大者胜，相同 counter 按 clientId 字典序。
- `__oplog__` 持久化节点 clock 与 tombstone，支持重放/删除/复活。
- API：`GET/POST /api/pages/{id}/schema/ops/`；WS：`/ws/designer-ops/{pageId}/`。
- 前端 diff/merge/rebase；全量 schema 保存仍负责持久化与版本冲突。

### Redis Channel Layer / 多 worker
- `REDIS_URL` 配置后使用 `channels_redis.core.RedisChannelLayer`，共享 group 广播与缓存。
- 未配置时保持 InMemoryChannelLayer，仅单进程。
- `python manage.py check_realtime_channels --ping` 诊断。
- 多 Daphne 进程 / uvicorn workers 需同一 REDIS_URL；详见 `docs/deployment/Redis.md`。

### 锁等待队列与超时
- 锁被占用时服务端排队，广播 queue position / timeoutAt。
- 释放/过期自动授予下一位；客户端 toast 显示等待位置与倒计时，可取消。
- 默认队列 30s、每节点最多 50 人；超时返回 lock-timeout。

### 区块版本可视化预览
- 版本对比支持 结构 / 视觉 / 列表 三视图。
- 视觉视图按 snapshot layout 绘制只读双栏迷你画布；长页面回退为缩进流。
- 点击节点查看字段 diff；最多 200 节点/侧。

### 变体数据绑定
- 变体 props 支持 `{__binding__: ...}` 与 `{{...}}` 表达式；运行时先合并变体再走绑定解析。
- 设计态按页面变量预览，缺失时使用 defaultValue / 占位符。
- 变体 style 绑定不支持，会在 UI/控制台提示。

### Playwright 双用户 / 锁冲突
- `frontend/e2e/lock-conflict.spec.ts`：远程锁阻止拖动、徽标清除、布局不变。
- `frontend/e2e/schema-sync.spec.ts`：两个上下文同页编辑，B 无刷新收敛。
- `npm run test:e2e` 覆盖 11 条设计器/后台回归。

### 实时协作
- `/ws/designer-lock/{pageId}/` 服务端原子节点锁，TTL 90s，心跳续期。
- 锁冲突返回 `lock-denied`；断开 / 释放广播 release。
- `sessionStorage` 保存 sessionId 与持有节点，重连恢复。
- `NodeLockOverlay` 显示远程锁徽标、用户名、描边；不阻塞交互。
- schema 实时同步：`/ws/designer-sync/{pageId}/` 广播 schema，带 revision。
- 保存冲突：schema PUT 支持 `base_revision`，不一致返回 409。

### 评论与通知
- 页面 / 节点评论；线程回复最多 3 层；删除为软删除并保留回复。
- 评论面板：回复、折叠、已删除占位、@ 提及高亮、`?comment=` 定位。
- 评论通过 `designer-comments/{pageId}` 实时刷新。
- `/admin/notifications` 通知中心：未读筛选、标记已读 / 全部已读、跳转评论。

### 素材与市场
- 应用素材库：上传、搜索、图片 / 文件预览、插入图片。
- `/admin/market`：组件 / 区块市场、搜索、分类、安装、签名、沙箱预览。
- 组件签名：SHA-256 + HMAC-SHA256；安装必须验签且未篡改。
- 沙箱：`sandbox="allow-scripts"` iframe，无 same-origin；父页面不 import/eval 远端代码。
- 组件安装写入 `ComponentMeta`，`source="custom-sandbox"`，元数据在 `payload_schema["x-wp-market"]`。

### 超大页面
- 大纲超过 150 行启用 30px 固定行高虚拟滚动；500 节点以上提示。
- 画布 free 布局 >300 节点裁剪视口外叶子 / 顶层子树。
- flow 布局 >500 节点使用 `content-visibility` / `contain-intrinsic-size`。
- 保留选中链、祖先、命名插槽、无 layout 节点；HUD 显示 mounted/total/culled。

### 录制与调试
- 操作录制：schema 快照、动作标签、100 条 / 8MB 上限、导出 / 导入 / 会话恢复。
- 回放：跳转、速度、暂停 / 继续 / 停止；整次回放合并为一条撤销命令。
- 交互调试：动作 / 绑定 / 事件 / 错误 / 导航 / 数据；筛选、暂停、导出。

### 发布质检
- 发布前质量与可访问性检查；错误二次确认。
- 区块自动随宿主页面发布；区块失败不阻塞宿主页面。
- 发布报告：published / skipped / missing / cycles / depth-limited blocks。

## 已知边界

- 实时 schema 同步为广播 + revision MVP；断线期间未保存远端变更可能丢失。
- 保存冲突返回 409，需要设计器弹出选择「重新加载 / 覆盖」。
- 服务端锁 TTL 90s；锁申请必须等待授权后才能拖动。
- 区块回滚只恢复草稿，不自动重发已发布页面。
- 画布裁剪会卸载视口外顶层子树，重新进入时局部状态可能重置。
- 评论最多 3 层；通知仅站内，不发送邮件 / IM。
- 市场签名覆盖 URL / 元数据 / schema，不覆盖远端 ESM 字节；HMAC 为对称签名。
- 沙箱要求 `source_url` 支持 CORS；只支持 custom element ESM，不支持 slots / React。
- 录制快照超限会截断 / 省略，回放可能近似。

## 关键文件

```text
frontend/src/designer/DesignerView.vue
frontend/src/designer/components/CanvasArea.vue
frontend/src/designer/components/OutlinePanel.vue
frontend/src/designer/components/PropertyPanel.vue
frontend/src/designer/components/BlockLibrary.vue
frontend/src/designer/components/CommentsPanel.vue
frontend/src/designer/lock-session.ts
frontend/src/designer/schema-sync.ts
frontend/src/designer/recorder.ts
frontend/src/engine/NodeRenderer.vue
backend/pages/block_services.py
backend/pages/block_views.py
backend/collab/
backend/market/
```

## 测试

```text
frontend: vue-tsc --noEmit, vite build
frontend: canvasVirtualization / virtualList / recorder-history selftest
frontend: Playwright e2e
backend: pages.tests_block_versions, pages.tests_blocks, pages.tests_block_publish
backend: collab.tests, collab.tests_locks, market.tests_signing
```
