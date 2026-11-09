# harness-server 架构

> 后端（Fastify + zod + Drizzle/SQLite）的结构与约束。决策编号（D4、D7、D24–D26 等）见 `docs/framework-decisions.md`。
>
> 这个包的**约束大部分写在代码注释里**，而注释在改代码时最容易被忽略。这里把"什么在哪儿、为什么在那儿、改的时候要注意什么"集中成一处。每条结论都能在指出的文件里找到依据；没有依据的一律标"待确认"。

---

## 1. 这一层负责什么

| 负责 | 依据 |
|---|---|
| 框架自有数据的持久化与 CRUD：工作区、专家、模型配置、Agent 代理配置 | `src/routes/*.ts` 共 33 个处理器 |
| 前端静态托管（生产态）与 SPA 深链接回退 | `src/app.ts:79-80`、`src/app.ts:129-136` |
| 模块清单扫描与合法性上报 | `src/routes/modules.ts`、`src/modules/registry.ts` |
| 跨源模块的桥接会话签发 | `src/routes/bridge.ts`、`src/bridge/session.ts` |
| 密钥落盘（只写不读回明文） | `src/credentials/store.ts` |

**不负责**：模型连通性探测（`src/routes/model.ts:65-76` 返回 501）、Agent 运行本体（`framework/shared/src/contracts/agent-proxy.ts:3-4`："框架不实现 Agent 运行本身"）、用户/登录体系（D25 = A：v1 本地单用户）。

两个前提决定了后面所有安全设计：**前端同源托管**——生产态 `harness-web` 的 dist 由本服务提供，前端 API 基址是相对路径 `/api`（`framework/web/src/api/client.ts:21`），因此桥接 cookie 的 `SameSite=Lax` 在宿主页面内可用；**模块跨源接入**——D24 = A 要求模块跑在与宿主不同的源上，否则 iframe `sandbox` 无意义，校验在 `framework/shared/src/contracts/module.ts:95-103`（`same_origin_as_host`），消费在 `framework/web/src/components/module/ModuleHost.tsx:20-27`。

---

## 2. 分层与依赖方向

依赖方向：`routes → services（装配容器）→ repositories → db（SQLite + 凭据文件）`。

| 层 | 目录 | 该写什么 | 不该写什么 |
|---|---|---|---|
| 路由 | `src/routes/` | HTTP 语义：状态码、路径参数、调用仓储、抛 `AppError` | SQL、`fetch`、`process.env` |
| 仓储 | `src/repositories/` | 查询构造、行 → 契约对象映射、应用层约束（唯一性） | HTTP 概念（`reply`、状态码） |
| 桥接/凭据/模块 | `src/bridge/`、`src/credentials/`、`src/modules/` | 各自领域的状态与文件 IO | 数据库访问 |
| 装配 | `src/services/container.ts` | 建目录 → 开库 → 迁移 → 建仓储 | 业务逻辑 |
| 配置 | `src/config/` | 环境变量解析、路径解析 | 被其它层绕过直接读 `process.env` |

**依赖是单向的**：`routes` 只经 `app.services`（`src/plugins/services.ts:12-20` 的模块类型增强）拿到仓储，不直接 `import` 仓储类。这样测试能用临时库整体替换容器（`tests/helpers/context.ts:39-41`）。

**校验发生在两处**：**HTTP 入口**——路由的 `schema` 用契约层的 zod schema（如 `src/routes/expert.ts:24` 的 `expertListQuerySchema`），经 `validatorCompiler`（`src/app.ts:71`）在处理函数之前执行，失败即 422；**契约层解析**——`harness-shared` 的 zod schema 自带 `.default()`/`.transform()`/`.trim()`，所以 `request.body` 拿到的已是补过默认值的对象，路由里不必再写 `?? 默认值`（`framework/shared/src/contracts/model.ts:49-59`）。

`src/http/validation.ts` 单独存在的原因：zod/fastify 的原始 issue 只有机器码，而前端表单需要"哪个字段、用哪个 i18n 键、服务端兜底文案"三件事（`src/http/validation.ts:20-27`）。

---

## 3. 请求生命周期

启动顺序在 `src/index.ts:14-21`：**读配置 → 建目录/开库/迁移（`createServices`）→ 首次种子 → 装配 → 监听**。

插件注册顺序在 `src/app.ts:71-136`，其中两处是**有意的**，改动前先读注释：

```ts
// src/app.ts:74-96
decorateServices(app, services);
const serveSpa = config.webDistDir !== null;
installErrorHandler(app, { serveSpa });          // 必须在任何 register 之前
await app.register(cors,   { origin: config.corsOrigins, credentials: true });
await app.register(cookie, { hook: 'onRequest' });
await app.register(rateLimit, { max: RATE_LIMIT_MAX, timeWindow: RATE_LIMIT_WINDOW });
```

- `installErrorHandler` 提前到最前面：之后再装的话，带 prefix 的路由插件已建立各自的子上下文，异常会落到 Fastify 默认处理器（`src/app.ts:6-9` 记录了"曾经实际踩过"）。
- `@fastify/swagger` 必须在所有路由之前，否则收集不到 route schema，文档页为空（`src/app.ts:10-11`）。

一次请求：`onRequest`（cookie 解析、rate-limit 计数）→ 路由匹配（params/querystring/body zod 校验，失败即 422 信封）→ handler（失败抛 `AppError`）→ `sendOk`/`sendPaged`/`sendError` 构造信封；未捕获异常与未匹配路由由 `setErrorHandler`/`setNotFoundHandler` 兜底，**仍是同一信封**。

