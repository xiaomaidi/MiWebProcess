# MiWebProcess API 契约（v1）

- 基址：`/api`（前端 Vite 代理 `/api`、`/ws` → `http://127.0.0.1:8000`）。
- 鉴权：`Authorization: Bearer <access>`（simplejwt）。除「运行时」接口外全部要求登录。
- 统一错误：HTTP 状态码 + `{"detail": string | [string,...]}`。
- 分页：`?page=1&size=20` → 响应 `{count, results, page, size}`（运行时接口不分页）。

## 1. 认证 /api/auth

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/auth/token/ | `{username,password}` → `{access, refresh, user:{id,username,is_superuser}}` |
| POST | /api/auth/token/refresh/ | `{refresh}` → `{access}` |
| GET | /api/auth/user/ | 当前用户 `{id, username, first_name, last_name, email, is_superuser, created_at}` |
| PUT | /api/auth/user/ | 修改 `first_name/last_name/email` |
| GET | /api/auth/users/?q=&page= | 平台管理员：用户列表 |
| POST | /api/auth/users/ | 管理员：`{username,password,first_name,last_name,email,is_superuser}` |
| PUT | /api/auth/users/{id}/ | 管理员：修改资料/`is_superuser`（不能改自己超管位） |
| DELETE | /api/auth/users/{id}/ | 管理员：禁用（`is_active=false`），不能删自己 |

## 2. 应用 /api/apps

对象 `App`：`{id, name, code, description, owner_id, status: draft|published|archived, version, created_at, updated_at}`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/apps/?q=&status=&page= | 列表（含我是成员的；平台管理员全部） |
| POST | /api/apps/ | `{name, code, description}` → 201；创建者成为 owner |
| GET/PUT/PATCH | /api/apps/{id}/ | 详情/更新（owner 或平台管理员） |
| DELETE | /api/apps/{id}/ | 归档（`status=archived`） |
| GET | /api/apps/{id}/members/ | 成员列表 `{user_id, username, first_name, last_name, role}` |
| POST | /api/apps/{id}/members/ | `{user_id, role: owner|editor|viewer}` |
| PUT | /api/apps/{id}/members/{user_id}/ | 改 `role` |
| DELETE | /api/apps/{id}/members/{user_id}/ | 移除 |

行级权限：非成员不可访问应用下任何资源；owner 可管理成员与发布；editor 可编辑草稿/页面/数据源/模型；viewer 只读。

### 页面（嵌套于应用 + 独立路由）

对象 `Page`：`{id, app_id, name, path, type: page|layout|popup, status: draft|published|archived, version, schema_version, thumbnail_url, current_version_id, created_at, updated_at}`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/apps/{id}/pages/?page= | 页面列表 |
| POST | /api/apps/{id}/pages/ | `{name, path, type}` → 201；`path` 为单段 slug，应用内唯一 |
| GET | /api/pages/{id}/ | 详情 |
| PUT/PATCH | /api/pages/{id}/ | 改 `name/path/type/thumbnail_url` |
| DELETE | /api/pages/{id}/ | 删除草稿（已发布快照保留） |
| GET | /api/pages/{id}/schema/ | `{schema: PageSchema}`（草稿） |
| PUT | /api/pages/{id}/schema/ | `{schema: PageSchema}` → 校验（警告不阻塞）、`version+1`、WS 广播 `draft_saved` |
| POST | /api/pages/{id}/publish/ | `{changelog?}` → 严格校验 → 创建 `PageVersion` → 返回 `{page_version}` |
| GET | /api/pages/{id}/versions/?page= | 版本列表（新→旧） |
| POST | /api/pages/{id}/versions/{version}/rollback/ | 将该快照载入草稿（`version+1`） |

`PageVersion`：`{id, page_id, version, schema, schema_version, publisher_id, published_at, changelog}`

## 3. 组件 /api/components

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/components/?category=&enabled=&q= | 元数据列表 |
| PUT | /api/components/{id}/ | 更新元数据（平台管理员或组件 owner）；版本号变更自动写 `ComponentVersion` |
| GET | /api/components/registry/ | 完整注册表 JSON（与 `shared/component-registry.json` 同构，运行时配置用） |
| GET | /api/components/{id}/versions/?page= | 版本历史 |
| POST | /api/components/custom/ | `{name, label, source}`（Vue SFC 源码）→ 建 meta+version，Celery 静态校验任务 |
| GET | /api/components/{id}/versions/{version}/source | 自定义组件源码（运行时浏览器端编译用） |
| POST | /api/components/{id}/upgrade/ | `{version}` 批量升级：把含该组件的草稿 schema 的 `componentVersion` 升级（人工确认后由前端调） |

元数据字段：`{id, name, label, type: basic|business|layout, category, version, props_schema, default_props, events, slots, accept_children, icon, is_custom, source_url, is_enabled, updated_at}`

## 4. 数据源 /api/datasources（嵌套 /api/apps/{id}/datasources/ 创建）

对象 `DataSource`：`{id, app_id, name, type: rest|sql|static, config, transform, test_status: unknown|ok|fail, last_test_at, created_at, updated_at}`
`config` 响应中**永远脱敏**（`token/password/username` → `***`）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/apps/{id}/datasources/ | 列表 |
| POST | /api/apps/{id}/datasources/ | `{name, type, config, transform?}` |
| GET/PUT/PATCH | /api/datasources/{id}/ | 详情/更新（config 增量合并，`***` 占位保留原值） |
| DELETE | /api/datasources/{id}/ | 删除 |
| POST | /api/datasources/{id}/test/ | 测试连接 → `{ok, message, latency_ms}` |
| POST | /api/datasources/{id}/query/ | `{params?}` → `{data, from_cache, cached_at}`；GET 结果缓存 60s，非 GET 不缓存 |

`config` 结构：
- rest：`{url, method: GET|POST|PUT, headers:{}, auth_type: none|bearer|basic, token?, username?, password?, body?, data_path?, response_map?, flatten?, timeout?}`
- sql：`{query}`（仅允许 SELECT；`{param}` 占位参数化，防注入）
- static：`{value}`

`transform`：`{type: map|pick|list, config}` 可选结果整形。

## 5. 数据模型 /api/models（嵌套 /api/apps/{id}/models/ 创建）

`DataModel`：`{id, app_id, name, fields: [{name,type: string|number|boolean|date|json, required, default, description}], relations: [{name, target_model, field, type: one_to_many|many_to_one}], indexes: [{fields: []}], created_at, updated_at}`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/apps/{id}/models/ | 列表/创建 |
| GET/PUT/DELETE | /api/models/{id}/ | 详情/更新/删除（连同记录） |
| GET | /api/models/{id}/records/?field__eq=&field__ne=&field__contains=&field__gt=&field__lt=&q=&sort=&order=&page= | 记录（JSONB 动态过滤） |
| POST | /api/models/{id}/records/ | `{data}` → 校验必填/类型 |
| GET/PUT/PATCH | /api/models/{id}/records/{rid}/ | 记录详情/更新（`{data}`） |
| DELETE | /api/models/{id}/records/{rid}/ | 删除 |
| POST | /api/models/{id}/records/batch/ | `{ids: []}` 批量删除 |

