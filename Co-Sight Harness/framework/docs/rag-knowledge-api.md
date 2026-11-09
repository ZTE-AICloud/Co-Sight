# RAG 知识库跳转路由接口

> **面向：需要把用户带到「知识库」界面的本机其他模块**（会话区、开发页等）。
> 本文自足，可直接转发——不需要读框架源码。
> 第 1–8 节是模块面（只读，需令牌）；第 9 节是设置面的写入接口（框架自用，
> 模块作者可以跳过）。
> 状态：已实现（2026-10-27；2026-10-28 加入模块用的 Agent API Key）。
>
> 同一套基址、同一枚令牌、同一道门禁下还有模型与工作区两组接口，见
> [`model-config-api.md`](model-config-api.md) 与 [`workspace-api.md`](workspace-api.md)。
> 框架侧的完整说明（含内部取舍）见 [`module-facing-api.md`](module-facing-api.md)。

## 1. 一句话

用户在框架的「设置 → 知识库路由设置」里维护若干条「名称 + 跳转地址（+ 可选的登录账号密码、
+ 可选的 Agent API Key）」，其中**至多一条生效**。你的模块只要取那一条，把用户导过去；
一个 `GET` 就够，**没有写接口**。

框架自己也是这条数据的消费方：左侧「知识库」菜单点下去，宿主在**新的浏览器标签页**里打开
当前生效的那条地址；一条都没配时，它直接把用户送到「设置 → 知识库路由设置」的新增表单。
你的模块取到地址后，用真链接交给用户在浏览器里打开即可（见第 6 节第 4、5 条）。
（宿主仍保留 `/knowledge` 路由，直接访问或旧书签会把这条地址嵌进主面板。）

## 2. 基址

```
http://127.0.0.1:4300/api/framework/v1/rag-knowledge
```

端口以框架实际监听为准。探活：`GET /api/health`（不需要令牌），返回体里的
`cosightHome` 是实际生效的数据目录，第 3 节读令牌时用得上。

## 3. 鉴权

与模型、工作区接口完全相同，三条都必须满足：

| 位置 | 要求 | 不满足 |
|---|---|---|
| 来源 | 本机回环地址；`Host` 头是 `localhost` / `127.0.0.1` / `[::1]`（可带端口） | `403` |
| `Origin` 头 | **不能带**——带了就拒，**包括你自己模块的前端页面** | `403` |
| `Authorization` 头 | `Bearer <令牌>`，只认这个头 | `401` |

令牌在 `$COSIGHT_HOME/.module-token`（默认 `~/.cosight-harness/.module-token`），
单行、`0600`。**自己读文件，不要注入成环境变量**（模块常把 `process.env` 透传给模型子进程），
并按框架同一套 `COSIGHT_HOME` 规则解析目录：

```ts
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const home = process.env.COSIGHT_HOME ?? path.join(os.homedir(), '.cosight-harness');
const token = fs.readFileSync(path.join(home, '.module-token'), 'utf8').trim();
```

## 4. 两个端点

| 方法 | 路径 | 返回 |
|---|---|---|
| `GET` | `/api/framework/v1/rag-knowledge` | 全量列表（`createdAt` 升序） |
| `GET` | `/api/framework/v1/rag-knowledge/active` | 当前生效的一条；**没配置时 `200 + data: null`，不是 404** |

列出全部只在"让用户自己选一条"时才有意义——多数模块只需要 `/active`。

两个端点在**凭据**上分工不同，和模型接口一致：

| 端点 | `username` | 密码 | Agent API Key |
|---|---|---|---|
| 列表 | 有 | **没有**。只有 `hasPassword` | **没有**。只有 `hasApiKey` |
| `/active` | 有 | **明文** `password`（没配就是 `null`） | **明文** `apiKey`（没配且服务端也没默认就是 `null`） |

明文只出现在 `/active`：要登录知识库、或要调知识服务 Agent API 的模块，拿到地址的同时
就得拿到凭据，而"列出全部"只是给用户挑一条，用不上。**拿到之后按凭据对待**——只放在
内存或自己模块的配置里，不要写进日志、不要塞进 URL、不要回传给浏览器以外的进程。

### API Key 的两层

| 层 | 存在哪 | 谁配 | 谁看得见 |
|---|---|---|---|
| 单条路由的 Key | `$COSIGHT_HOME/.credentials.yaml`（`rag-knowledge-api-key:<id>`） | 用户在设置里填 | 模块面 `/active` 的明文 |
| 服务端默认 | 环境变量 `COSIGHT_KNOWLEDGE_API_KEY`，其次 `CO_KNOWLEDGE_API_KEY` | 部署者 | 模块面 `/active`（作为那枚 `apiKey`）；浏览器面只看到 `hasDefaultApiKey` 布尔 |

