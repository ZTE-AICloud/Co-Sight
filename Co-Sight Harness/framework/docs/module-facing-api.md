# 模块面接口：本机其他模块怎么和框架打交道

> 读者：**任何模块的作者**（smart-factory、task-center、以及以后接进来的模块）。
> 本文说的是框架对外提供的能力，不涉及具体某个模块怎么改自己。
>
> 要直接转发给对方团队的话，用 [`model-config-api.md`](model-config-api.md)（只讲模型，
> 自足、不含内部取舍）。两份讲的必须是同一套接口，由
> `framework/server/tests/module-model-api-doc.test.ts` 的一致性断言钉住。

## 0. 一句话

本机的其他模块进程可以用 `/api/framework/v1/*` 读完框架的平台配置——**模型配置（含明文密钥）**
、工作区与 **RAG 知识库跳转路由**——也能改写前两者。代价是必须出示一枚只在
`$COSIGHT_HOME/.module-token` 里的令牌。

模块面下现在有**三个**子树：`/models`、`/workspaces`（都可读写）与 `/rag-knowledge`
（**只读**，见第 5 节）。

---

## 1. 为什么有两套模型接口

框架对同一份数据开了两个面，**两者的差别就是密钥**：

| | 浏览器面 `/api/models/*` | 模块面 `/api/framework/v1/models/*` |
|---|---|---|
| 调用方 | 框架的前端页面 | 本机的其他模块进程 |
| 密钥 | 只有 `hasApiKey` 与固定掩码 `apiKeyMasked`，**永远没有明文** | 详情、`/active`、以及写操作的响应**返回明文 `apiKey`** |
| 门禁 | 无鉴权（D25 = A：本机单用户）。注意默认监听 `0.0.0.0`，同网段能连到端口即可调用；只绑本机需设 `COSIGHT_HOST=127.0.0.1` | 回环校验 + 本机令牌 |
| 写操作 | 增删改齐全 | 增删改齐全（D33，见第 7 节） |

浏览器面"永不回传明文"是一条被测试钉死的硬契约（`framework/server/tests/api-model.test.ts`）。
模块面**没有松动它**——两面各自走一条独立的路由、一套独立的投影函数，明文只从模块面的
几条路由出去。两面能共存，是因为模块面的门禁要求"能读到本机 0600 文件"，而浏览器里的
任何代码都做不到这件事。

工作区没有密钥，所以两个面**形状完全一样**（不像模型那样要两套投影）。它之所以也有两个面，
只是因为调用者不同：那边是框架自己的页面，这边是本机其他模块的进程。

---

## 2. 令牌怎么拿

令牌在 **`$COSIGHT_HOME/.module-token`**（默认 `~/.cosight-harness/.module-token`）：
单行 base64url、43 字符、32 字节熵、文件权限 `0600`、父目录 `0700`。
框架**启动时**创建它（存在就原样沿用，**不轮换**），启动日志里会打出路径。

**令牌只能自己读这个文件——框架没有、也不会有"签发令牌"的接口。** 这不是没来得及做：
任何签发接口都得先认证调用者，而本机的认证手段归根到底只有"能读到某个只有本机属主能读的东西"，
那就是这个文件本身——绕一圈回到原点，还白多开一个浏览器能打到、能被 DNS rebinding 利用的面。
所以文件是令牌的唯一真源，也是唯一的取法。

读之前把目录**按框架那套规则**解析出来（`framework/server/src/config/env.ts`）：

```ts
const home = process.env.COSIGHT_HOME ?? path.join(os.homedir(), '.cosight-harness');
const token = fs.readFileSync(path.join(home, '.module-token'), 'utf8').trim();
```

必须有 `.trim()`（文件末尾带换行），也**必须用同一套 `COSIGHT_HOME` 规则**——
框架在开发机上常被指到别处，两边解析不一致的表现是"文件不存在"或读到另一个实例的令牌（都是 401）。
拿不准就先打一次 `GET /api/health`：它会报出**实际生效**的 `cosightHome`，
拿这个值去拼路径比靠猜可靠。这个接口不需要令牌（它只给路径，不给令牌）。

两种读不到文件的情形，都**不在支持范围内**：进程与框架**不同用户**（0600 拦的就是这个），
以及模块跑在**容器/另一台机器**里（模块面假定同机；容器要塞就把 `$COSIGHT_HOME` 或
单独 `.module-token` 只读挂进去，别指望有别的通路）。

```bash
TOKEN=$(cat ~/.cosight-harness/.module-token)
curl -H "Authorization: Bearer $TOKEN" \
     http://127.0.0.1:4300/api/framework/v1/models/active
```

