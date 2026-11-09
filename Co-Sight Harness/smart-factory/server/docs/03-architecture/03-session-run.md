# Smart Factory 会话与运行

> 状态：**已定稿**。本文定义会话与运行的生命周期编排、四阶段目录、工作区解析、沙箱物化与启动关闭收口。
> 代码落点：`server/src/modules/session/*`、`server/src/modules/run/*`、`server/src/shared/workspace/*`、`server/src/index.ts`。验收测试：`server/tests/session-api.test.ts`、`server/tests/runs.test.ts`。
> 相关篇：表结构与状态机见 [`02-data-model.md`](./02-data-model.md)；引擎接缝见 [`04-engine.md`](./04-engine.md)；挂起语义见 [`06-approval.md`](./06-approval.md)。

## 1. 目录与沙箱

### 1.1 两个根

模块的数据分两处落盘：模块库在 `{COSIGHT_HOME}`，智能体产物在框架工作区目录下。

```text
{COSIGHT_HOME}/smart-factory.db          # 模块库，路径口径见 02-data-model.md §2
{workspace.directory}/.smart-factory/    # 模块根，每个工作区一份
└── agents/{agentId}/                    # agentRoot
    ├── .state/                          # 沙箱物化标记（非阶段目录，产物浏览不可见）
    │   ├── preview.json                 # {version:1, source, mtimeMs}
    │   └── evaluation.json              # 同上，按阶段各一份
    ├── development/                     # development cwd，智能体产物本身
    │   ├── .agent-genesis/work/**/orchestrator-state.yaml   # 生产门禁：pipeline_status 须 COMPLETED
    │   └── output/agents/{agentName}/{latest vN}/           # 产物版本；runtime cwd，原地
    ├── preview/                         # preview cwd，整拷自 development 最新 vN
    └── evaluation/                      # evaluation cwd，整拷自 preview
```

`workspace.directory` 来自框架工作区记录，`directory` 为 `null` 时模块根不存在，起 run 明确报错。

四个阶段目录都在 agentRoot 下。

### 1.2 四阶段

`stage` 取值与目录名逐字一致：`development` / `preview` / `runtime` / `evaluation`。

| 阶段 | stage 与目录名 | cwd | 目录怎么来 |
|---|---|---|---|
| 开发 | `development` | `<agentRoot>/development/` | 创建智能体时建出；创建向导与后续开发会话都在这里 |
| 预览 | `preview` | `<agentRoot>/preview/` | 每次 run 前 ensure：源是 development 最新 vN，源路径与最新 mtime 未变则跳过，变了才清空整体重拷 |
| 运行 | `runtime` | `<agentRoot>/development/output/agents/{agentName}/{latest vN}/` | **原地**，不拷贝；源就是开发产物 |
| 评估 | `evaluation` | `<agentRoot>/evaluation/` | 每次 run 前 ensure：先递归 ensure preview，再从 preview 沙箱整体拷贝；源未变则跳过 |

- **development 与 runtime 不是隔离关系**：runtime cwd 就在 development 树内，runtime 直接跑开发产物，两者共享同一棵树。
- **preview 与 evaluation 是隔离副本**：沙箱里改文件、删文件、跑飞都不影响开发产物。
- **物化链只有拷贝没有移动**：`development/output/agents/{latest vN}` →(整拷)→ `preview/` →(整拷)→ `evaluation/`；evaluation 的源是 preview 沙箱，preview 因源变化重拷时 evaluation 连带重拷。
- **评估产物约定**：评估 run 把报告写在 `<agentRoot>/evaluation/` 下的 e2e-test-* 目录里（generated_datasets / run_datasets / eval_datasets / eval_trace_results 四步落盘），`/evaluations/*` 端点读它归一化（见 [`4.09-评估报告.md`](../04-api/4.09-评估报告.md)）。**物化重拷会清掉旧评估产物**——语义是「评估结果属于某个源版本」，开发产物变了旧报告随之作废属预期。
- **runtime cwd 每次起 run 时按当时最新版本解析**：同一个 runtime 会话的多次 run 可能落在不同的 `vN` 目录，cwd 不随实例固化。
- **runtime 多会话共享 cwd**：同一 agent 的不同 runtime 会话解析到同一版本目录时，共用同一 cwd 与产物目录；共享 cwd 的写冲突边界见 [`02-data-model.md`](./02-data-model.md) §6。
- 同一 `(agentId, preview)` / `(agentId, evaluation)` 各只有一个沙箱目标，每次 run 前 ensure 一次：源路径与最新 `mtime` 未变则跳过，沙箱里的改动保留；源变了才清空目标后整体拷贝，此时前一次 run 在沙箱里的改动随之丢失（对话历史不受影响）。
- 版本层只指开发产物的 `vN` 目录约定，不表示 `agents` 表有版本字段。

