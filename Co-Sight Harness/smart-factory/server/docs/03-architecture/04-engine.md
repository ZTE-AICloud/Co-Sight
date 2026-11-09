# Smart Factory 引擎接缝

> 状态：**已定稿**。本文定义引擎端口、适配器与注册表：换引擎只动本文覆盖的代码。
> 代码落点：`server/src/shared/engine/*`。验收测试：`server/tests/engine.test.ts`、`server/tests/message-persistence.test.ts`、`server/tests/e2e/session-flow.mjs`（真实引擎场景）。
> 相关篇：配置与运行环境见 [`01-architecture.md`](./01-architecture.md)；驱动链见 [`03-session-run.md`](./03-session-run.md)。

## 1. 端口

```ts
/** 引擎向宿主提的请求。审批与交互走同一个通道，用 kind 区分。 */
export interface InputRequest {
  kind: 'approval' | 'tool_interactive';
  toolCallId?: string;
  toolName?: string;
  title: string;
  description?: string;
  input?: unknown;
  questions?: QuestionItem[];   // kind=tool_interactive 时才有
  allowAll?: boolean;           // 仅当引擎禁止「本会话全部允许」时为 false，缺省表示可以
  agentId?: string;             // 子智能体 id，等于其 task_id；主线程请求没有该字段
}

export interface InputDecision {
  decision?: 'approved' | 'approved_all' | 'rejected' | 'aborted';
  answers?: Record<string, string[]>;
}

export interface EngineContext {
  session: SessionRow;
  run: RunRow;
  instance: Instance;
  cwd: string;
  /** 本次运行的输入：起 run 时那条用户消息的正文 */
  prompt: string;
  /** 本次运行的模型配置；每个会话的模型必填非空 */
  model: EngineModel;
  /** 引擎接续标识；null = 开新引擎会话 */
  resumeSessionId: string | null;
  /** 会话级审批模式 */
  mode: SessionMode;
  /** 会话级推理强度 */
  effort: SessionEffort;
  /** 引擎首次产出 resume 标识时回调；宿主负责落库 */
  onSessionId?: (resumeSessionId: string) => void | Promise<void>;
  /** 落库与广播由 session 层做，引擎不碰 DB、不碰 HTTP */
  emit(ev: EngineEvent): void | Promise<void>;
  /** 引擎问、宿主答。挂起多久由实现决定，本设计是不超时。 */
  requestInput(req: InputRequest): Promise<InputDecision>;
  signal: AbortSignal;
}

export interface EngineAdapter {
  readonly engine: string;
  run(ctx: EngineContext): Promise<{ output: string }>;
}
```

`requestInput` 必须是 **request/response 形状**，不能是 callback 形状：两家的机制不同，但都能装进「问与答」这个端口。

`EngineEvent` 的联合类型定义在 `shared/engine/port.ts`：引擎产出流式事件与消息草稿两类（`{type:'delta', messageType:'text', delta}` / `{type:'thinking', phase:'start'|'delta'|'stop', text?}` / `{type:'message', draft}`），另把 CLI 的 `task_started` / `task_notification` 转成宿主任务事件（对外广播为 `task.started` / `task.notified`），由 session 层决定建子 run 或结算子 run。session 层把正文增量广播为 `chat.delta`、思考阶段广播为 `chat.thinking`（`phase='delta'` 带 `text`），其余事件（`connection.ready` / `session.status` / `run.*` / 兼容事件 / `task.*`）由宿主产生。消息只以**草稿**形式交回宿主，`id` / `seq` / 落库由宿主负责 - 引擎不碰 DB。

