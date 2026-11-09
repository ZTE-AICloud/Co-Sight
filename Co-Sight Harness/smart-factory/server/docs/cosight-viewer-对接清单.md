# cosight-viewer 对接 smart-factory 协议与接口清单

> 面向：cosight-viewer 客户端团队
> 服务端：smart-factory server
> 日期：2026-10-19
> 前提：smart-factory 只改服务端，cosight-viewer 代码由客户端团队评估修改。
> 完整对比矩阵见 [`cosight-viewer-ws-能力对比.md`](./cosight-viewer-ws-能力对比.md)；本文只列需要对齐的动作项。

## 1. 结论

- 帧信封、心跳已经一致；成功/错误响应 `method` 统一为 `<请求 method>.result`（`ping` 为 `pong`），WS 错误码只有 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`。
- 9 个上行方法中 8 个可以直接使用。
- `send` 首帧需要把 `versionId` 换成 `agentId`，并带上必填的 `modelId`（可选 `mode` / `effort`）；**不选智能体时不发 `agentId`**（自由对话，仍要带 `modelId`）；续聊改发 `sessionId`。
- `send` 在建 run 前完成引擎 / 工作区 / cwd / 模型解析；解析失败直接返回错误，不建 run、不落用户消息、不改会话状态。建 run 即 `running`，响应与 `run.started` 都给出运行态（`run.started` 在响应前广播）。
- 9 个下行事件中 8 个已经可用。
- 服务端另有 `chat.thinking` / `chat.retry` / `settings.changed` 与 2 个 `task.*` 原生事件；客户端未注册，忽略即可，现有 9 个事件名不变（payload 只增加附加字段）。旧的 `chat.thinking.delta` 已删除，要展示思考必须改接 `chat.thinking`。
- `interactive.timeout` 服务端刻意不实现。
- 客户端还需要切换 base URL、agents 数据源、会话恢复端点和 version UI。
- 服务端协议已经就绪；**本次只改服务端与文档，cosight-viewer 代码未由我们修改**，客户端不改代码无法自动完成这些切换。

### 1.1 刻意差异（客户端必须知道）

- **没有 `versionId`**：首帧 `send` 必须发 `modelId`；选了智能体再带 `agentId`（新建 runtime 会话），不选智能体就只发 `modelId`（自由对话，新建目录会话）。续聊必须发 `sessionId`。
- **每个会话都有非空模型**：`sessions/create` 与首帧 `send { agentId }` 必填 `modelId`；`model.switch` 只能换成另一个非空模型，不能清空，也没有工作区默认 / 框架生效 / 本机配置回退。
- **没有审批/交互超时**：`approval.request` 不带 `expiresAt`，`tool.interactive` 不带 `timeout`，服务端永远不会发 `interactive.timeout`。
- **没有 `connectionToken` / 鉴权**：`connection.ready` 的 `restored` 恒为 `false`、`sessionId` 恒为 `null`；重连后必须重新 `subscribe`。
- **没有模型回退**：`send.result.modelFellBack` 恒为 `false`；模型解析失败直接返回错误，不在多个模型间自动切换。

## 2. 连接信息

```text
WS:   ws://localhost:4100/api/smart-factory/v1/ws
HTTP: http://localhost:4100/api/smart-factory/v1
```

信封保持不变：

```json
{
  "id": "msg_...",
  "type": "request | response | event",
  "method": "...",
  "timestamp": 1760000000000,
  "payload": {},
  "error": null
}
```

客户端现有地址在 `client/src/config/api-config.ts:16,19`，仍是 `127.0.0.1:15907`，需要改成上面的地址。

## 3. 首帧建会话

### 3.1 客户端现在发什么

```json
{
  "method": "send",
  "payload": { "prompt": "你好", "versionId": "default" }
}
```

### 3.2 smart-factory 需要什么

选了智能体：

```json
{
  "method": "send",
  "payload": {
    "prompt": "你好",
    "agentId": "agt_...",
    "modelId": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5",
    "mode": "workspace_write",
    "effort": "high"
  }
}
```

没选智能体（自由对话）：

```json
{
  "method": "send",
  "payload": {
    "prompt": "你好",
    "modelId": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5",
    "mode": "workspace_write",
    "effort": "high"
  }
}
```

- `agentId` 必须是 smart-factory 的 agent id，形如 `agt_...`；不选智能体时**整个字段不发**，不是发空串。
- 框架 experts 的 id 不是 smart-factory agent id。
- 本开源版没有 `versionId` 概念，不要发送 `versionId`。
- `modelId` 必填且非空（两种首帧都一样）；`mode` / `effort` 可选，缺省 `workspace_write` / `high`。
- 每次首帧都新建一条会话（有 `agentId` 是 runtime 会话，没有是目录会话），不复用已有会话；要续聊必须使用响应里的 `sessionId`。

### 3.3 首帧响应

响应帧 `method` 为 `send.result`，`payload` 形状如下：

```json
{
  "sessionId": "sess_...",
  "runId": "run_...",
  "instanceId": "inst_...",
  "status": "running",
  "effort": "high",
  "modelId": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5",
  "modelName": "claude-sonnet-4-5",
  "modelFellBack": false,
  "message": {
    "id": "msg_...",
    "sessionId": "sess_...",
    "runId": null,
    "seq": 1,
    "role": "user",
    "type": "text",
    "status": null,
    "content": { "text": "你好" }
  },
  "run": {
    "id": "run_...",
    "sessionId": "sess_...",
    "instanceId": "inst_...",
    "status": "running",
    "startedAt": "2026-10-19T00:00:00.255Z"
  }
}
```

客户端只需要读顶层 `sessionId`、`runId`、`instanceId`。顶层 `status` 与 `run.status` 均为 `running`，收到响应即可进入运行态，不需要再等 `run.started` 才认为已起跑；`run.started` 实际在响应前广播（run 已被并发中止时不发）。`modelFellBack` 恒为 `false`（不实现模型回退）。

### 3.4 首帧行为

- `sessionId` 与 `agentId` **至多给一个**，两个都给返回 WS `VALIDATION`；**都不给是自由对话**（不选智能体），首帧只发 `{ modelId, mode?, effort?, prompt, attachments? }`。
- 首帧 `{ agentId, modelId, mode?, effort? }` **每次都新建一条 runtime 会话**，不复用已有会话。
- 自由对话首帧 **每次都新建一条目录会话**（`agentId=null`、`stage='runtime'`）：cwd 取框架当前生效工作区目录；没有生效工作区时落到 `{COSIGHT_HOME}/smart-factory/chat`（服务端按需创建）。
  - `modelId` / `mode` / `effort` 规则与 `agentId` 首帧相同；
  - 目录实例是实例级仲裁：同一工作区同时只能有一个活跃顶层 run，第二个首帧返回 `CONFLICT`（`agentId` 首帧不受此限，见下文「并发首帧」）；
  - 会话详情里 `instance.agentId` 为 `null`（`instance.stage` 是它的用途：自由对话 = `runtime`、工坊 = `development`），客户端展示时不要依赖专家名；判「目录会话」只看 `agentId`。
  - 工作区存在但未绑目录 / 框架不可达返回 `INTERNAL`，不会悄悄换目录。
- 新会话的字段：
  - `modelId` 必填且非空（缺失 / 空串 / 非字符串 `VALIDATION`）；
  - `mode` 缺省 `workspace_write`；
  - `effort` 缺省 `high`；
  - `resumeSessionId` 为 `null`。
  三个设置都落在新会话上，首轮 run 使用它们。
- 服务端在建 run 前解析引擎适配器、工作区 / 阶段 cwd（预览 / 评估在此物化）与模型；解析失败直接返回错误，**不建 run、不落用户消息、不改会话状态**，新建的会话会被删除。
- `stage` 固定为 `runtime`。
- agent 必须已有生产产物；产物缺失时 `send` 返回错误，不建 run。
- 未知 `agentId` 返回 WS `NOT_FOUND`。
- 并发首帧：同一 agent 的不同会话各自新建并起 run，不因实例已有活跃 run 返回 `CONFLICT`；产物门禁失败仍按上一条返回错误。
- 模型不存在 / 协议不符 / 缺密钥 / 缺 `modelName` 返回 WS `VALIDATION`；框架不可达 / 5xx 返回 WS `INTERNAL`。
- run 建行即 `running` 并写 `startedAt`；`run.started` 在 `send` 响应前广播（若返回前被并发中止则不广播）。

### 3.5 客户端改动点

- `client/src/api/chat-socket.ts:279-303`：`sendMessage` 的 `versionId` 参数改成 `agentId`（可选）并增加必填 `modelId`，payload 发 `agentId`（选了才发）/ `modelId` / `mode` / `effort`。
- `client/src/pages/chat/useChatSession.ts:679-713`：`startSession` 改为校验当前选中模型，有选中智能体时调用 `createInstanceAndSend({ agentId: agent.id, modelId, mode, effort, prompt })`；没有智能体时调用同一方法但不传 `agentId`（自由对话）。
- `client/src/pages/chat/useChatSession.ts:818`：`canSend` 从 `selectedAgent?.versionId` 改为 `selectedAgent?.id`，并要求已选模型。

## 4. 续聊

客户端发：

```json
{
  "method": "send",
  "payload": { "prompt": "再说详细点", "sessionId": "sess_..." }
}
```

响应 `method` 为 `send.result`，载荷与首帧相同：顶层带 `runId` / `status:"running"` / `effort` / `modelId` / `modelName` / `modelFellBack:false`，另带 `message` / `run`（`run.status` 为 `running`），没有 `created`。
续聊使用该会话的 `modelId` / `approvalMode` / `effort`；请求里不要带 `modelId` / `mode` / `effort`，带了返回 WS `VALIDATION`。

客户端现有代码 `useChatSession.ts:743-748` 已经读 `payload.runId`，不需要改。

## 5. history

### 5.1 请求

```json
{
  "method": "history",
  "payload": {
    "sessionId": "sess_...",
    "limit": 50,
    "offset": 0,
    "includeTelemetry": false
  }
}
```

### 5.2 响应

响应 `method` 为 `history.result`：

```json
{
  "method": "history.result",
  "payload": {
    "sessionId": "sess_...",
    "total": 1,
    "messages": [
      {
        "id": "msg_...",
        "sessionId": "sess_...",
        "runId": "run_...",
        "role": "user",
        "type": "text",
        "content": "你好",
        "createdAt": "2026-10-19T00:00:00.000Z"
      }
    ]
  }
}
```

- `messages` 按 `seq` 升序，最早在前。
- `total` 是该会话的**全部消息条数**，与 `limit` / `offset` 无关。
- `content` 恒为字符串。
- `offset` 从最新一条往前跳过。
- `includeTelemetry` 接收但忽略。
- `history` 成功后会隐式订阅该会话，恢复会话后可以直接收到后续实时事件，不需要额外调用 `subscribe`。

### 5.3 客户端改动点

- `client/src/api/chat-socket.ts:262-274` 已经按这个形状发请求。
- 如果客户端校验响应 `method`，需要接受 `history.result`。
- 如果客户端只按 `id` 匹配响应，不需要改。

## 6. 三个 switch

三个方法都是会话级设置，**下个 run 生效，活跃 run 不中断**，不会返回 409。

| 方法 | 请求 | 取值 | 成功响应 payload |
|---|---|---|---|
| `model.switch` | `{ sessionId, modelId }` | 框架模型 uuid，必须非空；不能清空，空串或非字符串返回 `VALIDATION` | `{ sessionId, modelId, appliesTo: "nextRun" }` |
| `mode.switch` | `{ sessionId, mode }` | `read_only` / `workspace_write` / `full_access` | `{ sessionId, mode }` |
| `effort.switch` | `{ sessionId, effort }` | `low` / `medium` / `high` / `xhigh` / `max` | `{ sessionId, effort }` |

- 响应 `method` 分别为 `model.switch.result` / `mode.switch.result` / `effort.switch.result`。
- 变更同时广播 `settings.changed`：`{ sessionId, settings:{mode,effort,modelId}, changedBy:{channel:"ws"|"http", actorId:""}, appliesTo?, at }`；viewer 可忽略，多端同步时用它更新设置 UI。
- 客户端现有代码 `useChatSession.ts:649-669` 已经按这个形状发送，不需要改。

注意：首帧 `send { agentId }` 已经接受 `modelId` / `mode` / `effort`，新会话的首轮直接使用这三个值，不再需要先 `send` 再补 switch。

- `send { sessionId }` 续聊时首轮使用该会话原来的设置，三个 switch 从下一个 run 开始生效。
- 若要在续聊的下一轮改设置，用 `model.switch` / `mode.switch` / `effort.switch`。
- `model.switch` 不能清空模型；清空不是支持的操作。

## 7. 审批与工具应答

### 7.1 approval.respond

客户端发：

```json
{
  "method": "approval.respond",
  "payload": { "approvalId": "msg_...", "decision": "approved" }
}
```

- `approvalId` 就是 `approval.request` 里的审批消息 id。
- `decision` 取 `approved` / `approved_all` / `rejected`。
- 响应 `method` 为 `approval.respond.result`，载荷 `{ approvalId, decision, resolved: true }`；客户端不读响应字段，结算后的 `Message` 走 `message` 事件。

### 7.2 tool.respond

客户端发：

```json
{
  "method": "tool.respond",
  "payload": {
    "toolCallId": "call_...",
    "answers": [
      { "question": "选哪个？", "answer": "A" }
    ]
  }
}
```

- 服务端同时接受数组形态和对象形态 `{ "问题原文": ["A"] }`。
- 响应 `method` 为 `tool.respond.result`，载荷 `{ toolCallId, received: true }`；客户端不读响应字段，结算后的 `Message` 走 `message` 事件。

客户端现有代码 `useChatSession.ts:791-816` 已经按这个形状发送，不需要改。

## 8. 下行事件

客户端注册的 9 个事件中，8 个已经对齐；`interactive.timeout` 刻意不实现。

| 事件 | smart-factory payload | 说明 |
|---|---|---|
| `chat.delta` | `{ sessionId, runId, parentRunId, messageType: "text", delta }` | 只承载正文 |
| `chat.thinking` | `{ sessionId, runId, parentRunId, phase: "start" \| "delta" \| "stop", text?, at }` | 思考阶段；`text` 仅 `delta` 出现。旧的 `chat.thinking.delta` 已删除，要展示思考必须改接本事件 |
| `chat.retry` | `{ sessionId, runId, parentRunId: null, attempt, maxRetries, errorStatus, error }` | 引擎 API 重试通知，run 仍在继续；可选消费 |
| `chat.final` | `{ sessionId, runId, parentRunId, content, messageId }` | 成功 run 恰好一次；`messageId` 指向落库终稿 |
| `chat.error` | `{ sessionId, runId, parentRunId, code: "RUN_ERROR", message }` | 失败 run 收尾 |
| `chat.aborted` | `{ sessionId, runId, parentRunId, reason }` | 中止 run 收尾 |
| `approval.request` | `{ approvalId, sessionId, runId, parentRunId, toolCallId, agentId?, toolName, title, description, input, options }` | `approvalId` 即审批消息 id；无 `expiresAt`；`allowAll=false` 时 `options` 不含 `approved_all` |
| `tool.interactive` | `{ sessionId, runId, parentRunId, toolCallId, toolName, input: { questions } }` | 与客户端形状一致；没有 `timeout` |
| `tool.executing` | `{ sessionId, runId, parentRunId, toolCallId, toolName, input }` | 与客户端形状一致 |
| `tool.executed` | `{ sessionId, runId, parentRunId, toolCallId, toolName, input, output, isError }` | `toolName` / `input` 从对应 `tool_use` 回填 |
| `settings.changed` | `{ sessionId, settings: { mode, effort, modelId }, changedBy: { channel: "ws" \| "http", actorId: "" }, appliesTo?, at }` | 设置变更的多端同步通知；可选消费 |
| `interactive.timeout` | 永不发出 | 服务端对审批/交互不设超时 |

客户端现有事件处理器 `useChatSession.ts:344-428` 不需要改：新增字段都是附加字段，客户端按原有字段读取即可。

`chat.final` 是唯一结束 loading 的兼容事件；`message` / `run.status` 是 smart-factory 原生事件，客户端没有注册，会忽略。

### 8.1 错误帧

- 成功与错误响应的 `method` 都是 `<请求 method>.result`（`ping` 为 `pong`）。
- `error.code` 是字符串枚举，只有 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`。
- `SLOW_CONSUMER` 不是响应错误码，只出现在连接级 `error` 事件的 payload 里；收到后要重连 + 重订阅 + 重拉。
- 客户端只读 `error.message`。
- 客户端类型里 `code` 是 `number`，如果你们开严格类型检查，改成 `string` 即可，运行时没有影响。

