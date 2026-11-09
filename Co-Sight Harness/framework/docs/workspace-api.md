# 工作区接口：基址、鉴权、七个端点、以及它们怎么动磁盘

> **面向：需要从框架读写工作区的本机其他模块**（smart-factory 等），以及框架前端的维护者。
> **本文自足，可直接转发**——不需要读框架源码，也不必先读别的文档。
> 状态：已实现，已在真实环境逐条验证（2026-10-16）。下面每一个响应都是**真的抓下来的**
> （服务跑在 `127.0.0.1:4399`，数据目录隔离在 `/tmp/ws-doc-probe`，全新的空库），
> 不是照着代码手写的。
>
> 本文讲工作区。**模型配置有一份同构的对外接口文档**
> [`model-config-api.md`](model-config-api.md)——**基址、令牌、四道门完全同一套**，
> 只是子树从 `/models` 换成 `/workspaces`；两份可以一起转发。
> 框架侧的完整说明（内部取舍与残余风险）见
> [`module-facing-api.md`](module-facing-api.md)，**为什么**这么设计（slug 规则、保留名、
> 权限策略、与 deepseek-harness 的刻意分叉）见
> [`workspace-design.md`](workspace-design.md)——那两份是给框架维护者的。

## 1. 一句话

工作区**没有密钥**，所以接口很简单：七个 CRUD 端点，模块面全部挂在
`/api/framework/v1/workspaces` 之下，出示一枚本机令牌即可读写。
唯一要小心的两件事：**`POST` 会在工作区根下建一个目录**；
**`DELETE` 会删掉框架建的那个目录**（外部绑定的用户目录保留）。

> **只读的消费方请注意**：如果你只是"看看用户有哪些工作区、当前用哪个"，三条 `GET` 就够。
> 写接口的存在**不是**给你的邀请——你多要一份写权限，你的进程就多一份被利用的价值。
> 见第 11 节。

## 2. 基址

```
http://127.0.0.1:4300/api/framework/v1/workspaces
```

这一串拆成两截，两截的来源都只有一个：

| 片段 | 来源 |
|---|---|
| `http://127.0.0.1:4300` | 框架服务端实际监听的地址。默认监听 `0.0.0.0:4300`（本机访问用 `127.0.0.1`），端口可用 `COSIGHT_PORT` 覆盖（**不是** `PORT`） |
| `/api/framework/v1` | 模块面挂载点，常量 `MODULE_FACE_BASE_PATH`（`framework/shared/src/contracts/module-model.ts:112`） |
| `/workspaces` | 本次要用的子树。**模型接口是同一个基址下的 `/models`** |

**基址是全模块面共用的**：models 与 workspaces 挂在同一个前缀下、走同一道门禁、
用同一枚令牌。所以消费方只需要一个 `FRAMEWORK_BASE_URL` 变量，两套接口一起用。

两条省事的取法：

- **框架启动日志里直接打出来了**，和令牌文件路径打在一起：
  `moduleApi: http://127.0.0.1:4300/api/framework/v1`（`framework/server/src/index.ts`）。
  同一条日志里还有 `工作区根目录`——工作区目录会被建在哪，那里有答案。
- **探活 `GET /api/health`**（不需要令牌）返回体里的 `cosightHome` 是**实际生效**的数据目录，
  第 3.2 节拿它去拼令牌路径，比靠代码猜可靠。

浏览器面是另一条路：`http://127.0.0.1:4300/api/workspaces`（开发态前端在 4310，
Vite 把 `/api` 代理到 4300）。它**不带** `/framework/v1`，也没有门禁——那是框架自己页面的接口，
与本节的基址不是一回事，见第 4 节。

## 3. 鉴权

### 3.1 四道门，逐条都会返回 403 或 401

| 位置 | 要求 | 不满足 |
|---|---|---|
| 来源 | 必须是本机回环地址（与监听地址无关：默认虽绑 `0.0.0.0`，这一面仍只放行回环来源） | `403` |
| `Host` 头 | 必须是 `localhost` / `127.0.0.1` / `[::1]`，可带端口 | `403` |
| `Origin` 头 | **不能带**。带了就拒——**包括模块自己的前端页面** | `403` |
| `Authorization` 头 | `Bearer <令牌>`，**只认这个头**（query 参数、自定义头、Cookie 都不认） | `401` |

`Origin` 那一条要理解成一句话：**令牌只该留在模块的服务端进程里**。
不要在模块的浏览器页面里直接调这七个接口——被 403 挡住是对的，绕过它则是把令牌送进了浏览器。

这四道门对 models 与 workspaces **是同一次校验**（同一个 `onRequest` hook，
`framework/server/src/routes/module-face.ts`）。与 [`model-config-api.md`](model-config-api.md)
第 3.1 节是同一张表——不是"两边各自实现了一套相似的规则"，是**同一条规则**。

### 3.2 令牌从哪来

令牌在 **`$COSIGHT_HOME/.module-token`**（默认 `~/.cosight-harness/.module-token`）：
单行 base64url、43 字符、32 字节熵、文件权限 `0600`、父目录 `0700`。
框架**启动时**创建它（存在就原样沿用，**不轮换**）。

