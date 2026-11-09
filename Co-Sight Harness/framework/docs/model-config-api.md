# 模型配置对外接口

> **面向：需要从框架读取（或写入）模型配置的本机其他模块**（smart-factory 等）。
> 本文自足，可直接转发——不需要读框架源码。
> 状态：已实现，已在真实环境逐条验证（2026-10-15）。
>
> 本文只讲**模型**。同一套基址、同一枚令牌、同一道门禁下还有一整套工作区接口
> （`/api/framework/v1/workspaces/*`），那份说明**同样自足、可与本文一并转发**：
> [`workspace-api.md`](workspace-api.md)——只有你的模块需要帮用户建/改工作区时才用得上。
>
> 框架侧的完整说明（含内部取舍与残余风险）另见 [`module-facing-api.md`](module-facing-api.md)，
> 那份是给框架维护者的。

## 1. 一句话

框架把"用户已经配好的模型"通过 HTTP 开放给本机其他模块进程，用来启动你自己的模型客户端，
也可以反过来帮用户建/改/删模型配置。**六个接口**：三条 GET（其中两条**返回明文密钥**）、
三条写接口，代价都是出示一枚本机令牌。

> **只读的消费方请注意**：如果你的模块只是"拿一份配置去起模型客户端"（smart-factory 就是
> 这一类），那么你只需要三条 GET。写接口的存在**不是**给你的邀请——你多要一份写权限，
> 你的进程就多一份被利用的价值。见第 12 节。

## 2. 基址

```
http://127.0.0.1:4300/api/framework/v1/models
```

端口以框架实际监听为准。探活：`GET /api/health`（不需要令牌），
返回体里的 `cosightHome` 是实际生效的数据目录，第 3 节读令牌时用得上。

## 3. 鉴权

### 3.1 四道门，逐条都会返回 403 或 401

| 位置 | 要求 | 不满足 |
|---|---|---|
| 来源 | 必须是本机回环地址（与监听地址无关：默认虽绑 `0.0.0.0`，这一面仍只放行回环来源） | `403` |
| `Host` 头 | 必须是 `localhost` / `127.0.0.1` / `[::1]`，可带端口 | `403` |
| `Origin` 头 | **不能带**。带了就拒——**包括模块自己的前端页面** | `403` |
| `Authorization` 头 | `Bearer <令牌>`，**只认这个头**（query 参数、自定义头、Cookie 都不认） | `401` |

`Origin` 那一条要理解成一句话：**密钥只该留在模块的服务端进程里**。
不要在模块的浏览器页面里直接调这三个接口——被 403 挡住是对的，绕过它则是把密钥送进了浏览器。

### 3.2 令牌从哪来

令牌在 **`$COSIGHT_HOME/.module-token`**（默认 `~/.cosight-harness/.module-token`）：
单行 base64url、43 字符、文件权限 `0600`。框架启动时创建它（已存在就沿用，不轮换）。

```ts
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const home = process.env.COSIGHT_HOME ?? path.join(os.homedir(), '.cosight-harness');
const token = fs.readFileSync(path.join(home, '.module-token'), 'utf8').trim();
```

三条硬要求，每条都有一个具体的坑：

1. **自己读这个文件，不要把它注入成环境变量。** 模块通常会把 `process.env` 整体透传给模型子进程
   （smart-factory 的 `claude-adapter.ts` 就是 `{ ...process.env, ...anthropicEnv }`），
   令牌一旦进了环境就等于交给了模型能调用的工具链。读文件则只存在于你自己的进程内存里，不被继承。
2. **必须按同一套 `COSIGHT_HOME` 规则解析目录**（`process.env.COSIGHT_HOME ?? ~/.cosight-harness`）。
   框架在开发机上常被指到别处，两边规则不一致的表现是"文件不存在"，或者更糟——读到**另一个实例**的令牌，
   连上去得到一个静默的 401。拿不准就先打一次 `GET /api/health` 对一下 `cosightHome`。
3. **令牌不是权限系统，别宣传成权限系统。** 同机同用户的其他进程本来就能直接读
   `$COSIGHT_HOME/.credentials.yaml`，根本不需要走 HTTP 拿令牌。这枚令牌挡住的是**浏览器里跑的代码**，
   这就是它存在的全部理由。

**没有"签发令牌"的接口**——只能读文件。这是刻意的：任何签发接口都得先认证调用者，而本机的认证手段
归根到底就是"能读到这个文件"，绕一圈回到原点，还白多开一个浏览器能打到的面。

**轮换与撤销**：服务端每个请求都重读该文件、不缓存，所以

```bash
rm ~/.cosight-harness/.module-token      # 立即全部 401，不用重启框架
```