### 8.2 心跳

- 客户端每 30 秒发 `ping`。
- 响应 `method` 为 `pong`，载荷 `{ serverTime }`；客户端原本不读响应，无需改。
- 服务端 2 倍间隔没有收到任何上行帧才断开。
- 客户端现有心跳满足要求。

### 8.3 `task.*` 事件（新增，无需消费）

- 服务端新增两个原生事件：`task.started`（子 agent 任务开始）与 `task.notified`（子 agent 任务结束）。
- 客户端没有注册这两个事件，收到后忽略即可，不需要改动代码。
- 现有 9 个下行事件的名称与到达顺序不变；payload 只增加附加字段，客户端按原有字段读取即可。
- 子 agent 的内容事件会把 `runId` 填成子 run id；`chat.*` / `tool.*` / `approval.request` / `tool.interactive` 额外带 `parentRunId`；客户端可继续忽略这些字段，审批与交互仍按 `approvalId` / `toolCallId` 结算。
- `task.started` 的 wire 字段：`{ sessionId, runId, parentRunId, taskId, toolCallId, subagentType, delegationDepth, description? }`；`toolCallId` 在 REST `Run` DTO 里叫 `parentToolUseId`。
- `task.notified` 的 wire 字段：`{ sessionId, runId, parentRunId, taskId, status, subagentType, error?, summary? }`；`status` 用 SDK 原值 `completed` / `failed` / `stopped`（DB 映射为 `succeeded` / `failed` / `aborted`）。
- 如需展示子 agent 会话状态，见 `server/docs/04-api/4.05-运行.md` 的 `runs/children` 与 `4.06-实时通道.md` 的 §5.8 / §5.9。