`/active` 返回的 `apiKey` **永远是生效的那一枚**：这条路由自己配了就用自己的，没配就回落到
服务端默认；两层都没有才是 `null`。消费方不需要自己判断该用哪一层。默认值不落库、
不回显，改环境变量即对所有没配 Key 的路由同时生效。

对 smart-factory：它读的是自己的 `CO_KNOWLEDGE_API_KEY`（`X-API-Key` 调
`/api/co-knowledge/v1/agent/workflows`）。产物布局下 `cosight.env` 里的同名变量会被框架和
模块同时继承，写一行就够；开发态在启动 `pnpm dev:all` 的 shell 里 export 同一个变量。
框架侧不代人改模块的环境配置（见 `module-integration-smart-factory.md` 第 11 节）。

```bash
TOKEN=$(cat "${COSIGHT_HOME:-$HOME/.cosight-harness}/.module-token")
API=http://127.0.0.1:4300/api/framework/v1

curl -s -H "Authorization: Bearer $TOKEN" "$API/rag-knowledge/active" | python3 -m json.tool
```

```json
{
  "success": true,
  "data": {
    "id": "3f2a8c1e-6b8d-4a2f-9c31-0d5e7b2f4a10",
    "name": "产品知识库",
    "routeUrl": "https://kb.example.com/kb/42",
    "username": "kb-reader",
    "hasPassword": true,
    "hasApiKey": true,
    "password": "kb-s3cret",
    "apiKey": "ragk_0123abcd_...",
    "description": "对外版",
    "isActive": true,
    "createdAt": "2026-10-27T09:12:31.000Z",
    "updatedAt": "2026-10-27T09:12:31.000Z"
  },
  "error": null,
  "meta": null
}
```

没配置时：

```json
{ "success": true, "data": null, "error": null, "meta": null }
```

## 5. 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | uuid | 稳定标识，可作前端缓存键 |
| `name` | string，1–64 字 | 用户起的名字，显示用 |
| `routeUrl` | string，≤2048 | **要打开的那个地址**；框架保证是 `http(s)` 绝对地址、不含内嵌账号密码 |
| `username` | string \| null | 登录账号；用户没填就是 `null` |
| `hasPassword` | boolean | 是否配了密码。两个端点都有 |
| `password` | string \| null | **仅 `/active`**。明文密码；没配就是 `null`（不是缺键） |
| `hasApiKey` | boolean | 这条路由自己有没有配 Agent API Key。两个端点都有。注意它**不代表** `/active` 里 `apiKey` 为 `null`——服务端默认会兜底 |
| `apiKey` | string \| null | **仅 `/active`**。生效的那一枚 Agent API Key（路由自己的优先，其次是服务端默认）；两层都没有才是 `null` |
| `description` | string \| null | 可空，≤256 字 |
| `isActive` | boolean | 列表里至多一条为 `true`；`/active` 返回的那条必然是 `true` |
| `createdAt` / `updatedAt` | ISO 8601 | UTC |

## 6. 使用口径（六条）

1. **「没有生效知识库」是正常态**——用户还没配，或刚删掉生效项。按 `data === null`
   处理：隐藏"去知识库"入口即可，不要重试、不要弹错误。
2. **这个面只读。** `POST` / `PATCH` / `DELETE` 在本路径上一律 `404`。写入者是设置里的
   用户，模块没有写理由；少一个写入口，泄漏的令牌就少一分杀伤面。
3. **模块的前端不能直接调**：浏览器请求带 `Origin`，会被门禁拒掉。正确姿势是模块自己的
   服务端代取、前端调自己的后端——这也让令牌只留在服务端进程里。
4. **打开用真链接**：`<a href={routeUrl} target="_blank" rel="noopener noreferrer">`。
   `noopener` 让被打开的页面拿不到 `window.opener`，`noreferrer` 不把本页地址放进 Referer。
5. **模块不要自行 iframe 内嵌。** 框架直接访问 `/knowledge` 时确实会内嵌**当前生效**这一条
   （侧栏入口已改为新标签页打开），但那是一条由本机用户在设置里显式选定的地址，
   承载它的也是与模块宿主相同的最小权限沙箱。
   模块侧拿到的可能是多条候选，`routeUrl` 本身也不受 `allowedOrigins` 约束——自行铺进
   iframe 等于把"只嵌入受信任来源"这条边界绕开。模块只用它做一件事：带用户去某个地址。
6. **密码只从 `/active` 取，且只当密码用。** 它是明文（用户可能把知识库的登录口令填在这里），
   只在你的服务端进程里用：不要写日志、不要拼进 `routeUrl`、不要下发给浏览器；
   需要用户自己登录时，把用户带到 `routeUrl` 就好。