换新令牌就覆写这个文件（一行 base64url），同样立即生效。

## 4. 读取接口（三条）

### 4.1 `GET /api/framework/v1/models` — 模型列表

**不含明文密钥**，也**不含掩码字段**（掩码在模块面没有语义，给了只会让人误用）。

```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5",
        "provider": "anthropic",
        "protocol": "anthropic",
        "label": "deepseek-v4-flash",
        "modelName": "deepseek-v4-flash",
        "baseUrl": "https://api.deepseek.com/anthropic",
        "hasApiKey": true,
        "isActive": true,
        "createdAt": "2026-10-15T06:10:13.679Z",
        "updatedAt": "2026-10-15T06:10:19.275Z"
      }
    ],
    "activeId": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5"
  },
  "error": null,
  "meta": null
}
```

`activeId` = 当前生效模型的 id，没有生效模型时为 `null`。
一次调用就能把下拉框预选中——分两次（先列表再查 active）的话，这两次调用之间用户换了模型会产生一个真实的竞态。

### 4.2 `GET /api/framework/v1/models/active` — 当前生效的模型（含明文密钥）

**没有生效模型时返回 `200` 且 `data: null`，不是 404**——"还没配过模型"是首次启动的正常状态，不是错误。

```json
{
  "success": true,
  "data": {
    "id": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5",
    "provider": "anthropic",
    "protocol": "anthropic",
    "label": "deepseek-v4-flash",
    "modelName": "deepseek-v4-flash",
    "baseUrl": "https://api.deepseek.com/anthropic",
    "hasApiKey": true,
    "isActive": true,
    "createdAt": "2026-10-15T06:10:13.679Z",
    "updatedAt": "2026-10-15T06:10:19.275Z",
    "apiKey": "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "temperature": 0.7,
    "topP": 1,
    "maxOutputTokens": null,
    "contextWindow": null,
    "timeoutSeconds": 120
  },
  "error": null,
  "meta": null
}
```

（示例里的 `apiKey` 是占位符；真实响应里就是明文，本机 `baseUrl` 与 `modelName` 也以实际返回为准。）

### 4.3 `GET /api/framework/v1/models/{id}` — 按 id 查详情（含明文密钥）

响应形状与 `/active` 完全相同。`{id}` 不存在 → `404`；不是合法 uuid → `422`。

## 5. 写入接口（三条）

三条写接口的**响应形状与读取完全一致**：都返回该模型的详情（`ModuleModelSecret`，**含明文
`apiKey`**）。这样"建完就地用"不需要再多一次 GET——而这个场景是真实存在的：建完配置立刻拿去起
子进程。代价是明文出现在写响应里，与详情、`/active` 一样，靠同一枚令牌兜着。

### 5.1 `POST /api/framework/v1/models` — 新建

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

成功 **`201`**。`provider` 非法 → `422`。

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"provider":"anthropic","label":"内部 Sonnet","modelName":"claude-sonnet-5-5",
       "baseUrl":"https://gateway.internal/anthropic","apiKey":"sk-…","isActive":false}' \
  "$BASE"
