# Market 组件签名与沙箱

本目录实现「市场组件代码签名 + 安装时校验 + 前端 iframe 沙箱占位」。

## 数据模型（`market/models.py`，migration `0002`）

`MarketItem` 新增：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code_hash` | `CharField(64)` | 签名 canonical JSON 的 SHA-256 十六进制摘要 |
| `signature` | `CharField(64)` | HMAC-SHA256 十六进制签名 |
| `signed_at` | `DateTimeField(null=True)` | 最近一次签名时间 |
| `signer` | `FK(User, null=True, SET_NULL)` | 签名人；用户删除后置空 |
| `sandboxed` | `BooleanField(default=True)` | 组件安装/签名时强制为 True；区块可关闭 |
| `policy` | `JSONField(default=dict)` | 规范化后的沙箱策略 |

`ComponentMeta` **未改模型、未新增迁移**。安装后的沙箱元数据写入现有
`payload_schema` 的 `x-wp-market` 键，并把 `source` 设为 `custom-sandbox`：

```json
{
  "x-wp-market": {
    "schema": "wp-market-signing/v1",
    "market_item_id": 12,
    "sandboxed": true,
    "source": "custom-sandbox",
    "source_url": "...",
    "element": "wp-widget-hello",
    "policy": {"network": "none", "timeout_ms": 10000, "...": "..."},
    "code_hash": "...",
    "signature": "...",
    "signed_at": "...",
    "signed_by": "owner"
  }
}
```

`components.views.component_registry` 已原样输出 `payload_schema` 与 `source`，
因此无需修改 components 应用。

## 签名密钥

```python
# config/settings.py
MARKET_SIGNING_KEY = _env("MARKET_SIGNING_KEY", "")
```

- 生产环境必须设置 `MARKET_SIGNING_KEY`（建议 ≥ 32 字节随机值）。
- 未设置时回退 `SECRET_KEY`，仅为开发兼容；轮换 `SECRET_KEY` 会使历史签名失效。
- 密钥不会经任何 API 返回；响应只含 `code_hash`/`signature`/`signed_at`/`signer`
  /`signed`/`signature_valid`/`signature_error`。
- 修改密钥后，所有市场组件都需要重新签名。

## Canonical 签名对象

`backend/market/signing.py` 对以下对象做 `json.dumps(sort_keys=True,
separators=(",", ":"), ensure_ascii=False)` 后 UTF-8 编码：

```json
{
  "schema": "wp-market-signing/v1",
  "kind": "component",
  "name": "<MarketItem.name>",
  "slug": "<MarketItem.slug>",
  "sandboxed": true,
  "policy": {"...规范化策略..."},
  "source_url": "<payload.source_url>",
  "element": "<payload.element 或由 slug 派生>",
  "payload": {"...完整组件 payload..."}
}
```

- `code_hash = SHA-256(canonical_json)`
- `signature = HMAC-SHA256(MARKET_SIGNING_KEY, canonical_json)`
- 校验时重新读取**数据库中已存储**的 payload 重算，客户端提交的 hash/signature 不被信任。
- 展示性字段（`description`、`tags`、`preview`）不参与签名；修改它们不会使签名失效。

## API

### `POST /api/market/items/{id}/sign/`

- 权限：条目创建者或平台管理员（`core.permissions.is_platform_admin`）。
- 组件会重新校验 `payload` 与 `source_url`，并强制 `sandboxed=true`；
  可选 body `{"policy": {...}}` 先规范化再签名。
- 响应为完整的 MarketItem 元数据（含签名信息），不返回密钥。
- 区块也可签名，但安装不要求签名。

### `POST /api/market/items/{id}/install/`

- 仍要求目标应用 `editor` 及以上角色。
- **组件**：先校验 `signature`，再校验 `sandboxed`，然后才创建/更新 `ComponentMeta`。
  未签名、签名格式错误、payload 被修改、策略被修改都会返回 400 `{"signature": ...}`。
- 组件安装会拒绝覆盖平台内置组件，以及被其他市场条目占用的同名组件。
- 安装后的 `ComponentMeta.source="custom-sandbox"`、`element` 为自定义元素名，
  `payload_schema["x-wp-market"]` 保存审计元数据。
- **区块**：保持原行为，不要求签名。

### 策略规范化

只接受 `network`（`none`/`allowlist`）、`allowed_origins`（纯 origin，最多 20 个）、
`timeout_ms`（1000–30000）。`sandbox`、`allow_scripts` 强制 true；
`allow_same_origin`、`allow_forms`、`allow_popups` 强制 false。未知键被丢弃。

## 前端

- 新增 `frontend/src/components/market/SandboxedComponent.vue`
  - `sandbox="allow-scripts"`，无 `allow-same-origin`。
  - 父页面只 `postMessage` props，绝不 `import`/`eval` 远端代码。
  - iframe 内用 `import(source_url)` 加载 ESM，`customElements.whenDefined(element)`，
    创建元素并设置 property（primitive 回退 attribute）。
  - 事件、ready、error、高度经 `postMessage` 回传；父页面用 `event.source` 校验来源。
  - 生成文档带 CSP：`default-src 'none'`、`script-src 'unsafe-inline' <source origin>`、
    `connect-src` 受 policy 控制、`img-src data: blob:`、禁止 form/base/object。
- 修改 `frontend/src/views/admin/MarketView.vue`
  - 卡片展示签名/沙箱 badge、hash、签名人/时间、失效原因；
  - 条目创建者可「签名/重签」；组件未通过签名校验时安装按钮禁用；
  - 组件沙箱预览 dialog；
  - 创建组件时填写 `source_url`、可选 `element`，并合并进 payload。

### 页面运行时接入（需在允许修改 `NodeRenderer.vue` 时完成）

当前 `NodeRenderer.vue` 对 `source === "custom"` 会直接动态 import 远端 ESM（无沙箱）。
本次把市场组件安装为 `source="custom-sandbox"`，现有渲染器会安全地回退为占位，
不会在父页面执行未签名代码。要让已安装沙箱组件真正参与设计器渲染，需要在
`NodeRenderer.vue` 的组件解析函数中加入：

```ts
if (source === "custom-sandbox") {
  return SandboxedComponent; // 通过 attrs 传 source_url/policy/props
}
```

或新增一个包装组件，从 `meta.payload_schema["x-wp-market"]` 读取
`sandboxed`/`policy`/`source_url`，再渲染 `SandboxedComponent`。
**本次遵循 ownership 限制，未修改 NodeRenderer。**

## 测试

```powershell
cd backend
python manage.py test market.tests_signing -v 2 --noinput
```

覆盖：签名/验签、密钥不回传、owner/admin 权限、篡改与改名后失效、未签名拒绝安装、
成功安装的 marker/source/element、重复安装、应用角色权限、区块免签名、内置组件保护、
策略收紧、canonical JSON 稳定性。

> 本机同时运行多个 Django test 进程时，PostgreSQL 的 `test_webprocess` 建库/迁移
> 可能互相死锁；可用 `USE_SQLITE=1` 隔离运行本套测试。

## 安全说明与限制

1. 签名保护的是**市场条目元数据与 URL/schema**，不是远端 ESM 文件字节。
   CDN 原地替换文件时 URL 不变，签名仍有效。建议使用不可变、内容寻址的构建产物。
2. 校验只发生在安装时；安装后管理员直接改 `ComponentMeta` 不会再次验签。
3. `source="custom-sandbox"` 在现有 `NodeRenderer` 中不渲染，需完成上述接入。
4. iframe 是 opaque origin：远端模块必须允许 CORS。**当前同源 `/media/`
   静态文件默认没有 `Access-Control-Allow-Origin`，浏览器会拒绝在 sandbox
   iframe 内 `import()` 同源 ESM。** 部署时必须为组件构建产物（如
   `/media/custom-components/**`）返回 `Access-Control-Allow-Origin: *`
   （或 `null`），或改用带 CORS 的 CDN。否则沙箱预览会报加载失败。
   组件无法读取父页面/cookie/localStorage。
5. CSP 默认禁止网络与远程图片；需要网络的组件必须在签名策略里显式配置 `allowlist`。
6. `postMessage` 的目标 origin 为 `"*"`（opaque origin 无法指定），父页面以
   `event.source === iframe.contentWindow` 校验；仅发送 props，不发送 token。
7. 客户端沙箱无法阻止 CPU/内存 DoS；加载超时仅覆盖启动阶段。
8. HMAC 是对称密钥：能签发的人也能伪造签名；签名身份依赖平台账号与审计，不是
   第三方不可否认签名。需要外部发布者不可抵赖时应改用非对称签名（Ed25519）。