读之前把目录**按框架那套规则**解析出来：

```ts
const home = process.env.COSIGHT_HOME ?? path.join(os.homedir(), '.cosight-harness');
const token = fs.readFileSync(path.join(home, '.module-token'), 'utf8').trim();
```

必须有 `.trim()`（文件末尾带换行），也**必须用同一套 `COSIGHT_HOME` 规则**——
框架在开发机上常被指到别处，两边解析不一致的表现是"文件不存在"或读到另一个实例的令牌（都是 401）。
拿不准就先打一次 `GET /api/health`，用它报出的 `cosightHome` 拼路径。

**令牌只能自己读这个文件——框架没有、也不会有"签发令牌"的接口。**
这不是没来得及做：任何签发接口都得先认证调用者，而本机认证手段归根到底只有"能读到某个
只有本机属主能读的东西"，那就是这个文件本身。

```bash
TOKEN=$(cat ~/.cosight-harness/.module-token)
curl -H "Authorization: Bearer $TOKEN" \
     http://127.0.0.1:4300/api/framework/v1/workspaces
```

### 3.3 三条要求，每条都有明确的理由

1. **模块进程自己读这个文件。**
   **不要**把令牌注入成环境变量（`.env`、`launch.json` 的 `env`、`export` 都不行）——
   模块通常会把 `process.env` 整体透传给子进程，令牌一旦进了环境，就等于交给了
   模型能调用的工具链，被工具调起的 agent 一条 `printenv` 就拿到了。
   读文件则只存在于模块进程自己的内存里，不被继承。
2. **只认 `Authorization: Bearer <token>` 头。** 理由不是习惯：框架的日志已经把它
   `redact` 掉了（`framework/server/src/app.ts`），令牌不会落进日志；换成自定义头
   就必须记得去加 redact，漏一次就是静默泄漏。而 query 参数会进 Referer、浏览器历史、
   反向代理访问日志——所以**只认头，不认 query**。
3. **令牌不是访问控制边界。** 同机同用户的其他进程可以**直接读**那个文件，根本不需要走 HTTP。
   这枚令牌挡住的是**浏览器里跑的代码**，这就是它存在的全部理由。别把它当权限系统用。

### 3.4 轮换与撤销

`verify()` **每个请求都重读文件**，不缓存。所以：

```bash
rm ~/.cosight-harness/.module-token      # 立刻全部 401，不用重启框架
```

要换新令牌就覆写这个文件（一行 base64url、至少 16 字符），同样立即生效。
v1 不提供轮换 CLI——删文件/写文件已经够用。

## 4. 两个面

同一份数据开了两个面，**实体形状完全一样**（工作区没有密钥，不像模型那样需要两套投影），
差别只在谁在调、以及列表的信封：

| | 浏览器面 | 模块面 |
|---|---|---|
| 基址 | `http://127.0.0.1:4300/api/workspaces` | `http://127.0.0.1:4300/api/framework/v1/workspaces` |
| 谁在调 | 框架自己的页面（经 Vite `/api` 代理到 4300） | 本机其他模块的**服务端进程** |
| 门禁 | 无（D25：本机单用户，框架自有接口不设认证） | 回环 + 拒 `Origin` + `Authorization: Bearer <令牌>` |
| 列表的 `data` | **裸数组** `[Workspace, …]` | **`{ items, activeId }`** |
| 代码 | `routes/workspace.ts` | `routes/module-workspace.ts` |

**为什么形状一样却要开两个面**：调用者不同——一边是页面、一边是本机进程（带令牌）。
两面共用同一个 `services/workspaces.ts`，所以业务规则只有一份。

**为什么列表的信封故意不一样**（这条有断言钉着，别"统一一下"）：

- 浏览器面是纯列表，页面本来就要另外渲染"当前是哪个"；
- 模块面给 `{ items, activeId }`——消费方几乎总是"拿列表 + 知道当前项"，
  分成两次调用会引入一个真实的竞态：两次之间有人切了工作区。

见 `framework/server/tests/api-module-workspace.test.ts` 的「列表的信封**刻意不同**」那条用例
（`framework/server/tests/api-module-workspace.test.ts:300`）。

## 5. 字段（`Workspace` 契约）

契约定义在 `framework/shared/src/contracts/workspace.ts`，两个面返回的就是它本身。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | uuid | **身份**。不是目录路径——目录只是可选属性 |
| `name` | string | 1–64（先 `trim`）。**全局唯一**，重名 `409` |
| `directory` | string \| null | 绑定的本地绝对路径。框架建的那个存的是 `realpath` 结果；未绑定为 `null` |
| `defaultModelId` | uuid \| null | 该工作区的默认模型；`null` = 沿用全局当前模型 |
| `defaultAgentId` | uuid \| null | 该工作区的默认 Agent 代理；`null` = 沿用全局默认 |
| `createdAt` / `updatedAt` | ISO 8601 | |

写入侧的契约（`createWorkspaceInputSchema` / `updateWorkspaceInputSchema`）：