### 三条要求，每条都有明确的理由

1. **模块进程自己读这个文件。**
   **不要**把令牌注入成环境变量（`.env`、`launch.json` 的 `env`、`export` 都不行）——
   模块通常会把 `process.env` 整体透传给模型子进程
   （`smart-factory/server/src/shared/engine/claude-adapter.ts` 就是
   `env: { ...process.env, ...anthropicEnv }`），令牌一旦进了环境，就等于交给了
   模型能调用的工具链，被工具调起的 agent 一条 `printenv` 就拿到了。
   读文件则只存在于模块进程自己的内存里，不被继承。

2. **只认 `Authorization: Bearer <token>` 头。**
   Query 参数、自定义头、Cookie 都不认。用 `Authorization` 是因为框架的日志已经把它
   `redact` 掉了（`framework/server/src/app.ts`），令牌不会落进日志。

3. **令牌不是访问控制边界。** 同机同用户的其他进程可以**直接读**
   `$COSIGHT_HOME/.credentials.yaml`（文件 0600 挡的是"属主 vs 其他人"，挡不住同 UID 的进程），
   根本不需要走 HTTP。这枚令牌挡住的是**浏览器里跑的代码**，这就是它存在的全部理由。
   别把它当权限系统用。

### 轮换与撤销

`verify()` **每个请求都重读文件**，不缓存。所以：

```bash
rm ~/.cosight-harness/.module-token      # 立刻全部 401，不用重启框架
```

要换新令牌就覆写这个文件（一行 base64url、至少 16 字符），同样立即生效。
v1 不提供轮换 CLI——删文件/写文件已经够用，加命令是多余的。

---

## 3. 模型端点（六个）

基址：`http://127.0.0.1:4300/api/framework/v1/models`
（端口以框架服务端实际监听为准；前端在开发态是 4310，Vite 会把 `/api` 代理到 4300）。

三条读、三条写，都在同一个前缀下：

| Method | Path | 响应 |
|---|---|---|
| `GET` | `/api/framework/v1/models` | `{ items, activeId }`，**无明文密钥** |
| `GET` | `/api/framework/v1/models/active` | 当前生效的模型，**含明文 `apiKey`**；没有则 `200 + data: null` |
| `GET` | `/api/framework/v1/models/:id` | 指定模型，**含明文 `apiKey`**；不存在 → `404` |
| `POST` | `/api/framework/v1/models` | 新建，`201`，响应形状同详情 |
| `PATCH` | `/api/framework/v1/models/:id` | 部分更新，响应形状同详情 |
| `DELETE` | `/api/framework/v1/models/:id` | `{ id, deleted: true }` |

**如果你的模块只需要"读一份配置去起模型客户端"，到此为止**——三条 GET 就够，
写接口的权限面见第 7 节。

### `GET /api/framework/v1/models` — 列表