- **claude-cli**：审批与交互**都经 CLI 的 `can_use_tool` control 请求**（启动时带 `--permission-prompt-tool=stdio`）。CLI 发 `control_request {subtype:'can_use_tool', tool_name, input, tool_use_id, …}`，适配器经 `ctx.requestInput` 问宿主，再回 `control_response {subtype:'success', response: {behavior:'allow'|'deny', updatedInput, toolUseID, decisionClassification}}`。判别靠 `toolName`：内置 `AskUserQuestion` → `kind='tool_interactive'`，其余工具权限询问 → `kind='approval'`。交互 → `{behavior:'allow', updatedInput: { questions: 原样带回, answers: 归一后的 { 问题原文: 选项拼接串 } }}`。因此 `--allowed-tools` 若被使用，必须包含 `AskUserQuestion`。
- **codex（预留）**：审批是 app-server 的 JSON-RPC 事件加应答，`item/commandExecution/requestApproval` 进来，我们回 `accept | acceptForSession | decline | cancel`。适配器把 `requestInput` 接到这条 RPC 上，应答是一条独立消息而不是返回值。

## 2. 注册表与选值

```ts
const ENGINE_ADAPTERS: Record<string, () => EngineAdapter> = {
  'fake': () => new FakeAdapter(),
  'claude-cli': () => new ClaudeAdapter(),
  // 'codex-sdk': () => new CodexAdapter(),   // 预留，本期不实现
};

export function resolveEngineAdapter(engine: string): () => EngineAdapter { /* 未知即抛，fail-fast */ }
```

适配器**没有构造期依赖**：cwd、session、挂起句柄都经 `EngineContext` 每次运行传入。

- **选值**：建实例时取 `.env` 的 `ENGINE`（见 [`01-architecture.md`](./01-architecture.md) §5）写入 `instances.engine`；本期之后只能直接改库。取值在**启动时**校验注册表（`resolveEngineAdapter(config.engine)`），未知即拒绝启动，不会落到实例创建或运行期。
- **取值 = 执行方式**：`claude-cli` 表示外部 Claude Code CLI；`fake` 表示测试桩。这个值会持久化进 `instances.engine`。
- **`fake` 是合法的开发 / 测试取值**：建实例写入 `engine='fake'`，走 `FakeAdapter`。
- **加一个适配器 = 加一个文件 + 注册表加一行**，其余源码零改动：没有注册表类、没有插件扫描、没有动态 import 目录。
- 适配器放 `shared/engine/`，不放 `infrastructure/engine/` - 本项目不上 DDD 四层（见 ADR-0001），没有 `infrastructure/` 这一层；不定义注入令牌，注册表这一个 `Record` 就是唯一绑定点（没有 DI 容器，token 是死代码）。

## 3. claude-cli 适配器要点

CLI 由用户自行安装，本发行物不携带；适配器只负责 spawn 并走 stream-json / control 协议。