### 1.3 agentId 形态校验

正则 `^[a-z0-9][a-z0-9._-]{0,63}$` - 以小写字母或数字开头、总长 1–64 的单段目录名。全小写是硬要求：NTFS 大小写不敏感，`Demo` 与 `demo` 会落到同一目录而库里是两行。这一条已排除空串、路径分隔符、`..`、绝对路径前缀与隐藏目录；另有两条黑名单：Windows 保留名（`con`/`nul`/`com1` 等，含带扩展名变体）与以点结尾（Windows 会静默丢掉结尾点）。细则见 [`4.03-会话.md`](../04-api/4.03-会话.md)。

`agentId` 参与路径拼接（`<agentRoot>` 与四个阶段 cwd），**这是本设计的安全边界之一，不能省**。工作区目录来自框架，不来自请求；`agentId` 仍是唯一由调用方提供的路径段。

智能体**本身**的存在性必须先校验：`agents` 表是唯一权威，`sessions/create` 先查表、未知 `agentId` 返回 `404`。工作区目录与 agentRoot 的存在性在起 run 时校验，缺失明确报错，不猜路径、不重建空目录。产物浏览另有相对路径防逃逸校验，见 [`07-artifact.md`](./07-artifact.md)。

### 1.4 预览 / 评估物化

工作区解析见 §1.5；本节只讲源定位与拷贝。

物化在**每次 run 前**执行，`sessions/create` 不做物化，也不碰磁盘。

源定位与完成判定（口径唯一，代码在 `shared/workspace/production.ts`）：

- 产物根固定为 `<development>/output/agents/`；候选下必须**恰好一个**子目录，它就是 `agentName`。
- 在 `<agentName>/` 下取版本号最大的 `vN`，源就是 `<agentName>/<latest vN>/`。
- 完成判定：`.agent-genesis/work/{agentName}/orchestrator-state.yaml` 必须存在且唯一匹配；交付门禁 `gate-results/*.json` 的 verdict ∈ `PASS` / `CONCERNS`；流程收尾（full 认 `pipeline_status=COMPLETED`，fast 认收尾步：create 的 `step-f1-fast-build` / optimize 的 `step-f2-fast-optimize`）。
- 门禁文件优先 `current_step` 对应的 `gate-results/<step_id>.json`，其次 `g028-exit-sanity.json`，再回落 full 的 `step-4-implementation.json` / fast 的 `step-f1-fast-build.json`、`step-f2-fast-optimize.json`。
- 产物缺失、候选下多个子目录、没有 `vN`、状态文件缺失或不唯一、流程未收尾、门禁未过，一律明确报错，不做猜测。

物化规则：