## 9. 客户端数据源与会话恢复

### 9.1 agents 数据源

现状：

- `client/src/api/agent-api.ts:141-142` 的 `fetchAllAgents` 读框架 experts。
- `client/src/api/harness-api.ts:44` 的 `DEFAULT_AGENT_VERSION_ID` 把所有 agent 的 version 固定成 `"default"`。
- `client/src/api/agent-api.ts:162-185` 的 `fetchAgentDetail` 伪造一个版本。

需要对齐：

- agents 改读 smart-factory `GET /api/smart-factory/v1/agents`。
- smart-factory agents 的 `id` 形如 `agt_...`，可以直接作为首帧 `send` 的 `agentId`。
- 删除或停用 `versionId` / `DEFAULT_AGENT_VERSION_ID` / `fetchAgentDetail` 的伪造版本逻辑。
- `AgentPickerDialog` 和 `fetchAllAgents` 使用同一份 smart-factory agents 数据。

如果继续使用框架 experts 的 id，服务端 `send {agentId}` 会因为 agent 不存在返回 404。
框架 experts 和 smart-factory agents 目前没有映射关系。

### 9.2 会话恢复

现状：

- `client/src/pages/chat/session-api.ts:18` 调 agent-runtime `GET /v1/sessions/{sessionId}`。
- 期望 `{ data: { agentId, modelId, effort, approvalMode } }`。

