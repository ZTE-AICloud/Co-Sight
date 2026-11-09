# 前端契约

> **本文件只写代码里读不出来的东西**：跨仓的接口约定、前端与后端之间必然会不一样的地方。
> **不抄** interface、props、组件树、字段清单 —— 那些以 `src/shared/api/*.ts` 与页面代码为准。
> 判断标准一句话：删掉这段，代码还说得清吗？说得清就是在抄，别写。
>
> 最后核对：2026-10-16

## 1. 接口风格

本仓后端（`server/`）的接口正本在 `server/docs/04-api/` 与 `server/docs/05-openapi/`，
前端所有请求都按这一套走。两条要记住的：

- **只许 `GET` / `POST`**，删除也是 POST，不提供 `put` / `patch` / `delete`。
- **路径与身份传法，迁移前后是两套**（前端目前两套都打）：
  - `05-openapi/` 覆盖的资源（**agents**）走**「资源身份一律进路径」**：
    集合 `GET|POST /agents`，个体 `GET /agents/{id}`、`POST /agents/{id}/update|delete`，
    请求体只承载可变字段。
  - `04-api/` 下的旧资源（sessions / runs / messages）仍是 `<资源>/<动作>` + **id 不进路径**。
    新增接口往 `05-openapi/` 那套靠，别照旧的抄。
- 错误统一 `{ error, message }`；错误码只用契约里已有的词汇：
  `BAD_REQUEST`(400) / `NOT_FOUND`(404) / `CONFLICT`(409) —— 目前 409 只有「重名」一种。

## 2. 前端侧的规矩

- **唯一 HTTP 出口是 `src/shared/api/client.ts`**（`createApiClient` + `ApiError`）。
  页面不自己拼 `fetch`。
- 每个后端一个文件：`shared/api/agents.ts`（智能体）、`shared/api/models.ts`（模型）、
  `shared/api/client.ts` 的 `api`。**服务地址只写在那几个文件的 BASE_URL 上**，
  `agents.ts` 的默认值直接拼 `VITE_API_BASE_URL`，所以本仓后端不用配任何环境变量。
- 失败提示的措辞留在调用点（各页要给出不同的下一步动作），**但「后端没起」的判据是共享的**：
  `shared/api/agents.ts` 的 `isBackendDown` —— 响应根本不是 JSON（整个服务没起、或 vite 代理
  连不上时，回的是 HTML 而不是 `{error,message}`）。后端自己报的 4xx / 5xx 有 JSON，
  不走这条，要把它的原话透出来。

## 3. 谁不在这个仓里

- **只有模型管理的真后端在别的组件**：`shared/api/models.ts` 打本仓 server 的只读代理，数据源是框架的模型配置（框架模块面没有写接口）。
- **智能体管理已经收进本仓**（`server/src/modules/agent/`，`web/mock/agents-plugin.ts` 已删）——
  它的接口形状、状态机、盘库副作用都以 `server/docs/` 为正本，前端不再自己定。
- 端侧形态：前端与 Claude Code 同机，**没有「上传附件」这回事**，一律是选本地路径。
  路径从 `GET /fs/roots` + `GET /fs/list` 来（主目录与工作区只是快捷入口，整机任意绝对路径都能选），随 `send` 的
  `attachments: [{ path }]` 传给后端，落进消息自己的 `content.files`；前端不读文件内容、
  也不自己拼绝对路径。`/files` 那个上传端点只服务封面图这类要长期保存的资源。
  **只挂附件、不写正文也可以直接发送**（`send` 的 `prompt` 与 `attachments` 任一项非空即可）；
  首页在这种情况下的创建请求用文件名兜名字（`features/home/create-agent.ts` 的 `nameFromFile`）。

## 4. 创建会话：首页 → 创建页的交接（**过渡实现已落地，目标契约待后端**）

> **现状（2026-10-18）：用的是过渡方案 —— 路由 state 交接 + 设计页补发。**
> 首页把原话与后端建好的初始化会话 id 放进 `navigate(..., { state })`；设计页优先进那场
> 会话，打开后若是 development 且一条消息都没有，就经实时会话补发一次
> （`features/agent-create/useCreationChat.ts` 的 `seed`）。刷新时 `history.state`
> 通常还在；新标签页 / 手输地址会丢载荷 —— 此时退化为空对话，不会误发，也不会重复。
> **后端 `agents/create` 的 `init.input` 目前只做形态校验：不落库、不起 run。**
>
> 下面这套仍是目标契约（刷新、多标签、换设备都收敛到服务端那一场会话）：

用户在首页写的那句话，**不是智能体的一个字段，而是一场创建会话的第一轮消息**。
它在后端，前端只读 —— 这样刷新、多标签、换设备都收敛到同一场会话，前端不需要任何"交接载荷"。

```
首页   POST agents/create { name, description(截断的摘要), firstPrompt(需求全文) }
         └─ 后端在登记身份的同时：建这场创建会话，写入 turn=0 的 user 消息（state=pending）

创建页 GET  session({ agentId, purpose: 'create' })     → 会话 + 消息列表（首轮就是那句话）
       POST start({ sessionId })                        → 幂等点火；后端已开跑就返回当前状态
       WS   订阅这场会话                                 → 之后一切由推送驱动
```

**每条消息带 `state`，这是"有没有被使用"的唯一表示：**

| state | 含义 | 创建页该做什么 |
|---|---|---|
| `pending` | 已入库，**还没有执行体接手** | 调一次 `start`（幂等，抢不到锁也没关系） |
| `running` | 已被消费，正在处理 | 什么都不做，渲染进行态 |
| `done` / `failed` | 这一轮结束 | 渲染结果；`failed` 给"重试"（对同一 messageId 再调 start） |

**几条硬约定：**

- **`start` 是幂等动作，不是"消费掉一个标记"**：后端用 `WHERE state='pending'` 抢锁，抢到才跑。重复调用返回当前状态，不产生第二个执行体。
- **状态挂在消息上，不挂在会话上**：一次创建是多轮的（首轮需求 + 后续补充），会话级的一个 `startedAt` 回答不了"我补充的这句被处理了没有"。
- **写入按 `(sessionId, turn)` 幂等**：首轮与重试重复提交返回同一条消息，不产生第二条。
- **身份创建也要幂等键**（`requestId`，前端生成，随 `agents/create` 一起发）：两个标签页各点一次发送会各建一个智能体 —— 会话那层的抢锁挡不住这个（那是两场不同的会话）。后端按 `requestId` 去重：**同一个键返回同一个智能体**（手抖、两标签、网络重试都收敛），不同的键才是"用户真的又要了一个"，照常走重名规则。
- **前端的职责边界**：只读状态、按 state 渲染、按 state 决定"要不要调一次幂等的 start"。**不做"是否已消费"的判断** —— 前端读到的都是快照，两个标签页或一段网络延迟就能让它判断错。

## 5. 契约偏差表

**另立一份：[`deviations.md`](./deviations.md)** —— 前端与后端逐条要确认的地方。

拆开的理由是打开动机不同：这份（`contracts.md`）是**改接口 / 改代码**时看的，
那份是**要跟后端对齐**时看的。改代码不用翻偏差表，对齐接口不用通读契约。