- 标记放 `<agentRoot>/.state/`，按阶段各记一份（`preview.json` / `evaluation.json`），内容是格式版本（`version: 1`）、源的绝对路径与源树最新 `mtime`。
- 目标存在且标记中的源路径与最新 `mtime` 都没变：跳过拷贝。
- 源变了：清空目标后整体拷贝；目标缺失时同样整体拷贝。
- 标记先删、拷贝成功后再写回：拷贝中途失败时下一轮不会误判为已同步。删除目标带重试（`maxRetries: 10` / `retryDelay: 100`），吸收 Windows 上文件被短暂占用的 EBUSY / EPERM。
- 拷贝的是版本目录的**内容**，目标根就是 `<agentRoot>/preview/` 或 `<agentRoot>/evaluation/`；evaluation 的源是 preview 目标目录（ensure evaluation 前先 ensure preview）。
- 物化在 `send` 内、**建 run 前**执行，与工作区 / cwd 解析同阶段；失败时 `send` 直接返回错误，不建 run、不落用户消息、不改会话状态。大目录会推迟 `send` 响应，但不会产生「已受理却未起跑」的 run。
- 物化失败时本次 `send` 返回明确错误，不建 run，不用空目录兜底。
- **development 有活跃 run 时拒绝进入其它阶段**（`409`）：重建期间产物可能正在改写，不能拿旧状态当起跑依据。
- **同一 agent 有活跃 runtime run 时拒绝启动 development**（`409`）：runtime 正在读取开发产物，development 的写入会与它竞争同一棵树。
  runtime 启动同样受 development 活跃 run 约束（见上一条）：它读取的是已完成版本目录，但 development 正在改写产物时不能拿旧状态作为起跑依据。

runtime 不做物化：`send` 在建 run 前按当时最新版本解析 cwd 并走同一完成门禁，跑的就是开发产物本身，缺失或未完成同样明确报错，`send` 返回错误且不建 run。

对外可读的完成状态见 [`../04-api/4.10-智能体产物状态.md`](../04-api/4.10-智能体产物状态.md)；`ready === true` 才允许进入预览 / 评估。

### 1.5 工作区解析与框架客户端

解析顺序固定三步：

1. 按 `agentId` 查 `agents` 表，取 `workspace_id`；无行即 `404`。
2. 调框架模块面 `GET /api/framework/v1/workspaces/{id}`，取 `directory`。
3. 模块根 = `<directory>/.smart-factory/`；agentRoot = `<模块根>/agents/{agentId}`。

`directory` 为 `null`、工作区不存在、框架不可达，三者都使本次 `send` 返回错误（REST `502 BAD_GATEWAY` / WS `INTERNAL`），**不建 run**。**不猜路径、不回退到默认目录**。这是 send 内的出口；需要框架的 HTTP 端点在上游失败时同样返回 `502 BAD_GATEWAY`（见 [`../04-api/4.02-通用规范.md`](../04-api/4.02-通用规范.md) §11 与 [`04-engine.md`](./04-engine.md) §3）。

框架客户端规则：

- 基址取 `FRAMEWORK_BASE_URL`，缺省 `http://127.0.0.1:4300`；模块面路径为 `/api/framework/v1`。
- 令牌读 `$COSIGHT_HOME/.module-token`，**每个请求现读**；不注入环境变量、不写日志、不下发前端、不缓存。
- 本服务是只读消费方，只调 GET；模型与工作区的写接口不使用。
- 工作区 `directory` 可在内存缓存 60 秒；令牌仍按请求现读。
- 作为 HTTP 端点调用时，框架不可达、超时或返回非 2xx 一律映射 `502 BAD_GATEWAY`；`send` 内的解析失败按上文返回错误，不建 run，不降级。

对外另有 `GET /api/smart-factory/v1/workspaces/list` 代理：返回 `{ items: [{ id, name }], activeId }`，**不下发 `directory`**，供前端与 e2e 取 `workspaceId`。它不参与路径解析。

### 1.6 启动收养与删除

- **启动收养按工作区扫描**：工作区清单来自框架，逐个扫 `<workspace.directory>/.smart-factory/agents/` 的直接子目录；细则见 [`08-agent.md`](./08-agent.md) §5。
- **删智能体删整棵 agentRoot**：先解析工作区目录，再删 `<workspace.directory>/.smart-factory/agents/{agentId}/`；工作区目录不可解析时不删库。细则见 [`08-agent.md`](./08-agent.md) §4。
- **删会话不触碰磁盘**：只删库里的消息、run 与会话行。

## 2. 会话与运行编排

编排集中在 `modules/session/session.service.ts`，规则四条：

