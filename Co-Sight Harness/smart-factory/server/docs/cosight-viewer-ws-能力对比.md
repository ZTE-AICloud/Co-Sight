# WebSocket 服务端能力对比(商用客户端所需 ↔ 开源版目标服务端)

> **对比双方**
> - **左**:商用版 cosight-viewer 连接并消费的 agent-runtime。我们**拿不到它的服务端实现**,所以这里的"商用行为"= **客户端契约(它发什么、期望收什么)** + 开发态 mock 的实证。
> - **右**:开源版目标服务端 smart-factory `ws://localhost:4100/api/smart-factory/v1/ws`(代码 `server/src/shared/live/ws-gateway.ts`;契约 `server/docs/04-api/4.06-实时通道.md`)。
>
> 生成日期:2026-10-19 ｜ **同日更新**:按当前工作树实现(含兼容方法 / 事件)重新核对,状态以下表为准。
> 面向客户端的动作清单见 [`cosight-viewer-对接清单.md`](./cosight-viewer-对接清单.md)。
>
> **判定口径(以"商用客户端不改、直连 smart-factory"为前提)**
> - **一致**:客户端原样调用即可工作。
> - **不一致**:能力存在,但请求/响应/字段/事件形状不同,客户端必须改。
> - **不支持**:smart-factory 没有这项能力(方法不存在 / 事件永不发出 / 概念缺失),客户端必须改或删。

---

## 0. 对比口径

**"商用服务端的能力" = 商用客户端实际调用/注册的能力**(唯一依据是 `chat-socket.ts` 与 `useChatSession.ts` 的代码):

- 上行:**9 个方法**(其中 `send` 有两种调用形态:首帧建会话 / 续聊);
- 下行:**9 个事件**(`HANDLER_METHODS`);
- `subscribe` 库里有定义但 **UI 从未调用**;`unsubscribe` 客户端未定义;
- 服务端的实现细节(回放、限流、心跳强制、错误码类型)客户端不依赖,不列入对比。

