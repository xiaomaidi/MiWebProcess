# Redis Channel Layer 与多 worker 实时部署

本文说明 MiWebProcess 的 Channels Channel Layer 如何从单进程内存模式切换到
生产 Redis 模式，以及多 ASGI worker 时的部署、验证和注意事项。

相关文件：

- `backend/config/settings.py`：`CHANNEL_LAYERS` / `CACHES` 环境变量驱动
- `backend/config/asgi.py`：HTTP + WebSocket 路由（LocMem 与 Redis 模式共用，无需改代码）
- `backend/realtime/management/commands/check_realtime_channels.py`：配置/连通性诊断
- `backend/requirements.txt`：`channels_redis` 依赖
- `.env.example`：`REDIS_URL`、`CHANNEL_LAYER_CAPACITY`、`CHANNEL_LAYER_EXPIRY`

## 1. 行为矩阵

| 环境 | `CHANNEL_LAYERS` | `CACHES` | Celery | 实时能力 |
| --- | --- | --- | --- | --- |
| 未设置 `REDIS_URL` | `channels.layers.InMemoryChannelLayer` | LocMem | eager 模式 | 仅单进程；不同进程的 WebSocket 组互不可见 |
| 设置 `REDIS_URL` | `channels_redis.core.RedisChannelLayer` | `django.core.cache.backends.redis.RedisCache` | Redis broker | 所有 ASGI worker 共享广播组与在线状态 |

注意事项：

- 当前配置中 `REDIS_URL` 同时驱动缓存、Channels 和 Celery；不配置则整体降级为内存 + eager。
- 未配置 `REDIS_URL` 时，`CHANNEL_LAYER_CAPACITY` / `CHANNEL_LAYER_EXPIRY` 不生效。
- `channels_redis` 只在 Redis 模式使用；未安装时不会在 settings 阶段报错，但首次建立
  WebSocket 连接、实例化 Channel Layer 时会失败。这是有意为之：静默回退到 InMemory 会让
  多 worker 广播"看起来正常、实际丢消息"。
- Redis 服务端建议 **7.x**（`docker-compose.yml` 使用 `redis:7-alpine`）。`channels_redis`
  4.3 + redis-py 8 默认使用 RESP3（`HELLO`）；Redis 5 不支持该命令，Channel Layer 连接会
  报 `unknown command 'HELLO'`。`check_realtime_channels --ping` 使用 RESP2 做连通性探测，
  在 Redis 5 上可能成功但会额外打印版本告警，不能仅凭 PING 判断 Channel Layer 可用。
  本地 Redis 5 可通过 `REDIS_URL=redis://127.0.0.1:6379/0?protocol=2` 强制 RESP2；已实测
  `channels_redis` 跨进程 group send/receive 正常。生产仍建议 Redis 7.x。

## 2. 依赖安装

`backend/requirements.txt` 已包含：

```text
channels_redis>=4.3,<5.0
redis>=5.0
```

安装并确认：

```bash
cd backend
pip install -r requirements.txt
python -c "import channels_redis, redis; print(channels_redis.__version__, redis.__version__)"
```

Channels 4 已移除旧的 `channels.layers.RedisChannelLayer`；本项目使用
`channels_redis.core.RedisChannelLayer`。

## 3. 环境变量

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `REDIS_URL` | 生产必填 | 空 | `redis://[:password@]host:port/db`；TLS 用 `rediss://`。留空 = 单进程内存模式 |
| `CHANNEL_LAYER_CAPACITY` | 否 | `1500` | 每个 channel 的待处理消息上限，按压测调整 |
| `CHANNEL_LAYER_EXPIRY` | 否 | `60` | 消息在 Redis 中的过期时间（秒） |

示例（生产建议使用独立 Redis DB 或实例，并开启 ACL/密码）：

```dotenv
REDIS_URL=redis://:strong-password@redis.internal:6379/2
CHANNEL_LAYER_CAPACITY=1500
CHANNEL_LAYER_EXPIRY=60
```

TLS 示例：