不含明文密钥。**也不含 `apiKeyMasked`**——掩码在模块面没有语义，给了只会让人误用。

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "3f1c…",
        "provider": "openai",
        "protocol": "openai",
        "label": "内部 Qwen3-32B",
        "modelName": "qwen3-32b",
        "baseUrl": "https://gateway.internal/v1",
        "hasApiKey": true,
        "isActive": true,
        "createdAt": "2026-01-01T00:00:00.000Z",
        "updatedAt": "2026-01-02T00:00:00.000Z"
      }
    ],
    "activeId": "3f1c…"
  },
  "error": null,
  "meta": null
}
```

`activeId` 一并给出，是为了让消费方**一次调用就能预选中下拉项**——先拉列表再拉 `/active`
的话，这两次调用之间"当前生效的模型被换掉"会产生一个真实的竞态。

### `GET /api/framework/v1/models/active` — 当前生效的模型（含明文）

返回 `ModuleModelSecret`（字段见下表）。**没有生效模型时返回 `200` 且 `data: null`，
不是 404**——"还没有配过模型"是首次启动的正常状态，不是错误。这与浏览器面
`GET /api/models/active` 的语义一致。

### `GET /api/framework/v1/models/:id` — 按 id 查详情（含明文）

返回 `ModuleModelSecret`。id 不存在时返回 **`404`**，`error.code` 为 `NOT_FOUND`。

### 写接口（三条）

三条写接口的**响应形状与详情完全一致**（`ModuleModelSecret`，**含明文 `apiKey`**；`DELETE` 例外，
返回 `{ id, deleted: true }`）。这样"建完就地拿去起子进程"不需要再多一次 GET——这个场景是真实存在的。
代价是明文出现在写响应里，与详情、`/active` 一样，靠同一枚令牌兜着。

#### `POST /api/framework/v1/models` — 新建

请求体（`CreateModelConfigInput`）：

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `provider` | ✅ | | `openai` / `anthropic` / `azure-openai` / `ollama` / `openai-compatible` |
| `label` | ✅ | | 显示名，1–64 |
| `modelName` | ✅ | | 发给供应商的 model 字段，1–128 |
| `apiKey` | | `null` | **明文入参**，只写不读（读回来是详情里的 `apiKey`） |
| `baseUrl` | | `null` | 必须是 http(s)；`null` = 用官方地址 |
| `isActive` | | `false` | 置 `true` 会**把原来的生效项顶掉**（全局至多一个生效模型） |
| `temperature` / `topP` / `maxOutputTokens` / `contextWindow` / `timeoutSeconds` | | 见契约 | 推理参数 |

成功 **`201`**；`provider` 非法 → `422`。

#### `PATCH /api/framework/v1/models/{id}` — 部分更新

请求体只放要改的字段，**至少一个**（空对象 → `422`）。`undefined` = 不改、`null` = 清空，
两者语义不同，这个区别在 `apiKey` 上最要紧：

| `apiKey` | 效果 |
|---|---|
| 不传 | **保持原密钥不动** |
| `null` | **清除密钥**（此后 `hasApiKey: false`、详情里 `apiKey: null`） |
| 字符串 | 覆盖 |

**切换当前生效的模型也是这条**：`PATCH { "isActive": true }`。模块面**没有**单独的 `/activate`
（浏览器面那条是给"列表行上的一个按钮"用的便利路由）。`{id}` 不存在 → `404`。

#### `DELETE /api/framework/v1/models/{id}` — 删除

成功返回 `{ "id": "…", "deleted": true }`（**不是**模型详情）。同时会删掉
`.credentials.yaml` 里对应的那条密钥。`{id}` 不存在 → `404`。

### 字段表

| 字段 | 类型 | 列表 | 详情 | 说明 |
|---|---|---|---|---|
| `id` | uuid | ✓ | ✓ | |
| `provider` | 枚举 | ✓ | ✓ | 供应商：`openai` / `anthropic` / `azure-openai` / `ollama` / `openai-compatible` |
| `protocol` | `anthropic` \| `openai` | ✓ | ✓ | **线协议**，由 `provider` 派生，见下 |
| `label` | string | ✓ | ✓ | 界面上显示的名称 |
| `modelName` | string | ✓ | ✓ | 发给供应商的 model 字段（CC 配置里的那种），**不是**显示名 |
| `baseUrl` | string \| null | ✓ | ✓ | 自定义网关地址；`null` = 用该供应商的官方地址 |
| `hasApiKey` | boolean | ✓ | ✓ | |
| `isActive` | boolean | ✓ | ✓ | |
| `createdAt` / `updatedAt` | ISO 8601 | ✓ | ✓ | |
| `apiKey` | string \| null | ✗ | ✓ | **明文**；没配过为 `null` |
| `temperature` | number | ✗ | ✓ | 0–2 |
| `topP` | number | ✗ | ✓ | 0–1 |
| `maxOutputTokens` | number \| null | ✗ | ✓ | `null` = 不限制 |
| `contextWindow` | number \| null | ✗ | ✓ | `null` = 跟随模型默认 |
| `timeoutSeconds` | number | ✗ | ✓ | |

### `provider` 不是 `protocol`——请务必用 `protocol`

`provider` 说的是**哪家供应商**（决定鉴权方式与官方地址），`protocol` 说的是
**线上跑什么协议**（Anthropic Messages vs OpenAI chat-completions）。两者不是一回事：
`azure-openai` / `ollama` / `openai-compatible` 都是 `provider` 各异的 OpenAI 兼容端点。

消费方如果拿 `provider === 'anthropic'` 之外的都当 OpenAI 用、又自己硬编码
"协议类型"，就会出现**用户设了一个 OpenAI 兼容模型、模块却拿 Anthropic SDK 去打它**，
表现为一句语焉不详的上游报错。所以 `protocol` 直接给出来：

| `provider` | `protocol` |
|---|---|
| `anthropic` | `anthropic` |
| `openai` / `azure-openai` / `ollama` / `openai-compatible` | `openai` |

`protocol` 是**派生字段**，不落库。将来若要允许用户覆盖，服务的响应形状不变。

`baseUrl` 为 `null` 时**框架不做默认值推导**——`azure-openai` 的地址要带 deployment 段，
一律推导会静默给出错误地址，比 `null` 更糟。消费方拿到的就是 `null` 或用户填的值。

---

## 4. 工作区端点（七个）

基址：`http://127.0.0.1:4300/api/framework/v1/workspaces`