右列 smart-factory 的行为以代码与 `4.06` 文档为准,逐项核对过。
协议对齐后,上行共 **12 个方法**(原生 6 + 兼容 6),下行共 **19 个事件**(原生 9 + 兼容 10)。
响应 `method` 统一为 `<请求 method>.result`(`ping` 为 `pong`);响应错误码只有 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`。

---

## 1. 结论摘要

| 能力面 | 商用版用到 | smart-factory | 判定 |
|---|---|---|---|
| 帧信封 | `{id,type,method,timestamp,payload,error}`(`chat-socket.ts:10-39`) | 同款 | **一致** |
| 上行方法(9 个 / 10 种调用形态) | 见 §2 | 12 个(原生 6 + 兼容 6) | **一致 9 / 不一致 1 / 刻意不支持 0** |
| 下行事件(9 个) | 见 §3 | 19 个(原生 9 + 兼容 10) | **一致 8 / 刻意不支持 1** |
| 会话创建 | 首帧 `send` 一次完成 | 首帧 `send {agentId, modelId, mode?, effort?, prompt}` 一次完成,每次新建会话;`versionId` 由 `agentId` 取代 | **不一致(字段改名)** |

---

## 2. 上行方法逐项对比(商用版实际用到的 9 个方法)

> 括号内为商用客户端的代码依据。`send` 拆成两行(两种调用形态)。

| # | 能力 | 商用客户端所需 | smart-factory 行为 | 判定 |
|---|---|---|---|---|
| 1 | `send` **首帧(建会话)** | 发 `{prompt, versionId}`;期望回 **`{sessionId, runId, instanceId?}`**,缺 `sessionId` 直接抛错(`useChatSession.ts:700-713`) | `send {agentId, modelId, mode?, effort?, prompt}` 一次性完成:按 `(agentId, runtime)` **每次新建**会话并起 run;`agentId` 可省 —— 省掉即**自由对话**,新建一条目录会话(cwd = 当前工作区目录,没有工作区落 `{COSIGHT_HOME}/smart-factory/chat`)。响应 `method=send.result`,回 **`{sessionId, runId, instanceId, status:"running", effort, modelId, modelName, modelFellBack:false, message, run}`**(`run.status` 同为 `running`),没有 `created`;`run.started` 在响应前广播。本开源版**没有 `versionId`,由 `agentId` 取代**,`modelId` 两种情况都必填 | **不一致(字段改名)** |
| 2 | `send` **续聊** | 发 `{prompt, sessionId}`;期望回 **`{runId}`**(`useChatSession.ts:743-748`) | 发 `{sessionId, prompt}`;响应 `method=send.result`,回 `{sessionId, runId, instanceId, status:"running", effort, modelId, modelName, modelFellBack:false, message, run}`,顶层 `runId` 可直接读;`run.status` 为 `running`;请求携带 `modelId` / `mode` / `effort` 回 `VALIDATION` | **一致** |
| 3 | `history` | WS `{sessionId, limit:50, offset:0, includeTelemetry:false}`;期望 `payload.messages[]` 且 `content` 为**字符串**(`chat-socket.ts:262-274`、`useChatSession.ts:615`) | WS `history` 同形;响应 `method=history.result`,载荷 `{sessionId, messages, total}`(`total` 为会话全部消息数);`content` 恒为**字符串**;`offset` 从最新往前跳过;`includeTelemetry` 接收但忽略 | **一致(附注响应 method)** |
| 4 | `model.switch` | WS `{sessionId, modelId}`;首轮 `send` 响应后**串行**发(`useChatSession.ts:649-669`) | WS `model.switch` 同形;`modelId` 必须非空、不能清空;响应 `{sessionId, modelId, appliesTo:"nextRun"}`;只改会话字段,**下个 run 生效,活跃 run 不中断**,不返回 409;其它订阅端收到 `settings.changed` | **一致**(短约束:不能传空串) |
| 5 | `mode.switch` | WS `{sessionId, mode}`;mode ∈ read_only / workspace_write / full_access(`:655`) | WS `mode.switch` 同形;响应 `{sessionId, mode}`;会话 `mode` 缺省 `workspace_write`,下个 run 生效;广播 `settings.changed` | **一致** |
| 6 | `effort.switch` | WS `{sessionId, effort}`;effort ∈ low…max(`:658`) | WS `effort.switch` 同形;响应 `{sessionId, effort}`;会话 `effort` 缺省 `high`,下个 run 生效;广播 `settings.changed` | **一致** |
| 7 | `run.abort`(**上行方法**;对应的**下行事件**是 §3 的 `chat.aborted`) | `{runId}`;不读响应字段,失败仅 warn(`useChatSession.ts:777-789`) | `{runId}` → `{runId, aborted:true}`(`runId` 为解析后的顶层 run);已终态 `CONFLICT` | **一致** |
| 8 | `approval.respond` | `{approvalId, decision}`;decision 取 `options[].value`(`:791-800`) | WS `approval.respond` 同形;`approvalId` 即 `approval.request` 里的审批消息 id;响应 `{approvalId, decision, resolved:true}`,结算结果走 `message` 事件 | **一致** |
| 9 | `tool.respond` | `{toolCallId, answers:[{question, answer}]}`(`:802-816`) | WS `tool.respond` 同形;`answers` 同时接受 `[{question, answer}]` 数组与 `{问题原文:[选项]}` 对象;响应 `{toolCallId, received:true}` | **一致** |
| 10 | `ping` | `{}`;不等 pong(`chat-socket.ts:390-402`) | `ping` → 响应 `method=pong`,载荷 `{serverTime}` | **一致** |

> **不计入"商用版用到"的两个**:`subscribe`(`chat-socket.ts:250-253` 有定义,UI 从未调用;smart-factory 支持且会补发挂起的审批 / 交互,帧为 `approval.request` / `tool.interactive`)、`unsubscribe`(客户端未定义;smart-factory 支持)。二者对判定无影响。

**第 1 行为什么判"不一致"**:客户端发的是 `versionId`,本开源版的服务端只认 `agentId`,且 `modelId` 必填;不改客户端会因缺少 `agentId` / `modelId` 与 `sessionId` 收到 `VALIDATION`。改法见 §5。

---

## 3. 下行事件逐项对比(客户端注册的 9 个)

注册清单:`useChatSession.ts:113-123`(`HANDLER_METHODS`)。

| # | 事件 | 商用客户端所需 | smart-factory 行为 | 判定 |
|---|---|---|---|---|
| 1 | `chat.delta` | `{delta}`;直接累加为正文(`useChatSession.ts:344-347`) | `{sessionId, runId, parentRunId, messageType:'text', delta}`;**只承载正文**,thinking 走 `chat.thinking` | **一致** |
| 2 | `chat.final` | `{content}`:完整终稿,客户端随后丢弃流式缓冲(`:349-356`) | 已发出:成功 run 恰好一次,`{sessionId, runId, parentRunId, content, messageId}` | **一致** |
| 3 | `chat.error` | 读 `error.message` / `payload.message`;不追加消息(`:358-363`) | 已发出:失败 run 收尾,`{sessionId, runId, parentRunId, code:"RUN_ERROR", message}` | **一致** |
| 4 | `chat.aborted`(**下行事件**,与 §2 的 `run.abort` 成对:客户端请求中止 → 服务端告知已中止) | `{reason?}`:清流式、`isLoading=false`、追加「[Aborted] …」(`:365-375`) | 已发出:中止 run 收尾,`{sessionId, runId, parentRunId, reason}` | **一致** |
| 5 | `interactive.timeout` | `{toolName?}`:关交互卡(`:377-384`) | **刻意不实现**:服务端对审批/交互**不设超时**,永远不会发出该事件 | **不支持(设计决策)** |
| 6 | `approval.request` | `{approvalId, sessionId, runId, toolName, title, description, input, options[], expiresAt?}`(`:49-59,386-388`) | 已发出:增加 `parentRunId` / `toolCallId`,可选 `agentId`;`approvalId` 即审批消息 id;不带 `expiresAt`,没有任何超时字段;`allowAll=false` 时 `options` 不含 `approved_all` | **一致** |
| 7 | `tool.interactive` | `{toolCallId, toolName, input:{questions[]}}`(`:62-75,390-393`) | 已发出,增加 `sessionId` / `runId` / `parentRunId`;没有 `timeout` 字段 | **一致** |
| 8 | `tool.executing` | `{toolCallId, toolName, input}`(`:395-406`) | 已发出,增加 `sessionId` / `runId` / `parentRunId`;其余同形 | **一致** |
| 9 | `tool.executed` | `{toolCallId, toolName, input, output, isError?}`(`:408-428`) | 已发出,增加 `sessionId` / `runId` / `parentRunId`;`toolName` / `input` 从对应 `tool_use` 回填 | **一致** |
| - | `connection.ready` | 未注册(忽略) | 会发 `{connectionId, restored:false, sessionId:null}`;未注册(忽略) | **一致**(均无影响) |

smart-factory 另有 `session.status` / `run.started` / `run.status` / `message` / `error` / `chat.thinking` / `chat.retry` / `settings.changed` / `task.started` / `task.notified` 等原生或补充事件,不在商用客户端契约里;客户端忽略未知事件即可。
其中 `chat.thinking.delta` 已删除;需要思考展示的客户端改消费 `chat.thinking` 的 `start` / `delta` / `stop` 三阶段。
兼容事件与原生 `message` / `run.status` 同时发送,客户端不要重复追加正文。

---

## 4. 行为层对比(左列仅代表客户端假设/需求)

| 项 | 商用客户端所需/假设 | smart-factory | 判定 |
|---|---|---|---|
| 信封 / 响应关联 | 按 `id` 匹配 | 按 `id` 回显 | **一致** |
| 错误帧 | `error:{code,message}`;**只读 message** | 同形,另带可选的 `messageKey` / `params`(i18n,旧客户端忽略即可);成功/错误响应 `method` 为 `<请求>.result`;code 只有 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL`,`SLOW_CONSUMER` 只出现在连接级 `error` 事件 | **一致(新增字段向后兼容)** |
| 心跳 | 客户端 30s ping;**不校验 pong**;服务端是否强制断开未知 | 客户端 30s ping;**2× 间隔无上行即 `close(1000)`** | **一致**(30s ping 满足) |
| 断线/回放 | 客户端按"无回放、需重拉"实现 | 无回放;重连后 REST 拉历史 + 重新 `subscribe`(只补挂起的审批 / 交互,帧为 `approval.request` / `tool.interactive`) | **一致** |
| 背压 | 未知 | >4MB → `error(SLOW_CONSUMER)` 后断开 | 已实现(客户端不依赖) |
| 审批/交互超时 | 客户端**期待**有 `interactive.timeout` | **刻意不设超时**;该事件永不发出 | **不支持(设计决策)** |
| 鉴权 | 无(仅 query `userId`) | 无;`connection.ready` 不带 `connectionToken`,`restored` 恒 `false`、`sessionId` 恒 `null` | **一致** |
| 版本概念 | 首帧 `send {versionId}` | **没有 `versionId`**;用 `agentId` 定位智能体 | **不一致(字段改名)** |
| 模型绑定 | 客户端首帧不一定带模型,可依赖服务端默认 | 每个会话必须绑定非空 `modelId`:首帧 `send`(带不带 `agentId` 都一样)与 `sessions/create` 必填,没有工作区默认 / 框架生效 / 本机配置回退 | **不一致(新增必填字段)** |
| 事件按会话过滤 | 客户端**不按 sessionId 过滤**,一连接一会话 | 按订阅扇出,`send` 隐式订阅 | **一致** |