1. **建会话**：按 `(agentId, stage)` get-or-create 实例（撞唯一约束 `P2002` 时重查一次返回已有行，不把约束错误抛给调用方）；`stage` 缺省 `development`。
   落会话行前的校验依次是入参（`agentId` 形态 → `stage` 枚举 → `modelId` 必填非空）、`agents` 表（未知 `agentId` 404）、模型可运行性（不存在 / 协议不符 / 无密钥 400，框架不可达 502）、实例活跃 run 检查（仅非 `runtime` 阶段；有则 409，`runtime` 不因实例下已有活跃 run 拒绝）；**不解析工作区目录、不物化沙箱、不碰磁盘**。
   非空 `modelId` 落 `sessions.modelId`；没有自动解析或回退，首次 `send` 还会按模型详情解析端点与密钥。
   会话**不抄写**实例的任何配置：要判断「这次运行用哪个引擎」，从 `session.instance` 取，模型从 `session.modelId` 取；运行目录由服务端解析，不下发 DTO，不存在双份真值。
2. **起 run**：先解析发送目标（见 §2.1）：`sessionId` 直取会话，或按 `agentId` 新建 runtime 会话；再在**建 run 前**解析引擎适配器、agent → 工作区目录 → 阶段 cwd（preview / evaluation 在此物化，runtime 在此校验最新版本目录）与模型；任一步失败直接返回 `send` 错误，**不建 run、不落用户消息、不改会话状态**，`agentId` 路径下新建的会话会被删除。
   解析通过后 `createActiveRun` 在事务内抢两级仲裁（[`02-data-model.md`](./02-data-model.md) §6 的两个部分唯一索引兜底，都只看顶层 run）：session 级覆盖所有 stage，该会话已有活跃顶层 run 即 409；instance 级只覆盖非 `runtime` 阶段，同 agent 同 stage 已有活跃顶层 run 即 409。
   `runtime` 的新会话没有活跃 run，也不看实例级名额，因此不同会话的并发首帧都能通过。
   通过后以 `status='running'`、`startedAt` 已落值创建 run 并写入 `sessionId`、冗余的 `instanceId` 与 `stage`；`agentId` 路径下仲裁失败同样删除新建会话。
   `development` 起 run 另有跨阶段守卫：同一 agent 有活跃 runtime run 时返回 409（见 §1.4），该检查与仲裁在同一事务内完成。
   随后通过 `onSessionResolved` 让 WS 先订阅，再落 user 消息、置会话 `in_progress` 并广播；注册中止句柄并广播 `run.started`（仅当 run 仍为 `running`，终态 run 永不发），最后返回响应。
   引擎在响应后异步启动，启动链只使用已解析的适配器 / cwd / 模型，不重复解析、不重复置 running。
3. **会话状态**：起 run 置 `in_progress`；发消息可把 `completed` 会话复活为 `in_progress`；无活跃 run 时按 [`02-data-model.md`](./02-data-model.md) 的派生 SQL 置 `completed`，派生 SQL 覆盖子 run。
4. **run 终态**：一律条件更新，顶层与子 run 都适用；`abort` 从被中止的 run 向上解析到顶层 run，级联见 §2.5，并放行被阻塞的引擎；终态后不再接受该 run 的任何写入。

### 2.1 发送目标

REST `messages/send` 与 WS `send` 使用同一套解析规则：`sessionId` 与 `agentId` **至多给一个**，两个都给返回 400；**都不给按自由对话处理**，新建一条目录会话（cwd = 框架当前生效工作区目录；没有工作区时落 `{COSIGHT_HOME}/smart-factory/chat`）。

1. 给了 `sessionId`：直接取会话及其实例；会话或实例不存在返回 `404`。使用该会话的 `modelId` / `approvalMode` / `effort`；请求里出现 `modelId` / `mode` / `effort` 任一字段返回 400。
2. 只给 `agentId`：形态校验并查 `agents` 表（未知 404），校验 `modelId` 必填、非空且可运行（不存在 / 协议不符 / 无密钥 400，框架不可达 502），按 `(agentId, runtime)` get-or-create 实例，然后**每次都新建一条会话**，不复用任何已有会话。
   `mode` 缺省 `workspace_write`，`effort` 缺省 `high`。三者落在新会话上，首轮 run 使用它们，`resumeSessionId` 为 `null`。
