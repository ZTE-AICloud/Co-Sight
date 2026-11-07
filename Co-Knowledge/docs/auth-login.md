# 本地账号登录

> 入口 `frontend/src/pages/login/LoginPage.vue`；后端
> `backend/src/auth/`；契约见 `docs/api-reference.md` §11.5。
> 本页描述当前实现与运维口径。

## 1. 三种模式

| `AUTH_MODE` | 用途 | 行为 |
|---|---|---|
| `none` | 开发 / 隔离网络 | 全放行；`X-Emp-No` 缺失时用 `AUTH_DEFAULT_USER`（默认 `admin`）作为归属 |
| `local` | **推荐** | 本地账号 + HttpOnly 会话；未登录的 UI/API 请求返回 401 |
| `gateway` | 内网已有统一网关 | 只检查 `X-Auth-Value` / `X-Auth-Token` / `Authorization` 是否存在；由网关做真正鉴权 |

未知取值（包括 `jwt`）会让服务**启动失败**，不会静默放行。

## 2. 登录流程

```text
GET  /auth/status            公开；前端据此决定是否启用守卫
POST /auth/login             校验 scrypt + 限流 → Set-Cookie: ragstudio_session
  Cookie: HttpOnly; Path=/; SameSite=Lax; Max-Age=12h[; Secure]
GET  /auth/me                当前用户（401 = 会话无效）
POST /auth/password          改密；撤销其它会话
POST /auth/logout            撤销会话并清 Cookie（幂等）
```

- 会话 token 是 32 字节随机串，库里只存 SHA-256；每次请求查 `auth_session`
  并校验 `expires_at` / `revoked_at` / 用户 `enabled`。
- `must_change_password=true` 时，中间件只放行 `/auth/me`、`/auth/password`
  （以及公开的 status/login/logout），其余返回 `403 password_change_required`；
  前端守卫把用户送到 `/change-password`。
- `/agent/*` 与 `/mcp` **绕过**浏览器会话，继续使用 Agent API Key。
- 身份归属：`AUTH_MODE=local` 时 `current_user()` **只认** `request.state.auth_user`；
  `X-Emp-No` / `username` 是可伪造头，绝不回落。

## 3. 账号管理

### 3.1 首次启动

`AUTH_MODE=local` 且 `auth_user` 为空时，启动期创建 admin：

- 用户名 `RKB_ADMIN_USERNAME`（默认 `admin`）；
- 密码 `RKB_ADMIN_PASSWORD`；为空则随机生成；
- 密码写入 `RKB_ADMIN_PASSWORD_FILE`（默认 `/data/rkb/initial-admin-password`，0600）；
- `must_change_password=true`（`RKB_ADMIN_MUST_CHANGE=false` 可关闭，仅建议 E2E 自动栈）；
  首次改密成功后删除该密码文件。

密码文件写不进去时，日志会打印一次生成的密码（唯一出口），请立即改密。

显式设置的 `RKB_ADMIN_PASSWORD` **允许低于常规 8 位策略**（仅 bootstrap；CLI/改密
仍要求 8–128 位），用于运维先用一个临时弱口令把系统点起来。日志会给出 warning；
建议保持 `RKB_ADMIN_MUST_CHANGE=true`，或首次登录后立即用
`python3 -m auth.cli reset-password --username admin` 换成合规口令。

⚠️ 播种条件是“账号表为空”。如果运维把最后一个账号也删掉，下次启动会重新创建
admin（等同于重置）；不允许这种情况时请至少保留一个管理员账号。

### 3.2 CLI

容器内：

```bash
python3 -m auth.cli list
python3 -m auth.cli create --username alice --display-name 张三 --email a@x.com --generate
python3 -m auth.cli reset-password --username alice --generate [--no-must-change]
python3 -m auth.cli disable --username alice
python3 -m auth.cli enable  --username alice
python3 -m auth.cli delete  --username alice --yes
```

宿主包装：`python3 tools/user-admin.py ...`（需要与容器同一份 `RKB_DB_*`，
且通常把 `RKB_DB_HOST` 指到 `127.0.0.1`）。