需要对齐：

- 改调 smart-factory `GET /api/smart-factory/v1/sessions/detail?sessionId=...`。
- 响应是 `Session` 对象，不是 agent-runtime 的 `{ code, data }` 信封。
- 字段映射：

| 客户端字段 | smart-factory 字段 |
|---|---|
| `agentId` | `instance.agentId` |
| `modelId` | `modelId` |
| `effort` | `effort` |
| `approvalMode` | `approvalMode` |
| `resumeSessionId` | `resumeSessionId`（客户端不需要使用） |

### 9.3 version UI

- `client/src/pages/ChatPage.tsx:42` 的 `initialVersionId` 不再参与 send。
- `useChatSession.ts:530-562` 的 `resolveVersion` / `selectedAgent.versionId` 可以删除或保留为纯 UI 占位。
- `canSend` 改为检查 `selectedAgent.id`。
- URL 上的 `?versionId=` 可以忽略或删除；`?agentId=` 继续使用。

### 9.4 models 数据源

- `fetchModels` 继续读框架浏览器面 `GET http://127.0.0.1:4300/api/models` 即可。
- 模型 id 是框架模型 uuid，和 smart-factory `model.switch` / `resolveModelConfig` 使用同一 id 空间。
- 模型部分不需要改。

### 9.5 base URL