> 本节只讲**模块面**这一次的读法，口径是给框架维护者的。**要转发给消费方就用
> [`workspace-api.md`](workspace-api.md)**——它与 [`model-config-api.md`](model-config-api.md)
> 同构（基址 / 鉴权 / 端点 / 错误 / 接入写法一应俱全），自足、不含内部取舍；
> 两个面并排的完整参考（含浏览器面、每个端点的真实响应、字段契约的坑、磁盘边界）也在那一份里。

工作区**没有密钥**，所以这一组在两个面上**形状完全一样**（不像模型那样要两套投影）。
字段就是 `Workspace` 契约本身：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | uuid | 身份。**不是**目录路径——目录是可选的属性 |
| `name` | string | 1–64，**全局唯一**（重名 → `409`） |
| `directory` | string \| null | 绑定的**绝对路径**（`realpath` 规范化后的值）；未绑定为 `null` |
| `defaultModelId` | uuid \| null | 该工作区的默认模型；`null` = 沿用全局当前模型 |
| `defaultAgentId` | uuid \| null | 该工作区的默认 Agent 代理；`null` = 沿用全局默认 |
| `createdAt` / `updatedAt` | ISO 8601 | |

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/api/framework/v1/workspaces` | `{ items, activeId }`（与模型列表同款：一次调用拿到当前项，避开"列表与 active 之间被切换"的竞态） |
| `GET` | `/api/framework/v1/workspaces/active` | 当前工作区；**没有生效工作区时 `200 + data: null`，不是 404** |
| `GET` | `/api/framework/v1/workspaces/:id` | 不存在 → `404` |
| `POST` | `/api/framework/v1/workspaces` | 建记录（+ 可能建目录，见下），`201` |
| `PATCH` | `/api/framework/v1/workspaces/:id` | 改记录；**不动磁盘** |
| `POST` | `/api/framework/v1/workspaces/:id/activate` | 切换当前工作区 |
| `DELETE` | `/api/framework/v1/workspaces/:id` | 删记录，返回 `{ id, deleted: true }`；框架建的目录一并删除，外部绑定目录保留 |

### `POST` 的 `directory`：留空 = 框架建目录，填了 = 只绑定

这一条是本组接口里唯一会碰到磁盘的地方，也是最容易误解的地方：

| 请求体里的 `directory` | 框架做什么 |
|---|---|
| **不传** 或 `null` | 在工作区根目录（`$COSIGHT_HOME/workspaces`，可用 `COSIGHT_WORKSPACES_ROOT` 覆盖）下，**按工作区名派生一个目录名并创建它**，然后把该目录的绝对路径写进 `directory` 返回 |
| 传一个绝对路径 | **只绑定，不创建**。而且**不要求目录已经存在**——用户可以先登记、之后再准备目录 |

目录名不是把工作区名直接当路径用：名字会先被规范化成一个 slug
（保留字母/数字/`-`/`_`，中文原样保留，其余折叠成 `-`，截断到 48 字符），
再在根目录下作**不区分大小写**的重名检查，冲突时依次尝试 `<slug>-2`、`<slug>-3`…
所以名字里带 `../../` 也**逃不出根目录**。规则细节、保留名与全部取舍见
[`workspace-design.md`](workspace-design.md)。

`POST /api/framework/v1/workspaces` 成功是 **`201`**；`name` 与已有工作区重名 → `409`。

```bash
curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"周报助手开发"}' "$API/workspaces" | python3 -m json.tool
# directory 会被填成 /…/workspaces/周报助手开发 这样的绝对路径，且目录已经建好

curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"已有代码目录","directory":"/srv/projects/existing"}' "$API/workspaces"
# 原样绑定，不创建、也不校验它是否存在

curl -s -X POST -H "Authorization: Bearer $TOKEN" "$API/workspaces/<id>/activate"
```

### `PATCH` 不动磁盘；`DELETE` 只删框架建的目录

- **改名不改目录**：`PATCH` 里传新的 `name` 只改记录。目录在创建时绑定，之后是稳定的——
  这样"文件夹在访达/Finder 里被重命名"就不会把绑定弄丢。
- **删除会清理框架自己建的目录**：`POST` 不传 `directory` 时框架在工作区根下建的那个
  目录，会连同内容一并删除。用户手填绝对路径绑定的外部目录**只解除记录，不删除**——
  框架不会替用户 `rm -rf` 他的项目目录。删记录时框架会打一条 info 日志，
  带 `directory` 与 `directoryDisposition`。**如果你的模块原先以为"删工作区不删文件"，
  请改这个预期**：框架建的目录已经不在了。

`PATCH` 的请求体同样是"只放要改的字段、至少一个"，`null` 可以**解除目录绑定**
（只解绑，不删目录，也不删文件）。

---

## 5. RAG 知识库端点（两个，只读）

基址：`http://127.0.0.1:4300/api/framework/v1/rag-knowledge`

