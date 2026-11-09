# Smart Factory 架构

> 状态：**已定稿**。本文定义定位、分层、目录、接口风格与工程约定。
> 设计正文按变更边界分篇：数据模型 [`02-data-model.md`](./02-data-model.md)、会话与运行 [`03-session-run.md`](./03-session-run.md)、引擎接缝 [`04-engine.md`](./04-engine.md)、实时通道 [`05-realtime.md`](./05-realtime.md)、审批与交互 [`06-approval.md`](./06-approval.md)、产物浏览 [`07-artifact.md`](./07-artifact.md)、智能体 [`08-agent.md`](./08-agent.md)；接口形状见 [`../04-api/4.01-接口总览.md`](../04-api/4.01-接口总览.md)；分层决策见 [`../99-adr/0001-no-ddd-four-layers.md`](../99-adr/0001-no-ddd-four-layers.md)。

## 1. 定位与边界

一个端侧本地服务，把「智能体怎么造出来、怎么跑起来」从命令行能力变成有界面的产品能力。一次对话 = 一个 **session**；每次执行 = 一个 **run**；过程中的每条产出与每次挂起 = 一条 **message**。

两个调用方视角的能力：

- **开发（development）**：AgentGenesis 跑在我们的会话里，把一个智能体目录从无到有产出来；后续开发会话也在同一目录。
- **预览（preview）**：每次 run 前把开发产物最新版本整体物化到隔离沙箱里试跑。
- **运行（runtime）**：直接在开发产物的最新版本目录里跑，原地不拷贝。
- **评估（evaluation）**：从预览沙箱再物化一层隔离副本做评估。

四阶段的目录与 cwd 见 [`03-session-run.md`](./03-session-run.md) §1.2。

### 1.1 明确不做（减法清单）

刻意砍掉，不是遗漏：

- 技能加载、MCP 接入、知识检索、技能创建（只做智能体）；
- 模型管理（无模型表、无模型 CRUD、无模型配置项；模型目录由框架提供，会话必须选择一个非空模型，不读工作区默认模型、框架生效模型或本机 Claude Code 配置，见 [`04-engine.md`](./04-engine.md) §3）；
- 版本管理与 git（无 `AgentVersion`、无 worktree、无发布快照）；
- 技能市场、资产中心、发布与安装；
- 鉴权与操作者归属（端侧单用户）；
- 细粒度遥测消息（`tool_progress` / `task_progress` / `task_updated`）；
- 产物的写接口与登记（浏览只读见 [`07-artifact.md`](./07-artifact.md)；上传 / 改名 / 删除不做，目录的写方只有引擎）；
- SDK 会话 resume（重启不续跑，库里不存 SDK session id）。

### 1.2 交付形态

- **后端**：本文的全部内容，`cd server && npm run dev` 起一个 Node 进程（前后端统一起停见 §7）。
- **前端**：由前端负责人推进（`web/src/features/` 已有智能体列表与创建页演示），接口契约冻结在 [`../04-api/4.01-接口总览.md`](../04-api/4.01-接口总览.md)；前端需要什么形状，改契约文档而不是让后端迁就。跨端待对齐项见 [`../04-api/4.07-待前端对齐.md`](../04-api/4.07-待前端对齐.md)。
- **数据落盘**：`$COSIGHT_HOME/smart-factory.db` 一个 SQLite 文件；智能体产物按工作区落在 `<workspace.directory>/.smart-factory/agents/{agentId}/`，四个阶段目录都在其下（引擎状态不落这里，见 [`04-engine.md`](./04-engine.md) §3）。

### 1.3 子 run 模型

一次执行仍是一个 run；引擎派生子智能体时，每次派生对应一条**子 run**，与顶层 run 同表、同状态机（子 run 直接以 `running` 起步）。

- `runs.parent_run_id` 指向上级 run（顶层 run 为 `null`），`delegation_depth` 表示嵌套深度（顶层 0）；`parent_tool_use_id` 与 `task_id` 对应 SDK 的派生工具调用与任务标识，`subagent_type` 是子智能体类型。
- 子 run 继承 `session_id` / `instance_id`，消息仍按 `sessionId + seq` 落在同一段对话里，消息的 `run_id` 指出归属。
- 活跃顶层 run 的并发不变量以 [`02-data-model.md`](./02-data-model.md) §6 为权威表述。
  约束只落在**顶层 run** 上；子 run 由各自的 `task_started` 创建、由 `task_notification` 结算，可以并发存在。
- 前端会话视图仍只读顶层 run；子智能体状态经 `runs/children` 查询，实时事件按 `task.*` 下发。生命周期见 [`03-session-run.md`](./03-session-run.md) §2.4，字段与约束见 [`02-data-model.md`](./02-data-model.md) §3、§6。