- `client/src/config/api-config.ts:16,19` 的 `AGENT_RUNTIME_API_URL` / `AGENT_RUNTIME_WS_URL` 需要指向 smart-factory。
- 如果保留框架 experts/models 的读取，`HARNESS_API_BASE` 仍然是 `http://127.0.0.1:4300/api`，不需要改。

### 9.6 workspaces 数据源（内置智能体监控）

现状：viewer 的工作区清单来自框架 `GET /api/framework/v1/workspaces`（`server/routes/workspaces.js`，
`server/routes/sessions.js` 的 `/sessions/facets` 也单独取了一次）。框架清单里只有用户工作区，而 smart-factory
自己创建的会话都落在 `{COSIGHT_HOME}/smart-factory/` 下，不属于任何工作区：

- 内置专家 runtime 会话：`builtin-agents/{id}/`
- 技能工坊的创建 / 优化技能会话：`skill-workshop/`
- 没有生效工作区时的自由对话：`chat/`

这些会话的 cwd 不在任何工作区目录下，于是永远落不进 viewer 的按目录过滤 —— 这就是「监控不到」的原因。

smart-factory 新增只读端点：

```text
GET http://127.0.0.1:4100/api/smart-factory/v1/workspaces/directories/list
→ { items: [{ id, name, directory, defaultModelId, kind }], activeId }
```