| 字段 | 建（POST） | 改（PATCH） |
|---|---|---|
| `name` | 必填 | 可选 |
| `directory` | 可选，默认 `null`；必须是绝对路径（`/…` 或 `C:\…`） | 可选；传 `null` = **解除绑定** |
| `defaultModelId` / `defaultAgentId` | 可选，默认 `null` | 可选 |
| 空请求体 | — | 不行：**至少给一个字段**，`{}` → `422` |

**未知字段（含拼错的）会被静默丢掉，不会报错。** zod 对象默认是 strip 语义，这两个 schema
都不是 strict。实测：`{"name":"x","DefaultModelId":"1111…"}` 返回 `201`，而 `defaultModelId`
**仍然是 `null`**——大写的 `D` 让你以为设上了。所以这里的取舍是"`name` 拼错会当没传"，
`name` 是必填所以会立刻 `422`，但**其余四个字段拼错只会静默无效**。写调用方时请对着本表的字段名抄。

## 6. 端点总表（七个）

两个面的**路径后缀完全相同**，只差前缀：

| Method | 路径（后缀） | 说明 | 成功码 |
|---|---|---|---|
| `GET` | `/` | 列表。模块面多返回 `activeId` | 200 |
| `GET` | `/active` | 当前工作区；**没有时 `200` + `data: null`，不是 404** | 200 |
| `GET` | `/:id` | 详情；不存在 → `404` | 200 |
| `POST` | `/` | 建记录（+ **可能建目录**，见 §8）；重名 → `409` | **201** |
| `PATCH` | `/:id` | 改记录；**不动磁盘**；不存在 → `404` | 200 |
| `POST` | `/:id/activate` | 切换当前工作区；不存在 → `404` | 200 |
| `DELETE` | `/:id` | 删记录，返回 `{ id, deleted: true }`；**框架建的目录一并删除**，外部绑定目录保留 | 200 |

**模块面的完整路径**（就是第 2 节那个基址接上后缀）——照着抄这一张表就够：

| Method | Path |
|---|---|
| `GET` | `/api/framework/v1/workspaces` |
| `GET` | `/api/framework/v1/workspaces/active` |
| `GET` | `/api/framework/v1/workspaces/{id}` |
| `POST` | `/api/framework/v1/workspaces` |
| `PATCH` | `/api/framework/v1/workspaces/{id}` |
| `POST` | `/api/framework/v1/workspaces/{id}/activate` |
| `DELETE` | `/api/framework/v1/workspaces/{id}` |

（浏览器面把 `/api/framework/v1/workspaces` 换成 `/api/workspaces`，其余照旧。）

`{id}` 一律按 uuid 校验：把一个不是 uuid 的值当 `:id` 传进来是 `422`，
不会走到查询层再报"未找到"。
`/active` 注册在 `/:id` 之前（`find-my-way` 里静态段本就优先，但读代码的人不该被迫知道这一点）。

## 7. 逐个端点的真实请求与响应

所有响应都套同一个信封（`framework/shared/src/envelope.ts`）：恒定四段
`{ success, data, error, meta }`，不分页时 `meta` 是 `null` 而不是缺省。

### 7.1 `GET /` — 列表

```bash
# 浏览器面：data 是裸数组
curl -s http://127.0.0.1:4300/api/workspaces

# 模块面：data 是 { items, activeId }
curl -s -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:4300/api/framework/v1/workspaces
```

空库时：

```json
{ "success": true, "data": [], "error": null, "meta": null }
```

模块面空库时：

```json
{ "success": true, "data": { "items": [], "activeId": null }, "error": null, "meta": null }
```

有数据时（模块面），`items` 的元素就是第 5 节的 `Workspace`：

```json
{ "success": true,
  "data": {
    "items": [
      { "id": "b45b59de-ccb5-405d-ba17-99a7b7619b0e",
        "name": "周报助手开发",
        "directory": "/…/workspaces/周报助手开发",
        "defaultModelId": null,
        "defaultAgentId": null,
        "createdAt": "2026-10-16T01:58:26.998Z",
        "updatedAt": "2026-10-16T01:58:27.621Z" }
    ],
    "activeId": "b45b59de-ccb5-405d-ba17-99a7b7619b0e"
  },
  "error": null, "meta": null }
```

### 7.2 `GET /active` — 当前工作区

没有任何工作区（或当前指针悬空）时是 **`200` + `data: null`**，不是 `404`：
"还没有生效工作区"是**正常状态**，不是错误。前端因此不需要为它写一个 catch 分支。

```json
{ "success": true, "data": null, "error": null, "meta": null }
```

**指针悬空会自愈**：读它的时候如果发现 id 指向的工作区已经不在库里，顺手把指针清掉
（`services/workspaces.ts` 的 `findActive`）。所以 `DELETE` 之后不需要谁来收尾。

### 7.3 `GET /:id` — 详情

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$API/$ID"
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" \
  "$API/00000000-0000-4000-8000-000000000000"
# 404
```

### 7.4 `POST /` — 新建

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"周报助手开发"}' "$API"
```

真实响应（`201`）：