1. **启动参数**：`--output-format stream-json --input-format stream-json --verbose`，按需追加 `--include-partial-messages`、`--model`、`--resume`、`--permission-mode`、`--permission-prompt-tool=stdio`、`--strict-mcp-config`、`--effort`、`--allow-dangerously-skip-permissions`、`--no-session-persistence`（探测）与 `--settings <临时文件>`。
2. **模型与端点凭据由服务端解析后经 flag settings 下发**：建 run 前服务端按 [`03-session-run.md`](./03-session-run.md) §2.3 的规则解析会话模型。`modelOptionsOf(model)` 返回的 `settings`（含 `env`）由传输层写成 `0600` 临时文件、经 `--settings` 下发；凭据不进命令行、不进日志，进程退出即删。写入 `ANTHROPIC_AUTH_TOKEN`（Bearer）、`ANTHROPIC_BASE_URL`（`baseUrl ?? ""`，空串 = 官方地址）、`CLAUDE_CODE_SUBAGENT_MODEL` 与四个 `ANTHROPIC_DEFAULT_*_MODEL`，保证子代理定义里的 `model: sonnet` 等别名也锁到本场模型；不写 `ANTHROPIC_API_KEY`。
3. **设置文件**：整个 `settings` 写临时文件（目录 `0700`、文件 `0600`），进程退出即删；显式 `disableAllHooks: false` 覆盖 user settings 的 `true`，托管层（组织策略）仍然优先。代价是操作者个人 hook（如工具门禁）也会进入产品运行。
4. **stdin 保持打开**：首条用户消息后不结束输入，直到 `result` 且没有后台任务；否则 `can_use_tool` 回写会失败。后台任务由 `background_tasks_changed` 维护，久不收尾时用兜底定时器收口。
5. **审批**：CLI 以 `control_request {subtype:"can_use_tool"}` 发来（见 §1），适配器经 `ctx.requestInput` 问宿主，再回 `control_response`。`toolUseID` 写入 `content.toolCallId`；`agentID` 写入 `InputRequest.agentId`；CLI 已渲染好的 `title` / `description` 直接作卡片文案，缺失时才按工具名与输入拼装；`suggestions` 不回填，避免写共享 cwd 的 settings；`suppressAlwaysAllowRule` 为真时置 `content.allowAll=false`；`decisionClassification` 原样透传。
6. **中止**：先发 `control_request {subtype:"interrupt"}`，再 `AbortController.abort()`；超时未退出才 `SIGTERM` / `SIGKILL`。
7. **只认显式下发的 MCP 服务器**：`--strict-mcp-config`，操作者本机与插件带的 MCP 不进入产品工具集。
8. **不设 `CLAUDE_CONFIG_DIR`**：CLI 直接读写操作者本机 `~/.claude`；端点、凭据与模型名经子进程环境覆盖本机配置。会话转录写进 `~/.claude/projects/`，会话标题也从那里读。
9. **审批模式映射**：纯函数 `permissionModeOf(mode)`：`read_only` → `plan`，`workspace_write` → `acceptEdits`，`full_access` → `bypassPermissions`；`full_access` 同时传 `--allow-dangerously-skip-permissions`。
10. **推理强度**：`ctx.effort` 原样传给 `--effort`，取值 `low` / `medium` / `high` / `xhigh` / `max`。
11. **版本门禁**：initialize 回执里的 `claude_code_version` 必须 >= `2.1.287`；低于直接给出升级提示。老 CLI 不报版本时放行，真正的协议错误在调用界面暴露。
12. **探测**：`--no-session-persistence --permission-mode plan --strict-mcp-config --settings "{\"disableAllHooks\":true}"`，拿 `initialize` 回执后立即 kill，不落会话、不跑用户 hooks。
13. **未安装 CLI**：`ClaudeCliNotFoundError` → `/engine/detail` 返回 `available:false` 与安装提示；服务本身照常启动，创建 / 管理不受影响。

## 4. 事件产出与消息落库

引擎产出 §1 的流式事件与消息草稿两类事件，另转发子智能体任务事件；分工以「流式事件是瞬态、message 是终稿」为准：

| 来源 | 事件 | 宿主行为 |
|---|---|---|
| `stream_event` 的 `content_block_start` / `content_block_delta` / `content_block_stop`（需 `includePartialMessages: true`） | `{ type:'delta', messageType:'text', delta }` / `{ type:'thinking', phase:'start' \| 'delta' \| 'stop', text? }` | 正文广播 `chat.delta`、思考阶段广播 `chat.thinking`，**不落库**：断线即丢，刷新后由终稿补齐 |
| 完整的 `assistant` / `user` 消息 | `{ type:'message', draft }` | 落库（`seq` 由仓储分配）后广播 `message`，前端按 `id` 覆盖渲染 |

**落库以完整消息为准，不从 delta 自己拼文本**：`draftsOf(message, questionToolCallIds)` 是 `claude-adapter.ts` 里的纯函数，负责「CLI 消息 → 草稿数组」，`run()` 的主循环逐条调用它。逐块映射如下（`content` 形状以 [`../04-api/4.04-消息.md`](../04-api/4.04-消息.md) §3 为准）：

