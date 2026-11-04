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

### 发布质检
- 发布前质量/可访问性检查：空容器、图片地址、链接、按钮文本、表单 label、重复 ID、悬空引用、循环、不可达节点、低对比度、固定宽度溢出、Meta、隐藏必填、深层树、节点数、自由布局越界/重叠。
- 右栏“质检”面板，按严重级别过滤，点击定位节点。
- 发布对话框显示错误/警告；存在错误时二次确认。

## 已知边界
- 实时多人光标/在线状态尚未实现；当前提供评论协作和保存冲突检测。
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