记录对象：`{id, data, created_at, updated_at, created_by}`

## 6. 发布 /api/releases

`Release`：`{id, app_id, version, status: active|previous|archived, traffic_ratio, previous_release_id, bundle_url, page_versions: {page_id: page_version_id}, changelog, created_at}`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/apps/{id}/releases/ | `{changelog?}` → 逐页校验（未发布的页随本次发布补建快照）→ 新 active release；旧 active → previous |
| GET | /api/apps/{id}/releases/?page= | 列表 |
| GET | /api/releases/{id}/ | 详情 |
| PUT | /api/releases/{id}/traffic/ | `{traffic_ratio: 0..100}`（灰度） |
| POST | /api/releases/{id}/rollback/ | 新建 release 指向其 previous 的 `page_versions` |
| GET | /api/releases/{id}/tasks/ | 任务列表 |
| GET | /api/releases/tasks/{task_id}/ | `{id, status: pending|running|success|failed, log, created_at}` |

## 7. 运行时（公开）

`GET /api/runtime/{app_code}/{path}`
→
```json
{
  "app": {"code": "demo", "name": "演示应用"},
  "page": {"id": 3, "name": "首页", "path": "home"},
  "page_version": {"version": 4, "schema": {...PageSchema}, "published_at": "..."},
  "config": {
    "components": [ ...注册表条目(含 props_schema/default_props/events/slots/accept_children) ],
    "datasources": [{"id":1, "name":"users", "type":"rest", "public_config": {}}]
  }
}
```
不存在 → 404。灰度：`traffic_ratio<100` 且存在 previous 时，按比例随机取前/后版本快照。

## 8. 审计 /api/audit-logs

`GET /api/audit-logs/?app_id=&user_id=&object_type=&action=&start=&end=&page=`
→ 记录：`{id, user_id, username, app_id, object_type, object_id, action: create|update|delete|publish|login|..., before, after, ip, created_at}`
权限：平台管理员全部；应用成员仅本应用。

## 9. WebSocket `/ws/{app_id}/?token=<access>`

- 连接即加入 `app_{app_id}` 组（JWT 校验失败 → 拒绝）。
- 服务端 → 客户端：
  - `{"type":"draft_saved","page_id":1,"user":"u","version":12,"ts":...}`
  - `{"type":"presence","user_id":..,"username":"u","ts":..}`
  - `{"type":"task_update","task_id":..,"status":"success","ts":..}`
- 客户端 → 服务端：`{"type":"presence","username":"u"}` 广播给同组。

## 10. 页面 Schema 结构（PageSchema）

```jsonc
{
  "schemaVersion": 1,
  "rootId": "n1",
  "nodes": {
    "n1": {
      "id": "n1",
      "type": "wp-container",          // 组件注册表 name
      "componentVersion": "1.0.0",
      "props": {"gap": 8},            // 字面量；或 {"__binding__": DataBinding}
      "style": {"width": "600px"},    // 可选 CSS 声明
      "customCss": "",                // 可选自定义类（运行态 .wp-node-n1）
      "events": {"click": [ ActionStep ]},   // 动作链
      "children": ["n2", "n3"],       // 流式子节点 id 列表
      "slots": {"header": ["n9"]},    // 命名单元子节点（仅组件声明的槽）
      "condition": {"expr": "user.admin"},   // 条件渲染（可空）
      "dataBinding": {                 // 数据绑定（可空）
        "source": "datasource|variable|model",
        "ref": "ds-id 或 变量名 或 model-id",
        "field": "rows",               // 结果内取数路径（a.b.c，可含 [*] 取全部）
        "loopVar": "item",             // 列表绑定时子树作用域变量名
        "defaultValue": [],
        "transform": ""                // 可选表达式，对取数结果再求值
      }
    }
  },
  "assets": {"logo": {"url": "/media/...png", "name": "logo.png", "type": "image"}},
  "variables": {"user": {"value": {"admin": false}, "scope": "global"}},
  "layout": {"mode": "flow|free", "width": 1200, "height": 800, "grid": 8}
}
```

### ActionStep

```jsonc
{"id": "a1", "kind": "setVariable|callDatasource|navigate|openModal|message|record|condition|http",
 "params": {
   "setVariable":  {"name": "x", "value": 1},
   "callDatasource": {"ref": "ds-id", "params": {}},       // 结果存入 variables["ds_{id}"]
   "navigate":     {"path": "/home", "target": "_self"},
   "openModal":    {"nodeId": "n5"},
   "message":      {"type": "success", "text": "ok", "duration": 3000},
   "record":       {"model": "model-id", "op": "create|update|delete", "data": {}},
   "condition":    {"expr": "x > 1"},
   "http":         {"url": "/api/...", "method": "GET", "headers": {}, "body": {}, "resultVar": "res"}
 },
 "then": [ActionStep],   // 仅 condition 有效
 "else": [ActionStep]}
```

运行时变量作用域：`variables`（页面变量）+ `ds_{id}`（数据源结果）+ `loopVar`（循环）+ `form_{id}`（表单值）+ 内置 `page`/`app`。

## 11. 前端内置组件契约

- `frontend/src/builtin/*` 按注册表 `name` 提供组件，`NodeRenderer` 以 `type` 解析。
- 组件通过 `NodeRenderer` 收到：解析后的 `props`（`__binding__` 已求值）、`events` 映射（runtime 下触发即执行 ActionStep 链）、`children/slots`（递归渲染）、`binding`（原始 dataBinding，用于列表 v-for）。
- 表单类组件向祖先 `wp-form` 注册 `{field, value}`（provide/inject），`wp-form` 的 `submit` 事件参数含 `values`。

## 12. v2 注册表与渲染协议

### 12.1 注册表

`shared/component-registry.json` 顶层：`version`、`schemaVersion: 2`、`categories[]`、`style_schema`、`components[]`。
组件字段：`name/label/category/type/version/icon/source/element/is_container/is_form_field/default_children/actions_supported/props_schema/style_schema/default_props/events/slots/accept_children/accepts`。

`source` 取值：`element-plus | native | chart | rich | advanced | legacy | custom`。
- Element Plus 组件：`element` 为实际导出名（如 `ElButton`），运行时按名取组件。
- 原生：`element` 为标签名（`div/img/video/...`）。
- 图表：`chart-*` 统一走 `ChartRenderer`，可传 `option`（ECharts 兼容子集）或 `data/xField/valueField/series`。
- 富文本：`rich-text`、`markdown`、`code-block`。
- 高级：`html/svg/canvas/component-slot/repeater/conditional/portal`。