```

### 5.2 `PATCH /api/framework/v1/models/{id}` — 部分更新

请求体只放要改的字段，**至少一个**（空对象 → `422`）。`undefined`=不改、`null`=清空，
两者语义不同，这个区别在 `apiKey` 上最要紧：

| `apiKey` | 效果 |
|---|---|
| 不传 | **保持原密钥不动** |
| `null` | **清除密钥**（此后 `hasApiKey: false`、详情里 `apiKey: null`） |
| 字符串 | 覆盖 |

`{id}` 不存在 → `404`。

```bash
# 只改名，密钥与其它字段一概不动
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"label":"改个名字"}' "$BASE/<id>"
```

**切换当前生效的模型也是这条**：`PATCH { "isActive": true }`。
模块面**没有**单独的 `/activate`（浏览器面那条是给"列表行上的一个按钮"用的便利路由）。

### 5.3 `DELETE /api/framework/v1/models/{id}` — 删除

成功返回 `{ "id": "…", "deleted": true }`（**不是**模型详情）。同时会删掉
`.credentials.yaml` 里对应的那条密钥。`{id}` 不存在 → `404`。

## 6. 字段表

| 字段 | 类型 | 列表 | 详情 | 说明 |
|---|---|---|---|---|
| `id` | uuid | ✓ | ✓ | |
| `provider` | 枚举 | ✓ | ✓ | **供应商**：`openai` / `anthropic` / `azure-openai` / `ollama` / `openai-compatible` |
| `protocol` | `anthropic` \| `openai` | ✓ | ✓ | **线协议**，由 `provider` 派生，见第 7 节 |
| `label` | string | ✓ | ✓ | 界面上显示的名称 |
| `modelName` | string | ✓ | ✓ | 发给供应商的 model 字段（CC 配置里的那种），**不是**显示名 |
| `baseUrl` | string \| null | ✓ | ✓ | API 地址；`null` 表示用该供应商的官方地址 |
| `hasApiKey` | boolean | ✓ | ✓ | |
| `isActive` | boolean | ✓ | ✓ | |
| `createdAt` / `updatedAt` | ISO 8601 | ✓ | ✓ | |
| `apiKey` | string \| null | ✗ | ✓ | **明文**；没配过密钥为 `null` |
| `temperature` | number | ✗ | ✓ | 0–2 |
| `topP` | number | ✗ | ✓ | 0–1 |
| `maxOutputTokens` | number \| null | ✗ | ✓ | `null` = 不限制 |
| `contextWindow` | number \| null | ✗ | ✓ | `null` = 跟随模型默认 |
| `timeoutSeconds` | number | ✗ | ✓ | 秒 |

## 7. `provider` 不是 `protocol`——请一律用 `protocol`

`provider` 说的是**哪家供应商**（决定鉴权方式与官方地址），`protocol` 说的是**线上跑什么协议**
（Anthropic Messages vs OpenAI chat-completions）。两者不是一回事：
`azure-openai` / `ollama` / `openai-compatible` 都是 provider 各异的 OpenAI 兼容端点。

自己从 `provider` 硬推协议，会出现**用户设了一个 OpenAI 兼容模型、你却拿 Anthropic SDK 去打它**，
表现为一句语焉不详的上游报错。所以框架把结果直接给你：

| `provider` | `protocol` |
|---|---|
| `anthropic` | `anthropic` |
| `openai` / `azure-openai` / `ollama` / `openai-compatible` | `openai` |

`baseUrl` 为 `null` 时框架**不做默认值推导**——比如 `azure-openai` 的地址要带 deployment 段，
一律推导会静默给出错误地址，比给 `null` 更糟。拿到 `null` 就按你所选 SDK 的默认地址处理。

## 8. 错误

所有响应都是同一个信封：`{ success, data, error, meta }`。

| HTTP | `error.code` | 何时 |
|---|---|---|
| `401` | `UNAUTHORIZED`（`messageKey` = `error.unauthorized.module_token`） | 没带 `Authorization` / 方案不是 `Bearer ` / 令牌不对 / 令牌文件缺失或内容非法 |
| `403` | `FORBIDDEN` | `Host` 不是回环名，或来源不是回环地址，或请求带了 `Origin` |
| `404` | `NOT_FOUND` | 4.3 / 5.2 / 5.3 的 `{id}` 不存在 |
| `409` | `CONFLICT` | 写操作撞上唯一性约束（模型里目前只有"工作区重名"，模型接口本身不会遇到；列出来是为了让你别把它当未知错误） |
| `422` | `VALIDATION_FAILED` | 路径参数不是合法 uuid；请求体不合契约（空 `PATCH`、`provider` 非法、`baseUrl` 不是 http(s)…） |

**401 的四种原因返回同一句话，这是刻意的**：区分它们等于向外泄漏本机文件系统的状态
（"文件不存在" vs "内容非法"）。排查第一步永远是看服务端启动日志——里面会打出令牌文件的实际路径。

## 9. 推荐的接入写法

启动时取一次配置、缓存住；按 `protocol` 选 SDK 而不是按 `provider`；拿不到就**快速失败**，
不要静默降级成空配置：

```ts
async function loadModel(): Promise<{ model: string; baseUrl?: string; apiKey: string }> {
  const token = fs.readFileSync(path.join(home, '.module-token'), 'utf8').trim();
  const response = await fetch(`${FRAMEWORK_BASE}/api/framework/v1/models/active`, {
    headers: { authorization: `Bearer ${token}` },
  });

  if (response.status === 401) {
    throw new Error(`框架拒绝了模块令牌：检查 ${home}/.module-token`);
  }
  if (!response.ok) {
    throw new Error(`取模型配置失败：HTTP ${response.status}`);
  }

  const { data: model } = (await response.json()) as { data: ModelConfig | null };
  if (model === null) throw new Error('框架里还没有设置激活的模型');
  if (model.apiKey === null) throw new Error(`模型「${model.label}」没有配置密钥`);
  if (model.protocol !== 'anthropic') throw new Error(`暂不支持 ${model.protocol} 协议的模型`);

  return {
    model: model.modelName,
    ...(model.baseUrl === null ? {} : { baseUrl: model.baseUrl }),
    apiKey: model.apiKey,
  };
}
```

## 10. Postman / curl

### Postman

必须用**桌面版**——Web 版是从浏览器发请求的，必然带上 `Origin` 头，会被 403。

1. 取令牌：`cat ~/.cosight-harness/.module-token`（43 字符，文件末尾有换行，别把空白一起复制）
2. 新建请求 → 方法 `GET` → URL `http://127.0.0.1:4300/api/framework/v1/models`
3. Headers 加 `Authorization` = `Bearer <令牌>`（或 Authorization 页签选 Bearer Token 只填令牌，等价）
4. Send