```json
{
  "success": true,
  "data": {
    "id": "b45b59de-ccb5-405d-ba17-99a7b7619b0e",
    "name": "周报助手开发",
    "directory": "/tmp/ws-doc-probe/workspaces/周报助手开发",
    "defaultModelId": null,
    "defaultAgentId": null,
    "createdAt": "2026-10-16T01:58:26.998Z",
    "updatedAt": "2026-10-16T01:58:26.998Z"
  },
  "error": null,
  "meta": null
}
```

注意 `directory` 被**框架填成了绝对路径**——请求里根本没传它。这就是第 8 节说的那一步。

手填绝对路径则原样绑定，**不创建、也不要求它存在**：

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"已有代码目录","directory":"/srv/projects/existing"}' "$API"
```

```json
{ "id": "02254934-ed04-40f7-9fad-86438cd65a1e",
  "name": "已有代码目录",
  "directory": "/srv/projects/existing" }
```

（抓完确认过：`/srv/projects/existing` 至今不存在。这是**故意的**，理由见第 8.4 节。）

重名 `409`：

```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "CONFLICT",
    "messageKey": "error.conflict.workspace",
    "message": "工作区名「周报助手开发」已存在",
    "details": null,
    "traceId": "req-8"
  },
  "meta": null
}
```

### 7.5 `PATCH /:id` — 改

请求体只放要改的字段，**至少一个**（空 `{}` → `422`，`details[0].path` 是空串）。

```bash
# 改名：只改记录，目录**不动**
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"周报助手开发V2"}' "$API/$ID"

# 解除目录绑定：只解绑，不删目录、不删文件
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"directory":null}' "$API/$ID"
```

改名后 `name` 变了，`directory` **仍是创建时那个**：

```json
{ "name": "周报助手开发V2",
  "directory": "/tmp/ws-doc-probe/workspaces/周报助手开发",
  "updatedAt": "2026-10-16T01:58:27.621Z" }
```

解绑后：

```json
{ "name": "模块建的工作区", "directory": null, "updatedAt": "2026-10-16T01:58:28.183Z" }
```

**`null` 与"不传"是两件事**：不传 = 保持原值不动，传 `null` = 清空/解绑。
`defaultModelId` 同理（传 `null` = 回到"沿用全局当前模型"）。这条与模型接口的
`apiKey` 三态是同一种语义。

### 7.6 `POST /:id/activate` — 切换当前工作区

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$API/$ID/activate"
```

返回切换后的那条工作区（与 `GET /:id` 同形状）**，不返回 `{ id }` 之类的短回复**：
调用方拿到就能直接更新界面，不必再查一次。

**"当前工作区"是服务端状态**（`app_state` 表），不是前端的 store——它会被多个页面和后端共用，
放前端就会出现"两个标签页各有一个当前工作区"的错位。

### 7.7 `DELETE /:id` — 删

```bash
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$API/$ID"
```

```json
{ "success": true, "data": { "id": "b45b59de-ccb5-405d-ba17-99a7b7619b0e", "deleted": true },
  "error": null, "meta": null }
```

删掉之后再查是 `404`。目录的处置取决于它是不是框架自己建的：

- 创建时**没填** `directory`、由框架在 `<工作区根>` 下建出来的目录：**连同内容一并删除**；
- 创建/编辑时**填了绝对路径**的外部目录（如 `/srv/projects/existing`）：**只解绑，不删**；
- `_public` 是框架保留空间，即使被绑定也不删。

服务端会留一条 info 日志，带 `workspaceId`、`directory` 与 `directoryDisposition`：

```
"msg":"工作区记录已删除",
"directory":"/…/workspaces/周报助手开发",
"directoryDisposition":"deleted"   // 或 external / absent / unbound / not-directory
```

"删了工作区但文件夹还在"是用户一定会问的第一个问题，日志里的 `directoryDisposition`
能直接回答它。

## 8. 磁盘：这七个端点里唯一会动的地方

### 8.1 哪一步动盘

| 操作 | 磁盘 |
|---|---|
| `POST`，**不传** `directory` | **建** `<工作区根>/<slug>`，绑定它的 `realpath` |
| `POST`，传了绝对路径 | **不建**、**不要求存在**，只绑定 |
| `PATCH`（含改名） | **不动**。目录在创建那一刻绑定，之后是稳定的 |
| `DELETE` | **只删框架建的目录**（工作区根的直接子目录，`_public` 除外）；外部绑定目录不动 |
| `GET` 三个 | **不动**。唯一的例外是 `GET /active`：指针悬空时它会顺手把库里的指针清掉（写的是库，不是磁盘上的目录） |

### 8.2 目录名不是工作区名——中间有一层 slug

`name` 只 `trim` 与限长 1–64，**不限制字符**（它是显示名，凭什么不让人叫「周报助手 / 2026 Q1」），
但它要变成一个路径段，而 `../../etc/passwd` 恰好是个合法的显示名。所以有 `lib/slug.ts`
的白名单式 slug 化。**这是安全项，不是美化项。**

真实抓到的三例：