7. **`apiKey` 是给模块用的，不是给浏览器用的。** 它对应知识服务的 Agent API
   （smart-factory 走 `X-API-Key`）。与密码同一条纪律：只在模块服务端进程里用，
   不要下发到前端。它可能来自服务端默认，所以"用户没在这条路由里填"不等于"拿不到"。

框架**不探测** `routeUrl` 是否可达——地址可能是内网服务，服务端主动去连就成了 SSRF 的
跳板，而且"现在连不上"也不代表配置错了。可达性交给打开它的那一刻。

## 7. 错误

信封与其余模块面接口一致（`{success, data, error, meta}`）：

| HTTP | `error.code` | 何时 |
|---|---|---|
| 401 | `UNAUTHORIZED` | 没有 `Authorization`、方案不是 `Bearer `、令牌不对或文件不存在 |
| 403 | `FORBIDDEN` | `Host` 不是回环名，或来源 socket 不是回环，或带了 `Origin` |
| 500 | `INTERNAL` | 数据目录不可写等意外；按"稍后重试"处理即可 |

**401 的几种原因返回同一句话**是刻意的：区分它们等于向外泄漏本机文件系统的状态。
排查时看服务端启动日志里的令牌文件路径。

## 8. 相关代码

| 位置 | 作用 |
|---|---|
| `shared/src/contracts/rag-knowledge.ts` | 契约与上限（浏览器面与模块面共用） |
| `shared/src/contracts/module-rag-knowledge.ts` | 模块面契约：列表去掩码，`/active` 加明文 `password` / `apiKey` |
| `server/src/routes/module-rag-knowledge.ts` | 模块面两个只读端点 |
| `server/src/services/module-rag-knowledge.ts` | 模块面投影：只在 `/active` 读 `.credentials.yaml` 取明文；API Key 没配时回落到服务端默认 |
| `server/src/routes/rag-knowledge.ts` | 浏览器面（设置里用的增删改与激活） |
| `server/src/repositories/rag-knowledge.repository.ts` | "至多一条生效"的写入逻辑；密码进 `.credentials.yaml`（D26） |
| `server/src/seed/seed.ts` | 表为空时写入出厂默认路由（`DEFAULT_RAG_KNOWLEDGE`） |
| `web/src/features/rag-knowledge/` | 设置 → 知识库路由设置面板 |
| `web/src/components/shell/KnowledgeNavItem.tsx` | 侧栏「知识库」：有生效项时在新标签页打开 `routeUrl`，没有时直接打开设置里的新增表单 |
| `web/src/pages/KnowledgePage.tsx` | `/knowledge`（直接访问 / 旧书签）：把生效项的 `routeUrl` 嵌进主面板；未配置时给空态与「去设置新增」 |

---

## 9. 附录：设置面（浏览器）接口

> **读者：框架仓库内的集成方**（另做一套本机 UI、写自动化脚本、或排查设置面板的行为）。
> 模块作者可以跳过这一节——模块面只读，改配置是用户在设置里的动作。

基址：`http://127.0.0.1:4300/api/rag-knowledge`（同一进程，端口以实际监听为准）。

| 方法 | 路径 | 作用 | 成功 |
|---|---|---|---|
| `GET` | `/api/rag-knowledge` | 全量列表（`createdAt` 升序） | `200` |
| `GET` | `/api/rag-knowledge/active` | 当前生效项；没有时 `data: null` | `200` |
| `GET` | `/api/rag-knowledge/defaults` | 服务端有没有预置默认 API Key：`{"hasDefaultApiKey": boolean}`，**不含值** | `200` |
| `GET` | `/api/rag-knowledge/{id}` | 单条 | `200` |
| `POST` | `/api/rag-knowledge` | 新增 | `201` |
| `PATCH` | `/api/rag-knowledge/{id}` | 局部更新，至少一个字段 | `200` |
| `POST` | `/api/rag-knowledge/{id}/activate` | 设为可用，等价于 `PATCH {"isActive": true}` | `200` |
| `DELETE` | `/api/rag-knowledge/{id}` | 删除 | `200` |

**这一面不要令牌**。第 3 节的门禁（回环 / `Origin` / `Bearer`）只保护模块面；设置面与其余
设置接口一样，按 D25 的前提（本机单用户、只监听回环）由浏览器直接调用。不要把模块令牌
塞进这里的请求头——它既不检查，也会让日志里多出一份凭据。

### 9.1 请求体

`POST /api/rag-knowledge`：

```json
{
  "name": "产品知识库",
  "routeUrl": "https://kb.example.com/kb/42",
  "username": "kb-reader",
  "password": "kb-s3cret",
  "apiKey": "ragk_0123abcd_...",
  "description": null,
  "isActive": false
}
```