```dotenv
REDIS_URL=rediss://:strong-password@redis.internal:6380/2
```

所有 ASGI worker、Celery worker 必须使用完全相同的 `REDIS_URL`（以及相同的
`CHANNEL_LAYER_*`），否则它们不在同一个广播域。不要提交真实密码到仓库；通过
systemd `EnvironmentFile`、容器 secret 或 KMS 注入。

## 4. 诊断命令

不连接 Redis 的基础检查：

```bash
cd backend
python manage.py check_realtime_channels
```

InMemory 模式示例输出：

```text
Realtime channel layer
  backend : channels.layers.InMemoryChannelLayer
  mode    : in-memory (single ASGI process only; not for multi-worker)
  hosts   : (none; no external broker)
  deps    : channels_redis=4.3.0, redis=8.1.0
```

Redis 模式示例输出（密码始终显示为 `***`）：

```text
Realtime channel layer
  backend : channels_redis.core.RedisChannelLayer
  mode    : redis (groups shared across ASGI workers)
  hosts   :
    - redis://wpuser:***@10.0.0.12:6379/2
  capacity: 1500
  expiry  : 60s
  deps    : channels_redis=4.3.0, redis=8.1.0
```

连通性检查（会实际连接 Redis）：

```bash
python manage.py check_realtime_channels --ping
python manage.py check_realtime_channels --ping --timeout 5
```

- 成功：`PING redis://wpuser:***@10.0.0.12:6379/2 OK (1.2 ms)`，退出码 0。
- 任一 host 失败：错误写入 stderr，命令以 `CommandError` 退出（退出码非 0）。
- 输出中的 URL 会遮蔽 userinfo 密码和 `password/token/secret/auth` 等 query 参数；
  异常文本也会脱敏。
- InMemory 模式下 `--ping` 会提示跳过，不发起连接。
- 该命令仅验证 Redis TCP/认证/`PING`，不验证 Channel Layer 的 group 收发；上线前请按
  第 6 节做双 worker WebSocket 冒烟测试。

## 5. 多 worker 部署

### 5.1 Daphne 没有 `--workers`

Daphne 是单进程 ASGI 服务器（一个事件循环），没有内置多 worker 参数。要利用多核和提高
并发连接数，需要启动多个 Daphne 进程（不同端口），由 Nginx/HAProxy 做反向代理：

```bash
# 进程 1
python -m daphne -b 127.0.0.1 -p 8001 config.asgi:application

# 进程 2（同一 REDIS_URL）
python -m daphne -b 127.0.0.1 -p 8002 config.asgi:application
```

Nginx 示例（WebSocket 需要 Upgrade 头；`proxy_read_timeout` 要覆盖空闲连接）：

```nginx
upstream miwebprocess_asgi {
    server 127.0.0.1:8001;
    server 127.0.0.1:8002;
}

server {
    listen 80;
    server_name _;

    location /ws/ {
        proxy_pass http://miwebprocess_asgi;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://miwebprocess_asgi;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Redis 模式不要求 WebSocket 会话粘滞（sticky session）：WebSocket 连接建立后固定在某一个
worker，组消息通过 Redis 广播到所有 worker。客户端用 JWT `?token=...` 认证，握手落到任意
worker 都可完成。若使用 InMemory 模式，则必须只开一个 ASGI 进程并使用粘滞会话。

systemd 模板（每个实例一个 unit，替换端口与 `EnvironmentFile`）：

```ini
[Unit]
Description=MiWebProcess ASGI :8001
After=network.target redis.service

[Service]
Type=simple
WorkingDirectory=/srv/miwebprocess/backend
EnvironmentFile=/etc/miwebprocess/backend.env
ExecStart=/srv/miwebprocess/backend/.venv/bin/python -m daphne -b 127.0.0.1 -p 8001 config.asgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`/etc/miwebprocess/backend.env` 至少包含相同的 `REDIS_URL`、`CHANNEL_LAYER_*` 和数据库配置。

### 5.2 Uvicorn / Gunicorn