`src/app.ts:129-136` 的静态托管用 `wildcard: false`：交给 404 处理器决定单页回退，否则未命中路径会被静态插件直接判 404，SPA 深链接刷新白屏（`tests/error-handler.test.ts:106-110`）。

---

## 4. 响应信封与错误模型

**每个响应都是同一形状**，包括 404 与校验失败（`framework/shared/src/envelope.ts:18-52`）：

```ts
{ success: true,  data: T,   error: null,     meta: PageMeta | null }
{ success: false, data: null, error: ApiError, meta: PageMeta | null }
```

`meta` 未分页时是 `null` 而非缺省，客户端不需要做 `'meta' in res` 判断（`envelope.ts:5`）。分页信息全在 `meta`，`data` 只是 `{ items }`（`src/http/reply.ts:17-26`）。

路由**不允许**裸 `reply.send({...})`：绕过信封后前端就得对两种形状做分支（`src/http/reply.ts:5-6`）。

### 错误码与状态码

映射表只有一份，在 `framework/shared/src/errors.ts:28-41`。**路由不自行指定状态码**，`sendError` 按错误码查表（`src/http/reply.ts:29-31`）。

| 错误码 | HTTP | 来源 |
|---|---|---|
| `VALIDATION_FAILED` | 422 | zod 校验失败（`error-handler.ts:64-74`） |
| `NOT_FOUND` / `CONFLICT` / `UNAUTHORIZED` | 404 / 409 / 401 | `AppError.notFound/conflict/unauthorized` |
| `NOT_IMPLEMENTED` | 501 | `model.ts:74-76` 探测接口 |
| `INTERNAL` | 500 | 其余一切未捕获异常 |
| `BAD_REQUEST`/`PAYLOAD_TOO_LARGE`/`UNSUPPORTED_MEDIA_TYPE`/`RATE_LIMITED` | 400/413/415/429 | Fastify 内建错误的 `statusCode` 回落（`error-handler.ts:28-34`） |

`FORBIDDEN`、`UPSTREAM_UNAVAILABLE` 在枚举里但当前无调用点（待确认：是留给后续模块调用还是遗漏）。

### `messageKey` 为什么不是句子

`ApiError` 同时给 `messageKey`（i18n 键）与 `message`（服务端已渲染的中文兜底）（`errors.ts:6-9`）：D28 = B 要求中英双语，前端优先用 key 翻译，缺键时退化为 `message`，避免出现空白错误提示。所以 `AppError` 的三个构造参数是"错误码 / i18n 键 / 中文兜底"，`Error.message` 只进服务端日志（`errors.ts:79-80`）。

### 错误处理器兜住了什么、不泄漏什么

`src/plugins/error-handler.ts:55-93` 三条分支：`AppError` 按码映射（原始 message 只进 `warn` 日志）；zod 校验错误转成 `FieldIssue[]`（点分路径 + `validation.<code>` 键）；其余按 `statusCode` 记日志后回落（4xx 记 `info`，5xx 记 `error` 含堆栈）。

**5xx 的响应体只有 `error.internal` / "服务内部错误"，不含原始 message**（`error-handler.ts:36-40`）。`tests/error-handler.test.ts:60-72` 用一段含 `.credentials.yaml` 与 `sk-live-` 的文本做字符串包含断言，把这条钉死。未列入映射表的状态码（如库抛出的 418）**回落到 500 而非原样透出**（`error-handler.ts:84`），前端只需处理契约定义过的状态码（`tests/error-handler.test.ts:74-81`）。

### 已知取舍：没有响应 schema

`src/app.ts:13-17` 写明：只声明请求侧 schema。若逐条声明 response schema，就要为每个接口重复信封结构，且 Fastify 序列化器会按 schema 裁剪字段。代价是 OpenAPI 文档页里响应体只有通用信封说明。这是 v1 明确的取舍。

---

## 5. 数据模型

Schema 在 `src/db/schema.ts`，两条贯穿全表的约定（`schema.ts:4-9`）：列名显式 `snake_case`（契约层 camelCase，映射只发生在仓储层）；**密钥永不入库**，一律存 `*_ref`。

| 表 | 主键 | 关键字段与约束 | 索引 |
|---|---|---|---|
| `workspaces` | `id` text | `name` NOT NULL；`directory` / `default_model_id` / `default_agent_id` 可空 | 无（见下） |
| `experts` | `id` text | `tags` 存 JSON 数组；`use_count` NOT NULL；`is_preset` NOT NULL | `use_count` / `created_at` / `is_preset` / `name` 四条（`schema.ts:43-46`） |
| `model_configs` | `id` text | `api_key_ref` 可空；`temperature` / `top_p` real；`is_active` NOT NULL | 无 |
| `agent_proxy_configs` | `id` text | `token_ref` 可空；`extra` 存 JSON；`security_analyzer` NOT NULL | 无 |
| `app_state` | `key` text | 单行 kv：`value` + `updated_at` | — |

**没有唯一索引，也没有外键**。工作区名唯一由应用层保证而非唯一索引（`repositories/workspace.repository.ts:4-5`）：这样能返回带 i18n 键的 `CONFLICT`（`routes/workspace.ts:29`）而不是把 `SQLITE_CONSTRAINT` 透给用户；本地单用户没有并发建同名的现实风险。同理 `workspace.default_model_id` 可以指向不存在的模型——`tests/api-workspace.test.ts:117-139` 用假 uuid 绑定是**预期的**。