| 字段 | 必填 | 约束 |
|---|---|---|
| `name` | 是 | 1–64 字，前后空白会被 trim |
| `routeUrl` | 是 | `http(s)` 绝对地址，≤2048，**不得内嵌账号密码** |
| `username` | 否 | ≤128 字，前后空白会被 trim；空串按 `null` 存 |
| `password` | 否 | 1–2048 字，**不 trim**（尾部空格可能是密码的一部分）；空串会被拒，"不设置"用 `null` 或省略 |
| `apiKey` | 否 | 1–2048 字，规则同 `password`。留空 = 不配自己的 Key，模块面回落到服务端默认（若有） |
| `description` | 否 | ≤256 字或 `null`；省略时按 `null` 存 |
| `isActive` | 否 | 默认 `false`；`true` 会清掉原来的生效项 |

`PATCH /api/rag-knowledge/{id}`：字段语义与模型 / Agent 代理一致——**省略 = 不改**，
`null` 只用于清空 `description` / `username` / `password` / `apiKey`，其余字段给值即覆盖。
请求体不能是空对象。密码与 API Key 因此都是**三态**：不传 = 保持原值，传值 = 覆盖，
传 `null` = 清除；清掉路由自己的 Key 后会回落到服务端默认。

密码与 API Key 遵循 D26：明文只落在 `$COSIGHT_HOME/.credentials.yaml`（`0600`），数据库里只存
引用键（`rag-knowledge:<id>` / `rag-knowledge-api-key:<id>`）。这一面**永远读不回明文**——
返回的只有固定掩码（`passwordMasked` / `apiKeyMasked`: `"**********"`）与
`hasPassword` / `hasApiKey`，和模型密钥完全同一条路。

```json
{ "routeUrl": "https://kb.example.com/kb/43" }
```

### 9.2 响应

成功信封与模块面相同（`{success, data, error, meta}`）：

```json
{
  "success": true,
  "data": {
    "id": "3f2a8c1e-6b8d-4a2f-9c31-0d5e7b2f4a10",
    "name": "产品知识库",
    "routeUrl": "https://kb.example.com/kb/42",
    "username": "kb-reader",
    "passwordMasked": "**********",
    "hasPassword": true,
    "apiKeyMasked": "**********",
    "hasApiKey": true,
    "description": null,
    "isActive": true,
    "createdAt": "2026-10-27T09:12:31.000Z",
    "updatedAt": "2026-10-27T09:12:31.000Z"
  },
  "error": null,
  "meta": null
}
```

`DELETE` 返回 `{"success": true, "data": {"id": "<id>", "deleted": true}, "error": null, "meta": null}`。

### 9.3 错误

| HTTP | `error.code` | 何时 |
|---|---|---|
| 404 | `NOT_FOUND` | `{id}` 不存在（含对已删除项 `activate`） |
| 422 | `VALIDATION_FAILED` | 字段不合法（含非 `http(s)` 地址、内嵌凭据、超长）、`PATCH` 空对象 |
| 500 | `INTERNAL` | 数据目录不可写等意外 |

地址不合法是 `422`，不是 `400`：全仓库的校验错误都走同一个 `VALIDATION_FAILED`。

### 9.4 四条语义

1. **全局至多一条 `isActive: true`**。`POST`/`PATCH`/`activate` 任一方式把它设为 `true`，
   原来的生效项都会变成 `false`；数据库还有一条部分唯一索引兜底。
2. **删除生效项不自动补位**。删完就是"当前没有"（`/active` → `200 + null`），
   系统不会替用户挑下一条。
3. **不做连通性探测**。写入时不请求 `routeUrl`；能不能打开由用户的浏览器去试。
4. **删除连带清掉密码与 API Key**。删记录时 `.credentials.yaml` 里对应的
   `rag-knowledge:<id>` 与 `rag-knowledge-api-key:<id>` 一并移除，不留没人引用的孤儿凭据。
5. **服务端默认 Key 不落库**。`GET /api/rag-knowledge/defaults` 只回
   `{"hasDefaultApiKey": boolean}`；值来自环境变量 `COSIGHT_KNOWLEDGE_API_KEY`
   （其次 `CO_KNOWLEDGE_API_KEY`），只从模块面 `/active` 出去。改环境变量对所有
   没配自己 Key 的路由同时生效，不需要逐条改。

### 9.5 出厂默认

服务启动时，若表里**一条都没有**，会写入一条出厂记录并设为当前可用：

| 字段 | 值 |
|---|---|
| `name` | `知识库默认路由` |
| `routeUrl` | `http://localhost:8080/#/login?redirect=/kb` |
| `username` | `admin` |
| `password` | `admin`（只进 `.credentials.yaml`，接口读回是掩码） |

语义与预置专家、默认工作区一致：**只在表为空时写**，用户删光后再启动会重新建出来，
用户自己建过一条则完全不介入。

出厂记录**不带 API Key**：默认 Key 只来自环境变量（见 9.4 第 5 条），不会写进库或
`.credentials.yaml`。