| 请求里的 `name` | 建出来的目录名 |
|---|---|
| `周报助手开发` | `周报助手开发` |
| `周报助手 / 2026 Q1` | `周报助手-2026-Q1` |
| `../../etc/passwd` | `etc-passwd` |

第三条是重点：名字里带着穿越，目录**仍然落在工作区根之下**。完整规则（NFKC 规范化、按码点截断到
48、`_` 开头的保留名靠剥前缀进不来、`<slug>-2` 撞名后缀、`mkdir` 的 `EEXIST` 才是原子判重）
见 [`workspace-design.md`](workspace-design.md) §3。

### 8.3 建完之后，工作区空间长这样

真实 `find` 输出（走了上面全部请求）：

```
/tmp/ws-doc-probe/workspaces
/tmp/ws-doc-probe/workspaces/模块建的工作区
/tmp/ws-doc-probe/workspaces/周报助手-2026-Q1
/tmp/ws-doc-probe/workspaces/周报助手开发      ← 若这条记录被 DELETE，框架建的目录会一起消失
/tmp/ws-doc-probe/workspaces/etc-passwd
/tmp/ws-doc-probe/workspaces/_public
```

```
$COSIGHT_HOME/                     默认 ~/.cosight-harness，0700
├── sqlite.db                      工作区**记录**在这里（真相是库）
├── .module-token                  0600，模块面令牌
├── modules/<任意目录名>/module.json
└── workspaces/                    ← 工作区根，0700
    ├── _public/                   公共空间（框架自用的命名空间），0700
    ├── 周报助手开发/               普通工作区目录，0775（由 umask 决定）
    └── etc-passwd/
```

**两条权限不一样是刻意的**：根与 `_public` 是 `0700`（框架自己的东西，最小权限）；
**工作区子目录一律用进程 umask 的默认值**，因为里面装的是用户的代码，不该由框架收紧。

**记录在库里，不在目录里**：目录是可选的绑定，不是身份的来源。两条记录可以指向同一个目录
（框架不禁止、也不去重），一条记录也可以谁都不绑。

### 8.4 根目录在哪

| | |
|---|---|
| 默认 | `$COSIGHT_HOME/workspaces` |
| 覆盖 | `COSIGHT_WORKSPACES_ROOT`（相对路径按进程 cwd 解析，**不展开 `~`**，与 `COSIGHT_HOME` 同口径） |
| 在 `$COSIGHT_HOME` 之内 | 启动时建为 `0700` |
| 在 `$COSIGHT_HOME` 之外 | **只创建，不 chmod**——把根指到 `/srv/projects` 的人多半有自己的一套权限模型 |

想确认实际生效的根目录，看框架启动日志里 `工作区根目录` 那一行。

**用户手填的绝对路径不创建**，这条边界比"顺手帮用户建好"更值得守：`POST` 的入参来自 HTTP，
对任意绝对路径执行 `mkdir -p` 等于把一个写原语交给调用方去碰用户整台机器，而且会静默造出
多层父目录。要"先登记、之后再准备目录"也完全可以——绑定不要求目录已存在。

## 9. 错误

都是同一个信封，错误码是有限枚举（`framework/shared/src/errors.ts`），
HTTP 状态由 `ERROR_HTTP_STATUS` 映射，路由不自行指定。

| HTTP | `error.code` | 何时 |
|---|---|---|
| 401 | `UNAUTHORIZED`，`messageKey` = `error.unauthorized.module_token` | **仅模块面**：缺 `Authorization`、方案不是 `Bearer `、令牌不匹配、令牌文件读不到 |
| 403 | `FORBIDDEN` | **仅模块面**：`Host` 不是回环名、来源 socket 不是回环、或**请求带了 `Origin`** |
| 404 | `NOT_FOUND` | `/:id`（含 `PATCH` / `DELETE` / `activate`）不存在 |
| 409 | `CONFLICT` | `name` 与**别的**工作区重名（`PATCH` 改到自己身上不算） |
| 422 | `VALIDATION_FAILED` | 路径参数不是 uuid；`directory` 不是绝对路径；空 `PATCH`；`name` 超长（`details[0].code` = `too_big`）… **注意：未知字段不会走到这里，它被静默丢掉**（见 §5） |
| 429 | `RATE_LIMITED` | 全局限流：600 次 / 分钟（`app.ts`），两个面、两套接口共用这一道 |
| 500 | `INTERNAL` | 兜底。`message` 不外泄（避免泄漏堆栈/路径/SQL），细节看服务端日志的 `traceId` |

**401 的四种原因（缺头 / 方案不对 / 值不匹配 / 文件读不到）返回同一句话**，是刻意的：
区分它们等于向外泄漏本机文件系统的状态。排查第一步是看服务端启动日志——里面会打出令牌文件路径。

**403 的三种情形**：`Host` 头不是回环名（防 DNS rebinding：恶意站点把自己的域名解析到
`127.0.0.1`，浏览器便认为在跟同源通信，CORS 完全不介入，唯一露馅的就是 `Host`）、
来源 socket 不是回环、以及**请求带了 `Origin` 头**（浏览器发的请求会带，本机进程不会）。
展开见 [`model-config-api.md`](model-config-api.md) 的错误一节与
[`module-facing-api.md`](module-facing-api.md) §5——**这三种情形两套接口完全一样**。