**`app_state` 为什么是 kv 表而不是给 `workspaces` 加 `is_active` 列**：v1 只有一处用途——记录"当前工作区"（需求 2.1 的切换）。它是服务端状态而非前端 localStorage，否则多标签页各自记一份、互相矛盾；而将来还会有别的单例状态（默认语言、上次打开的路由），加列会让这些语义混进工作区自身的数据里（`schema.ts:90-98`）。键名以常量给出（`repositories/app-state.repository.ts:14`），避免拼错键名静默读到 `undefined`。

**悬空指针会自愈**：`GET /api/workspaces/active` 发现 id 对应记录不在时顺手删掉指针（`routes/workspace.ts:46-51`）；删除当前工作区时写入端也清指针（`routes/workspace.ts:101-106`）。两层都做，因为读取端自愈只覆盖"已经坏了"的情况。

**迁移：drizzle-kit 生成，不是手写 DDL**。`drizzle.config.ts:9-16` 配置 `out: './drizzle'`；`pnpm db:generate` 产出 `drizzle/0000_lame_thunderbolts.sql` 与 `meta/` 快照；运行时由 `src/db/migrate.ts:21-26` 调 migrator 顺序应用，`__drizzle_migrations` 记账表保证重复启动幂等。改 schema 后要跑 `pnpm db:generate`，**不要手写** `drizzle/` 下的 SQL。

**连接**：用 `@libsql/client` 而非 `better-sqlite3`（`src/db/client.ts:2-8`）——后者是原生模块，在本项目的 Node 24（ABI 137）上加载直接 `ERR_DLOPEN_FAILED`。连接必须在退出时显式关闭，否则进程吊住不退（`services/container.ts:73-76`）。

---

## 6. 落盘约定

`$COSIGHT_HOME` 默认 `~/.cosight-harness`（`src/config/env.ts:46`）。目录布局（`src/config/paths.ts:1-10`）：

```
$COSIGHT_HOME/
├── sqlite.db            业务数据
├── .credentials.yaml    密钥，文件 0600、父目录 0700
├── .module-token        模块面令牌，单行 base64url，文件 0600
├── modules/             模块清单，一个模块一个子目录
└── workspaces/          工作区根，可用 COSIGHT_WORKSPACES_ROOT 整体覆盖（D32）
    └── _public/         公共空间，框架自用的命名空间
```

**密钥与业务数据分文件是刻意的**：备份或分享 `sqlite.db` 时不会连带泄漏密钥（`paths.ts:9`）。`tests/api-model.test.ts:66-71` 把整库文件读成字符串断言不含明文密钥。

**工作区根可以被指到 `$COSIGHT_HOME` 之外**（`COSIGHT_WORKSPACES_ROOT`，解析口径与
`COSIGHT_HOME` 完全一致）。这时权限策略跟着变：home 之内的目录一律 `0700`，
home 之外的**只创建、不 chmod**——把根指到 `/srv/projects` 的人多半有自己的一套权限模型，
框架不该去动它。这条判断在 `ensureOwnedDirectory()`，用 `path.relative` 做（不是字符串前缀比较，
否则 `/a/bc` 会被误判成在 `/a/b` 之内）。

解析与创建分开：

- `resolveDataPaths()` 是**纯函数**，只拼路径，不碰文件系统（`paths.ts:27-34`）。
- `ensureDataPaths()` 在 `createServices` 里调用，建 `home`、`modules`、`workspaces` 与 `workspaces/_public`。
  **它只建这几层框架自己的目录**；具体某个工作区的目录由 `services/workspaces.ts` 在
  `POST /api/workspaces` 时按需创建（D32）。
- **`.credentials.yaml` 不在启动时创建**——它由 `CredentialStore.#write` 在自己写入前 `ensureDirectory(父目录)`（`credentials/store.ts:151-153`）。因此全新数据目录下这个文件不存在是正常状态。
- **`.module-token` 反过来，在启动时创建**（`credentials/module-token.ts` 的 `ensure()`，由 `services/container.ts` 调）：模块面必须在框架刚起来时就能用，不能等"第一次写入密钥"才把令牌准备好。它**单独一个文件**、不塞进 `.credentials.yaml`——否则会和模型密钥共用"可被 `listRefs()` 列出、被 YAML 快照整份改写"的生命周期，还会丢掉"撤销 = 删一个文件"这个干净语义。原子写与"临时文件先以 0600 创建"两条纪律与凭据文件共用 `src/lib/atomic-file.ts` 里的同一份实现。
- 权限用 `mkdirSync(mode)` **加** 显式 `chmodSync`：mkdir 的 mode 会被进程 umask 削掉（`paths.ts:36-41`）。`ENOSYS` 之外的 chmod 错误照常抛出（`paths.ts:44-52`）。

---

## 7. 凭据与密钥

`src/credentials/store.ts` 管一个 YAML 文件，形如 `{ version: 1, secrets: { "model:<uuid>": "sk-..." } }`。引用键由 `secretRef(kind, id)` 构造，`kind ∈ {'model','agent-proxy'}`（`store.ts:26-33`）。

### 什么进 sqlite、什么进凭据文件

| 数据 | 位置 | 依据 |
|---|---|---|
| 配置元数据（provider、label、温度、额度…） | `model_configs` 表 | `schema.ts:50-66` |
| 密钥引用字符串 `model:<id>` | `model_configs.api_key_ref` | `schema.ts:57` |
| 密钥明文 | `.credentials.yaml` | `credentials/store.ts:72-81` |
| 对外可见的密钥状态 | 固定掩码 `**********`（`SECRET_MASK`） | `repositories/model-config.repository.ts:40-41` |