用户在「设置 → 知识库路由设置」里维护若干条「名称 + 跳转路由（+ 可选的登录账号密码、
+ 可选的 Agent API Key）」，其中**至多一条处于生效状态**。模块需要知道的只有
「当前该把用户带到哪个地址、用哪枚凭据」。

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| `GET` | `/api/framework/v1/rag-knowledge` | 全量列表（`createdAt` 升序），供需要"让用户选一条"的模块用；**不含明文凭据** |
| `GET` | `/api/framework/v1/rag-knowledge/active` | 当前生效的一条；**没有生效项时 `200 + data: null`，不是 404** |

密码与 API Key 和模型密钥同一条口径：列表只有 `hasPassword` / `hasApiKey`，
**明文只从 `/active` 出**（`password` 与 `apiKey` 字段，没有就是 `null`）。`apiKey`
有两层——路由自己的优先，没配时回落到服务端环境变量 `COSIGHT_KNOWLEDGE_API_KEY`
（其次 `CO_KNOWLEDGE_API_KEY`），所以 `/active` 给的永远是**生效的那一枚**。
拿到后只在自己的服务端进程里用——不写日志、不拼进 URL、不下发给浏览器。

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/rag-knowledge/active" | python3 -m json.tool
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

三条使用口径：

1. **「没有生效知识库」是正常态**（用户还没配，或刚删掉生效项）。按 `data === null`
   处理，不要当失败重试，也不要弹错误提示。
2. **这个面只读。** `POST` / `PATCH` / `DELETE` 在本路径上一律 `404`——写入者是设置里的
   用户，模块没有写理由。少一个写入口，泄漏的令牌就少一分杀伤面。
3. **模块的前端不能直接调**：浏览器请求带 `Origin`，会被第二道门禁拒掉。正确姿势是
   模块自己的服务端代取、前端调自己的后端（与模型、工作区同一套要求）。

`routeUrl` 只接受 `http://` / `https://` 绝对地址，且不含内嵌账号密码（框架在写入时已校验）。
直接把它交给浏览器打开时，请带 `rel="noopener noreferrer"`。

框架自己的左侧「知识库」现在在**新的浏览器标签页**里打开当前生效的这一条（2026-10-28 调整）；
宿主直接访问 `/knowledge` 时仍会把它嵌成页（同一个最小权限 iframe 沙箱）——那是因为这条
地址由本机用户在设置里当场选定、且至多一条。**模块不要照搬内嵌**：模块侧拿到的可能是多条
候选，`routeUrl` 也不在 `allowedOrigins` 的约束里，自行 iframe 内嵌会绕过框架"只嵌入受信任
模块来源"的边界。凡需要一份可转发的单篇说明，见
[`rag-knowledge-api.md`](rag-knowledge-api.md)。

---

## 6. 错误

所有响应都是同一个信封（`{success, data, error, meta}`）。模块面可能返回：

| HTTP | `error.code` | 何时 |
|---|---|---|
| 401 | `UNAUTHORIZED`，`messageKey` = `error.unauthorized.module_token` | 没有 `Authorization` 头、方案不是 `Bearer `、令牌不对、令牌文件不存在或内容非法 |
| 403 | `FORBIDDEN` | `Host` 头不是回环名，或来源 socket 不是回环地址，或请求带了 `Origin` |
| 404 | `NOT_FOUND` | `/models/:id` 或 `/workspaces/:id`（含 `PATCH`/`DELETE`/`activate`）的 id 不存在 |
| 409 | `CONFLICT` | 工作区 `name` 与已有工作区重名（模型接口不会遇到，列出来是让你别把它当未知错误） |
| 422 | `VALIDATION_FAILED` | 路径参数不是合法 uuid；请求体不合契约（空 `PATCH`、`provider` 非法、`baseUrl` 不是 http(s)、`name` 超长…） |

**401 的四种原因返回同一句话**，是刻意的：区分它们等于向外泄漏本机文件系统的状态
（"文件不存在" vs "文件内容非法"）。排查时看服务端的启动日志：里面会打出令牌文件路径。

### `403` 的三种情形，以及为什么带 `Origin` 也被拒

框架**只接受本机回环地址**的请求：