---

## 4.5 具体帧示例(改动点都在这里)

### 4.5.1 不一致:① `send` 首帧(`versionId` → `agentId`)

客户端发:

```json
{ "id": "msg_1760000000000_7f3a", "type": "request", "method": "send",
  "timestamp": 1760000000000,
  "payload": { "prompt": "你好", "versionId": "default" } }
```

smart-factory 需要:

```json
{ "id": "msg_1760000000000_7f3a", "type": "request", "method": "send",
  "timestamp": 1760000000000,
  "payload": { "prompt": "你好", "agentId": "weather-agent",
               "modelId": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5",
               "mode": "workspace_write", "effort": "high" } }
```

smart-factory 回:

```json
{ "id": "msg_1760000000000_7f3a", "type": "response", "method": "send.result",
  "payload": {
    "sessionId": "sess_abc", "runId": "run_001", "instanceId": "inst_1",
    "status": "running", "effort": "high",
    "modelId": "a7cf0154-020b-4f97-b2bc-5ab8eb3bf0b5", "modelName": "claude-sonnet-4-5",
    "modelFellBack": false,
    "message": { "id": "msg_1001", "sessionId": "sess_abc", "runId": null,
                 "seq": 1, "role": "user", "type": "text", "status": null,
                 "content": { "text": "你好" } },
    "run": { "id": "run_001", "sessionId": "sess_abc", "instanceId": "inst_1",
             "status": "running", "startedAt": "2026-10-19T00:00:00.255Z" }
  }, "error": null }
```