**为什么这样分**：库文件可以被随意复制、贴进 issue，而密钥文件权限收紧且不进版本库。写入顺序是**先密钥后数据库**（`model-config.repository.ts:9-11`）：反过来一旦密钥写失败，库里会留下指向不存在密钥的引用（静默坏数据）；先写密钥最坏只留下一个没人引用的密钥（无害，可用 `listRefs()` 清理）。

### 前端接口会不会回传密钥——明确结论

**不会。** 保证机制在映射函数而不是靠路由自觉：`apiKeyMasked: row.apiKeyRef === null ? null : SECRET_MASK`（`repositories/model-config.repository.ts:40-41`）——`Row` 里根本没有明文字段可取，`apiKeyRef` 是引用键；同理 `agent-proxy.repository.ts:43-44` 的 `tokenMasked`/`hasToken`。契约层也**没有任何字段会返回明文**（`framework/shared/src/contracts/model.ts:5-7`）。

这一点由测试从响应体层面钉死，包括**创建响应本身**——很多实现只保证"列表不回明文"，却在创建时把入参原样回显（`tests/api-model.test.ts:50-60`、`tests/api-agent-proxy.test.ts:53-62`）。

其他三条实现约束（`store.ts:6-15`）：临时文件以 0600 创建，**不是**创建后再 chmod（后者会留下一个短暂的世界可读窗口）；**原子写** = 写临时文件 → `fsync` → `rename`（`store.ts:159-170`），进程中途被杀不会留下半截 YAML；**进程内串行**，写操作挂在一条 promise 链上且本次失败不让链条断掉（`store.ts:95-105`）——**跨进程并发未做文件锁，v1 不支持多实例**。

「看不懂的文件必须报错」是刻意的：顶层不是映射、`secrets` 不是映射、YAML 语法错都会抛 `CredentialsError`（`store.ts:118-149`）。否则下一次 `set()` 会把用户原有内容整体覆盖，造成静默数据丢失。

### 模块面会回传明文密钥——两面为什么能共存

上面那条"前端接口永不回传明文"是**浏览器面**（`/api/models/*`）的契约。框架另有一张脸——
**模块面** `/api/framework/v1/models/*`——它**回传明文 `apiKey`**，因为本机其他模块进程要拿真实
密钥去起自己的模型客户端（那些适配器最终要 `ANTHROPIC_API_KEY` 这类环境变量）。

两面能共存，靠的是四条各自独立、互不影响的安排：

| | 浏览器面 | 模块面 |
|---|---|---|
| 明文 | 永远没有（只有 `SECRET_MASK`） | 详情、`/active`、以及**写操作的响应**有 |
| 投影函数 | `repositories/model-config.repository.ts` 的 `toModelConfig()` | `services/module-models.ts` 的 `ModuleModelService` |
| 门禁 | 无（D25 = A） | 回环校验 + `$COSIGHT_HOME/.module-token` 令牌 |
| 契约 | `framework/shared/src/contracts/model.ts` | `framework/shared/src/contracts/module-model.ts`（**不经 barrel 导出**） |

**关键是"没有共享代码可以同时坏掉两面"**：两面的投影函数在两个文件里，`ModelConfigRepository`
甚至**没有**一个返回明文的兄弟方法——不是靠注释提醒后来者别在同一个文件里顺手加一条，
而是那条路根本不存在。同理，模块面的契约**不写进** `contracts/index.ts` 与 `shared/src/index.ts`
（两者都是 `export *`），前端唯一入口 `harness-shared` 看不到它；
`tests/module-contract-isolation.test.ts` 把这个"看不到"变成了断言。

**写接口（D33）没有松动上面任何一条。** 模块面的 `POST` / `PATCH` / `DELETE` 复用**同一个**
`ModelConfigService`，差别只在投影：它们返回 `ModuleModelService` 的 `#toSecret()` 而不是
`toModelConfig()`。浏览器面"永不回传明文"是**签名级**保证的——那条路径根本不经过模块面的投影。

门禁的实质是**"能读到本机 0600 文件"**——浏览器里跑的代码做不到这件事，所以这枚令牌挡住的是
浏览器（含 XSS 与 DNS rebinding），不是同机同用户的其他进程。完整说明与残余风险见
`framework/docs/module-facing-api.md`。

### 模块面的门禁挂在哪一层

`routes/module-face.ts` 是模块面**唯一**的插件：它自己挂 `onRequest` 门禁，再在内部注册
`/models` 与 `/workspaces` 两个子树。`app.ts` 只 `register` 这一个插件
（`prefix: MODULE_FACE_BASE_PATH`）。

上提这一层的理由是**失败形态**：漏挂门禁**不会报错**——它只是静默多出一个不需要认证的
读写接口，直到有人来读密钥。挂在一个父插件上之后，往模块面加第四条子树时门禁自动继承，
结构上无法忘记。`app.ts` 里那段"不要改成逐个注册子路由"的注释就是为了保住这一点。

`tests/api-module-token.test.ts` 用"不带令牌打 `/workspaces` 也是 401"把"门禁是继承来的"
变成了断言——否则这条纪律只是一句注释。

### 工作区为什么不需要两套投影

工作区**没有密钥**，所以模块面与浏览器面返回的形状**完全一样**，直接复用 `Workspace` 契约
（`contracts/workspace.ts` 是公开 barrel 的一部分）。给两个面各写一套投影只会多一份要同步的形状。
需要分开的从来不是"数据有几个面"，而是"**同一份数据里有没有必须互斥的字段**"——
模型有（明文 vs 掩码），工作区没有。