- `Host` 必须是 `localhost` / `127.0.0.1` / `[::1]`（带端口也可以）。
  防的是 **DNS rebinding**：恶意站点把自己控制的域名解析到 `127.0.0.1`，浏览器便认为
  在跟同源通信——CORS 完全不介入，`Origin` 也没有异常。此时唯一露馅的是 `Host`。
  （这一道依赖 `trustProxy: false`，见 `framework/server/src/http/loopback.ts` 的文件头。）
- 来源 socket 地址必须是回环。
- **请求带 `Origin` 头就拒。** 浏览器发的请求会带 `Origin`，本机进程不会。
  这条**包括模块自己的前端页面**——密钥只该留在模块的**服务端进程**里，
  任何前端代码都不该拿到它。

---

## 7. 写接口的权限面（请读完再决定要不要用）

模块面现在**可写**（D33）。这条决定同时包含模型与工作区，所以先说清代价：
一枚令牌原来只能**读走**模型密钥；现在它还能把**这台机器上的平台配置改成攻击者想要的样子**
（最典型的一种：把某个模型的 `baseUrl` 改到自己控制的端点，用户的密钥就自动送过去了，
而框架界面完全看不出来），以及**在磁盘上创建目录**。

### 6.1 令牌仍不是权限系统，所以写接口没有额外的门

第 2 节第 3 条已经说过：同机同用户的其他进程本来就能直接读 `.credentials.yaml`，
根本不需要令牌。写接口**没有改变这一点**，它改变的是**爆炸半径**。

这不是"设计缺陷"而是本机单用户模型的固有形状。它的实际含义是：
**不该要写权限的模块就别要。** 只读的消费方（smart-factory 就是这一类）用第 3 节那三条 GET，
一条写接口也别碰——你多要一份写权限，你的进程就多一份被利用的价值。

### 6.2 写操作有审计日志

模块面的写操作（`POST` / `PATCH` / `DELETE`）在通过令牌校验后会**记一条 warn**，
内容是方法、路径、对端地址（`routes/module-face.ts`）。模块面**没有操作者身份**，
所以出了"谁把生效模型改坏了"这类问题时，这条日志是唯一能回答"哪台机器、什么时候"的东西。
读取（`GET`）不记——那是噪声。

### 6.3 同一个数据目录只能有一个框架进程

这是**既有限制**，不是写接口引入的：`.credentials.yaml` 的写入串行化只在**单个进程内**有效
（`credentials/store.ts`，跨进程没有文件锁）。

上一轮把这个当成"不能开写接口"的硬理由，现在看清楚了它**不成立**：模块面的写
**全部经 HTTP 打到那一个框架进程**，写成序列化的那个 `CredentialStore` 实例始终只有一个。
跨进程风险只存在于"有人绕过 HTTP 直接改那个文件"（手工编辑、另起一个框架实例），
这与浏览器面今天的情况没有任何区别。

但推论的边界要划清：**别用同一个 `$COSIGHT_HOME` 起两个框架实例。**
今天这样做的后果是"丢一次密钥更新"，加了模块面写入之后是"两个进程都认为自己该管这份配置"。
要跑第二个实例，用另一个 `COSIGHT_HOME`。

### 6.4 没有乐观并发控制

模块翻 `isActive` 与框架界面上的设置页可能同时在写同一条配置，**没有 `If-Match`、没有版本号**，
后写的赢。本机单用户的量级下这不是问题，但如果你要写一个"轮询并自动切换生效模型"的守护进程，
请知道这个形状。

### 6.5 工作区写入会在磁盘上留下东西

`POST /api/framework/v1/workspaces`（不传 `directory` 时）会**真的创建目录**。
边界收得很紧，但值得写出来：

- **只在框架自己的工作区根之下创建**。用户在请求体里手填的绝对路径**只绑定、不创建**——
  对任意绝对路径执行 `mkdir -p` 是拿一个写原语去碰用户整台机器，而且它会静默造出多层父目录。
- **只删框架自己创建的直接子目录**：`DELETE` 会递归删掉工作区根下由框架按工作区名建出的
  那个目录（D43）；用户手填绝对路径绑定的外部目录只解除记录，**永不删除**。
  `PATCH` 仍然不碰磁盘，也不重命名目录。
- 工作区根目录可以用 `COSIGHT_WORKSPACES_ROOT` 指到别处（`/srv/projects`、共享盘…）。
  指到共享目录时 slug 化仍能挡住路径穿越，但挡不住"另一个用户在同目录里建同名工作区"
  和"同步软件半途复制出半个目录"——与 `COSIGHT_HOME` 指向 `/tmp` 是同一类风险，
  见第 9 节。

---

## 8. 客户端示例