属性 Schema 的紧凑写法（后端 `components/registry.py` 与前端 `registry-normalize.ts` 同规则归一化）：
```jsonc
"text": ["string", "文字", "按钮"],
"type": ["string", "类型", "primary", {"enum": ["primary","success"], "ui": "select", "g": "外观"}]
```

### 12.2 PageSchema v2 增补

```jsonc
{
  "schemaVersion": 2,
  "meta": {
    "title": "页面标题", "lang": "zh-CN", "favicon": "/media/favicon.ico",
    "seo": {"description": "", "keywords": "", "ogImage": ""},
    "globalStyle": {"cssVars": {"--wp-accent": "#409eff"}, "fontFamily": "sans-serif"},
    "background": {"backgroundColor": "#fff"}
  },
  "customCss": "body { background: #f5f7fa; }",
  "nodes": {
    "n1": {
      "responsive": {"md": {"fontSize": "12px"}, "xs": {"padding": "4px"}},
      "componentVersion": "2.0.0"
    }
  }
}
```
- `responsive` 由 NodeRenderer 编译为 `@media`，作用域 `[data-wp-node="<id>"]`。
- 页面 Meta 在运行态写入 `document.title`、`lang`、favicon、SEO meta 与 CSS 变量。

### 12.3 ActionStep v2

`kind` 新增：`closeModal/openDrawer/closeDrawer/notification/confirm/loop/parallel/tryCatch/delay/setStyle/emit/submitForm/resetForm/download/copy/print/js`。
`condition/confirm/loop/parallel/tryCatch` 使用 `then`、`else`、`catch` 子动作数组。
`js` 仅允许表达式（发布时白名单扫描，禁止语句、`eval`、`new Function`、DOM/网络 API）。
表达式内置函数：`$ds/$state/$form/$user/$now/$uuid/$i18n/$if/$match/$filter/$map/$find/$sum/$len`，并支持 `{{expr}}` 插值。

### 12.4 运行时响应 v2

`GET /api/runtime/{app_code}/{path}` 在原有字段上新增：
```jsonc
{
  "meta": {"title": "...", "seo": {}},
  "registry": {"ElButton": "2.0.0", "...": "..."},
  "style": "页面级 customCss"
}
```
`config.components[]` 同时返回 `source/element/is_container/is_form_field/style_schema/actions_supported` 等字段，运行时可按 registry 懒加载。

> 说明：当前前端未引入 Tiptap/ECharts/DOMPurify 依赖，富文本使用 contenteditable + 安全清洗，图表使用内置 SVG 渲染 ECharts option 的常用子集，HTML 使用自研白名单清洗；接口与字段已按可替换实现预留。

## 13. 组织架构与部门层级权限 `/api/org`

对象 `Department`：`{id,name,code,parent_id,path,level,sort,leader_id,leader_name,description,is_active,member_count,display_path,created_at,updated_at}`。
`path` 为物化路径（`/1/4/9/`），`level` 从 0 开始，子树判定为 `path` 前缀匹配。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/org/departments/?q=&parent_id=&include_inactive= | 部门扁平列表 |
| POST | /api/org/departments/ | 建部门；根部门仅平台管理员，子部门需上级负责人 |
| GET/PATCH/DELETE | /api/org/departments/{id}/ | 详情/编辑/删除（删除级联子部门） |
| POST | /api/org/departments/{id}/move/ | `{parent_id}` 移动子树并重算 path |
| GET/POST | /api/org/departments/{id}/members/ | 成员列表 / 添加 `{user_id,role:leader\|member,title}` |
| PATCH/DELETE | /api/org/departments/{id}/members/{user_id}/ | 改角色 / 移除 |
| GET | /api/org/departments/{id}/subtree/ | 子树 id 与节点（数据范围预览） |
| GET | /api/org/tree/ | 扁平节点（前端自行组树） |
| GET | /api/org/me/ | 我的部门、可见部门、可管理部门、可用匹配 token |
| GET | /api/org/users/?q= | 成员选择器（负责人/平台管理员） |

数据权限（`DataModel`）：
- `data_scope`：`all | owner | dept | dept_and_children`；
- `dept_field`：记录中保存部门的字段名（默认 `dept`，值可为部门 id / code / name）；
- 负责人可见自己的部门 + 全部子部门；普通成员仅本部门；平台管理员不受限；
- 写入时非管理员不能把记录写到不可见部门，缺省自动归属主部门。

应用级组织可见性（`App`）：`department_id` + `department_visible`。开启后，归属部门（含子部门）成员获得 `viewer` 角色；`?scope=member` 会包含这些应用。

## 14. 内容审核 `/api/moderation`

`DataModel` 审核配置：`review_required`（布尔）、`review_roles`（`owner/editor/viewer` 子集，默认 `["owner"]`）。

对象 `ContentReview`：`{id,app_id,model_id,model_name,record_id,status:pending|approved|rejected|cancelled,revision,title,snapshot,record_data,submitted_by_name,submitted_at,reviewed_by_name,reviewed_at,comment,can_approve,can_withdraw,events[]}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/moderation/reviews/?app_id=&status=&model_id=&mine=&q=&page=&size= | 审核队列（普通成员只看自己提交的） |
| GET | /api/moderation/reviews/{id}/ | 详情 + 流转记录 |
| POST | /api/moderation/reviews/{id}/approve/ | `{comment?}` 通过 → 记录 `status=published` 并写索引 |
| POST | /api/moderation/reviews/{id}/reject/ | `{comment}` 必填 → `status=rejected` |
| POST | /api/moderation/reviews/{id}/withdraw/ | 提交人撤回 → `status=draft` |
| POST | /api/moderation/submit/ | `{model_id,record_id,comment?}` 手动送审 |
| POST | /api/moderation/reviews/batch/ | `{ids,action:approve\|reject,comment}` |
| GET | /api/moderation/summary/?app_id= | 各状态计数、可审模型 |
| GET | /api/moderation/policies/?app_id= | 模型级审核配置与待审数 |

流程：编辑保存 → `status=pending` 并生成/复用待审单（revision 递增）→ 通过自动发布或驳回；审核人自己保存内容会直接通过（记录“审核人直接发布”）。走 `POST /api/models/{id}/records/{pk}/publish/` 时，无审核权限的用户会得到 `202 {detail, review}`。

## 15. 搜索索引 `/api/search`

`SearchDocument` 由 `DataRecord` 写入信号增量维护（`transaction.on_commit`），另提供全量重建。
文档字段：标题/摘要/正文/模型/状态/是否公开/URL 路径/内容哈希。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/search/?app_id=&q=&model_id=&page=&size= | 登录态搜索（含私有文档） |
| GET | /api/search/stats/?app_id= | 文档数、公开已发布数、模型分布、最近索引时间 |
| GET | /api/search/suggest/?app_id=&q= | 标题联想 |
| POST | /api/search/rebuild/ | `{app_id}` 全量重建（owner） |
| GET | /api/runtime/{app}/search/?q=&page=&size= | 公开搜索，按标题/摘要/正文打分并返回高亮片段 |
| GET | /api/runtime/{app}/search/suggest/?q= | 公开联想 |

索引为空时运行时搜索会惰性重建一次。命令行：`python manage.py rebuild_search_index [--app code]`。
检索策略：SQL 子串预过滤 + 查询词/标题/摘要/正文加权打分 + 7 天内内容微加权；中文长词在精确匹配不足时回退二元组匹配（≥60% 命中）。

## 16. 实时通道 `/api/realtime`（MQTT + WebSocket）

对象 `RealtimeChannel`：`{id,app_id,name,slug,kind:mqtt|ws|both,topic,description,qos,retain,enabled,message_count}`。
对象 `RealtimeMessage`：`{id,channel_id,topic,payload,direction:in|out,transport, sender,created_at}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/realtime/channels/?app_id= | 通道列表 / 新建 |
| GET/PATCH/DELETE | /api/realtime/channels/{id}/ | 详情 / 编辑 / 删除 |
| POST | /api/realtime/channels/{id}/publish/ | `{payload,qos?,retain?}` 发送（WS + 可选 MQTT） |
| GET | /api/realtime/channels/{id}/messages/?limit=50 | 最近消息 |
| GET | /api/realtime/messages/?app_id=&limit=100 | 应用最近消息 |
| POST | /api/realtime/publish/ | `{app_id,topic,payload,channel_id?}` 按主题发送 |
| GET | /api/realtime/status/?app_id= | MQTT 桥接状态、paho 是否安装、在线人数 |
| POST | /api/realtime/cleanup/ | `{app_id?,keep}` 清理历史（平台管理员） |