工作区真正需要共享的是**业务规则**（名字唯一性、删当前工作区要清指针、建目录），
所以它们被提到 `services/workspaces.ts` 一处，两个面的路由都退化成
"校验入参 + 调服务 + 包信封"。规则见 `framework/docs/workspace-design.md`。

---

## 8. 桥接鉴权（D25 = A）

场景：模块跑在另一个源的 iframe 里（D24），要调框架 API，而 v1 没有登录体系。身份靠一次性令牌换取。

**代码注释里描述的三步流程**（`src/bridge/session.ts:4-10`）：

```
宿主 POST /api/bridge/token        → { token, exchangeUrl }
宿主 postMessage(host:init, token) → 令牌走消息通道，不进 URL
模块 POST exchangeUrl { token }     → 令牌作废，换回会话 cookie
模块后续请求带 cookie               → 即可访问 API
```

令牌不进 URL 的原因：查询串会被 `Referer` 带出去、进浏览器历史、进反代日志（`session.ts:12-14`）。协议类型定义在 `framework/shared/src/bridge.ts:36-52`（`host:init` 带 `bridgeToken`）。

> **注意**：当前**宿主侧没有实现这套 postMessage 流程**。`framework/web/src/components/module/ModuleHost.tsx:20-24` 明确写着"宿主不代模块做桥接会话""不做 postMessage 协议"，只把 `locale` 通过 URL 参数传给 iframe。也就是说第 2 步及之后的链路目前没有实现方。详见第 15 节。

### 服务端行为（已实现部分）

| 接口 | 行为 | 依据 |
|---|---|---|
| `POST /api/bridge/token` | 把请求头 `origin`（可为 null）记进令牌；返回 `{ token, expiresAt, exchangeUrl }` | `routes/bridge.ts:36-45` |
| `POST /api/bridge/exchange` | 校验并消费令牌，签发会话；同时设 cookie + 在响应体回 `{ sessionId, expiresAt }` | `routes/bridge.ts:47-66` |
| `GET /api/bridge/session` | 从 cookie **或** `Authorization: Bearer` 取候选值校验 | `routes/bridge.ts:68-80` |
| `POST /api/bridge/logout` | 吊销会话并清 cookie | `routes/bridge.ts:82-89` |

令牌性质（`src/bridge/session.ts`）：

- **一次性**：`exchange` 命中后立即 `#tokens.delete`，无论成功与否都消费掉（`session.ts:78`）——否则攻击者可以反复试来源（`tests/bridge-session.test.ts:60-66`）。
- **有期限**：令牌 TTL 60 秒（`session.ts:24`）；会话 TTL 12 小时（`session.ts:26`）。
- **与来源绑定**：`mintToken(origin)` 记录来源，`exchange` 时若记录非 null 则必须全等（`session.ts:83-85`）。
- **熵**：令牌 32 字节（256 位）`base64url`（`session.ts:63`）；会话 id 是 `randomUUID()`（`session.ts:87`）。
- **只存内存**：`#tokens`/`#sessions` 都是 `Map`，重启即失效（`session.ts:17-18`）；过期清理不另起定时器，签发令牌时 `#sweep()` 顺带扫（`session.ts:111-124`）。

cookie 属性按代码（`routes/bridge.ts:54-63`）：`path=/api`、`httpOnly: true`、`sameSite: 'lax'`、**`secure: false`**、`maxAge` 按会话剩余秒数。`secure: false` 是 D25 已知并接受的取舍：v1 是 `http://localhost` 本地访问，开启 `Secure` 会导致 cookie 根本不下发。会话同时以 cookie 和响应体两种形式给出（`routes/bridge.ts:10-14`）——跨源 iframe 发起的请求属于跨站，浏览器不会带 `SameSite=Lax` 的 cookie，此时模块改用 `Authorization: Bearer <sessionId>`。

### 这不是访问控制边界

`routes/bridge.ts:6-9` 写明：v1 无登录，能连上端口的人都能直接调 API；令牌解决的是"跨源模块如何拿到一个可验证身份"，不是"挡住未授权访问"。**默认监听 `0.0.0.0`（所有网卡）**（`env.ts:13-14`），所以默认的信任范围不再等于"本机进程"——同网段能连到端口的人都在范围里；只有显式设 `COSIGHT_HOST=127.0.0.1` 才回到"信任范围 = 本机进程"。工作区文件浏览、目录选择器与模型面里的敏感接口另有回环门禁，见 §7 与 `http/loopback.ts`。

**模块面令牌就是这条信任边界的具象化**（`src/credentials/module-token.ts`）：既然信任范围是本机进程，
那么"本机某个文件里的秘密，只有本机进程读得到"就是与它匹配的唯一凭证形式。它落在
`$COSIGHT_HOME/.module-token`（0600，父目录 0700），框架启动时创建、**存在即沿用不轮换**；
`verify()` **每个请求重读文件、不缓存**，所以 `rm` 掉文件就立即全部 401，改完也立即生效、不用重启。
浏览器读不到本机文件，这就是它挡住浏览器的全部机制。

> **两枚都叫 `Authorization: Bearer`，但互不通用。** 桥接用的是内存里的会话 id（第 8 节上半部分），
> 模块面用的是磁盘上的那份令牌，二者是不同资源上的不同凭据方案。模块面**不接受**桥接会话——
> "有 iframe 会话就能读明文密钥"是不成立的。用 `Authorization` 而非自定义头，是因为
> `app.ts:66` 的 pino `redact` 已经覆盖了 `req.headers.authorization`：这条保护本就存在且已被测试覆盖，
> 自定义头则意味着每次都要记得补 `redact`，漏一次就是静默泄漏。

---