3. 新建的会话若在起跑条件解析或活跃 run 仲裁阶段失败，直接删除，不留空会话。
4. 响应不带 `created`：`send { sessionId }` 的 `sessionId` 是请求里的值，`send { agentId }` 的 `sessionId` 是本次新建的会话；客户端要续聊必须使用它。

因此一个 runtime 实例可以有多条会话，重复按 `agentId` 发送会产生新对话；并发首帧同样各自新建会话并起 run，不互相挤占名额。
`completed` 的会话只在 `send { sessionId }` 续聊时复活为 `in_progress`。

### 2.2 引擎会话接续（resumeSessionId）

- 每轮 run 把 `sessions.resumeSessionId` 传给引擎：`null` 表示开新引擎会话，非 `null` 时由适配器作为 resume 选项下发（Claude 适配器映射为 `options.resume`）。
- 引擎首条携带 `session_id` 的消息触发 `onSessionId` 回调，session 层立即写回 `sessions.resumeSessionId`；写失败按驱动链收口，不在回调里吞错。
- 下一次 run 读到的就是上次落库的值，实现跨 run 的多轮续聊；进程重启后依然有效。
- 该字段 provider 相关，只对最后写入的 provider 有效；切换引擎或供应商后可能失效，届时由引擎报错，该 run 落 `failed`。

### 2.3 模型下发

模型是**纯会话级**配置，不存在实例级或全局模型绑定。

- `sessions.modelId` 存框架模型 uuid，**任何会话都非空**；`sessions/create` 必填，`POST /sessions/:sessionId/update` 与 WS `model.switch` 只能改成另一个非空 uuid，空串 400，不支持清空。
- `resolveRunModel(modelId)` 只接受非空 id：空串直接 400。
- 解析发生在 `send` 内、建 run 前；失败时本次 `send` 返回错误，不建 run：
  1. 服务端调框架详情 `GET /api/framework/v1/models/{id}`。
  2. 详情 404/422、`protocol` 不是 `anthropic`、`apiKey` 或 `modelName` 为空：`400 BadRequestError`，错误可读且不含密钥。
  3. 框架不可达、超时或其它非 2xx：`502`。
- **没有回退**：不读取工作区 `defaultModelId`、框架 `activeId`，也不跟随本机 Claude Code 的模型配置。
- 会话的模型只经 `model.switch` / `sessions/:sessionId/update` 变更，`send` 不会改写它。
- 下发方式：`options.model` 用 `modelName`（主模型只设置这一处）；模型端点、凭据与子代理模型名放进 flag settings 的 `env`（`ANTHROPIC_AUTH_TOKEN` 取 `apiKey`，`ANTHROPIC_BASE_URL` 取 `baseUrl ?? ''`，`CLAUDE_CODE_SUBAGENT_MODEL` 取同一 `modelName`），flag-settings 层优先级高于 user settings。
- **模型别名也锁到本场模型**：插件 / 子代理定义里的 `model: sonnet|opus|haiku|fable` 由引擎按自己的别名表解析成内置型号（如 `claude-sonnet-5-5`），既不看 `options.model` 也不看 `CLAUDE_CODE_SUBAGENT_MODEL`；网关没有该型号时子代理报 `model_not_found`。因此 `env` 里同时写 `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL = modelName`。
- 不限制 settings 源：用户级插件 / 命令正常加载，框架模型、端点、密钥仍压过 `~/.claude/settings.json`；`options.env` 只展开 `process.env` 并删除继承的 `ANTHROPIC_*` 与 `CLAUDE_CODE_SUBAGENT_MODEL`。
- 模型参数始终注入：不存在「没有模型、跟随本机配置」的分支，本机 user / local 设置中的模型项会被 flag settings 覆盖。
- `options.env` 会整体替换子进程环境，必须展开 `process.env`，否则子进程会丢掉 PATH 等基础变量。
- 四个 stage 共用同一条解析路径，不为单个 stage 写分支。
- 候选清单来自 `GET /models/list`。

解析在 session 层完成，适配器只消费结果：落库与广播由 session 层做，引擎侧仍零 DB、零 HTTP 依赖（见 [`04-engine.md`](./04-engine.md)）。