**差异**:本开源版**没有 `versionId` 概念,由 `agentId` 取代**(`agentId` 可省,省掉即自由对话、新建一条目录会话),且首帧必须带非空 `modelId`(可选 `mode` / `effort`);每次首帧都新建一条会话,不复用已有会话。响应顶层的 `sessionId` / `runId` / `instanceId` / `status` 与商用期望一致,`run.status` 同为 `running`,没有 `created`;`modelFellBack` 恒为 `false`(不实现模型回退)。
**写`running` 的时机**:服务端在建 run 前完成引擎 / 工作区 / cwd / 模型解析,建 run 即 `running` 并写 `startedAt`;`run.started` 在响应前广播。解析失败直接回 `send.result` 错误,不建 run、不落用户消息、不改会话状态,新建的会话会被删除。
**后果**:不改客户端会因既缺 `sessionId` 又缺 `agentId` 收到 WS `VALIDATION`;带 `agentId` 但缺 `modelId` 同样收到 `VALIDATION`。
**正确流程**:首帧发 `send { agentId, modelId, mode?, effort?, prompt }`,记住响应里的 `sessionId`;后续续聊发 `send { sessionId, prompt }`。需要指定 `stage` / `name` 时,仍可先 REST `POST /sessions/create { agentId, modelId, stage?, name? }`。