## 9. 模块注册表

`src/modules/registry.ts` 扫描 `$COSIGHT_HOME/modules/<id>/module.json`（`registry.ts:30-46`）：

1. `readdirSync` 只取**目录**，拼成 `<dir>/module.json`，过滤掉不存在的文件；目录不存在（`ENOENT`）返回空列表，**不报错**。
2. `JSON.parse` 失败 → 收集为 `invalid`，不抛出。
3. `moduleManifestSchema.safeParse`（`framework/shared/src/contracts/module.ts:46-60`）：`id` 只允许小写字母/数字/连字符、`entry`/`allowedOrigins`/`healthcheck` 必须是 `http(s)`（`primitives.ts:14`）、`mounts` 至少一项。
4. `validateModuleManifest(manifest, hostOrigin)` 校验 D24 跨源要求（`module.ts:79-149`）：`entry` 的源必须在 `allowedOrigins` 内（否则 `origin_not_allowed`）；**不得等于宿主源**（否则 `same_origin_as_host`）；`allowedOrigins` 每项必须是**纯源**（带路径/查询串报 `not_a_bare_origin`）且不得重复；`mounts` 里同一 capability 不得重复挂载。

**非法模块如何上报**：`GET /api/modules` 返回 `{ modules, invalid }`（`routes/modules.ts:15-19`），`invalid[]` 带**清单文件绝对路径**与问题清单（`registry.ts:19-23`）。接口**不因坏清单返回 500**——否则某个可选模块多一个逗号会让整个平台空白，而真实原因无从获知（`registry.ts:5-8`、`tests/api-modules.test.ts:69-83`）。

**`pickModuleForCapability` 的择优规则**（`module.ts:151-167`）：同 capability 有多个模块声明时取 version 更高者，version 相同则按 `id` 字典序；semver 只比较 `major.minor.patch`，忽略 prerelease/build 后缀。该函数**只在前端被调用**（`ModuleHost.tsx:34`），服务端 `/api/modules` 返回原始列表与 `invalid`，不替前端做选择。

**扫描的是运行时目录，不是仓库**：`{ modules: [], invalid: [] }` 是干净检出下的正常结果
（`registry.ts:9-11`），不是错误——清单要 `cp` 到 `$COSIGHT_HOME/modules/<id>/module.json` 之后
才被看到。仓库里的清单真源放在 `docs/modules/*.module.json`，接入方式与字段说明见
`docs/module-integration-smart-factory.md`；那份文件不是代码，因此由
`tests/module-manifests-doc.test.ts` 保证它始终是合法清单。

---

## 10. 跨源与限流

### CORS（`src/app.ts:82-85`）

```ts
await app.register(cors, { origin: config.corsOrigins, credentials: true });
```

- `corsOrigins` 默认 `['http://localhost:4310', 'http://127.0.0.1:4310']`（`env.ts:84`，开发态 Vite），可用 `COSIGHT_CORS_ORIGINS` 逗号分隔覆盖（`env.ts:76-92`）。
- `credentials: true` 允许跨源请求带 cookie——这是跨源模块用 cookie 通路的前提。

**两处需要注意**：

1. 默认值**不含模块的源**。跨源模块（如 `:5174`）调 `POST /api/bridge/exchange` 需要把它的源加进 `COSIGHT_CORS_ORIGINS`，否则会被浏览器 CORS 拦掉。
2. `readOrigins`（`env.ts:76-92`）**不做归一化**，与 `readHostOrigin`（`env.ts:99-109` 会 `new URL().origin`）不一致。填成 `http://localhost:4310/`（带尾斜杠）时浏览器 `Origin` 头不带斜杠，会静默不匹配。

### 模块面不受 CORS 影响——也不要给它加源

模块面 `/api/framework/v1/models/*` 的调用方是**本机进程**（服务端到服务端），本来就不经过浏览器，
CORS 对它完全不起作用。它自己的门禁是回环校验 + 令牌（第 8 节）。

**因此 `corsOrigins` 里不该出现任何模块的源，这一条被有意做成硬拒绝**：模块面要求
`Origin` 头缺失，而浏览器发的请求必然带 `Origin`——所以"把模块的源加进 `corsOrigins`"
既不会让模块面变得可用，又会扩大浏览器可读面，是纯粹的单向损失。

> 上面第 1 条说的是**跨源模块的前端页面**调 `POST /api/bridge/exchange`——那确实是浏览器发的请求，
> 确实要加源。两件事容易混：桥接是"模块的前端 → 框架"，模块面是"模块的后端 → 框架"。

### 限流（`src/app.ts:45-47`、`src/app.ts:93-96`）

```ts
const RATE_LIMIT_MAX = 600;
const RATE_LIMIT_WINDOW = '1 minute';
await app.register(rateLimit, { max: RATE_LIMIT_MAX, timeWindow: RATE_LIMIT_WINDOW });
```

取值偏宽是刻意的：本机单用户，前端滚动加载是正常流量（`app.ts:45`）。作用范围是**所有路由**——`@fastify/rate-limit` 的 `global` 默认为 `true`，插件通过 `onRoute` 钩子给其后注册的每条路由挂上限制，而 `rateLimit` 注册在所有路由插件之前（`app.ts:93`），因此健康检查、API、文档页、静态资源都在内。

计数键用库默认的 `request.ip`。本项目 `trustProxy: false`（`app.ts:68`），所以 `request.ip` 是 socket 地址——本机访问时所有客户端**共用同一个桶**（待确认：这是否是预期效果）。

---

## 11. 种子数据

两条路径，共用 `seedPresetExperts`（`src/seed/seed.ts:21-44`）：