## 2. 分层与模块

### 2.1 四件套 + shared，不上 DDD 四层

每个能力域内部固定四件套，职责单向依赖，不允许反向调用：

```
modules/<domain>/
├── <domain>.routes.ts      # 路由表：路径 → controller
├── <domain>.controller.ts  # HTTP 适配：取参 / 调 service / 组装响应
├── <domain>.service.ts     # 唯一业务承载：编排、事务、校验、状态机
└── index.ts                # 出口：只导出 router（service 按需导出）
```

分层纪律（比目录结构更管用）：

| 层 | 放哪 | 该写 | 不该写 |
|---|---|---|---|
| 路由 | `modules/<域>/<域>.routes.ts` | 路径与 HTTP 方法到 controller 的映射 | 任何逻辑 |
| 控制器 | `modules/<域>/<域>.controller.ts` | 取参、调 service、组装响应 | 业务规则；直接碰 store |
| 服务 | `modules/<域>/<域>.service.ts` | **唯一业务承载**：编排、事务、校验、状态机 | HTTP 概念（req/res/状态码） |
| 仓储 | `shared/store/*.repo.ts` | ORM 调用、行到领域对象的映射、条件更新守卫 | 业务规则；跨仓储编排 |
| 实时 | `shared/live/` | 连接、信封编解码、扇出、心跳 | 业务；DB |
| 引擎 | `shared/engine/` | SDK 私有形状的收敛与翻译 | 碰 DB、碰 HTTP |
| 工作区 | `shared/workspace/` | 目录推导与沙箱物化 | 业务 |

依赖方向单向：`routes → controller → service → store`，跨域只走 `service`。

### 2.2 能力域

`modules/` 下留五个目录：

```
server/src/modules/
├── agent/     # agents/* 路由；智能体元数据 CRUD，见 08-agent.md
├── session/   # sessions/* 与 messages/* 路由；会话、消息、交互结算、起 run
├── run/       # runs/* 路由；运行记录查询与中止
├── artifact/  # artifacts/* 路由；四 stage 目录的只读浏览（list / file / download）
└── health/    # health
```

- **`agent` 域承载智能体元数据**：创建智能体先落行、后建目录，重名按工作区判定，见 [`08-agent.md`](./08-agent.md)。
- **`instance` 不是域**（没有自己的路由）：它落在 `shared/store/instances.repo.ts` 与 `shared/workspace/`。
- `run` 域承载运行（顶层与子 run）；取消动作叫 `abort`，终态是 `aborted`；`runs/list` 只列顶层，`runs/children` 列子 run。

### 2.3 类型与错误

`shared/types/index.ts`：