### 2.4 子 run（子智能体）

顶层 run 内，引擎每次派生子智能体都会上报 `task_started`；会话层据此建子 run。

- **创建条件**：仅 `task_type='local_agent'` 或带 `subagent_type` 的任务建子 run 并广播 `task.started`，其余后台任务不建。
- **创建字段**：`status='running'` 并写 `startedAt`；`sessionId` / `instanceId` 继承顶层 run；`parentRunId` 取 `parent_task_id` 对应的 run，缺省为顶层 run；`delegationDepth` 优先取 `spawn_depth`（大于 `0` 时），缺失或为 `0` 时为父 run 深度 + 1（顶层子 run 为 `1`）；`parentToolUseId=tool_use_id`；`taskId=task_id`。
- **内容归位**：消息的 `agent_id`（等于 `task_id`）优先归到对应子 run；没有 `agent_id` 时按 `parent_tool_use_id` 找该次派生；两者都没有才归当前父 run。消息仍按会话分配 `seq`，子 run 的内容与顶层对话同序。
- **状态结算**：`task_notification` 按 `completed -> succeeded`、`failed -> failed`、`stopped -> aborted` 条件更新子 run 终态，更新成功即广播 `task.notified`；已终态时重放不生效。
- **审批**：`CanUseTool` 第三参的 `agentID` 是子 run 的 `task_id`；`InputRequest` 增加 `agentId`，审批消息落在子 run；是否自动放行读会话的 `approvedAll`，顶层 run 与子 run 同源。
- **SDK 转发**：子智能体的文本与思考不转发，只有工具调用 / 结果与任务事件参与归位；适配器配置见 [`04-engine.md`](./04-engine.md) §4。
- **事件**：`task.started` payload 为 `{ sessionId, runId, parentRunId, taskId, toolCallId, subagentType, delegationDepth, description? }`；`task.notified` payload 为 `{ sessionId, runId, parentRunId, taskId, status: completed | failed | stopped, subagentType, error?, summary? }`。线上字段名是 `toolCallId`、状态用 SDK 值；REST Run DTO 仍叫 `parentToolUseId`，库内状态仍按 `succeeded / failed / aborted` 落。
- `run.started` / `run.status` 只表示顶层 run；子 run 的 `message` / `chat.delta` / `chat.thinking` 带子 run 的 `runId`；`tool.*` / `approval.request` / `tool.interactive` 额外带 `runId` 与 `parentRunId`，viewer 忽略这两个字段。
- `cosight-viewer` 忽略 `task.*`，现有事件形状不变。

### 2.5 子 run 终止与收尾

- **abort 向上解析**：`runs/abort` 收到子 run id 时，沿 `parentRunId` 解析到顶层 run 再中止；子 run 不单独中止。
- **级联顺序（可观测事件）**：abort 信号 -> 该 run 树（顶层 run 及其全部子 run）内 pending 消息结算并广播 -> 子 run `task.notified` -> 顶层 `run.status` 与 `chat.aborted` -> `session.status`。收敛与挂起结算都按 run 血缘限定，不扫描同会话的其它顶层 run。
- `abortRun` 内立即广播上述事件，不等 adapter 返回；adapter 返回后 `closeRun` 幂等去重，不重复发终态。
- **正常收尾**：`closeRun` 把仍为活跃状态的子 run 统一收敛为 `aborted`，并补发遗漏的 `task.notified`；子 run 不发 `chat.aborted`，前端不会看到永远 `running` 的子 run。

### 2.6 子 run 查询

- `GET /runs/list?sessionId=` 只返回顶层 run（`parentRunId` 为空），分页与 `createdAt` 降序不变。
- `GET /runs/detail?runId=` 可查任意 run，子 run 同样带派生字段 `waiting`。
- 新增 `GET /runs/children?runId=&page=&pageSize=`：按 `parentRunId` 查直接子 run，按 `startedAt` 升序，每项带 `waiting`；`runId` 缺失返回 `400`，运行不存在返回 `404`。
- `POST /runs/abort { runId }` 传子 run id 时按 §2.5 解析到顶层 run。