环境变量：`MQTT_ENABLED=1`、`MQTT_BROKER_URL=mqtt://host:1883`、`MQTT_USERNAME/MQTT_PASSWORD/MQTT_CLIENT_ID`。
桥接进程：`python manage.py mqtt_bridge [--check]`（未安装 paho 或未配置时自动降级为纯 WebSocket，消息仍落库并广播）。

WebSocket 协议扩展（`/ws/{app_id}/?token=JWT`）：
- 客户端新增 `{"type":"subscribe","topics":["devices/+/telemetry"]}` / `{"type":"unsubscribe",...}` / `{"type":"ping"}` / `{"type":"presence"}`；
- 服务端新增 `{"type":"subscribed","payload":{topics}}`、`{"type":"pong"}`、`{"type":"presence","payload":{count,event}}`；
- 实时消息顶层带 `topic/direction`，服务端按 MQTT 通配符（`+`/`#`）过滤后下发；
- 默认订阅 `#`（全部应用消息），断线自动清理在线计数。

## 17. 截图级 AI 视觉评审 `/api/ai/design/visual-review/`

请求：`{app_id, image: "data:image/png;base64,..." | base64, schema?, page_id?, page_name?, prompt?}`，图片上限 6MB。
响应：`{score, summary, issues:[{level,category,message,suggestion,region}], metrics:{width,height,blank_ratio,contrast,brightness,edge_density,dominant_colors,color_count,blank_grid}, mode:vision|heuristic, model, warnings}`。

- 配置视觉模型（`AI_VISION_MODEL`，或默认模型名含 `gpt-4o/qwen-vl/glm-4v/...`）时走多模态 `image_url`；
- 否则用 Pillow 做像素级体检并与结构评审合并，始终返回可用结论；
- 前端截图由 `designer/screenshot.ts` 把画布 DOM 序列化为 SVG foreignObject → canvas → PNG，无需额外依赖。

## 18. AI 多轮 Agent `/api/ai/agent`

对象 `AiConversation`：`{id,app_id,page_id,title,context,message_count,created_at,updated_at}`；
对象 `AiMessage`：`{id,role:user|assistant|tool,content,tool_name,tool_args,tool_result,proposal,provider,model,created_at}`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | /api/ai/agent/conversations/?app_id= | 会话列表 / 新建（绑定页面） |
| GET/PATCH/DELETE | /api/ai/agent/conversations/{id}/ | 详情（含消息）/ 改标题 / 删除 |
| POST | /api/ai/agent/conversations/{id}/messages/ | `{message}` → `{user_message,assistant_message}` |
| POST | /api/ai/agent/conversations/{id}/apply/ | `{message_id}` 应用消息上的提案 → 新 schema |

工具：`get_page`、`list_components`、`list_models`、`search_records`、`review_page`（只读，直接执行）；
`propose_page_patch`、`propose_page_schema`（写操作只产生提案，用户确认后才落库）。
补丁算子：`update_node / add_node / remove_node / set_meta / set_theme / set_var`。
无 AI Provider 时使用本地规则 Agent（标题/按钮文案、深浅主题、新增按钮、删除节点、页面评审）。
应用提案时服务端会再次校验组件类型与节点引用，并写入 `Page` 草稿（version+1）与审计日志。

## 19. 完整 SSR 水合