真实的错误体（`details` 是字段级明细，表单逐项报错用它）：

```json
// 422：POST 里 directory 写了相对路径
{ "code": "VALIDATION_FAILED", "messageKey": "error.validation_failed",
  "message": "请求参数校验未通过",
  "details": [{ "path": "directory", "code": "custom",
                "messageKey": "validation.custom", "message": "必须是绝对路径" }],
  "traceId": "req-a" }

// 422：路径参数不是 uuid
{ "code": "VALIDATION_FAILED", "messageKey": "error.validation_failed",
  "message": "请求参数校验未通过",
  "details": [{ "path": "id", "code": "invalid_format",
   "messageKey": "validation.invalid_format", "message": "Invalid UUID" }], "traceId": "req-d" }

// 404
{ "code": "NOT_FOUND", "messageKey": "error.not_found.工作区",
  "message": "未找到工作区：00000000-0000-4000-8000-000000000000", "details": null, "traceId": "req-c" }

// 401（模块面，没有令牌）
{ "code": "UNAUTHORIZED", "messageKey": "error.unauthorized.module_token",
  "message": "缺少模块面令牌", "details": null, "traceId": "req-j" }

// 403（模块面，带了 Origin —— 浏览器页面发的一律拒）
{ "code": "FORBIDDEN", "messageKey": "error.forbidden",
  "message": "模块面不接受来自浏览器页面的请求", "details": null, "traceId": "req-k" }
```

`traceId` 是服务端注入的，把它贴给日志就能对上那一行。

## 10. 推荐的接入写法

### 10.1 TypeScript（Node 22+）

```ts
import fs from 'node:fs';
import path from 'node:path';

/** 与框架 `harness-shared` 的 `Workspace` 契约一致；模块不必依赖那个包，照抄即可。 */
interface Workspace {
  id: string;
  name: string;
  directory: string | null;
  defaultModelId: string | null;
  defaultAgentId: string | null;
  createdAt: string;
  updatedAt: string;
}

const COSIGHT_HOME = process.env.COSIGHT_HOME ?? path.join(process.env.HOME ?? '', '.cosight-harness');
/** 全模块面共用一个基址：workspaces 与 models 都在它之下（见第 2 节）。 */
const FRAMEWORK_BASE = process.env.FRAMEWORK_BASE_URL ?? 'http://127.0.0.1:4300';
const API = `${FRAMEWORK_BASE}/api/framework/v1/workspaces`;

/**
 * 令牌**每次现读文件**，不缓存、不走环境变量（见 3.3 第 1 条）。
 * `verify()` 每个请求都重读，所以运维换完令牌立即生效、不用重启你的模块。
 */
function readModuleToken(): string {
  return fs.readFileSync(path.join(COSIGHT_HOME, '.module-token'), 'utf8').trim();
}

async function callWorkspaces<T>(suffix: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${suffix}`, {
    ...init,
    headers: {
      authorization: `Bearer ${readModuleToken()}`,
      ...(init.body === undefined ? {} : { 'content-type': 'application/json' }),
      ...init.headers,
    },
  });

  if (response.status === 401) {
    throw new Error(`框架拒绝了模块令牌：检查 ${COSIGHT_HOME}/.module-token`);
  }

  const body = (await response.json()) as {
    success: boolean;
    data: T;
    error: { code: string; message: string } | null;
  };
  if (!body.success) {
    throw new Error(`工作区接口失败：${body.error?.code} ${body.error?.message}`);
  }
  return body.data;
}

/** 「列表 + 当前项」一次调用拿到——分成两次会有"两次之间被切换"的真实竞态。 */
const { items, activeId } = await callWorkspaces<{
  items: Workspace[];
  activeId: string | null;
}>('');

/**
 * 建一个工作区：不传 `directory` → 框架在工作区根下**建目录**，
 * 并把建出来的绝对路径填进返回值的 `directory`。
 * 成功是 `201`；重名是 `409`（因此这个调用**不幂等**，重试前先按 `name` 查一眼列表）。
 */
const created = await callWorkspaces<Workspace>('', {
  method: 'POST',
  body: JSON.stringify({ name: '模块建的工作区' }),
});

// `created.directory` 此刻一定存在；`DELETE` 会把这个框架建的目录一并删掉（第 8 节）。
```

### 10.2 curl

```bash
TOKEN=$(cat ~/.cosight-harness/.module-token)
API=http://127.0.0.1:4300/api/framework/v1/workspaces

# 读
curl -s -H "Authorization: Bearer $TOKEN" "$API"         | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$API/active"  | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$API/$ID"     | python3 -m json.tool

