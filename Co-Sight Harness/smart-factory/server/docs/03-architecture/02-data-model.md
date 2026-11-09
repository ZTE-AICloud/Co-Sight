# Smart Factory 数据模型

> 状态：**已定稿**。本文定义五张表、状态机、不变量与级联规则，是其余各篇的公共地基。
> 代码落点：`server/prisma/schema.prisma`、`server/src/shared/store/*`、`server/src/shared/types/index.ts`。
> 验收测试：`server/tests/store.test.ts`、`server/tests/instances.test.ts`、`server/tests/dir-session.test.ts`、`server/tests/agents.test.ts`、`server/tests/runs.test.ts`。
> 相关篇：会话与运行编排见 [`03-session-run.md`](./03-session-run.md)；智能体（元数据与产物目录的关系、盘库顺序、收养）见 [`08-agent.md`](./08-agent.md)；接口形状见 [`../05-openapi/5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml)、[`../04-api/4.01-接口总览.md`](../04-api/4.01-接口总览.md)。

## 1. 五张表

链路：`agent → instance → session → run → message`。

| 表 | 回答的问题 | 关键字段 |
|---|---|---|
| `agent` | 有哪些智能体、叫什么、在哪个工作区、什么状态、为什么被创建、创建时带了哪些本机文件 | `id`（同时是产物目录名）/ `workspaceId` / `name` / `initialInput` / `initialAttachments` / `tags` / `status` |
| `instance` | 哪个智能体（或哪个目录）、在哪个阶段、用哪个引擎 | `agentId` / `cwd` / `stage` / `engine` |
| `session` | 一段对话 | `instanceId` / `name` / `modelId` / `resumeSessionId` / `mode` / `effort` / `approvedAll` |
| `run` | 一次执行（顶层或子智能体） | `sessionId` / `instanceId` / `stage` / `status` / `parentRunId` / `parentToolUseId` / `subagentType` / `delegationDepth` / `taskId` |
| `message` | 对话里的每条产出与每次挂起 | `seq` / `type` / `status` / `content` |

- **`agent` 是智能体存在的唯一权威**（见 [`../99-adr/0002-agents-table-in-server.md`](../99-adr/0002-agents-table-in-server.md)）。`agents.id` 同时是产物目录名；`agents.workspace_id` 指向框架工作区（裸字符串、零外键）；`dir` 不入库，由工作区记录里的 `directory` 加 `.smart-factory/agents/{id}` 现算，见 [`03-session-run.md`](./03-session-run.md) §1.5；`instances.agent_id` 是指向 `agents.id` 的裸字符串（零外键），因此 `sessions/create` 必须先查表、未知 `agentId` 返回 404。
- 一个智能体至多四个实例（`development` / `preview` / `runtime` / `evaluation`），每个实例可以有多条会话（`send { agentId }` 每次新建一条 runtime 会话）；阶段 cwd 见 [`03-session-run.md`](./03-session-run.md) §1.2。
- **目录实例**：`agentId=null`、`cwd` 非空（创建时给定），不挂任何智能体 —— 承接「工作区外的目录里跑会话」的场景（技能工坊：`development`；自由对话：`runtime`；见 [`../04-api/4.03-会话.md`](../04-api/4.03-会话.md) §11、[`10-skill-library.md`](./10-skill-library.md) §3）。**形态只看 `agent_id` 是否为空，不看 `stage`**。两种形态对照：

| | 智能体实例（现状） | 目录实例（新增） |
|---|---|---|
| `agent_id` | 非空 | **null** |
| `cwd` | null（运行期推导） | **非空**，创建时给定 |
| `stage` | `development` / `preview` / `runtime` / `evaluation` | **同一套取值**（工坊 = `development`） |
| 唯一键 | `(agent_id, stage)` | `(cwd, stage)`（同一目录的不同用途是两个实例） |
| 物化 / 产物门禁 | 有（preview / evaluation） | 无 |
| `artifacts/*` | 适用 | **不适用**（没有 agentId） |
| 文件浏览 | `artifacts/*` | `fs/*` |
- `instance` 的价值是**表分职**：`session` 只表达「一段对话」，不带 `stage` / `engine`；预览 / 评估沙箱与 runtime 原地运行有主语；`engine` 有归属。由 `(agentId, stage)` get-or-create，无独立 CRUD 接口，只在 session 响应里内联。
- `run.instanceId` 抄自会话，`run.stage` 抄自实例（`session.instance.stage`），都是**纯冗余**（session 的 `instanceId` 不可变，`stage` 由实例决定，无漂移机会）。
  顶层 run 用它俩配合 §6 的部分唯一索引做仲裁，子 run 只随行记录；`stage` 只用于库内索引，Run DTO 不新增该字段。
- **子 run 与顶层 run 同表**：`parentRunId` 非空的是子智能体执行，`parentRunId` 为空的是顶层 run；`delegationDepth` 顶层为 0，子 run 优先取 SDK `spawn_depth`，缺失或为 0 时取父 run 深度 + 1（顶层子 run 为 1）。同一会话下允许多个子 run 并发，只有顶层 run 受 §6 的索引约束。
- `Message` 表不改：消息归属统一用 `runId`，子 run 的内容同样是 `messages` 里的一行，排序仍走会话级 `seq`。
- `session` 的四个运行参数：
  - `modelId` 是框架模型 id，**任何会话都非空**；建会话时必填，之后只能切换成另一个非空模型，不支持清空。没有工作区默认模型、框架生效模型或本机配置回退。
  - `resumeSessionId` 是引擎接续标识，首次 run 后由服务端写入，下一次 run 原样下发。
  - `mode` 是库列名，DTO 字段名是 `approvalMode`；缺省 `workspace_write`，与 `effort` 一样在下个 run 生效（切换语义见 [`../04-api/4.03-会话.md`](../04-api/4.03-会话.md) §9.1）。
  - `approvedAll` 是会话级「允许所有」开关，缺省 `false`。用户对审批选 `approved_all` 时置真，同时把 `approvalMode` 置 `full_access`；新 run 继承；`approvalMode` 切到任何非 `full_access` 的值时复位为 `false`。
    它不再挂在 run 上，[`06-approval.md`](./06-approval.md) §3 是唯一权威。

## 2. Prisma schema

位置 `server/prisma/schema.prisma`。枚举取值以接口契约各资源篇为准（会话与实例见 [`../04-api/4.03-会话.md`](../04-api/4.03-会话.md) §3、消息见 [`../04-api/4.04-消息.md`](../04-api/4.04-消息.md) §2、运行见 [`../04-api/4.05-运行.md`](../04-api/4.05-运行.md) §2），schema 注释为同值的可读提示。

`DATABASE_URL` 由 `COSIGHT_HOME` 推导，库文件固定为 `$COSIGHT_HOME/smart-factory.db`。`COSIGHT_HOME` 缺省 `~/.cosight-harness`，按框架同一口径用 `path.resolve` 解析（不展开 `~`）。旧库不迁移。
建库时由 `server/prisma/bootstrap.sql` 执行 `PRAGMA journal_mode=WAL`（WAL 持久在库文件头，无需每连接设置）。
`busy_timeout` 保持 Prisma 默认的 5000ms。
runtime 多会话并发时读不阻塞写，写与写仍由 SQLite 单写者串行化。

```prisma
generator client { provider = "prisma-client-js" }

datasource db {
  provider     = "sqlite"
  url          = env("DATABASE_URL")   // 由 config 在 boot 时从 COSIGHT_HOME 推导
  relationMode = "prisma"              // 数据库层不用外键，关联靠字符串字段 + 应用层校验
}

/// 一个智能体 = 一行元数据 + 一个 agentRoot。id 是目录名，不是外键。
/// 内置智能体（source='builtin'）没有工作区：workspace_id 恒为 null，目录是随产品分发的定义目录（08-agent.md §8）。
model Agent {
  id          String   @id
  workspaceId String?  @map("workspace_id") // 框架工作区 id（uuid 字符串），建后不可改；内置行恒为 null
  source      String   @default("user") @map("source") // user | builtin：来源是事实（只读 / 仅 runtime / 无工作区都由它派生），不是标签
  name        String                        // 展示名，工作区内唯一（字节精确比较）
  description String   @default("")
  initialInput String  @default("") @map("initial_input") // 创建时的 init.input 原文；空串 = 没带 init；建后不可改
  initialAttachments String @default("[]") @map("initial_attachments") // 创建时的 init.attachments，JSON 数组串（服务端解析后的真实路径）；建后不可改
  tags        String   @default("[]")        // 标签，JSON 数组串；空数组 = 没有标签（见 08-agent.md §7）
  icon        String   @default("")          // 封面图 HTTP(S) 地址；空串 = 没有封面
  createdAt   DateTime @default(now()) @map("created_at")
  updatedAt   DateTime @updatedAt      @map("updated_at")   // 同时是列表的排序键

  @@unique([workspaceId, name])              // 重名 409 只在本工作区内判定
  @@index([updatedAt])
  @@map("agents")
}

/// 一个智能体（或一个目录）在一个阶段的存在。agentId 是目录名，不是外键。
/// 两种形态：智能体实例（agentId 非空、cwd 为 null，运行期推导）与
/// 目录实例（agentId 为 null、cwd 非空，创建时给定）；恰有一个非空，见 §6。
model Instance {
  id        String   @id
  agentId   String?  @map("agent_id")            // 目录实例为 null
  stage     String                                // development | preview | runtime | evaluation（目录实例同套取值，工坊用 development）
  cwd       String?                               // 目录实例非空（绝对路径，realpath 后落库）；智能体实例恒为 null（cwd 存下来会过期）
  engine    String                                // 引擎适配器注册表 key，创建时由 config 写入
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt      @map("updated_at")

  @@unique([agentId, stage])                      // SQLite 里 NULL 互不相等，目录实例不受此约束
  @@map("instances")
}

/// 一段对话。业务字段一律不放这里。
model Session {
  id              String   @id
  instanceId      String   @map("instance_id")
  name            String   @default("")
  status          String   @default("not_started")  // not_started | in_progress | completed
  modelId         String   @map("model_id")  // 会话级框架模型 uuid，必填非空；没有自动解析 / 回退，不支持清空
  resumeSessionId String? // provider 相关:当前生效 SDK 返回的 resume 标识,用于引擎多轮 resume;仅对最后写入的 provider 有效
  mode            String   @default("workspace_write")  // read_only | workspace_write | full_access；会话级审批模式，DTO 字段名为 approvalMode
  approvedAll     Boolean  @default(false) @map("approved_all")  // 会话级「允许所有」；用户选 approved_all 时置真，approvalMode 切到非 full_access 时复位（见 06-approval §3）
  effort          String   @default("high")  // low | medium | high | xhigh | max；会话级推理强度
  createdAt       DateTime @default(now()) @map("created_at")
  updatedAt       DateTime @updatedAt      @map("updated_at")

  @@index([instanceId, createdAt])
  @@index([resumeSessionId])  // 支持 resumeSessionId 反查 sessionId
  @@map("sessions")
}

/// 一次执行。一条用户消息起一个顶层 run；子智能体每次派生一条子 run。
model Run {
  id              String    @id
  sessionId       String    @map("session_id")
  instanceId      String    @map("instance_id")
  stage           String                                // development | preview | runtime | evaluation；从 session.instance.stage 抄来的纯冗余，只用于部分唯一索引
  parentRunId     String?   @map("parent_run_id")        // 上级 run；null = 顶层 run
  parentToolUseId String?   @map("parent_tool_use_id")   // 派生子智能体的 tool_use id
  subagentType    String?   @map("subagent_type")        // SDK 子智能体类型
  delegationDepth Int       @default(0) @map("delegation_depth")  // 顶层 0，逐层 +1
  taskId          String?   @map("task_id")              // SDK task_id；内容归位与 task_notification 靠它
  status          String    @default("pending")          // pending | running | succeeded | failed | aborted
  error           String?
  startedAt       DateTime? @map("started_at")
  finishedAt      DateTime? @map("finished_at")
  createdAt       DateTime  @default(now()) @map("created_at")

  @@index([sessionId, createdAt])
  @@index([parentRunId])
  @@map("runs")
}

/// 对话里的每条产出。审批与交互也是 message，这是本设计的核心简化。
model Message {
  id        String   @id
  sessionId String   @map("session_id")
  runId     String?  @map("run_id")
  seq       Int                                 // 会话内单调递增，排序权威键
  role      String                              // user | assistant | system
  type      String   @default("text")           // 取值见 ../04-api/4.04-消息.md §2
  status    String?                             // 仅 approval / tool_interactive，其余恒为 null
  content   String   @default("")               // JSON 字符串，形状见 ../04-api/4.04-消息.md §3
  createdAt DateTime @default(now()) @map("created_at")

  @@unique([sessionId, seq])                    // 同时承担 (sessionId, seq) 的查询索引
  @@index([sessionId, type, status])            // 支撑 status=pending 过滤
  @@map("messages")
}
```

**零外键** ⇒ 没有数据库级联，删除由应用层在同一事务显式完成（§5）。

## 3. 状态机

**Agent**：没有落库的 status 列。列表 / 详情返回的 `status`（普通行）由服务端读 development 产物派生（与 `GET /agents/{id}/production` 同源），取值 `not_started | building | blocked | failed | completed`；内置智能体开箱即用，恒为 `completed`；`null` 仅表示该条读取磁盘状态失败。细节见 [`08-agent.md`](./08-agent.md) §2。

**Instance**：无状态机。智能体实例以 `(agentId, stage)` 为身份、目录实例以 `cwd` 为身份，均不可变；只有 `engine` 可变，改它只影响之后的 run。没有 `status`、没有启用 / 禁用、没有归档。

**Session**：只表达「这段对话是否还活着」。

```
not_started --(起 run)--> in_progress --(无活跃 run)--> completed
                                    <--(发消息复活)----
```

合法迁移仅 `not_started→in_progress` 与 `in_progress↔completed`。**没有 failed / aborted 会话状态** - 一次 run 失败不否定整段对话，成败记在 run 上。收口走派生 SQL，不用应用层计数：

```sql
UPDATE sessions SET status='completed', updated_at=?
WHERE id=? AND NOT EXISTS (
  SELECT 1 FROM runs WHERE session_id=? AND status IN ('pending','running'));
```

子 run 继承 `session_id`，因此上面的 `NOT EXISTS` 天然覆盖子 run：顶层与子 run 都落终态，会话才转 `completed`。

**Run**：沿用既有 `AgentRunStatus`，终态三者。

```
running --> succeeded | failed | aborted
```

`pending` 是枚举保留值（schema 默认值仍在），当前没有任何写入路径产生它：顶层 run 在 send 内解析完起跑条件后直接以 `running` 创建。

终态守卫一律条件更新：`updateMany({ where: { id, status: { in: ['pending','running'] } }, data: {...} })`，受影响行数为 0 即已终态 - 重放与竞态天然幂等。

**子 run**：创建即 `running`（`startedAt` 同时写入），不经过 `pending`；`task_notification` 按 `completed -> succeeded`、`failed -> failed`、`stopped -> aborted` 条件更新终态。顶层 run 与子 run 共用同一状态机与终态守卫，已终态的重复通知不影响任何行。

**Message.status**：只有交互类消息有生命周期。

```
approval:          pending --> approved | approved_all | rejected | aborted
tool_interactive:  pending --> answered | aborted
```

`aborted` 是服务端内部值，用于区分「用户拒绝」与「中止 / 重启」。

## 4. seq 分配

应用层在同一事务内 `MAX(seq)+1`，不用 SQLite `AUTOINCREMENT`（Prisma 对非 id 字段支持绕，且 SQLite 只允许 `INTEGER PRIMARY KEY` 自增）。SQLite 单写者天然串行化，但默认是 deferred `BEGIN`：两个并发事务可能先各读到相同的 `MAX(seq)`，写时一方撞 `@@unique([sessionId, seq])`。处置是把**整个事务**回滚后重试一次 - 事务内的失败必须整事务重来，不能只重试单条 insert；或在写事务开始时用 `BEGIN IMMEDIATE` 直接取写锁。迁移 Postgres 时改用 sequence（写进代码注释）。

## 5. 删除与级联

数据库层没有级联，删除边界由应用层在同一事务显式完成：

| 动作 | 事务内容 |
|---|---|
| 删会话（`POST /sessions/delete`） | `deleteMany(messages where sessionId)` → `deleteMany(runs where sessionId)` → `delete session` |
| 删智能体（`POST /agents/{agentId}/delete`） | `deleteMany(messages where sessionId in …)` → `runs` → `sessions` → `instances` → `agent`；**盘上的整个 agentRoot（`<workspace.directory>/.smart-factory/agents/{agentId}/`）在同一动作里先删**（先盘后库，见 [`08-agent.md`](./08-agent.md) §4） |
| 删实例 | 本期不提供 |

删会话要求该会话**无活跃 run**（有则 409，先 `abort`），因此不存在「会话行已删、引擎仍阻塞在挂起上」的状态。
子 run 与顶层 run 同在 `runs` 表，按 `sessionId` 的批量删除一并覆盖，不需要单独的级联规则。

实例行本期只 get-or-create 与按 id 取，不提供删除；删除守卫随实例管理端点一并实现。**删会话不触碰磁盘**：删行不会删 agentRoot（`<workspace.directory>/.smart-factory/agents/{agentId}/`）- 只有删智能体才连目录一起删，这也正是两个端点的边界（[`../05-openapi/5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml) 的 `delete` 一节）。

## 6. 活跃顶层 run 的并发不变量

建库不走迁移文件：`prisma db push` 按 schema.prisma 建结构，`Prisma` 表达不了的部分索引由 `server/prisma/bootstrap.sql` 手写补上（`node scripts/db.mjs sync` 建库、`node scripts/db.mjs reset` 清库重建，在 `server/` 下执行；重置或手工删库后需重启 server，运行中进程仍持有旧文件句柄）：

```sql
-- 节选：server/prisma/bootstrap.sql（PRAGMA journal_mode=WAL 见 §2；先删旧索引，再建新索引）
DROP INDEX IF EXISTS "uq_runs_one_active_per_instance";
DROP INDEX IF EXISTS "uq_runs_one_active_top_per_instance";

-- 同一 session 在任何 stage 至多一个活跃顶层 run。
-- parent_run_id 非空的子 run 不受此约束，可随任务并发。
CREATE UNIQUE INDEX IF NOT EXISTS "uq_runs_one_active_top_per_session"
  ON "runs"("session_id")
  WHERE "status" IN ('pending', 'running') AND "parent_run_id" IS NULL;

-- 非 runtime 阶段仍是实例级：同一 (agentId, stage) 至多一个活跃顶层 run，
-- 同一实例的 run 共用该 stage 的 cwd 与产物树，不同会话也不能并发。
-- runtime 允许同一 agent 的不同 session 各有一个活跃顶层 run 并发执行。
CREATE UNIQUE INDEX IF NOT EXISTS "uq_runs_one_active_top_per_instance_non_runtime"
  ON "runs"("instance_id")
  WHERE "status" IN ('pending', 'running') AND "parent_run_id" IS NULL AND "stage" <> 'runtime';

-- 目录实例：cwd 唯一（NULL 互不相等，智能体实例不受约束）。
CREATE UNIQUE INDEX IF NOT EXISTS "uq_instances_cwd"
  ON "instances"("cwd") WHERE "cwd" IS NOT NULL;
```

`bootstrap.sql` 先删旧索引再建新索引（runs 两条 + instances 的 `uq_instances_cwd`），新旧约束不并存。
`runs.stage` 是冗余列，只为让 SQLite 的部分索引能按阶段区分。

违反时返回 409 `CONFLICT`。
两条索引都只管**顶层** run，子 run 不占名额。

- **session 级（覆盖所有 stage）**：同一会话至多一个活跃顶层 run，`send { sessionId }` 撞上即 409。
- **instance 级（仅非 runtime）**：`development` / `preview` / `evaluation` 下同一 `(agentId, stage)`、非 runtime 的目录实例（`agent_id` 为 null，如工坊）下同一 `(cwd, stage)`，各自至多一个活跃顶层 run，不同会话也不能并发；`sessions/create` 与 `messages/send` 撞上即 409。目录实例因此免费得到「同一 cwd 至多一个活跃顶层 run」（[`../04-api/4.03-会话.md`](../04-api/4.03-会话.md) §11.2）。
- **runtime 无实例级名额**：同一 agent 的不同会话可以各有一个活跃顶层 run 并发执行；`sessions/create` 不因实例下已有活跃 run 返回 409。
- **跨阶段守卫**：`development` 与其它阶段读写同一棵树，`development` 有活跃 run 时 `preview` / `runtime` / `evaluation` 均不得起 run。
  `runtime` 有活跃 run 时 `development` 也不得起 run（保护 runtime 正在读取的产物树）。
  该检查不在索引里，与起 run 仲裁在同一事务内完成（见 [`03-session-run.md`](./03-session-run.md) §1.4、§2.1）。
- **共享 cwd**：runtime 的多条会话共用同一 cwd / 产物目录。
  不同文件的并发读写安全；同一文件的并发写是最后写入者胜出，最坏出现混合或截断；后端不加文件锁，固定文件名的报告需要按会话 / 运行区分目录或文件名。
- **目录实例不变量**：`agent_id` 与 `cwd` 恰有一个非空。Prisma 表达不了 CHECK（`db push` 会重建表），由 `instances.repo` 的两个入口方法保证：`getOrCreate(agentId, stage)` 保持不写 `cwd`；`getOrCreateByCwd(cwd, stage)` 固定 `agentId=null`、stage 由调用方给（工坊 `development`、自由对话 `runtime`），并发插入撞 `uq_instances_cwd_stage` 后重查，只落一行。