规则：用户名 `^[A-Za-z0-9_.@-]{3,64}$`；口令 8–128 位；邮箱可选但唯一；
`reset-password` / `disable` / `delete` 撤销该用户全部会话。

## 4. 部署

1. 空卷由 `deploy/init/pg/00-schema.sql` 自动建账号/会话表。
2. `.env` 设置 `AUTH_MODE=local`；按需设置 `RKB_ADMIN_*`、`RKB_AUTH_*`。
3. `docker compose up -d`。`/health` 始终公开，健康检查不受影响。
4. nginx 只需一条 `/api/co-knowledge/v1/auth/` location（已内置）：把
   `client_max_body_size` 压到 `8k`；Cookie 默认透传，其余与通用后端 location 相同。

`RKB_AUTH_COOKIE_SECURE=auto` 按请求 scheme / `X-Forwarded-Proto` 决定是否加
`Secure`；**HTTP 部署不要强制 true**（浏览器会丢弃 Cookie，表现为登录后立刻回登录页）。
反向代理终止 TLS 时建议设 `true`。

## 5. 安全设计

| 项 | 做法 |
|---|---|
| 口令存储 | `hashlib.scrypt(n=2^14, r=8, p=1)` + 16B 随机盐，PHC 风格串；参数升级后登录时顺手重哈希 |
| 会话 | 32B 随机 token；库里只存 SHA-256；不滑动续期；过期/撤销/禁用即失效 |
| Cookie | `HttpOnly`、`SameSite=Lax`、`Path=/`；`Secure` 自动/可强制；token 不进 localStorage |
| CSRF | SameSite=Lax 为主；已带会话 Cookie 的 unsafe 请求必须有匹配 `Origin`/`Referer`（`Host`/`X-Forwarded-Host`），否则 403 |
| 登录限流 | 进程内滑动窗口：账号+IP 15 分钟 5 次、每 IP 15 分钟 20 次；429 + `Retry-After` |
| 账号枚举 | 密码错误一律 `invalid_credentials`；未知用户也跑一次 dummy scrypt；先验密码再看 enabled |
| 日志 | 只记用户名/IP/原因，不记口令、token、Cookie |
| 身份伪造 | local 模式忽略 `X-Emp-No`；gateway 模式要求网关剥离客户端身份头 |

## 6. 部署建议与当前能力

- **认证边界**：登录会话保护控制台与 UI API；`role` 字段记录账号角色。
  需要按用户或团队隔离数据时，建议一实例一租户部署，或在网关层做实例级访问控制。
- **资源可见性**：图谱模板与私有算子按创建者可见；`AUTH_MODE=none` 时所有请求
  都归属同一默认用户（`AUTH_DEFAULT_USER`），因此表现为全局可见。
- **单副本前提**：登录限流与会话校验在进程内完成，RKB 以单副本部署；
  多副本部署需要在网关层做会话粘滞或限流。
- **账号生命周期**：账号由管理员通过 CLI 开通、重置、停用与删除；首次启动会
  播种管理员账号，适合私有化部署的初始接入。
- **机器访问**：外部脚本使用 Agent API Key，不依赖浏览器会话（HttpOnly Cookie
  不会暴露给脚本）。

## 7. 应急处理

1. **关闭登录**：设置 `AUTH_MODE=none` 并重启 RKB；前端回到“未启用登录”模式。
2. **清理账号数据**：手动 `DROP TABLE public.auth_session, public.auth_user;`
   （会丢失全部账号）。
3. **忘记 admin 密码**：
   `python3 -m auth.cli reset-password --username admin --generate`。

## 8. 验证

```bash
# 后端
cd backend && python -m pytest tests/test_auth_*.py -q
# 全量（AUTH_MODE=none 下也必须全绿）
python -m pytest -q

# 前端
cd frontend && npx vitest run
BASE_URL=/ npm run build

# 手动
AUTH_MODE=local RKB_ADMIN_PASSWORD='ChangeMe-123' docker compose -f deploy/docker-compose.yml up -d
# #/knowledge → #/login；错误密码内联报错；正确密码回 /knowledge；刷新保持；退出回 /login；
# 连续 5 次错误 → 429；直接 GET /api/co-knowledge/v1/knowledge-bases → 401 problem+json。
```