---

### 4.5.2 附注:② `history` 的响应 `method`

客户端发:

```json
{ "id": "msg_hist_1", "type": "request", "method": "history",
  "payload": { "sessionId": "sess_abc", "limit": 50, "offset": 0, "includeTelemetry": false } }
```

smart-factory 回:

```json
{ "id": "msg_hist_1", "type": "response", "method": "history.result",
  "payload": { "sessionId": "sess_abc", "total": 1, "messages": [
    { "id": "msg_1001", "sessionId": "sess_abc", "runId": "run_002",
      "role": "user", "type": "text", "content": "你好",
      "createdAt": "2026-10-19T00:00:00.000Z" }
  ] }, "error": null }
```

**差异**:响应 `method` 是 `history.result`,不是 `history`;新增 `total`(会话全部消息数);`content` 是字符串,与商用期望一致;`includeTelemetry` 接收但忽略。
**后果**:客户端若只按 `id` 匹配响应,无需改动;若校验响应 `method`,改为接受 `history.result`。

---

### 4.5.3 刻意不支持:③ `interactive.timeout`

- 客户端监听 `interactive.timeout { toolName? }` 来关闭交互卡。
- smart-factory **永远不会发这个事件**:审批与交互不设超时,挂起多久应答都有效。
- 出口只有四个:用户应答、用户中止(`run.abort` / `sessions/abort`)、服务重启、进程被杀。
- **客户端处理**:不要等待该事件;交互卡由用户操作或 `message` 结算事件驱动关闭。

---

## 5. 客户端改造清单(直连 smart-factory 后)

> 本次协议对齐只改服务端与文档,cosight-viewer 代码未由我们修改;下表是 viewer 团队需要自行落地的动作。