Uvicorn 可以自己 fork 多个 worker：

```bash
python -m uvicorn config.asgi:application --host 127.0.0.1 --port 8000 --workers 4
```

Gunicorn + UvicornWorker（不要使用 `--preload`，避免在 fork 前初始化连接池）：

```bash
gunicorn config.asgi:application \
  -k uvicorn.workers.UvicornWorker \
  -w 4 -b 127.0.0.1:8000 --timeout 120
```

容器场景下可把后端副本数扩展到多个（各自连同一个 Redis），由前置负载均衡暴露；注意
`docker-compose.yml` 当前把 backend 固定映射到 8000，扩缩容时需要改端口映射或只通过
反向代理访问容器网络。本文不修改 compose 文件。

## 6. 上线验证清单

1. 所有 ASGI worker / 容器安装 `channels_redis` 与 `redis`，并重启进程加载新代码。
2. 在每一台 ASGI 主机执行：
   ```bash
   python manage.py check_realtime_channels --ping
   ```
   确认 backend 为 `channels_redis.core.RedisChannelLayer`，hosts 正确且密码已遮蔽。
3. 启动至少两个 ASGI worker（例如 8001/8002），让前端分别连接不同端口：
   - 两个客户端加入同一个 `app_id` 房间；
   - 从其中一个发送实时消息，确认另一个也能收到（跨进程广播）；
   - 观察在线人数（presence）在两个连接上一致（依赖 Redis 缓存）。
4. 断开其中一个 worker 的 Redis 或重启 worker，确认其余 worker 的 HTTP 服务不受影响；
   WebSocket 客户端应能自动重连，重连后重新加入组。

## 7. 容量、过期与可靠性

- `capacity` 是每个 channel 的待处理队列上限（不是字节数）。过小在突发流量下会造成
  消息丢弃/ChannelFull，过大增加 Redis 内存；按实际消息速率和消费者处理能力压测后调整。
- `expiry` 是消息在 Redis 中的存活秒数。过小会让慢消费者错过消息，过大在 worker 崩溃时
  留下更多残留在途消息。
- Channels 的组消息是**尽力而为**的实时广播，不保证持久化/重放。业务关键消息应落库
  （项目已有 `RealtimeMessage`），前端断线重连后通过 API 拉取最近消息。
- Redis 是实时链路的单点：建议启用 Redis 主从/哨兵/集群、持久化策略与监控；`REDIS_URL`
  可以指向高可用地址。Channel Layer 数据是瞬态的，Redis 重启后组状态会重建（客户端需重连）。
- 不要把 Channel Layer 与使用 `allkeys-lru` 淘汰策略的缓存混用；建议独立 DB/实例并设置
  `maxmemory-policy noeviction`，避免 group/channel key 被提前淘汰。
- 当前 settings 用同一个 `REDIS_URL` 作为缓存、Celery broker/result 和 Channel Layer。
  高负载时建议后续拆分独立 URL/DB；在此之前至少确认 Redis 内存和连接数足够。

## 8. 安全

- Redis 不要暴露到公网；使用防火墙/安全组限制到 ASGI 与 Celery 主机。
- 启用 `requirepass` 或 ACL，生产使用 `rediss://` + 证书校验。
- `check_realtime_channels` 会遮蔽密码与敏感 query 参数，但环境变量本身仍应通过
  secret 管理注入，不要打进镜像、日志或提交到 Git。
- WebSocket 认证仍由 consumer 校验 JWT 与 app 成员身份；Redis 只承载广播，不替代授权。

## 9. 回滚

如果需要从 Redis 模式回滚：

1. 先停止多余的 ASGI worker，只保留**一个**进程，避免 InMemory 模式下跨进程丢消息。
2. 移除/清空所有 worker 的 `REDIS_URL` 并重启。
3. 注意此时 Celery 也会切回 eager 模式，缓存变为每进程 LocMem；生产环境通常不建议
   直接回滚到内存模式，优先修复 Redis 或切换到高可用 Redis。