构建：
```bash
cd frontend
pnpm build                                              # dist/ 静态资源
pnpm build:ssr                                          # dist-ssr/entry-server.js
cd ../backend
python manage.py ssr_prerender --app demo-portal        # 写入 static_prerender/
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/runtime/{app}/prerender/{path}/ | 优先返回 SSR 快照（含 `data-server-rendered` 与 `window.__WP_SSR__`），无快照回退轻量 SEO 模板 |
| POST | /api/runtime/{app}/ssr/rebuild/ | owner 触发快照生成，返回 `{generated[],errors[]}` |

水合协议：
- 快照文档 `<div id="app" data-server-rendered="true">` 内是 Vue 服务端渲染结果；
- `window.__WP_SSR__ = {url, payload, prefetch}`，`payload` 与运行时页面接口同构，`prefetch` 保存文章详情等预取数据；
- 文章详情快照会额外输出 schema.org `Article` JSON-LD；
- 静态资源默认按同源 `/assets/...` 输出，可用 `SSR_ASSET_BASE` 指向 CDN 或 Vite 开发服务器；
- 浏览器端 `createSSRApp` 水合，`RuntimeView` 直接使用注入 payload 跳过首屏请求，`article-detail` 用预取数据保证 DOM 一致；
- Node 不可用、`dist-ssr` 缺失或渲染失败时后端自动回退，不影响普通 SPA 运行。

## 20. AI 全自动建站 `/api/ai/autobuild`

一条指令创建完整站点：应用 → 内容模型 → 示例内容 → 动态页面（默认 6–9 页）→ 自动评审 →
发布 → 搜索索引 → SSR 快照；可选工作流、实时通道。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | /api/ai/autobuild/ | `{prompt, options?, sync?}` 启动任务；返回 202 + job（`sync=1` 且平台管理员时同步执行并返回 200） |
| GET | /api/ai/autobuild/?status= | 我的最近 20 个建站任务 |
| GET | /api/ai/autobuild/{id}/ | 任务详情：进度、步骤、日志、蓝图、结果 |
| POST | /api/ai/autobuild/{id}/cancel/ | 请求取消（排队中立即取消，执行中在步骤间生效） |

`options` 默认值：

```jsonc
{
  "sample_content": true,   // 生成 4 条已发布示例内容
  "create_workflow": true,  // 创建并发布“内容发布审批”工作流
  "create_realtime": true,  // 创建 WebSocket 实时通道
  "generate_ssr": true,     // 发布后生成 SSR 快照（需 dist-ssr）
  "publish": true,          // 自动发布应用
  "enable_review": false,   // 内容模型开启审核
  "use_llm": true           // 关闭则使用本地蓝图生成器
}
```

任务对象：`{id,status:pending|running|success|failed|cancelled,progress,current_step,steps[],logs,blueprint,result,error,provider,model}`。
`steps[]` 固定为 `plan/app/model/content/pages/review/workflow/realtime/release/index/ssr`，每步含 `status` 与 `message`。

`result` 示例：

```jsonc
{
  "app_id": 57, "app_code": "auto-site-b306", "app_name": "独立游戏评测站",
  "model_id": 59, "records": 4,
  "pages": [{"id":70,"name":"首页","path":"home","version":1}, "..."],
  "release_id": 90, "index_docs": 4, "ssr_pages": 9,
  "workflow_id": 3, "channel_id": 2,
  "links": {"runtime":"/run/auto-site-b306/home","search":"/run/auto-site-b306/search",
            "admin":"/admin/apps/57","designer":"/design/57/70","review":"/admin/reviews?app=57"}
}
```

约束：同一用户同时只能有 1 个执行中的任务，每用户每小时最多 5 次；页面由蓝图 `pages[]`
动态生成（核心 page/list/detail/about/contact/search 缺失时自动补齐），可在设计器中继续调整；
页面结构由模板生成，LLM 负责页面计划、站点蓝图、文案与示例内容。

## 21. PostgreSQL 数据源建站

`POST /api/ai/autobuild/` 的 `options.source` 启用数据源模式：

```jsonc
{
  "prompt": "做一个 A 股行情数据站，深色红黑配色",
  "options": {
    "source": {
      "host": "127.0.0.1", "port": 5432, "database": "db_stock",
      "username": "postgres", "password": "******", "schema": "public",
      "table": "Astock_stock", "limit": 200, "label": "行情"
    },
    "publish": true, "create_workflow": true, "create_realtime": true,
    "generate_ssr": true
  }
}
```

行为：

1. 读取表结构，PostgreSQL 类型映射为 `string/number/boolean/date/json`；
2. 创建公开 `DataModel`，并创建同名 PostgreSQL 只读数据源（`Datasource`，密码加密）；
3. 导入最多 500 行记录；缺少标题/摘要/详情列时生成派生字段；
4. 发布页面：`home`、`data`、`data/:id`、`search`、`about`，并额外生成 `live` 实时数据页；
5. 应用发布、搜索索引、SSR 快照与普通建站一致。

任务 `result.links` 额外返回 `list`（`/run/{code}/data`）与 `live`（`/run/{code}/live`）。

实时数据页使用「调用数据源」动作 + `dataBinding(source=datasource, ref=ds_{id}, field=data)`；
`/api/datasources/{id}/query/` 需要登录且是应用成员，匿名访客无法获取。

## 22. AI 助手的 PostgreSQL 数据源工具

设计器 Agent 新增工具（读取直接执行，导入需提案确认）：

| 工具 | 说明 |
| --- | --- |
| list_datasources | 列出当前应用数据源（不含密码/配置） |
| inspect_datasource | `{datasource_id}` → 表与字段结构 |
| preview_datasource | `{datasource_id, table, limit?}` → 只读预览前 N 行 |
| propose_datasource_import | `{datasource_id, table, model_name?, limit?}` → 生成 `datasource_import` 提案 |

`POST /api/ai/agent/conversations/{id}/apply/` 应用 `datasource_import` 提案时执行导入，
返回 `{ok, model_id, model_name, records, fields}`，不会自动生成页面；之后可让 AI 助手继续改页面
或到设计器里生成列表/详情页。工具结果会做 Decimal/日期/bytes 的 JSON 安全转换。

## 23. 动态页面计划（pages[]）

建站蓝图新增 `pages`，普通建站不再固定 5 页：

```jsonc
{
  "pages": [
    {"kind": "home", "name": "首页", "path": "home"},
    {"kind": "list", "name": "评测", "path": "reviews", "category": "评测", "title": "游戏评测"},
    {"kind": "detail", "name": "评测详情", "path": "reviews/:id", "list_path": "reviews"},
    {"kind": "about", "name": "关于我们", "path": "about"},
    {"kind": "contact", "name": "联系我们", "path": "contact"},
    {"kind": "pricing", "name": "价格", "path": "pricing"},
    {"kind": "docs", "name": "文档", "path": "docs"},
    {"kind": "search", "name": "搜索", "path": "search"}
  ]
}
```

- `kind` 支持 `home/list/detail/about/contact/pricing/docs/topic/search`；
- 缺少核心页面时后端自动补齐 home、至少一个 list、一个 detail、about、contact、search；
- 列表页按 `category` 过滤；详情页 `list_path` 决定返回列表；导航自动取顶层页面（最多 9 项）；
- 首页自动为带分类的列表页生成频道区块；示例内容会为缺失分类补 2 条，避免空频道。

## 24. Agent 写工具

除页面补丁/数据源导入提案外，Agent 新增直接写工具（执行前需应用 editor/owner 权限）：

| 工具 | 说明 |
| --- | --- |
| create_page | `{name, path, type?}` → 新建草稿页面 |
| create_model | `{name, fields[]}` → 新建公开数据模型 |
| publish_page | `{page_id?/path?}` → 发布页面并触发应用发布（owner） |
| publish_app | `{}` → 发布应用（owner） |
| bind_datasource | `{node_id, datasource_id, page_id?/path?, field?, loop_var?, trigger?}` → 写 dataBinding 或按钮点击动作 |
| create_workflow | `{name, description?, nodes?}` → 创建并发布审批流 |

所有工具返回 `{ok: true, ...id/path/version}`；工具结果统一 JSON 安全转换。

## 25. 自动评审与修复

建站步骤：`plan/app/model/content/pages/review/workflow/realtime/release/index/ssr`。

`review` 步骤：

1. 对每个页面跑 `review_schema`，统计 score/error/warning；
2. 缺 meta.title/description、缺 site-nav、缺 footer 等确定性问题自动修复、重新保存并发布；
3. 若本机有 Chrome/Edge 且 `FRONTEND_URL` 可访问，对首页/列表/关于最多 3 页截图，
   调用 `review_screenshot`；没有视觉模型时用启发式规则；
4. 结果写入任务 `result.review`：

```jsonc
{
  "structure": {"before": 93.6, "after": 95.2, "errors": 0, "warnings": 3},
  "visual": {"score": 95.3, "pages": 3, "issues": 4, "mode": "heuristic"},
  "fixed_pages": ["news"]
}
```

环境变量：`AUTOBUILD_SCREENSHOT=1` 开启截图评审，`AUTOBUILD_BROWSER` 指定浏览器路径。

## 26. 多数据源/多模型编排

`options.sources[]` 一次导入多张 PostgreSQL 表（最多 6 张），一表一模型：

```jsonc
{
  "options": {
    "sources": [
      {"host": "127.0.0.1", "port": 5432, "database": "db_stock", "username": "postgres",
       "password": "******", "schema": "public", "table": "Astock_stock", "limit": 100, "label": "个股"},
      {"host": "127.0.0.1", "port": 5432, "database": "db_stock", "username": "postgres",
       "password": "******", "schema": "public", "table": "Astock_bkname", "limit": 50, "label": "板块"}
    ]
  }
}
```

生成页面：

- `home`：首个模型的最新/排行；
- 每个模型：`data/{slug}` 列表 + `data/{slug}/:id` 详情；
- 多模型时追加 `overview` 数据总览（每个模型的卡片/最新 3 条）；
- `live`、`search`、`about`，以及蓝图声明的 contact/pricing/docs。

关联：模型字段名以 `_id` 结尾且前缀能匹配另一个模型名时，自动改为 `reference` 并写 `ref_model`。
单表仍兼容旧的 `options.source`。

## 27. AI 任意页面布局（dashboard / form / custom）

蓝图 `pages[]` 支持：

| kind | 用途 | 生成方式 |
| --- | --- | --- |
| dashboard | 数据大屏、仪表盘、图表报表 | LLM 生成 Schema；本地回退用 content-list + wp-barchart/wp-piechart/wp-statcard/wp-table |
| form | 复杂表单、录入、预约 | LLM 生成 Schema；本地回退用 auto-form（按模型字段） |
| custom / landing | 落地页、活动页、非对称布局 | LLM 生成 Schema；本地回退用行列卡片 + 内容区 |

页面可带 `brief` 描述布局目标，例如：

```jsonc
{"kind": "dashboard", "name": "数据大屏", "path": "dashboard",
 "brief": "顶部 4 个 KPI，下面左右两个图表，底部明细表"}