- `items` 是框架工作区 + 一条「内置与技能开发目录」；条目形状是 viewer `Workspace` 的超集（`id` / `name` / `directory` 原样可用）。
- `kind='workspace'`：`id` 是框架工作区 id，`directory` 可为 `null`（未绑目录），`activeId` 只会命中这一类。
- `kind='default'`：只有一条，`id` 固定 `default`、`name` 固定 `内置与技能开发目录`，
  `directory` 是 `{COSIGHT_HOME}/smart-factory`（symlink 已解）。上面三类 cwd 都在该目录之下，
  viewer 现有的「等于目录或在其下」前缀匹配即可全部命中；不按专家 / 技能分条，
  项目下拉里只多一项，不会混进一堆专家名。
- 这个名字与框架启动时自建的「默认工作区」**不同名**，是刻意的：两者都会出现在 viewer 的筛选下拉里，
  同名会被读成同一个东西。判别一律看 `kind` / `id`，不要看 `name`。
- 框架不可达时整端点返回 `502`（与 `/workspaces/list` 同口径），不做降级。
- 完整契约见 [`04-api/4.01-接口总览.md`](./04-api/4.01-接口总览.md) §4.6。

viewer 改动点（服务端两个文件即可，前端不用动）：

- `server/routes/workspaces.js`：改为请求上面的 smart-factory 端点；`items` 原样映射即可，
  `kind` / `defaultModelId` 是附加字段，viewer 不需要读。
- `server/routes/sessions.js` 的 `fetchWorkspaceDirectories`（`/sessions/facets`）：同样改为从该端点取 `directory`，
  否则统计 / 筛选用的 cwd 清单仍缺这条内置目录。
- 不要求 viewer 改 `client/src/lib/types/workspace.ts`：多出的 `kind` / `defaultModelId` 是附加字段。

## 10. 行为说明