# 写（不传 directory → 框架会在工作区根下建一个目录）
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"新建的工作区"}' "$API" | python3 -m json.tool
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"改个名"}' "$API/$ID" | python3 -m json.tool
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$API/$ID/activate" | python3 -m json.tool
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$API/$ID" | python3 -m json.tool
ls -l ~/.cosight-harness/workspaces/          # 创建后出现；DELETE 之后框架建的那个目录消失
```

写操作的 HTTP 状态码：`POST` 成功是 **`201`**，`PATCH` / `DELETE` / `activate` 是 `200`。

### 10.3 Postman

必须用**桌面版**。Web 版是从浏览器里发请求的，会带上 `Origin` 头，而模块面见 `Origin` 就 403（见第 9 节）。

1. 取令牌：`cat ~/.cosight-harness/.module-token`（43 字符，文件末尾有换行，别把空白一起复制进去）
2. 新建请求 → 方法 `GET` → URL `http://127.0.0.1:4300/api/framework/v1/workspaces`
3. Headers 加一条 `Authorization`，值 `Bearer <令牌>`；或在 Authorization 页签选 **Bearer Token** 后只填令牌，效果一样
4. Send

两个动作不要做：

- **不要手动设 `Host` 头。** 它是回环校验的依据，改成别的值会直接 403。
- **不要开 Interceptor** 之类的浏览器抓包转发——那样请求的 `Origin` 会跟着过来，同样 403。

存成集合时把 `baseUrl` 放环境变量——值是**模块面基址**（`http://127.0.0.1:4300/api/framework/v1`），
路径里再拼 `/workspaces`；这样同一套环境变量也能调模型接口。令牌自己占一个变量：
Postman 的 pre-request script 读不了本机文件（脚本沙箱里没有 `fs`），令牌只能粘一次。

**排查对照**：401 = 令牌没带/带错（四种原因同一句话，去服务端启动日志里找令牌文件路径）；
403 = 带了 `Origin`、或 `Host` 被改过；404 = 路径写错（注意没有结尾斜杠），或 `:id` 确实不存在；
409 = 工作区重名；422 = `:id` 不是合法 uuid，或请求体不合契约。

## 11. 消费方自己的责任，以及写接口的权限面

写接口在第 6 节那张表里。它们**能改这台机器上的平台配置，还能在磁盘上创建目录**，
所以下面几条请在动手前读完。

### 11.1 令牌仍不是权限系统，所以写接口没有额外的门

第 3.3 节第 3 条已经说过：同机同用户的其他进程本来就能直接读令牌文件，根本不需要走 HTTP。
写接口**没有改变这一点**，它改变的是**爆炸半径**：一枚泄漏的令牌原来只能读到"用户有哪些工作区"，
现在还能建/改/删工作区（其中一个后果是**在你自己这台机器上建目录**）。

这不是"设计缺陷"而是本机单用户模型的固有形状。它的实际含义是：
**不该要写权限的模块就别要。** 只读的消费方用第 6 节那三条 `GET`，一条写接口也别碰。

### 11.2 写操作有审计日志

模块面的写操作（`POST` / `PATCH` / `DELETE`）在通过令牌校验后会**记一条 warn**，
内容是方法、路径、对端地址（`routes/module-face.ts`）。模块面**没有操作者身份**，
所以出了"谁把当前工作区改坏了"这类问题时，这条日志是唯一能回答"哪台机器、什么时候"的东西。
读取（`GET`）不记——那是噪声。

### 11.3 重试之前先想清楚幂等性

| 调用 | 重试一次会怎样 |
|---|---|
| `POST /` | **不幂等**：`name` 全局唯一，第一次其实成功、第二次会拿到 `409`。要重试就先按 `name` 查列表（`name` 是天然的幂等键），别盲目重发 |
| `PATCH /:id` | 幂等（同一份 body 打两次结果一样；改名改到自己身上不算重名） |
| `POST /:id/activate` | 幂等 |
| `DELETE /:id` | 第二次是 `404`——对"我想让它不存在"这个意图来说，仍然算成功，**别把它当错误上报** |
| `POST /` 里"建目录"那一步 | 重试**不会**多建目录：同名会被第一道门（`name` 唯一）挡成 `409`。`<slug>-2` 那个后缀发生在**名字本来就不同、但 slug 撞成同一个**的时候 |

### 11.4 同一个 `$COSIGHT_HOME` 只能有一个框架进程

这是**既有限制**，不是写接口引入的：`.credentials.yaml` 的写入串行化只在**单个进程内**有效
（跨进程没有文件锁）。要跑第二个实例，用另一个 `COSIGHT_HOME`。

### 11.5 没有乐观并发控制

模块与框架界面可能同时在改同一条工作区，**没有 `If-Match`、没有版本号**，后写的赢。
本机单用户的量级下这不是问题，但如果你要写一个"轮询并自动切换当前工作区"的守护进程，
请知道这个形状：它会把用户手动切的当前工作区**每隔几秒顶回去**。

### 11.6 工作区目录里是用户的文件

框架对这些文件**不写、不移动**。只有删除工作区这一条会碰它们：框架自己创建的目录会
连同内容一并删除，用户外部绑定的目录只解绑（第 8 节）。

**只有一件事例外，而且是后加上的：框架现在会读它们。** 会话区右侧的「工作区文件」面板
靠三个**只读**端点列目录 / 读文本 / 读图片，它们**只在浏览器面**：