```

生成约束：

- 只使用平台已启用的真实组件；LLM 返回未知组件、孤儿节点、缺数据加载器时会自动回退本地布局；
- 仪表盘使用公开 `content-list` 作为隐藏数据加载器，`wp-barchart/wp-piechart/wp-statcard/wp-table`
  从运行时 scope 读取，匿名可访问；
- 表单使用 `auto-form`，`fields` 自动取模型字段；表单提交需要登录；
- 生成后仍经过 `save_draft`、严格 `validate_page_schema`、`publish_page` 和自动评审；
- Agent 的 `create_page` 新增 `kind` 与 `prompt` 参数，聊天中可直接生成任意布局页面。

示例提示词：

```text
做一个深色 A 股数据大屏，顶部 4 个 KPI，中间左右两个图表（分类柱状图 + 占比饼图），
底部 10 行明细表，全站导航保留首页/个股/大屏/关于/搜索。
```

```text
新增一个「运营上报」复杂表单页，双列表单，字段来自 article 模型，
带填写说明卡片和提交按钮，路径 /report-form。
```

## 28. 公开聚合报表接口

仪表盘/公开报表不再被迫走登录态模型接口：

```http
GET /api/runtime/{app_code}/content/{model_id}/report/?group_by=category&metrics=count,sum:amount&limit=20
```

- 仅允许 `is_public=true` 的模型；
- 自动过滤 `status != published` 的记录；
- 支持 `group_by / group_by2 / metrics / limit / filters`；
- `metrics` 支持 `count, sum:field, avg:field, min:field, max:field, count_distinct:field`；
- 返回 `{group_by, metrics, count, rows, fields, cross, cross_columns}`；
- 匿名可访问，缓存 30 秒。

前端 `report-table` 在运行时自动优先调用该接口，因此公开大屏也能做真实分组统计、Top N、柱状/饼图，
不再只是取前几行展示。

## 29. 建站前页面计划

```http
POST /api/ai/autobuild/plan/
```

请求与 `POST /api/ai/autobuild/` 相同（prompt + options，可不含真实连接密码），返回：

```jsonc
{
  "pages": [
    {"kind": "home", "name": "首页", "path": "home", "enabled": true},
    {"kind": "list", "name": "评测", "path": "reviews", "category": "评测", "enabled": true},
    {"kind": "detail", "name": "评测详情", "path": "reviews/:id", "list_path": "reviews", "enabled": true}
  ],
  "source_mode": false,
  "site": {"name": "..."},
  "provider": "deepseek-chat",
  "model": "...",
  "warnings": []
}
```

确认后把保留的页面作为 `options.pages_override` 传给 `POST /api/ai/autobuild/`：

```jsonc
{
  "prompt": "...",
  "options": {
    "pages_override": [
      {"kind": "home", "name": "首页", "path": "home", "enabled": true},
      {"kind": "list", "name": "资讯", "path": "news", "enabled": true}
    ]
  }
}
```

- 只生成勾选页面；核心页缺失会自动补齐；
- PostgreSQL `sources[]` 模式的表页路径由后端按表名生成，但可通过 `pages_override` 取消/改名；
- 计划接口不创建应用/任务，可反复预览。

## 30. 单页重生成

```http
POST /api/ai/pages/{page_id}/regenerate/
```

```jsonc
{"kind": "dashboard", "prompt": "改成更紧凑的三列布局", "publish": false}
```

- 只重生成指定页面，不重建应用；
- `kind` 省略时按 `schema.meta.aiKind` / 路径 / 组件推断；
- 支持 home/list/detail/about/contact/pricing/docs/search/dashboard/form/custom/landing；
- 生成前自动创建 `PageVersion` 快照；
- 默认回到 `draft`；`publish=true` 时发布并触发应用发布；
- 返回 `{ok,page_id,path,kind,provider,version,warnings}`。

Agent 工具 `rollback_page`：

```jsonc
{"page_id": 123, "version": 2}
```

不传 `version` 时回滚到最近一次 AI 快照；页面回到草稿状态，不影响已发布版本。

## 31. 数据源接入向导

```http
POST /api/ai/datasources/inspect/
```

```jsonc
{
  "type": "postgres",
  "host": "127.0.0.1", "port": 5432, "database": "db_stock",
  "username": "postgres", "password": "******", "schema": "public"
}
```

- 用临时连接读取表与字段，不创建 `Datasource`、不写库；
- 支持 PostgreSQL / MySQL / SQL Server；
- 返回最多 80 张表、每表前 40 个字段；
- 连接信息只在本次请求内使用，密码不落库、不写日志；
- 失败返回 `连接失败：...`，不会创建建站任务。

前端「全自动建站 → PostgreSQL」里的「测试连接并读取表」会调用该接口，读取成功后表名变为可搜索下拉框。

## 32. 公开表单提交

```http
POST /api/runtime/{app_code}/content/{model_id}/submit/
Content-Type: application/json