- 一个 `runtime` 实例可以有多条会话；每次 `send { agentId }` 都新建一条，不复用已有会话，响应返回新的 `sessionId`。
  同一 agent 的不同会话可以各有一个活跃顶层 run 并发执行；共享 cwd 的写冲突边界见 [`03-architecture/02-data-model.md`](./03-architecture/02-data-model.md) §6。
- 自由对话（首帧不带 `agentId`）每次也新建一条会话，落在目录实例上（`agentId=null`、`stage='runtime'`）。
  **同一工作区的自由对话可以并行**（runtime 是会话级仲裁，与智能体 runtime 会话一致）；工坊的目录实例是 development，才受实例级互斥。
  没有生效工作区时会话落到 `{COSIGHT_HOME}/smart-factory/chat`，服务端按需创建。
- 新会话的 `modelId` / `mode` / `effort` 来自首帧（`mode` / `effort` 缺省 `workspace_write` / `high`），首轮 run 直接使用，`resumeSessionId` 为 `null`。
- 续聊必须 `send { sessionId }`，使用该会话的 `modelId` / `approvalMode` / `effort`；请求携带 `modelId` / `mode` / `effort` 返回 `VALIDATION`。
- `sessions/create` 同样必填非空 `modelId`；所有 Session 的 `modelId` 恒非空，没有 auto / 回退。
- 模型解析或产物门禁失败时，刚建的会话会被删除；`send { agentId }` 不因实例已有活跃 run 冲突（新会话的活跃 run 名额为空），`send { sessionId }` 在该会话已有活跃 run 时返回 `CONFLICT`。
- `send` 在建 run 前解析引擎 / 工作区 / cwd / 模型；解析失败直接返回错误，不建 run、不落用户消息、不改会话状态。
- `send` 返回的顶层 `status` 与 `run.status` 恒为 `running`，`startedAt` 已落值；`run.started` 在响应前广播。只有并发中止导致 run 已终态时才跳过 `run.started`，终态 run 永不补发。
- `modelFellBack` 恒为 `false`：本服务不实现模型回退。
- `send {agentId}` 固定走 `runtime`，需要该 agent 有生产产物。
- `resumeSessionId` 由服务端保存并在下一轮传给引擎，客户端不需要处理。
- `interactive.timeout` 永不发出，客户端不要等待该事件，也不要在 UI 上显示倒计时。
- `history` 成功后会隐式订阅会话，恢复会话后可以直接收到实时事件；响应载荷是 `{ sessionId, messages, total }`，`total` 为会话全部消息条数。
- `subscribe` / `unsubscribe` 客户端可以继续不调用；`send` 和 `history` 都会隐式订阅。`unsubscribe` 响应是 `{ sessionId, unsubscribed: true }`。
- `run.abort` 响应是 `{ runId, aborted: true }`（`runId` 为解析后的顶层 run），客户端不读响应字段。
- `ping` 响应 `method` 为 `pong`、载荷 `{ serverTime }`，客户端不读响应字段。
- 思考展示：旧 `chat.thinking.delta` 已删除；需要展示就消费 `chat.thinking` 的 `start` / `delta` / `stop`，不需要就忽略。
- 设置同步：三个 switch 成功后会广播 `settings.changed`，多端场景用它刷新 UI；单端客户端可忽略。
- 错误码：WS 只有 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`，客户端只读 `error.message` 即可。

## 11. 客户端改造清单

| 优先级 | 文件 | 改动 |
|---|---|---|
| P0 | `client/src/config/api-config.ts` | WS/HTTP base 改到 smart-factory |
| P0 | `client/src/api/chat-socket.ts` | 首帧 `send` 发必填 `modelId`（可带 `mode` / `effort`）；选了智能体再发 `agentId`，不选就不发（自由对话）；去掉 `versionId`；续聊发 `sessionId` |
| P0 | `client/src/pages/chat/useChatSession.ts` | `startSession` / `canSend` 改用 `agent.id` |
| P0 | `client/src/api/agent-api.ts` / `harness-api.ts` | agents 改读 smart-factory `/agents`，删除伪造 version |
| P1 | `server/routes/workspaces.js` | 工作区清单改调 smart-factory `/workspaces/directories/list`，内置专家 / 技能开发 / 自由对话会话随「内置与技能开发目录」进入监控（§9.6） |
| P1 | `server/routes/sessions.js` 的 `/sessions/facets` | cwd 清单同样改从 `/workspaces/directories/list` 取，否则统计 / 筛选仍漏默认工作区 |
| P1 | `client/src/pages/chat/session-api.ts` | 会话恢复改调 smart-factory `/sessions/detail` 并映射字段 |
| P1 | `client/src/pages/ChatPage.tsx` / `useChatSession.ts` | 清理 `initialVersionId` / `resolveVersion` / `versionId` |
| P1 | `useChatSession.ts` 的 `interactive.timeout` 处理 | 不再等待该事件，移除倒计时 |
| P1 | `useChatSession.ts` 的思考展示 | 若展示思考，`chat.thinking.delta` 改为 `chat.thinking` 三阶段；不展示则忽略 |
| P2 | `client/src/api/chat-socket.ts` 的错误类型 | `error.code` 从 `number` 改为 `string`，取值 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`（可选） |
| P2 | `client/src/api/chat-socket.ts` 的响应匹配 | 若校验响应 `method`，改为接受 `<请求 method>.result`；`ping` 接受 `pong`（可选） |