| Method | Path |
|---|---|
| `GET` | `/api/workspaces/:id/files?path=` |
| `GET` | `/api/workspaces/:id/files/content?path=` |
| `GET` | `/api/workspaces/:id/files/image?path=` |

**模块面（`/api/framework/v1`）不开放这三个**，它们也没进本文件第 6 节的端点表——
吐的是用户文件的内容，不该跟着令牌的爆炸半径一起走。所以**你不需要为它们做任何事**：
这一句改动只是把"框架绝不读工作区内容"这个已经不成立的承诺收回来。
包含规则、四个上限、回环门禁（**把 UI 部署到非回环地址时这三个 GET 会 403**）
见 [`workspace-design.md`](workspace-design.md) §7。

因此：

- **`DELETE` 会清理框架创建的目录**（第 8 节）。你在模块里不要再对 `directory` 做一次
  `rm -rf`——框架已经处理过；外部绑定目录则永远不会被框架删除。
- **`PATCH` 的 `null` 只是解绑**，不是删除。想把工作区改去别的目录，先想清旧目录怎么办。
- **`COSIGHT_WORKSPACES_ROOT` 可以被指到别处**（`/srv/projects`、共享盘…）。
  拿到 `directory` 就按它用，别自己拼一份根路径——两边口径不一致时你会写到一个没人看的地方。

### 11.7 `directory` 是本机绝对路径

模块面假定**同机**（第 3 节那四道门本身就要求本机回环）。如果你的模块跑在容器或另一台机器里，
拿到的 `directory` 在那台机器上**没有意义**——这是设计上不支持的情形，不要靠映射猜。

## 12. 会被误解的几件事

| 误解 | 实际 |
|---|---|
| "基址和模型接口是两个" | **同一个**：都挂在 `/api/framework/v1` 之下（同一处常量、同一道门、同一枚令牌），只差子树名 `/models` 与 `/workspaces` |
| "删了工作区，目录应该也没了" | **分两种**：框架按名字建的直接子目录会连内容一起删；用户手填绝对路径绑定的外部目录**不删**，只解除记录（D43） |
| "改了名字，文件夹会跟着改" | **不跟着**。目录名是创建那一刻的一次性快照。跟着改会让编辑器/终端/别处记下的路径当场失效 |
| "绑定的目录必须先存在" | **不需要**。绑定与使用解耦，先登记后准备完全可以 |
| "`directory` 是我传什么就是什么" | 传了绝对路径才是原样；**不传**时是框架按名字派生并新建的 |
| "没有当前工作区应该报 404" | `200` + `data: null`。"还没有" 是正常状态，不该让前端写 catch 分支 |
| "列表在两面应该长得一样" | 实体一样，**信封不一样**：模块面多一个 `activeId`（省一次调用与一个竞态） |
| "字段拼错了它会报错" | 不会。未知字段被**静默丢掉**——`DefaultModelId` 这种大小写错误只会让那个字段保持原值，而请求返回 `201` |
| "框架从不读工作区里的文件" | **现在会读了**（只读：列目录 / 读文本 / 读图片，浏览器面三个端点）。不写、不移动这条没变；删除只发生在删工作区且只针对框架自己建的目录（D43）。见 11.6 |
| "文件浏览的接口模块面也能调" | **不能**。它们不在 `/api/framework/v1` 之下，也不在本文的端点表里。见 11.6 |

## 13. 相关

| 关注点 | 位置 |
|---|---|
| **同一套接口的模型版本文档（可一起转发）** | [`model-config-api.md`](model-config-api.md) |
| 契约（唯一定义） | `framework/shared/src/contracts/workspace.ts` |
| 模块面基址常量 | `framework/shared/src/contracts/module-model.ts` 的 `MODULE_FACE_BASE_PATH` |
| 三条不变量的落点（重名 / 清指针 / 建目录） | `framework/server/src/services/workspaces.ts` |
| 浏览器面路由 | `framework/server/src/routes/workspace.ts` |
| 模块面路由 | `framework/server/src/routes/module-workspace.ts` |
| 门禁（回环 / Origin / 令牌 / 写操作审计） | `framework/server/src/routes/module-face.ts` |
| 令牌文件 | `framework/server/src/credentials/module-token.ts` |
| slug 纯函数 | `framework/server/src/lib/slug.ts` |
| 布局与权限（唯一一处） | `framework/server/src/config/paths.ts` · `config/env.ts` |
| 前端封装 | `framework/web/src/api/workspaces.ts` · `features/workspace/` |
| 用例 | `framework/server/tests/api-workspace.test.ts`（浏览器面）· `api-module-workspace.test.ts`（模块面）· `workspace-directory.test.ts`（slug 与建目录）· `framework/web/tests/workspace-dialog.test.tsx` |
| 设计取舍 | [`workspace-design.md`](workspace-design.md) |
| 模块面整体（令牌、四道门、写接口的权限面） | [`module-facing-api.md`](module-facing-api.md) |
| 决策记录 | [`framework-decisions.md`](framework-decisions.md) 的 D16 / D32 / D33 / D43 |