**不要手动设 `Host` 头**（它是回环校验的依据，改了就 403），**不要开 Interceptor** 那类浏览器抓包转发
（`Origin` 会跟着过来，同样 403）。

### curl

```bash
TOKEN=$(cat ~/.cosight-harness/.module-token)
BASE=http://127.0.0.1:4300/api/framework/v1/models

# 读
curl -s -H "Authorization: Bearer $TOKEN" "$BASE"        | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/active" | python3 -m json.tool
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/<id>"   | python3 -m json.tool

# 写
curl -s -X POST  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"provider":"anthropic","label":"建一个","modelName":"claude-sonnet-5-5"}' "$BASE" | python3 -m json.tool
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"isActive":true}' "$BASE/<id>" | python3 -m json.tool
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$BASE/<id>" | python3 -m json.tool
```

写操作的 HTTP 状态码：`POST` 成功是 **`201`**，`PATCH`/`DELETE` 是 `200`。

## 11. 消费方自己的责任（框架管不了的部分）

- **`baseUrl` 是用户填的，框架只保证它是 http(s)。** 你必须自己校验地址
  （比如只允许内网段），不要把密钥发往不可信地址——这一层的 SSRF 面在调用方。
- **明文密钥只该存在于你的服务端进程内存里**：不要写进配置文件、不要进日志、不要发给前端。
- 密钥可能被用户在框架界面上改掉。如果你的进程是长驻的，要么接受"重启才生效"，
  要么定期重取；框架侧不做推送。

## 12. 写接口的权限面（请读完再决定要不要用）

写接口在第 5 节，它们**能改这台机器上平台级别的配置**：改模型、换生效项、删配置。
所以有三件事必须先说清。

### 12.1 令牌不是权限系统，所以写接口也没有额外的门

第 3.2 节第 3 条已经说过：同机同用户的其他进程本来就能直接读 `.credentials.yaml`，
根本不需要令牌。写接口**没有改变这一点**，它改变的是**爆炸半径**——
一枚泄漏的令牌原来只能读走密钥，现在还能把平台配置改成攻击者想要的样子
（最典型的一种：把某个模型的 `baseUrl` 改到自己控制的端点，用户的密钥就自动送过去了，
而框架界面完全看不出来）。

这不是"设计缺陷"而是本机单用户模型的固有形状。它的实际含义是：
**不该要写权限的模块就别要。** 如果你的模块只是读一份配置去起客户端，用 4 节那三条 GET。

### 12.2 写操作有审计日志

模块面的写操作（`POST`/`PATCH`/`DELETE`）在通过令牌校验后会**记一条 warn**，
内容是方法、路径、对端地址。模块面**没有操作者身份**，所以出了"谁把生效模型改坏了"
这类问题时，这条日志是唯一能回答"哪台机器、什么时候"的东西。
读取（GET）不记——那是噪声。

### 12.3 同一个数据目录只能有一个框架进程

这是**既有限制**，不是写接口引入的：`.credentials.yaml` 的写入串行化只在**单个进程内**有效
（`credentials/store.ts`，跨进程没有文件锁）。写接口没有加重它，因为模块面的写**全部经 HTTP
打到那一个框架进程**——写成序列化的那个 `CredentialStore` 实例始终只有一个，这正是
"跨进程丢更新"这条顾虑在写接口上**不成立**的原因。

但推论的边界要划清：**别用同一个 `$COSIGHT_HOME` 起两个框架实例。**
今天这样做的后果是"丢一次密钥更新"，加了模块面写入之后是"两个进程都认为自己该管这份配置"。
要跑第二个实例，用另一个 `COSIGHT_HOME`。

### 12.4 一次只有一个写者，没有版本号

模块翻 `isActive` 与框架界面上的设置页可能同时在写同一条配置，**没有乐观并发控制**
（没有 `If-Match`、没有版本号），后写的赢。本机单用户的量级下这不是问题，
但如果你要写一个"轮询并自动切换生效模型"的守护进程，请知道这个形状。