| CLI 消息 | 内容块 | 草稿 |
|---|---|---|
| `assistant` | `text` | `type:'text'`，`content:{ text }` |
| `assistant` | `thinking` | `type:'thinking'`，`content:{ text }`（流式阶段走 `chat.thinking`） |
| `assistant` | `tool_use` | `type:'tool_use'`，`content:{ toolCallId, toolName, input }` |
| `assistant` | `tool_use` 且工具名为 `AskUserQuestion` | 跳过：已由会话层那条 `type:'tool_interactive'` 的挂起消息承载，再落一条就是重复；其 `id` 记入集合 |
| `user` | `tool_result` | `role:'assistant'`、`type:'tool_result'`，`content:{ toolCallId, output, isError }` |
| `user` | `tool_result` 且 `tool_use_id` 属于跳过的 `AskUserQuestion` | 跳过（靠上面那套 `id` 对号） |

`assistant` / `user` 消息可能带 `parent_tool_use_id`、`agent_id`、`subagent_type`：主线程消息的 `parent_tool_use_id` 为 `null` 且没有 `agent_id`。适配器把这三个字段随草稿交给会话层，归位顺序是 `agent_id`（等于 task 的 `task_id`）-> `parent_tool_use_id` -> 当前父 run。

**子智能体任务消息**（只转发给宿主，不落草稿）：

| CLI 消息 | 关键字段 | 宿主行为 |
|---|---|---|
| `system` / `task_started` | `task_id` / `parent_task_id` / `tool_use_id` / `subagent_type` / `spawn_depth` / `task_type` / `description` | 转宿主 `task.started`；建子 run 的条件见 [`03-session-run.md`](./03-session-run.md) §2.4，`delegationDepth` 优先取 `spawn_depth`（大于 `0` 时），未给或为 `0` 时按父 run 深度 + 1 生成（顶层子 run 为 `1`） |
| `system` / `task_notification` | `task_id` / `status` / `summary` | 按 `task_id` 结算子 run：`completed -> succeeded`、`failed -> failed`、`stopped -> aborted`；条件更新终态 |
| `system` / `task_progress`、`task_updated` | - | 不消费 |

**子代理内容按 CLI 的默认行为进入消息流**：工具调用 / 工具结果与任务事件带 `parent_tool_use_id`，审批请求另带 `agentID`（见 §3 第 5 条）；适配器按 `agent_id` → `parent_tool_use_id` → 当前父 run 的顺序归位。

`user` 消息里的文本块不落库：用户那轮输入已由会话层在起 run 时落过。`draftsOf` 的第二个参数是**整轮共用一个** `Set`：跳过 `AskUserQuestion` 的调用时登记其 `id`，它的结果块再靠这套 `id` 跳过，两处判断才闭环。

**半截内容 flush**：适配器另用一份 `pending.text` / `pending.thinking` 缓冲累积增量，完整消息的对应块处理完即清空对应缓冲；流收尾（含 `ctx.signal` 已 abort）时缓冲非空则各补落一条终稿，中止后刷新仍看得到半截内容。非 abort 的异常不补落半截内容，原错误照常上抛；但未关闭思考块的 `stop` 在 `finally` 里一律补发，异常路径也不会留下流式占位。

**桩适配器（`fake`）**：提示词标记触发上述形态，供端到端脚本与测试覆盖。`FAKE_TRIGGER` 标记：`需要审批` / `需要提问` 走 `requestInput`，`连续审批` 在同一 run 连发两次审批（供 approved_all 短路验证），`带思考` 发一段 thinking 增量加终稿，`带工具` 落一对 tool_use + tool_result，`带会话` 触发引擎会话标识回调，`带子代理` / `子代理失败` / `子代理恢复` / `子代理中止` / `嵌套子代理` 覆盖子 run 生命周期、失败映射、resume 重建、级联中止与嵌套深度。不带标记的裸文本行为不变：只有流式增量与一条助手文本终稿。