| 现在(按商用客户端写法) | 改成(smart-factory) | 依据 |
|---|---|---|
| `ws://127.0.0.1:15907/v1/ws?userId=dev` | `ws://localhost:4100/api/smart-factory/v1/ws` | §1 |
| `http://127.0.0.1:15907/v1` | `http://localhost:4100/api/smart-factory/v1` | agents/models/sessions/messages |
| `send {prompt, versionId}` 建会话 | `send {agentId, modelId, mode?, effort?, prompt}`(无 `versionId`;每次新建会话,`modelId` 必填);响应顶层带 `status:"running"` / `effort` / `modelId` / `modelName` / `modelFellBack:false`,没有 `created`,可直接进入运行态 | 方法 1 |
| 续聊读 `payload.runId` | 不需改:响应顶层已带 `runId` | 方法 2 |
| `history` | 不需改:WS `history` 已实现;`content` 为字符串;按需接受响应 `method=history.result` 与 `payload.sessionId` / `payload.total`(会话全部消息数) | 方法 3 |
| `model.switch` | 不需改:WS `model.switch` 已实现,**下个 run 生效,活跃 run 不中断**;响应 `{sessionId, modelId, appliesTo:"nextRun"}`;REST `sessions/:id/update` 仍会在活跃 run 时 409 | 方法 4 |
| `mode.switch` / `effort.switch` | 不需改:WS 方法已实现,下个 run 生效;响应 `{sessionId, mode}` / `{sessionId, effort}` | 方法 5/6 |
| `approval.respond` | 不需改:`approvalId` 即 `approval.request` 给出的审批消息 id;响应 `{approvalId, decision, resolved:true}`,结算消息走 `message` 事件 | 方法 8 |
| `tool.respond` | 不需改:`answers` 数组形态被接受,服务端归一为 `Record`;响应 `{toolCallId, received:true}` | 方法 9 |
| `run.abort` | 不需改:响应改成 `{runId, aborted:true}`,客户端原本不读响应字段 | 方法 7 |
| `ping` | 不需改:响应 `method=pong`、载荷 `{serverTime}`,客户端原本不读响应字段 | 方法 10 |
| `chat.delta` | 不需改:现在只发正文增量,新增的 `parentRunId` 可忽略 | 事件 1 |
| `chat.final` | 不需改:已发出 `{content}`,新增 `sessionId` / `runId` / `parentRunId` / `messageId` 可忽略 | 事件 2 |
| `chat.error` / `chat.aborted` | 不需改:已发出 `{message}` / `{reason}`,新增字段可忽略;`chat.error.code` 恒 `RUN_ERROR` | 事件 3/4 |
| `approval.request` / `tool.interactive` | 不需改:已发出,新增 `parentRunId` / `toolCallId`(可选 `agentId`)与 `sessionId`;没有 `expiresAt` / `timeout` | 事件 6/7 |
| `tool.executing` / `tool.executed` | 不需改:已发出,新增 `sessionId` / `runId` / `parentRunId` 可忽略 | 事件 8/9 |
| `settings.changed`(可选) | 多端同步时消费;单端可忽略 | §3 |
| `chat.thinking.delta`(可选) | **该事件已删除**;要展示思考,改消费 `chat.thinking` 的 `start` / `delta` / `stop`;不展示则无需注册 | 事件 1 附注 |
| `interactive.timeout` | 删除或隐藏:刻意不实现,服务端不会发 | 事件 5 |
| `error.code` 类型 | 若做严格校验改为 `string`,取值 `VALIDATION` / `NOT_FOUND` / `CONFLICT` / `INTERNAL` | §4 |

---

## 6. 两个已确认的前提

1. **新建会话不需要工作区**:WS `send {agentId, modelId, mode?, effort?, prompt}` 或 REST `POST /sessions/create {agentId, modelId, stage?, name?}` 都可,`modelId` 都必填;实例由 `(agentId, stage)` get-or-create。WS 首帧每次新建会话,不复用。
2. **数据口径**:agents = `GET /agents`(裸 `{items,total}`、`agt_…`、tags/icon/status,无 author/useCount/isPreset/版本);models = `GET /models/list`(`{items, activeId}`,与框架同一 id 空间)。

---

## 7. 未验证项(明确不当作结论)

- 商用服务端的**回放、限流、背压、心跳强制、错误码类型** - 无实现可查,只有 mock 的弱参照。
- smart-factory 的 `session.status` / `run.started` 触发时机已由 `server/tests/{ws,session-compat}.test.ts` 覆盖;本对比不重复展开。

---

## 8. 代码落点

| 关注点 | 位置 |
|---|---|
| 客户端 WS 传输/信封/超时/心跳 | `client/src/api/chat-socket.ts`(463 行) |
| 客户端聊天状态机/事件注册/三个 switch | `client/src/pages/chat/useChatSession.ts`(854 行;`HANDLER_METHODS` 在 `:113-123`) |
| 客户端 WS/HTTP 基址 | `client/src/config/api-config.ts:16,19` |
| smart-factory WS 网关(12 方法 / 19 事件) | `smart-factory/server/src/shared/live/ws-gateway.ts`(方法分派见 `dispatch`) |
| smart-factory WS 契约 | `smart-factory/server/docs/04-api/4.06-实时通道.md` |
| 会话解析 / 三个 switch | `smart-factory/server/src/modules/session/session.service.ts`(`sendMessage` / `switchSessionField`) |
| 兼容事件广播 | `smart-factory/server/src/modules/session/session.service.ts`(`broadcastCompatibility` / `broadcastRunOutcome`) |
| 开发态 mock(弱参照) | `F:\code\cosight-viewer\tools\agent-runtime-mock\server.js` |