### TypeScript（Node 22+）

```ts
import fs from 'node:fs';

/** 与框架 `harness-shared/module-models` 的契约一致；模块不必依赖那个包，照抄即可。 */
interface ModuleModelSecret {
  id: string;
  provider: 'openai' | 'anthropic' | 'azure-openai' | 'ollama' | 'openai-compatible';
  protocol: 'anthropic' | 'openai';
  label: string;
  modelName: string;
  baseUrl: string | null;
  hasApiKey: boolean;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  apiKey: string | null;
  temperature: number;
  topP: number;
  maxOutputTokens: number | null;
  contextWindow: number | null;
  timeoutSeconds: number;
}

const COSIGHT_HOME = process.env.COSIGHT_HOME ?? `${process.env.HOME}/.cosight-harness`;
const FRAMEWORK_BASE = process.env.FRAMEWORK_BASE_URL ?? 'http://127.0.0.1:4300';

/**
 * 令牌**每次现读文件**，不缓存、不走环境变量。
 * 现读的代价是一次 ~几十微秒的 readFileSync，换来的是运维改完文件立即生效、不用重启模块。
 */
function readModuleToken(): string {
  return fs.readFileSync(`${COSIGHT_HOME}/.module-token`, 'utf8').trim();
}

async function fetchActiveModel(): Promise<ModuleModelSecret | null> {
  const response = await fetch(`${FRAMEWORK_BASE}/api/framework/v1/models/active`, {
    headers: { authorization: `Bearer ${readModuleToken()}` },
  });

  if (response.status === 401) {
    throw new Error('框架拒绝了模块令牌：检查 ' + `${COSIGHT_HOME}/.module-token`);
  }
  if (!response.ok) {
    throw new Error(`取模型配置失败：HTTP ${response.status}`);
  }

  const body = (await response.json()) as { data: ModuleModelSecret | null };
  return body.data;
}

// 用法：按 protocol 选 SDK，而不是按 provider
const model = await fetchActiveModel();
if (model === null) throw new Error('框架里还没有设置激活的模型');
if (model.apiKey === null) throw new Error(`模型「${model.label}」没有配置密钥`);
if (model.protocol !== 'anthropic') throw new Error(`暂不支持 ${model.protocol} 协议的模型`);
```

### curl

```bash
TOKEN=$(cat ~/.cosight-harness/.module-token)
API=http://127.0.0.1:4300/api/framework/v1
BASE=$API/models

# 模型：读
curl -s -H "Authorization: Bearer $TOKEN" "$BASE"        | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/active" | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/<id>"   | python3 -m json.tool

# 模型：写
curl -s -X POST  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"provider":"anthropic","label":"建一个","modelName":"claude-sonnet-5-5"}' "$BASE" | python3 -m json.tool
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"isActive":true}' "$BASE/<id>" | python3 -m json.tool
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE/<id>" | python3 -m json.tool

# 工作区：读
curl -s -H "Authorization: Bearer $TOKEN" "$API/workspaces"        | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$API/workspaces/active" | python3 -m json.tool

# 工作区：写（不传 directory → 框架会在工作区根下建一个目录）
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"新建的工作区"}' "$API/workspaces" | python3 -m json.tool
ls -l ~/.cosight-harness/workspaces/          # 目录确实出现了
```

写操作的 HTTP 状态码：`POST` 成功是 **`201`**，`PATCH` / `DELETE` / `activate` 是 `200`。

### Postman

必须用**桌面版**。Web 版是从浏览器里发请求的，会带上 `Origin` 头，而模块面见 `Origin` 就 403（见第 6 节）。

1. 取令牌：`cat ~/.cosight-harness/.module-token`（43 字符，文件末尾有换行，别把空白一起复制进去）
2. 新建请求 → 方法 `GET` → URL `http://127.0.0.1:4300/api/framework/v1/models`
3. Headers 加一条 `Authorization`，值 `Bearer <令牌>`；或在 Authorization 页签选 **Bearer Token** 后只填令牌，效果一样
4. Send

两个动作不要做：

- **不要手动设 `Host` 头。** 它是回环校验的依据，改成别的值会直接 403。
- **不要开 Interceptor** 之类的浏览器抓包转发——那样请求的 `Origin` 会跟着过来，同样 403。

存成集合时把 `baseUrl` 放环境变量（值就是上面那串到 `/models` 为止的地址），令牌自己占一个变量：
Postman 的 pre-request script 读不了本机文件（脚本沙箱里没有 `fs`），令牌只能粘一次。
运气好的一点是 `verify()` **每个请求都重读文件**，所以你在服务端换了令牌之后不用重启框架，
只改 Postman 里那个变量即可。