{"title": "...", "summary": "...", "content": "...", "_hp": ""}
```

条件：

- 模型必须 `is_public=true`；
- 应用中必须存在**已发布**页面，`meta.allowPublicSubmit=true`，且页面里有
  `auto-form` 的 `modelId` 等于该模型；
- AI 生成的 `form` 页面会自动写入这个 meta。

行为：

- 只接受模型字段白名单内的字段，忽略 `id/created_at/updated_at`；
- 校验必填字段；
- 有 `status` 字段时强制写 `pending`，不会直接进入公开内容；
- 同 IP + 模型 5 次/分钟；`_hp` 非空时返回成功但不落库；
- 成功返回 `201 {ok,id,status}`。

前端 `auto-form` 在运行时（有 app code）自动调用该接口；编辑模式仍走登录态 `/models/...`。

验证码：

```http
GET /api/runtime/{app_code}/content/{model_id}/challenge/
```

```jsonc
{"required": true, "token": "...", "question": "3 + 4 = ?"}
```

提交时带 `_captcha_token` / `_captcha_answer`；答案一次性使用，5 分钟失效。
公开提交会写入 AuditLog（`action=runtime.public_submit`），可在管理端审计日志查看。

公开表单转发第三方：

- 页面 `meta.forwardDatasourceId` 指向应用内 REST 数据源；
- 入库成功后服务端调用该数据源；
- 请求参数为表单字段 + `record_id` / `model_id` / `request_id`；
- 返回：

```json
{"ok": true, "forward": {"ok": true, "skipped": false, "status": 200, "error": ""}}
```

- 转发失败不回滚记录，写入 `runtime.public_forward` 审计；
- POST/PUT 不缓存；GET 结果缓存 60 秒。

## 33. AI 变更差异

```http
GET /api/ai/pages/{page_id}/diff/?version=2
```

- 不传 `version` 时对比最近一次 `PageVersion` 快照与当前草稿；
- 返回节点级变化：`added / removed / changed`，以及 `props.* / style.* / children / type` 前后值；
- 同时返回 `meta` 变化；
- 仅只读，不修改页面。

返回示例：

```jsonc
{
  "same": false,
  "summary": {"added": 0, "removed": 0, "changed": 3, "meta": 1, "total": 4},
  "nodes": [
    {"id": "heroTitle", "type": "wp-heading", "status": "changed",
     "changes": [{"field": "props.content", "before": "旧标题", "after": "新标题"}]}
  ],
  "meta": [{"field": "title", "before": "旧", "after": "新"}]
}
```

## 34. 复用已有数据源

```http
GET /api/ai/datasources/existing/
```

返回当前用户有权限访问的数据源（不返回密码）：

```jsonc
{"count": 2, "results": [
  {"id": 11, "name": "Astock_stock (PostgreSQL)", "type": "postgres",
   "app_id": 84, "app_name": "股市前线", "host": "127.0.0.1", "port": 5432,
   "database": "db_stock", "username": "postgres", "schema": "public"}
]}
```

```http
POST /api/ai/datasources/inspect-existing/
{"datasource_id": 11}
```

复用建站：

```jsonc
{
  "options": {
    "sources": [
      {"datasource_id": 11, "table": "Astock_stock", "limit": 100, "label": "个股"}
    ]
  }
}
```

- 服务端解密原数据源配置，不经过前端；
- 仍会在新应用下创建独立数据源，修改新数据源不会影响原应用；
- 仅支持 PostgreSQL 复用；手动填写连接仍兼容。

## 35. 公开主从页

数据源建站检测到 `*_id` 外键时，主表详情页使用内置组件 `public-master-detail`：

```jsonc
{
  "type": "public-master-detail",
  "props": {
    "masterModelId": 109,
    "masterKeyField": "id",
    "titleField": "bk_name",
    "relations": [
      {"modelId": 110, "foreignKey": "bk_name_id", "title": "板块明细", "columns": [...]}
    ],
    "backPath": "data/astock-bkname"
  }
}
```

组件行为：

- 按路由 `:id` 读取主记录；
- 主记录业务键保留在 `data.id`，DataRecord id 放到 `_recordId`；
- 子表按 `masterKeyField` 的值过滤，不再错误使用路由 DataRecord id；
- 匿名可读，仅使用公开内容 API；
- 支持多个关系、空明细、返回列表；
- `relations[].allowAdd=true` 时显示「+ 新增明细」，复用公开 submit 接口；
- 新增子表记录时，服务端按主记录业务键校验并写外键，客户端不能伪造主记录。

`master_detail` 选项默认开启；可用 `options.master_detail=false` 关闭主从区块。

公开写入条件：主从页 `meta.allowPublicSubmit=true`，且 `relations` 里声明了子模型。

通知环境变量：

```env
FORM_NOTIFY_WEBHOOK=
```

- 应用所有者邮箱需配置 `EMAIL_HOST`；
- Webhook 接收 `{"msgtype":"text","text":{"content":"..."}}`；
- 通知失败不影响提交。

组件注册：

```bash
python manage.py seed_builtin_components
```

## 38. 自定义组件导入

```http
POST /api/components/import/
Content-Type: multipart/form-data
```

字段：

| 字段 | 说明 |
| --- | --- |
| `file` | 构建后的 ESM `.js`，最大 8MB |
| `name` | 组件名，小写字母/数字/短横线 |
| `label` | 显示名 |
| `tag` | 自定义元素标签，必须 `wp-widget-` 开头 |
| `version` | 版本号 |
| `props_schema` | JSON 对象 |
| `events` | JSON 数组 |
| `default_props` | JSON 对象 |

组件要求：

```js
class MyWidget extends HTMLElement {
  connectedCallback() { this.textContent = "hello"; }
}
customElements.define("wp-widget-my", MyWidget);
```

保存后：

- 平台创建 `ComponentMeta`（`source=custom`）；
- 文件保存到 `media/custom-components/{name}/{version}/index.js`；
- 运行时通过 `source_url` 动态加载；
- 设计器可直接拖入使用。

限制：

- 仅平台管理员可导入；
- 不做沙箱；自定义组件代码可访问页面和 token；
- 组件依赖应自行打包，避免依赖平台构建产物；
- 同源加载，生产环境需保证 `/media/` 可访问。

## 39. 在线组件编译

```http
POST /api/components/compile/
Content-Type: application/json
```

```json
{
  "name": "stock-editor",
  "label": "库存编辑器",
  "tag": "wp-widget-stock-editor",
  "version": "1.0.0",
  "source": "<template>...</template>\n<script setup>...</script>",
  "props_schema": "{\"type\":\"object\",\"properties\":{}}",
  "events": "[]",
  "default_props": "{}"
}
```

流程：

- 服务端写入临时 Vite 工程；
- `@vitejs/plugin-vue` 编译 SFC；
- 生成 Web Component ESM；
- 内联 CSS；
- 走与导入相同的组件注册流程。

限制：

- 仅管理员；
- 源码最大 200KB；
- 构建超时 60 秒；
- 产物最大 8MB；
- 不做沙箱，执行的是管理员代码。

错误返回：

```json
{"detail": "组件编译失败：...", "line": 12, "column": 5}
```

组件版本回滚：

```http
POST /api/components/{id}/versions/{version}/rollback/
```

- 仅管理员；
- 切换组件元数据和 `source_url`；
- 旧版本构建文件不存在时拒绝回滚；
- 删除组件时会清理 `media/custom-components/{name}/` 目录。

## 40. AI 生成组件草稿

```http
POST /api/components/ai-draft/
```

```json
{
  "prompt": "做一个库存概览卡片组件，显示物料、库存和预警",
  "name": "inventory-card",
  "tag": "wp-widget-inventory-card",
  "current_source": "<template>...</template>"
}
```

返回：

```json
{
  "draft": {
    "name": "inventory-card",
    "label": "库存概览卡片",
    "tag": "wp-widget-inventory-card",
    "source": "<template>...</template>",
    "props_schema": {"type": "object", "properties": {}},
    "events": []
  },
  "provider": "DeepSeek",
  "model": "deepseek-chat",
  "warnings": []
}
```

- 仅管理员；
- 有 Provider 用 LLM，无 Provider 用本地模板；
- AI 结果仍需人工检查；
- 生成后可直接进入「编译并导入」。

## 41. 自定义组件运行时桥

导入的 Web Component 可以使用：

```js
const bridge = window.__WP_BRIDGE__;
```

可用能力：

```js
bridge.getState();                 // 全部页面变量
bridge.getState("selectedId");     // 单个变量
bridge.setState("selectedId", 1);  // 写入页面变量
bridge.watchState("selectedId", (value) => {}); // 订阅
bridge.emit("stock:selected", { id: 1 });
bridge.on("stock:selected", (detail) => {});
bridge.callDatasource(12, { warehouse: 1 });
bridge.request("/api/stock", { method: "GET" });
bridge.navigate("stock/detail");
bridge.message("已保存", "success");
bridge.user / bridge.page / bridge.app
```

- `callDatasource` 使用平台数据源代理；
- `request` 自动带平台 JWT；
- 状态存放在页面 `variables` 中，刷新页面后回到初始值；
- 组件间协作建议使用带命名空间的状态键和事件，例如 `stock:selected`、`stock:saved`。

样式规范：

- 使用 `--wp-accent`、`--wp-bg`、`--wp-text`、`--wp-border` 等变量；
- 类名统一加 `wp-` 前缀；
- 避免 `body`、`*` 等全局选择器；
- 复杂组件自行处理加载、空状态、错误状态。

## 42. 设计器节点属性 AI

```http
POST /api/ai/design/node-draft/
```

```json
{
  "app_id": 63,
  "node_type": "demo-stat-card",
  "node_label": "演示指标卡",
  "props_schema": {"type": "object", "properties": {}},
  "style_schema": {},
  "allowed_events": [],
  "current_props": {},
  "current_style": {},
  "current_events": {},
  "prompt": "改成青色，增加圆角和内边距"
}
```

返回：

```json
{
  "props": {"accent": "#06b6d4"},
  "style": {"borderRadius": "12px", "padding": "16px"},
  "events": {},
  "explanation": "……",
  "provider": "DeepSeek",
  "warnings": []
}
```

- 只允许 `props_schema` 中声明的属性；
- 只允许声明的事件名；
- style 使用 CSS 驼峰属性；
- 前端通过设计器历史记录应用，可撤销。

## 36. 子表公开编辑/删除

公开提交返回：

```json
{"ok": true, "id": 1280, "public_token": "签名token"}
```

前端把 token 存在：

```text
wp_public_tokens:{app_code}:{child_model_id}
```

更新：

```http
POST /api/runtime/{app}/content/{model_id}/{record_id}/update/
{"public_token": "...", "open": "9"}
```

删除：

```http
POST /api/runtime/{app}/content/{model_id}/{record_id}/delete/
{"public_token": "..."}
```

- token 使用 Django signing，7 天有效；
- 校验 token 的模型 id / 记录 id；
- 只允许已发布主从/表单页声明的模型；
- 修改后 `status=pending`（有 status 字段时）；
- 写 AuditLog：`runtime.public_update` / `runtime.public_delete`。

## 37. JOIN 聚合页

```http
GET /api/runtime/{app}/content/{master_id}/join/{child_id}/
    ?foreign_key=bk_name_id&master_key=id