## 12. 服务端已完成项

- 帧信封、心跳；成功/错误响应 `method` 为 `<请求>.result`，`ping` 为 `pong {serverTime}`。
- WS 错误码收敛为 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`。
- 12 个上行方法：原生 6 + 兼容 6；各方法的成功响应载荷已按目标协议收敛。
- 19 个下行事件：原生 9 + 兼容 10；其中 `task.started` / `task.notified` 是新增的子 agent 事件。
- `send` 首帧 `{ agentId, modelId, mode?, effort? }` 每次新建 runtime 会话，续聊 `{ sessionId }`；建 run 前完成解析，失败直接返回错误且不建 run，新建的会话会被删除；响应顶层带 `sessionId` / `runId` / `instanceId` / `status:"running"` / `effort` / `modelId` / `modelName` / `modelFellBack:false` / `message` / `run`（`run.status` 为 `running`），没有 `created`，`run.started` 在响应前广播。
- `history` 的升序、字符串 `content`、`offset`、`history.result`、`payload.sessionId`、`total`（会话全部消息数）、隐式订阅。
- `model.switch` / `mode.switch` / `effort.switch` 的 next-run 语义与 `{ sessionId, ... }` 响应，以及 `settings.changed` 广播。
- `approval.respond` 响应 `{approvalId, decision, resolved:true}`；`tool.respond` 响应 `{toolCallId, received:true}`。
- `chat.delta` 只发正文并带 `parentRunId`；thinking 走 `chat.thinking` 三阶段；`chat.thinking.delta` 已删除。
- `chat.retry`、`settings.changed` 已加入事件集。
- `approval.request` / `tool.interactive` 没有超时字段；`interactive.timeout` 按定案不实现。
- 连接不提供 `connectionToken` / 鉴权，`connection.ready.restored` 恒 `false`、`sessionId` 恒 `null`。
- `GET /workspaces/directories/list`：框架工作区（含 `directory`）+ 一条 `kind=default` 的内置与技能开发目录
  （`{COSIGHT_HOME}/smart-factory`），供 viewer 把内置专家、技能工坊、自由对话纳入监控；框架不可达时 `502`（§9.6）。
- 合入前需跑通服务端全量测试与 typecheck。

## 13. 需要双方确认的点

1. agents 数据源：cosight-viewer 是否接受改读 smart-factory `/agents`，不再使用框架 experts。
2. 首轮设置：首帧 `send { agentId }` 已接受 `modelId` / `mode` / `effort`，客户端把当前 UI 选择直接放进首帧即可；续聊首轮用会话原设置，switch 从下一轮生效。
3. `interactive.timeout`：确认客户端不再依赖该事件。
4. `send {agentId}` 固定 `runtime`：确认生产产物缺失时的错误展示由客户端承担。
5. 框架 experts 与 smart-factory agents 的产品关系：如果两者不是同一实体，需要明确 picker 展示哪一份数据。