**排查对照**：401 = 令牌没带/带错（四种原因同一句话，去服务端启动日志里找令牌文件路径）；
403 = 带了 `Origin`、或 `Host` 被改过；404 = 路径写错（注意没有结尾斜杠），
或 `:id` 确实不存在；409 = 工作区重名；422 = `:id` 不是合法 uuid，或请求体不合契约。

框架的界面里有一张「模块接入」卡（设置 → 模型设置 → 底部），直接给出这两条命令与令牌路径。

---

## 9. 残余风险（不假装不存在）

- **令牌不防同机同用户的进程。** 见第 2 节第 3 条。它的定位是"给消费方一个显式、可撤销的
  opt-in 契约"，不是访问控制边界。
- **同机不同用户**靠 `$COSIGHT_HOME` 0700 + 令牌文件 0600。两条例外：
  `ensureDirectory` 在非 POSIX 文件系统（`ENOSYS`）上会**静默吞掉** chmod 失败，
  那时 0700 根本没生效；以及 `COSIGHT_HOME` 被指到 `/tmp` 这类共享目录。
  框架在启动时实测一次权限，不是 0600 就打一条 WARN（不阻断启动）。
- **备份会带走令牌。** `tar` 整个 home、Time Machine、云盘同步都会。
  `.module-token` 与 `.credentials.yaml` 一样，都在"不要进备份、不要进版本控制"的清单里。
- **SSRF 面转移到了消费方。** 框架把明文密钥 + 用户填的 `baseUrl` 交给模块，模块拿它去起
  模型客户端。框架侧只保证 `baseUrl` 是 http(s)；**消费方必须自己校验地址**
  （比如只允许内网段），不要把密钥发往不可信地址。
- **令牌可能经应用日志泄漏。** 唯一保障是 `framework/server/src/app.ts` 里
  `redact: ['req.headers.authorization', ...]`。**模块面依赖它**——那次重构如果删掉这一项，
  就是静默泄漏。这条依赖写在代码注释里，也写在这里。
- **`COSIGHT_WORKSPACES_ROOT` 指向共享目录**（`/tmp`、NFS、云盘同步目录）：slug 化挡住了路径
  穿越，但挡不住"另一个用户在同目录里建同名工作区"和"同步软件半途复制出半个目录"。
  与 `COSIGHT_HOME` 指向 `/tmp` 是同一类风险，一条口径说完。另外这一层**不强制 0700**
  ——工作区里大概率是用户自己的代码，跟着框架的最小权限走反而是错的（见
  [`workspace-design.md`](workspace-design.md)）。
- **工作区目录里是用户的文件。** 框架对它们**只在 §7 的只读端点里读，不写、不移动**。
  `DELETE /workspaces/:id` 会删**框架自己创建的**那个目录，外部绑定的目录保留（第 4 节）。
  **框架现在会读**——会话区右侧的「工作区文件」面板
  用三个只读端点列目录 / 读文本 / 读图片。这三个端点**只开在浏览器面，不在
  `/api/framework/v1` 之下，也不在第 4 节的端点表里**，所以模块侧的令牌读不到文件内容。
  规则、四个上限、以及"把 UI 部署到非回环地址时它们会 403"这条代价，见
  [`workspace-design.md`](workspace-design.md) §7。**这条曾经写作"框架不读工作区目录里的
  任何内容"，那句话已经不再成立。**
- **`/api/docs` 会列出这一整组端点。** 那是本机文档页，可接受。

## 10. 相关代码

| 关注点 | 位置 |
|---|---|
| **门禁（三层）与两条子树的挂载** | `framework/server/src/routes/module-face.ts` |
| 模型路由 | `framework/server/src/routes/module-model.ts` |
| 工作区路由 | `framework/server/src/routes/module-workspace.ts` |
| 模型契约（zod schema） | `framework/shared/src/contracts/module-model.ts` |
| 工作区契约 | `framework/shared/src/contracts/workspace.ts`（**两面的共用契约**，不是模块面专用） |
| 回环判定 | `framework/server/src/http/loopback.ts` |
| 令牌存储 | `framework/server/src/credentials/module-token.ts` |
| 含密钥的模型投影 | `framework/server/src/services/module-models.ts` |
| 工作区业务规则（两个面共用一份） | `framework/server/src/services/workspaces.ts` |
| 目录名 slug 化 | `framework/server/src/lib/slug.ts` |
| 工作区方案的完整说明 | `framework/docs/workspace-design.md` |
| 契约隔离守卫（防它流进前端） | `framework/server/tests/module-contract-isolation.test.ts` |