```

- 仅当已发布主从页声明了该关系时可访问；
- 主表按 `master_key`、子表按 `foreign_key` 合并；
- 子表字段列名前缀 `child_`；
- 无子记录的master仍保留一行；
- 返回 `{columns, rows, count}`，缓存 30 秒。

多级关系：

```jsonc
relations=[{"modelId":114,"foreignKey":"bk_name_id","parentKey":"id"},
           {"modelId":120,"foreignKey":"detail_id","parentKey":"id"}]
```

- 最多 3 层；
- 列前缀：`child_`、`grandchild_`、`level3_`；
- 第一层仍需在主从页声明，后续层要求模型公开。

筛选/排序/分页/导出参数：

| 参数 | 说明 |
| --- | --- |
| `q` | 全字段搜索 |
| `filter_<field>` | 精确筛选，如 `filter_child_riqi=2025-11-11` |
| `filter_<field>__contains` | 包含 |
| `filter_<field>__gte/lte/gt/lt` | 数值比较 |
| `filter_<field>__in` | 多值，逗号分隔 |
| `sort` | 字段排序，`-` 前缀降序，如 `-child_open` |
| `page` / `size` | 分页，size 最大 200 |
| `export=1` | 返回 UTF-8 BOM CSV |

脱敏：

- 页面组件 `maskFields` 声明需要脱敏的字段，如 `["phone","child_email"]`；
- 后端还会自动识别 `phone/mobile/email/id_card/address/contact` 等字段；
- `content` 字段不会进入 JOIN 结果，避免正文夹带敏感信息；
- 表格与 CSV 导出使用同一套脱敏结果。

三层关系：

```jsonc
relations=[{"modelId":116,"foreignKey":"region_id","parentKey":"id"},
           {"modelId":117,"foreignKey":"store_id","parentKey":"id"}]
```

实测：区域 → 门店 → 订单 8 行、14 列（不含 content），手机号/邮箱已脱敏。

多表建站会自动生成路径：

```text
join/{master_slug}-{child_slug}
```

页面使用内置组件 `public-join-table`。