- **启动时自动跑**：`src/index.ts:19`，返回值只用于日志，不阻断启动。
- **CLI**：`pnpm db:seed [-- --force]`（`package.json:16` → `src/seed/run.ts`）。

**幂等性**：`seedPresetExperts` 先 `count()`，表非空且未传 `force` 时直接返回 `{ inserted: 0, skipped: true }`（`seed.ts:25-28`）。预置内容是随框架分发的，用户删掉一条就代表他真的不想要它，服务重启不该把它塞回来（`seed.ts:4-6`）。

**`--force` 不删旧数据**，只是无条件再插入一遍，因此重复执行会得到重复项（`run.ts:4-6`）。要对齐出厂状态需先清空数据目录——不做成"清空后写入"是因为这条命令在开发机上跑，一个手滑的删除太贵。

**预置专家从哪来**：`src/seed/data.ts:17-114`，12 条硬编码的 `CreateExpertInput`，署名统一为 `PRESET_AUTHOR = 'ZTE AI Lab'`。它们是**随框架分发的内置内容，不是测试假数据**——`预置` 页签没有它们永远是空的（`data.ts:3-5`）。名称与描述写中文而不做双语：`Expert.name`/`description` 在契约里是普通字符串（用户内容），不是 `LocalizedText`（`data.ts:7-9`）。

两个初始化细节：创建时间间隔 1 分钟（`seed.ts:19`、`seed.ts:34`），避免同一毫秒导致 `最新` 排序退化成 id 序；使用次数递减填充（`seed.ts:36-39`），让 `最热` 的顺序与数组顺序一致。种子是唯一使用 `setUseCount` 的地方——它和 `recordUse` 的区别是刻意的：前者"给内置内容一个初始热度"，后者"发生过一次使用"（`repositories/expert.repository.ts:132-138`）。

---

## 12. 如何新增一个接口

以给专家加一个"按标签统计"接口为例：

1. **契约放 `framework/shared/src/contracts/<域>.ts`**，不在服务端定义。入参用 zod schema 并 `z.infer` 出类型；响应对象也定义 schema。为什么：契约不做构建（`framework/shared/src/index.ts:1-10`，`exports` 直接指向 `src`），改动即刻对两端可见，不存在"改了 schema 忘了重新构建"的漂移。
2. **仓储加方法**（`src/repositories/<域>.repository.ts`）。排序必须带唯一兜底列（`id`），否则同分记录跨页会重复或遗漏（`expert.repository.ts:10-12`）。
3. **路由注册**：`app.get(..., { schema: { tags: [TAG], querystring: ... } }, handler)`。每个路由**必须带 `schema.tags`**，否则会挤在 OpenAPI 的 default 分组下（`routes/health.ts:8-11`）；返回用 `sendOk`/`sendPaged`，错误抛 `AppError.notFound/conflict/...` 而**不指定状态码**；部分更新区分 `undefined`（不改）与 `null`（显式清空），仓储里逐字段 `if (patch.x !== undefined)`（`workspace.repository.ts:74-88`）。
4. **新前缀**：在 `src/app.ts:121-127` 加 `app.register(xxxRoutes, { prefix: '/api/xxx' })`，并在 `src/app.ts:106-114` 的 `tags` 数组加分组描述。OpenAPI **自动生成**，路由 schema 经 `jsonSchemaTransform`（`app.ts:116`）转换，无需手写。
5. **测试**：集成测试放 `tests/api-<域>.test.ts`，用 `tests/helpers/context.ts` 的 `createTestContext()` 拿独立数据目录与真实 sqlite，断言**信封**而不只是 `data`。

`tests/api-app.test.ts:109-120` 是一条兜底断言：文档里每个 operation 都必须有非空 `tags`，新增接口忘写 tag 会让它红。

---

## 13. v1 明确不做的事

| 不做 | 代码依据 |
|---|---|
| 模型连通性探测 | `routes/model.ts:65-76` 如实返回 501。除"要不要做"未决策（D21 = C）外，`baseUrl` 由用户填写，服务端拿它发请求就是 SSRF 路径（可打内网、云元数据端点），真要做必须先过地址白名单与内网段黑名单 |
| Agent 运行本体 | `framework/shared/src/contracts/agent-proxy.ts:3-4`：框架只负责配置下来并显示 |
| 多用户 / 登录 | D25 = A；`env.ts:13-14` 默认监听 `0.0.0.0`，只绑本机需显式设 `COSIGHT_HOST=127.0.0.1` |
| 模型密钥回读 | `contracts/model.ts:5-7`：契约里没有任何字段会返回明文 |
| 前端调用创建专家接口 | `routes/expert.ts:30-34`：v1 前端不调用它，按 D14 跳到 Agent 开发模块创建；接口保留给种子、测试与后续模块回写 |
| 多实例部署与外部依赖（Redis / Postgres / 队列） | `credentials/store.ts:13-14`：跨进程并发未做文件锁；依赖清单只有 `package.json:18-32` 列出的项，存储是单文件 SQLite，会话是进程内 `Map` |
| 模块健康检查（`healthcheck` 字段） | `contracts/module.ts:59` 定义了字段，**服务端与前端均不消费它**（`/api/modules` 原样返回，`ModuleHost` 不探活）。唯一的消费点是框架的启动脚本 `framework/scripts/lib/module-probe.mjs:115-119`——它自己就注明了是"全仓库的第一个消费点"（`module-probe.mjs:10`）。**注意区分**：不是"没人消费"，而是"只有启动脚本消费"，且探活失败不影响启动与退出码（`framework/scripts/start.mjs:17-18`） |

