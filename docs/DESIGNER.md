# 页面设计器（企业版）

## 已实现

### 画布与布局
- 流式 / 自由布局，网格吸附、拖动、缩放。
- 智能参考线：页面边缘 / 中心 / 兄弟节点对齐吸附。
- 多选框选、多节点整体移动。
- 左 / 中 / 右、上 / 中 / 下对齐；水平 / 垂直等距分布。
- 组合 / 取消组合。
- 锁定、隐藏、层级与结构控制。
- 大纲树拖拽排序、移入容器、循环引用保护。
- 快捷键：保存、撤销、重做、删除、复制、粘贴、快捷复制。

### 响应式
- 桌面 1200 / 平板 768 / 手机 375 设备切换。
- `node.responsiveLayout` 保存平板/手机独立位置和尺寸。
- 运行时按视口宽度自动应用设备布局。
- 断点样式覆盖、设备隐藏、入场动效。
- 平板/手机布局面板：复制桌面、应用、清除覆盖。

### 复用区块 / 共享布局
- `PageBlock` 可复用区块；承载页面类型 `fragment`，可在现有设计器中编辑。
- 从当前选区创建区块，插入 `wp-block` 引用。
- 修改区块后，引用页面自动读取最新区块内容。
- 区块 ID 前缀隔离，避免节点 ID / CSS 冲突。
- 区块递归深度保护（8 层）。
- 区块 fragment 页面从发布 bundle、sitemap、普通页面列表中排除。

### 数据与交互
- 可视化绑定选择器：页面变量、数据源、数据模型、表单字段。
- 字段形状、类型兼容提示、真实/模拟预览、表达式模式。
- 结构化绑定和模板表达式兼容。
- 事件动作摘要、条件、动作排序、目标校验。
- 质检与发布前检查。

### 评论与协作
- 页面级 / 节点级评论。
- 评论解决 / 重新打开、删除、定位节点。
- 右侧面板“评论”标签。

### 素材
- 应用素材库：上传、搜索、图片/文件预览。
- 选中素材插入图片到画布。
- 复用区块库、素材库、变量、协同、质检统一在左/右面板。

### 服务端强制锁与会话恢复
- `/ws/designer-lock/{pageId}/` 服务端原子获取节点锁（唯一约束 + select_for_update）。
- 锁 TTL 90s，心跳续期；断开/释放自动广播。
- `sessionStorage` 保存会话 ID 和持有节点，重连后自动恢复/重新申请。
- 锁冲突由服务端返回 `lock-denied`，客户端显示他人锁并阻止拖动。

### 区块自动发布
- 普通页面发布时递归发现 `wp-block` 引用，自动发布承载 fragment 页面。
- 支持嵌套区块、缺失/循环/深度限制报告；区块发布失败不阻塞宿主页面。
- 管理命令 `republish_referenced_blocks`。

### 组件 / 区块市场
- `/admin/market`：组件与区块市场，搜索、分类、安装到目标应用。
- 区块安装复用 PageBlock/create_block；组件安装写入 ComponentMeta 并刷新注册表缓存。
- 支持草稿 / 发布 / 私有可见性、安装计数。

### 超大页面虚拟化
- 大纲超过 150 行启用固定 30px 行高虚拟滚动；500 节点以上显示非阻断提示。
- 保留多选、拖拽排序、锁定/隐藏、键盘导航。

### 操作录制 / 回放
- 录制 schema 快照和操作标签，100 条 / 8MB 上限，支持导出/导入/会话恢复。
- 回放支持跳转、速度、暂停/继续/停止。
- 入口：设计器头部「录制」抽屉。

### 实时评论与 @成员
- 评论通过应用 WebSocket topic `designer-comments/{pageId}` 实时刷新。
- `@username` 解析并生成站内通知；无效提及只提示不通知。
- 支持提及候选、提及高亮和「提到了你」标记。

### 服务端强制节点锁与会话恢复
- `ws/designer-lock/{pageId}/`：服务端原子获取/释放/续期节点锁，TTL 90s。
- 锁冲突返回 `lock-denied`；断开/释放广播 `lock` release。
- sessionStorage 按页面保存 sessionId 与持有节点；重连自动恢复持有锁。

### 区块随宿主页面自动发布
- 发布普通页面时递归发现 wp-block，自动发布承载 fragment 页面。
- 支持嵌套、缺失、循环、深度限制报告；区块失败不阻塞宿主发布。

### 组件 / 区块市场
- `/admin/market`：组件与区块市场，搜索/分类/安装到应用。
- 区块安装复用 PageBlock；组件安装写入 ComponentMeta 并刷新缓存。
- 支持草稿、发布、私有可见性和安装计数。

### 超大页面虚拟化
- 大纲超过 150 行启用 30px 固定行高虚拟滚动。
- 500 节点以上显示非阻断提示；保留多选、拖拽、锁定/隐藏、键盘导航。