### 2.7 会话级 approved_all

- 用户对审批选 `approved_all` 时，服务端在抢到结算仲裁之后、放行引擎之前把会话置为 `approvalMode='full_access'`、`approvedAll=true`；落库失败只记日志，不让本次响应失败。
- `approvedAll` 是会话级状态：本 run 的下一条审批、后续新 run 以及子 run 都读它。
- 新 run 继承会话状态；经 `mode.switch` 把 `approvalMode` 切到任何非 `full_access` 的值会把 `approvedAll` 复位为 `false`。
- run 终态不再封存或重置该开关；它是会话字段，只有 `mode.switch` 的降级路径会复位。

## 3. 启动序与关闭序

**启动**：`prisma.$connect()` → `failAllActiveRuns()`（含子 run）→ `abortPendingMessages()` → 启动收养（按工作区扫描）→ `http.createServer(app)` → `attachWsGateway(server)` → `server.listen()`。

**关闭**（SIGINT / SIGTERM）：`abortPendingMessages()` → `wsGateway.close()`（断开所有 socket）→ `server.close()` → `prisma.$disconnect()`。

进程入口用显式 `http.createServer`：`app.listen` 无法让 WS 共享端口。

## 4. 孤儿 run 与重启收口

审批无超时设计下，服务重启是唯一收口，因此以下为必需：

- `failAllActiveRuns()`：启动时把所有 `pending` / `running` run（含子 run）置 `failed`（error=「服务重启」），并按 [`02-data-model.md`](./02-data-model.md) 重算会话状态；
- `abortPendingMessages()`：启动与关闭各扫一遍残留 `status='pending'` 的消息置 `aborted`；
- `POST /runs/abort` / `sessions/abort`：把该 run 的所有挂起以 `aborted` 结算并放行引擎；传子 run id 时先按 §2.5 解析到顶层 run。
- 正常收尾的残留子 run 由 `closeRun` 收敛并补发 `task.notified`（见 §2.5）。

## 5. 竞态与幂等

| 竞态 | 处置 |
|---|---|
| 重复 / 并发审批应答 | 数据库条件更新仲裁，第二个调用拿 0 行 → 409（展开见 [`06-approval.md`](./06-approval.md) 与 [`../04-api/4.04-消息.md`](../04-api/4.04-消息.md) §6） |
| 并发 get-or-create | `@@unique([agentId, stage])` 兜底，`P2002` 重查返回已有行 |
| run 终态竞态 | 条件更新，受影响行数 0 即已终态 |
| 两次同时起顶层 run | 事务检查 + 部分唯一索引双保险；同一会话（任何 stage）或同一非 runtime 实例的后到者 409，runtime 的不同会话各自成功 |
| 子 run 重复 `task_notification` | 条件更新终态，受影响 0 行即忽略 |
| abort 与 `closeRun` 并发 | 顶层 run 条件更新仲裁；`closeRun` 幂等去重，终态事件不重复 |
| `send` 返回前被并发中止 | 中止句柄在响应前注册；`run.started` 只在 run 仍为 `running` 时广播，已终态则跳过且不启动适配器，`closeRun` 幂等收口；终态 run 永不补发 `run.started` |
| 工作区目录缓存过期 | 最多滞后 60 秒；`send` 时解析失败返回错误（HTTP `502` / WS `INTERNAL`），不建 run，不猜路径 |

## 6. 安全

端侧本地单用户，不做鉴权，勿把接口暴露到公网。安全边界有三：`agentId` 形态校验（§1.3）、工作区目录只来自框架（§1.5）与产物浏览的相对路径防逃逸（[`07-artifact.md`](./07-artifact.md)）。

模型 id 不是密钥，可以落库与下发；框架模型详情里的 `apiKey` 与端点只存在于服务端进程内存与引擎子进程环境，不落库、不下发前端、不进日志与错误消息。模型代理只暴露不含密钥的列表，详情只由服务端在起 run 时调用。模块令牌每请求从 `$COSIGHT_HOME/.module-token` 现读，不注入环境变量、不落日志。