- 新增 `Instance` / `Session` / `Run` / `Message` / `InstanceStage`；`InputRequest` / `InputDecision` 属引擎端口，定义在 `shared/engine/port.ts`；
- 智能体 DTO 与状态取值见 [`08-agent.md`](./08-agent.md) 与 [`5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml)；`AgentRunStatus` 的终态是 `aborted`；`PageResult` 保留；
- 前端 `web/src/shared/types/index.ts` 是对照副本，同步改。

`shared/errors.ts` 补 `ConflictError`（409）。领域错误抛 `AppError` 子类即可，响应格式由 `middleware/error-handler.ts` 统一产出；Express 5 会把 async handler 的 rejection 直接交给错误中间件，controller 不必包 try/catch。

## 3. 目录与文件布局

```text
server/src/
├── index.ts                   # 进程入口：启动序、优雅退出、attachWsGateway
├── app.ts                     # 应用装配：中间件 + 路由挂载（可被测试直接调用）
├── config/index.ts            # 环境配置集中读取
├── middleware/                # 请求日志、错误处理
├── modules/{agent,session,run,artifact,model,workspace,health}/
└── shared/
    ├── prisma/client.ts       # PrismaClient 单例 + disconnect
    ├── store/
    │   ├── agents.repo.ts     # 智能体元数据行；name 按工作区唯一
    │   ├── instances.repo.ts  # get-or-create(agentId, stage) / 按 id 取
    │   ├── sessions.repo.ts   # CRUD + 派生状态收口 SQL + 显式级联删 + approvedAll / approvalMode 映射
    │   ├── runs.repo.ts       # CRUD + 终态守卫 updateMany + createActiveRun + 子 run 创建与按父查询 + failAllActiveRuns
    │   └── messages.repo.ts   # append（事务内 seq 分配）/ listBySession / listByRun / settlePending / abortPending
    ├── framework/
    │   └── client.ts          # 框架模块面只读客户端：工作区解析；模型清单与详情在 modules/model/，令牌每请求现读
    ├── workspace/
    │   ├── dir-resolver.ts        # agentId / stage → 绝对路径；含 assertAgentId / assertRelativePath
    │   ├── workspace-resolver.ts  # agent → workspaceId → 框架工作区 directory
    │   └── materialize.ts         # 预览/评估沙箱物化与 runtime 产物定位
    ├── live/
    │   ├── live-hub.ts        # 进程内扇出 broadcast + waitFor(id) / settle(id, v)：审批的全部机器
    │   ├── ws-gateway.ts      # ws 服务端：信封编解码、method 分发、心跳、背压、订阅管理
    │   └── envelope.ts        # Envelope 类型与构造
    ├── engine/
    │   ├── port.ts            # EngineAdapter / EngineContext / EngineEvent / InputRequest / InputDecision
    │   ├── registry.ts        # ENGINE_ADAPTERS + resolveEngineAdapter（唯一绑定点）
    │   ├── fake-adapter.ts    # FakeAdapter：桩，流式吐文本 + 可选触发一次审批与一次交互
    │   ├── claude-adapter.ts  # ClaudeAdapter：唯一依赖 SDK 的文件
    │   └── codex-adapter.ts   # CodexAdapter：预留，本期不建
    ├── ids.ts                 # newId(prefix)：实体 id 前缀 + randomUUID
    ├── validate.ts            # 请求参数校验与分页 / limit 取值收敛
    ├── types/index.ts         # 领域类型（与前端对照，将来抽共享包）
    └── errors.ts              # AppError 及子类
server/prisma/schema.prisma    # 五表，见 02-data-model.md
```

前端 `web/src/features/<域>/` 与后端域对应，跨域复用的东西才上升到 `web/src/shared/`。

## 4. 接口风格

基址 `/api/smart-factory/v1`，开发态由 vite proxy 把 `/api` 转发到后端，前端代码只写相对路径。

工程约定 - 前缀、只许 `GET` 与 `POST`、动作词白名单、id 的位置（集合路径不带 id，个体与父子路径 id 进路径）、错误响应格式 - 完整定义见 [`../04-api/4.02-通用规范.md`](../04-api/4.02-通用规范.md)，本文不重复。

集合级端点路径里不出现 id，日志与监控不能靠路径区分资源，必须在日志里显式记录 id。

## 5. 配置

`config/index.ts` 集中读取，禁止散落的 `process.env` 访问：

| 键 | 来源 | 默认 | 说明 |
|---|---|---|---|
| `host` / `port` | `HOST` / `PORT` | `0.0.0.0` / `4100` | 监听地址与端口 |
| `nodeEnv` | `NODE_ENV` | `development` | |
| `corsOrigin` | `CORS_ORIGIN` | `*` | |
| `home` | `COSIGHT_HOME` | `~/.cosight-harness` | boot 时用 `path.resolve` 解析为绝对路径（不展开 `~`），与框架同一口径 |
| `databaseUrl` | 由 `home` 推导 | `$COSIGHT_HOME/smart-factory.db`，见 [`02-data-model.md`](./02-data-model.md) §2 | 推导后写入 `process.env.DATABASE_URL`；**`.env` 不配置该项** |
| `frameworkBaseUrl` | `FRAMEWORK_BASE_URL` | `http://127.0.0.1:4300` | 框架模块面基址，见 [`03-session-run.md`](./03-session-run.md) §1.5 |
| `engine` | `ENGINE` | `claude-cli` | 引擎适配器注册表 key |
| `wsPath` | 固定 | 见[4.06 实时通道](../04-api/4.06-实时通道.md) §1 | |
| `wsHeartbeatMs` | `WS_HEARTBEAT_MS` | `30000` | 心跳间隔；超时为间隔的 2 倍，见[4.06 实时通道](../04-api/4.06-实时通道.md) §2 |
| `wsMaxBufferedBytes` | `WS_MAX_BUFFERED_BYTES` | `4194304` | 背压阈值：写堆积超过即判定慢消费者并断开 |
| `artifactMaxFileBytes` | `ARTIFACT_MAX_FILE_BYTES` | `2097152` | `/artifacts/file` 读文本的大小上限，超限 413（下载不受限），见 [`07-artifact.md`](./07-artifact.md) |

**启动校验**：`ENGINE` 取值必须在引擎注册表内（见 [`04-engine.md`](./04-engine.md) §2），未知即拒绝启动。

模型配置由框架管理，本服务没有模型表、模型 CRUD 与端点/凭据配置项。
`sessions.modelId` 存框架模型 uuid（`sessions/create` 必填非空且须可运行，切换见 [`04-engine.md`](./04-engine.md) §3）。
建 run 前服务端解析模型并调框架详情取 `modelName` / `baseUrl` / `apiKey`，再注入引擎子进程；密钥不落库、不下发前端、不进日志与错误消息。
`sessions.modelId` 任何会话都非空：`sessions/create` 与 `send { agentId }`（新建会话）必填，`sessions/:sessionId/update` 与 WS `model.switch` 只能改成另一个非空模型，空串 `400`，不支持清空。
没有工作区默认模型、框架生效模型或本机 Claude Code 配置回退；`resolveRunModel` 只接受非空 id，空串直接 `400`。

## 6. 运行环境与平台要求

支持 Linux 与 Windows 双平台运行。

Windows 下先安装 Git for Windows：引擎（Claude Code CLI）的 Bash 工具依赖 Git Bash，探测不到时该工具不可用。

CLI 的自动探测只扫这几处：`C:\Program Files\Git\bin\bash.exe` 与 `C:\Program Files (x86)\Git\bin\bash.exe` 两个默认安装路径，以及 `where git` 定位到的 git 安装目录下的 `bin\bash.exe`；它不会在 PATH 上直接找 `bash.exe`。

Git 装在别处且自动探测失败时，用 `CLAUDE_CODE_GIT_BASH_PATH` 指向 `bash.exe`。

其余运行要求：

- **Node.js**：`>= 20`（`server/package.json` 的 `engines`；启动脚本按 major 号检查，低于 20 拒绝启动）。
- **依赖安装**：`npm install` 正常安装即可。本服务不再分发引擎原生二进制；Claude Code CLI 由用户在运行机自行安装，未安装时服务照常启动，运行入口给出安装指引。
- **数据目录**：默认 `~/.cosight-harness`（Windows 即 `%USERPROFILE%\.cosight-harness`），键见 §5。
- **防火墙**：首次监听如遇系统防火墙提示，需放行。

## 7. 启动与脚本

脚本统一放 `scripts/`，单入口 `scripts/dev.mjs`（Node、零依赖、跨平台，Windows 无需 bash）：

```bash
node scripts/dev.mjs setup    # 首次：装依赖、生成 server/.env、prisma generate、建数据目录与库（db push + bootstrap.sql）
node scripts/dev.mjs start    # 后台起前后端，日志写 .run/logs/
node scripts/dev.mjs status   # 查看状态
node scripts/dev.mjs stop     # 停止
node scripts/dev.mjs e2e      # 临时起后端（独立数据目录）跑端到端脚本
```

- 默认后端 `4100`、前端 `4110`；`SMART_FACTORY_SERVER_PORT` / `SMART_FACTORY_WEB_PORT` 可覆盖，显式设置服务端端口时脚本会透传 `PORT` 给后端，以免与 `server/.env` 错位。
- `start`（及 `setup` / `e2e`）先建库（db push + bootstrap.sql，见 [`02-data-model.md`](./02-data-model.md)）再起服务；建库不走迁移文件。
- 进程启动序与关闭序见 [`03-session-run.md`](./03-session-run.md)。

## 8. 文档地图

| 文档 | 管什么 |
|---|---|
| 本文 | 定位、减法清单、分层与目录、接口风格、配置、运行环境与平台要求、脚本 |
| [`02-data-model.md`](./02-data-model.md) | 五张表（含子 run 字段）、状态机、seq 分配、级联与不变量 |
| [`03-session-run.md`](./03-session-run.md) | 目录与四阶段沙箱、生命周期编排（含子 run 的创建与终止）、启动关闭与重启收口 |
| [`04-engine.md`](./04-engine.md) | 引擎端口、注册表与适配器 |
| [`05-realtime.md`](./05-realtime.md) | WS 信封、扇出、无回放边界、心跳与背压 |
| [`../04-api/`](../04-api/) | 接口契约十篇：总览、通用规范、会话、消息、运行、实时通道、待前端对齐、任务中心查询交接、评估报告、Web 交接 |
| [`06-approval.md`](./06-approval.md) | 审批即消息、approved_all 的会话级语义 |
| [`07-artifact.md`](./07-artifact.md) | 产物浏览：四 stage 目录的只读 list / file / download 与路径安全 |
| [`08-agent.md`](./08-agent.md) | 智能体：元数据行与产物目录的关系、status、先盘后库、启动收养、标签 |
| [`../99-adr/`](../99-adr/) | 架构决策（一决策一文件） |

同一事实只允许出现在一处：改数据模型先改 [`02-data-model.md`](./02-data-model.md)，改接口先改接口契约（[`../04-api/`](../04-api/)）。