### 操作录制与回放
- 录制 schema 快照/操作标签，100 条/8MB 上限。
- 支持导出/导入/会话保存、跳转、速度、暂停/继续/停止回放。
- 设计器头部「录制」抽屉。

### 实时评论与 @成员
- 评论通过应用 WebSocket topic `designer-comments/{pageId}` 同步。
- `@username` 解析、候选、高亮、站内通知；无效提及不通知。
- 评论面板支持提及标记和「提到了你」。

### 市场组件签名与沙箱
- MarketItem 保存 `code_hash`、HMAC-SHA256 `signature`、`signed_at`、`signer`、`sandboxed`、`policy`。
- `POST /api/market/items/{id}/sign/` 服务端签名；组件安装必须验签且未被篡改。
- 沙箱组件通过 `sandbox="allow-scripts"` 的 iframe 运行，父页面不 import/eval 远端代码；props/事件走 postMessage。
- 签名覆盖 URL/元数据/schema，不覆盖远端 ESM 字节；source_url 需 CORS。

### 区块版本与市场流水线
- `PageBlockVersion` 保存区块 schema 快照；区块创建/更新自动生成版本。
- `GET/POST /api/blocks/{id}/versions/`、版本详情、草稿回滚。
- `POST /api/blocks/{id}/publish-market/` 将区块发布/更新到市场，payload 可直接安装。
- 区块库 UI 提供「版本」「发布市场」。

### 画布大规模虚拟化
- free 布局 >300 节点裁剪视口外叶子/顶层子树；flow >500 节点使用 content-visibility。
- 保留选中链、祖先、命名插槽、无 layout 节点；HUD 显示 mounted/total/culled。
- 被裁节点不在 DOM，快速滚动/拖拽自动滚动时可能短暂空白。

### 评论线程与通知中心
- PageComment 支持 parent/root/depth/deleted，最多 3 层回复；删除为软删除并保留回复。
- 评论列表线程树、回复 composer、折叠/展开、`?comment=` 定位。
- `/admin/notifications` 通知中心：未读筛选、标记已读/全部已读、跳转页面评论。

### 录制回放与撤销栈
- 回放默认以单条历史命令写入撤销栈（`replayHistoryMode: "single"`）。
- 回放中止提交部分结果；`jumpTo` 每次生成单条命令；`"none"` 保留旧行为。

### 多用户锁节点徽标
- NodeRenderer 在画布上挂载 `NodeLockOverlay`：远程节点显示锁图标、用户名、彩色描边。
- 只显示他人锁；pointer-events none，不阻塞选择/拖拽；支持缩放反向缩放。

### 实时协作与调试
- 设计器复用应用 WebSocket 频道：在线成员、远程光标、选区、节点编辑锁。
- 在线头像 / 连接状态 / 远程锁定数量。
- 远程锁节点禁止本地拖动。
- 交互调试面板：录制动作 / 绑定 / 事件 / 错误 / 导航 / 数据事件，支持筛选、搜索、暂停、清空、导出 JSON。
- 移动端设计器：左/右面板变为抽屉，画布可独立使用。

### 发布质检
- 发布前质量/可访问性检查：空容器、图片地址、链接、按钮文本、表单 label、重复 ID、悬空引用、循环、不可达节点、低对比度、固定宽度溢出、Meta、隐藏必填、深层树、节点数、自由布局越界/重叠。
- 右栏“质检”面板，按严重级别过滤，点击定位节点。
- 发布对话框显示错误/警告；存在错误时二次确认。

## 已知边界
- 实时协作基于应用 WebSocket 中继；节点锁由客户端协商，不是服务端强制事务锁。
- 远程光标坐标采用设计器画布区域坐标，缩放/滚动极大时可能有偏差。
- 区块样式/布局属性不会自动套到 fragment 根节点；区块内部使用自己的布局。
- 区块 code 重命名不会自动重写旧引用。
- 响应式覆盖目前针对自由布局的位置/尺寸；流式布局依靠断点样式。
- 对比度检查仅在同节点显式声明文字色与背景色时生效。
- PWA 仍无离线 Service Worker。

## 关键文件
```text
frontend/src/designer/DesignerView.vue
frontend/src/designer/components/CanvasArea.vue
frontend/src/designer/components/OutlinePanel.vue
frontend/src/designer/components/BlockLibrary.vue
frontend/src/designer/components/CommentsPanel.vue
frontend/src/designer/components/QualityPanel.vue
frontend/src/designer/components/MediaLibraryPanel.vue
frontend/src/designer/components/DeviceLayoutPanel.vue
frontend/src/designer/quality.ts
frontend/src/designer/responsive-layout.ts
frontend/src/builtin/components/wp-block.vue
backend/pages/block_services.py
backend/pages/block_views.py
backend/collab/
```