---

## 14. 配置项一览表

全部在 `src/config/env.ts:119-137` 解析一次。散落的 `process.env.X` 会让"某个配置没设"变成运行期 undefined 事故，在这里 fail-fast 能在启动瞬间报出来（`env.ts:2-6`）。

| 变量 | 默认值 | 必填 | 不合法时 |
|---|---|---|---|
| `COSIGHT_HOME` | `~/.cosight-harness` | 否 | 无校验；经 `path.resolve` 归一 |
| `COSIGHT_DATABASE_URL` | `file:<cosightHome>/sqlite.db` | 否 | 无校验（libsql URL 需绝对路径，见 `db/client.ts:28-34`） |
| `COSIGHT_WORKSPACES_ROOT` | `<cosightHome>/workspaces` | 否 | 无校验；经 `path.resolve` 归一，口径与 `COSIGHT_HOME` **完全一致**（不展开 `~`）。指到 home 之外时不改该目录权限（D32） |
| `COSIGHT_HOST` | `0.0.0.0` | 否 | 无校验；只绑本机写 `127.0.0.1` |
| `COSIGHT_PORT` | `4300` | 否 | `ConfigError`，启动失败（1–65535，`env.ts:55-64`） |
| `COSIGHT_WEB_DIST` | 开发态 `null`；生产态 `<cwd>/public` | 否 | 无校验；给了就 `path.resolve`（`env.ts:111-117`） |
| `COSIGHT_CORS_ORIGINS` | `http://localhost:4310,http://127.0.0.1:4310` | 否 | 无校验；逗号切分、丢弃空项、**不归一化**（`env.ts:76-92`） |
| `COSIGHT_HOST_ORIGIN` | `http://<host>:<port>`（host 为 `0.0.0.0` 时取 `127.0.0.1`） | 否 | `ConfigError`；经 `new URL().origin` 归一成纯源（`env.ts:99-109`） |
| `COSIGHT_LOG_LEVEL` | `info` | 否 | `ConfigError`（白名单 `fatal\|error\|warn\|info\|debug\|trace\|silent`，`env.ts:66-74`） |
| `NODE_ENV` | — | 否 | `=== 'production'` 时置 `isProduction`，决定前端产物默认目录 |

`src/version.ts:10` 的 `SERVER_VERSION = '0.1.0'` 用常量而非 `process.env.npm_package_version`（后者只在 `pnpm start` 下存在，会让健康检查在两种启动方式下返回不同的东西）；它和 `package.json` 的一致性由 `tests/version.test.ts` 钉住。

---

## 15. 已知缺口与不一致

诚实标注，供后续批次处理。第 2、5 条已在源码中修正，此处按修正后的现状记录；第 1、3 条仍是缺口。以上均按代码现状写结论，若决策者另有意图，以决策为准。

1. **桥接的宿主侧未实现**（上文第 8 节）。`src/bridge/session.ts:1-19` 与 `framework/shared/src/bridge.ts:36-52` 描述/定义了 `postMessage(host:init, bridgeToken)` 流程，但 `framework/web/src/components/module/ModuleHost.tsx:20-24` 明确不做 postMessage、不代模块换会话。服务端接口（`/token`、`/exchange`、`/session`、`/logout`）本身是完整且已测的；缺的是调用方。
2. **服务端没有词典目录（`framework/server/src/i18n/` 不存在）——已修正为一致**。原 `framework/shared/src/locale.ts` 文件头注释指向该不存在的目录（`grep -rn i18n framework/server/src/` 只命中注释）。事实形态不变：服务端的 `message` 是 `AppError` 各工厂里硬编码的中文（`framework/shared/src/errors.ts:103-136`），`messageKey` 只是发给前端的键，服务端不做翻译。**注释已改写为与实现一致**（`locale.ts:1-7`）：词典只有前端有（`framework/web/src/i18n/messages/`），服务端只给键。
3. **`settings-schema.ts` 定义了但没有接线**。`framework/shared/src/contracts/settings-schema.ts` 的 `settingsFieldSchemaSchema` 目前**只被它自己的测试引用**，服务端与前端都没有消费点；`moduleManifestSchema`（`module.ts:46-60`）也**没有** settings 字段。而 `contracts/agent-proxy.ts:8-10` 写着"模块自己在 manifest 里声明它需要的设置字段（见 settings-schema.ts）"——这条路径尚未打通。
4. **`readOrigins` 缺归一化**（第 10 节）。与 `readHostOrigin` 的处理不一致，带尾斜杠的 CORS 配置会静默失效。
5. **`routes/health.ts` 注释曾写"27 个接口"——已修正**。原注释用写死的数字解释"没有 tag 的接口会堆在 default 分组"，但数字会随新增接口过期且没人会想起来改。现改为不带数字的表述并补了一句说明（`health.ts:8-13`）。**统计本身仍然有用**：当前共 46 个处理器——health 1、workspace 7、expert 5、model 8、agent-proxy 7、modules 1、bridge 4，加上**模块面 13**（model 6 + workspace 7，`module-face.ts` 自身只挂门禁、不注册路由）（`grep -c` 逐文件统计）。
6. **响应侧没有 OpenAPI schema**（第 4 节末）。文档页里响应体只有通用信封说明——这是 `app.ts:13-17` 明确接受的取舍，不是疏漏，但会给"照着文档页写前端"的人造成不便。
7. **`FORBIDDEN` / `UPSTREAM_UNAVAILABLE` 两个错误码无调用点**（第 4 节）。待确认：预留给模块调用还是遗漏。
