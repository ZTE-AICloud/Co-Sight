# 技能库与目录会话

> 状态：**待评审**。本文定义「技能工坊」所需的两项后端能力：**目录会话**（会话不再只挂在智能体上）与**技能库扫描**。
> 代码落点：`server/prisma/*`、`server/src/shared/store/instances.repo.ts`、`server/src/modules/session/*`、新增 `server/src/modules/skill/*`、`server/src/config/index.ts`。
> 相关篇：会话契约 [`../04-api/4.03-会话.md`](../04-api/4.03-会话.md)、数据模型 [`02-data-model.md`](./02-data-model.md)、产物浏览 [`07-artifact.md`](./07-artifact.md)、智能体 [`08-agent.md`](./08-agent.md)、把库技能复制进智能体产物 [`../04-api/4.13-智能体技能.md`](../04-api/4.13-智能体技能.md)。

## 1. 定位与范围

四能力入口里，「创建技能」和「技能自进化」要在**工作区外的一个目录**里跑会话（skill-foundry 的产物就是那个目录下的 `output/skills/`）。现有会话模型只认智能体：

- 实例身份是 `(agentId, stage)`，cwd 由 agent → workspace → stage 推导；
- 内置智能体只认 `runtime`，cwd 写死成定义目录；
- `sessions/create` 没有 cwd / workspaceId 入参。

结果是没有哪个目录能承接技能线。本文用两件事解决，**不给工坊造智能体**：

1. **目录会话**：实例支持「有 cwd、没有 agentId」的形态，会话可以落在任意目录；
2. **技能库扫描**：`GET /skills` 一次返回库内技能 + 当前工作区智能体产出的技能。

明确不做：技能表（继续扫描）、技能删除 / 重命名、会话与技能的关联字段、工坊的前端页面（见 `web/docs/`）。

## 2. 技能库布局

```text
{COSIGHT_HOME}/smart-factory/
├── builtin-agents/            随包分发、只读；不往这里写用户数据
└── skill-workshop/            ← 工坊会话的 cwd（CC 在这里启动）
    ├── output/skills/         ← 技能库
    │   └── <name>/v1/{SKILL.md,references/,scripts/,templates/}
    └── .agent-genesis/work/   skill-foundry 的过程产物（work_root = .agent-genesis/work/{name}/）
```

`.agent-genesis/` 是 skill-foundry 自己的过程目录（工作方案、门禁结果、fast 车道快照），跟着 cwd 走；它不是技能库的一部分，`GET /skills` 不扫它。

| 项 | 取值 |
|---|---|
| 配置 | `config.skillsRoot`，env `SKILLS_ROOT`，缺省 `{COSIGHT_HOME}/smart-factory/skill-workshop` |
| 技能库 | `{skillsRoot}/output/skills/` |
| 工坊会话 cwd | `{skillsRoot}`（见下） |

- **cwd 是 `skill-workshop/`，库在它的 `output/skills/` 下**：skill-foundry 的输出恒为 `<cwd>/output/skills/<name>/vN`，这是技能的固定约定，cwd 目录名与库名解耦。本目录曾定名 `skills/`，最终形态 `skills/output/skills/<name>/v1` 两段 `skills` 重复、易误读，2026-10-22 评审改为 `skill-workshop/`（工坊会话目录，实现未启动，零迁移成本）。接口同时返回 `root`（库）与 `cwd`（会话根），前端一个都不拼。
- **全局共享**：技能库不属于任何工作区，切换工作区看到同一套。这是有意为之 —— 技能是端侧用户的资产，不随工作区分叉。
- **智能体技能**（只算当前工作区、`source=user` 的智能体，两处面，都归 `source=agent`）：
  - `<agent.dir>/development/output/skills/<name>/vN` —— 产出的独立技能；
  - `<agent.dir>/development/output/agents/<name>/<latest vN>/.claude/skills/<name>` —— 当前产物自带技能（构建器写入或 4.13 装配进来）。只认最新 `vN`，与运行期一致；`preview` / `evaluation` 下的 `.claude/skills` 是物化副本，**不扫**。
- **内置智能体不纳入**：`{COSIGHT_HOME}/smart-factory/builtin-agents/*/.claude/skills` 是随包定义，不是用户资产。

## 3. 目录会话

### 3.1 两种实例

| | 智能体实例（现状） | 目录实例（新增） |
|---|---|---|
| `agent_id` | 非空 | **null** |
| `cwd` | null（运行期推导） | **非空**，创建时给定 |
| `stage` | `development` / `preview` / `runtime` / `evaluation` | **同一套取值**（工坊 = `development`） |
| 唯一键 | `(agent_id, stage)` | `(cwd, stage)`（自由对话用 runtime，同一目录可有两个实例） |
| 物化 / 产物门禁 | 有（preview / evaluation） | 无 |
| `artifacts/*` | 适用 | **不适用**（没有 agentId） |
| 文件浏览 | `artifacts/*` | `fs/*` |

**cwd 只存在目录实例上。** 智能体实例的 cwd 每次 `send` 前重新推导 / 物化（`4.03` §2），存下来会过期。

### 3.2 schema

```prisma
model Instance {
  id        String   @id
  agentId   String?  @map("agent_id")   // 目录实例为 null
  stage     String                       // 不加取值：目录实例同样用 development / preview / runtime / evaluation
  cwd       String?                      // 目录实例非空，绝对路径
  engine    String
  createdAt DateTime @default(now()) @map("created_at")
  updatedAt DateTime @updatedAt @map("updated_at")

  @@unique([agentId, stage])             // SQLite 里 NULL 互不相等，目录实例不受此约束
  @@map("instances")
}
```

`prisma/bootstrap.sql` 追加（Prisma 表达不了部分索引，与 runs 同一套做法）：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS "uq_instances_cwd"
  ON "instances"("cwd") WHERE "cwd" IS NOT NULL;
```

**不变量**：`agent_id` 与 `cwd` 恰有一个非空。Prisma 表达不了 CHECK（`db push` 会重建表），由 `instances.repo` 的两个入口方法保证：

- `getOrCreate(agentId, stage)` —— 保持现状，不写 cwd；
- `getOrCreateByCwd(cwd, stage)` —— 新方法，`agentId = null`、stage 由调用方给（工坊 `development`、自由对话 `runtime`）；并发插入按 `uq_instances_cwd_stage` 兜底后重查（与现有 get-or-create 同款）。

### 3.3 为什么 stage 是 `development`，不引入专用取值

阶段表示「在这个目录里做什么」：工坊在开发技能，所以就是 `development`（2026-10-26 修正过一版专用值 `dir`）。**「目录实例 vs 智能体实例」的判据是 `agent_id` 是否为空**，不是 stage —— runtime 会话的 cwd 同样是一个目录，只是它由产物推导、属于智能体实例。代码里所有分流（跳过工作区解析 / 物化）都按 `agentId === null` 判。

并发仍按实例互斥：`runs.stage` 从实例抄来，索引条件是 `stage <> 'runtime'`（`bootstrap.sql`）：

```sql
CREATE UNIQUE INDEX uq_runs_one_active_top_per_instance_non_runtime
  ON "runs"("instance_id") WHERE ... AND "stage" <> 'runtime';
```

`development` 非 runtime，因此**免费得到「同一 cwd 至多一个活跃顶层 run」**，不用在服务层补检查。若取 `runtime` 则默认允许并行，两场会话同时改同一个技能目录会互相踩 —— 所以工坊必须是 development（自由对话才用 runtime，它不改技能目录）。

代价：`sessions/list?stage=development` 会同时命中智能体的开发会话与工坊会话；要区分得再看 `instance.agentId` / `instance.cwd`（DTO 两列都有）。工坊历史按 `cwd + stage=development` 查。

### 3.4 端点变更

**`POST /sessions/create`** 新增一种入参形态，与 `agentId` 形态互斥：

| 字段 | 类型 | 说明 |
|---|---|---|
| `cwd` | string | 目录形态必填；绝对路径、必须存在且是目录；服务端 `realpath` 后落库 |
| `agentId` | string | 智能体形态必填；**与 `cwd` 恰好给一个**，同时给或都不给 `400` |
| `modelId` | string | 必填、非空且可运行（规则不变） |
| `name` | string | 可选，缺省空串 |

- 路径校验不做白名单：与 `/fs/*` 同口径。
- 目录形态不查 `agents` 表、不查 stage 门禁（stage 恒为 `development`）、不做物化；按 `agentId === null` 分流。
- 响应 `Session.instance` 中 `agentId` 为 `null`、`cwd` 为绝对路径。

**`GET /sessions/list`** 新增过滤参数：

| 参数 | 类型 | 说明 |
|---|---|---|
| `cwd` | string | 目录会话按 cwd **精确**过滤；与 `agentId` / `stage` 取交集；非法路径形态 `400` |

历史会话因此不需要任何新端点：`sessions/list?cwd=<技能库根>` 就是工坊历史，`?cwd=<某个技能目录>` 就是该技能的历史（后者要求优化的 cwd 定到技能目录，见 §6）。

### 3.5 起跑条件

`resolveRunSetup`（`session.service.ts:895`）加一个分支，放在最前：

```text
if (instance.cwd) → cwd = instance.cwd，跳过 resolveAgentWorkspace / resolveStageCwd / 物化
```

适配器与模型解析不变；工作区不可达不再影响目录会话（这正是技能线要的：技能库在框架之外）。

### 3.6 DTO 兼容性

- `instance.agentId` 由 `string` 变 `string | null`，`instance.cwd: string | null` 新增；
- Web 端现有两处读 `instance.agentId`：`web/src/features/agent-create/useCreationChat.ts:392`（有值才比较）、`web/src/features/session-debug/SessionDebugPage.tsx:586`（展示）；都只需容忍 null；
- WS 下行事件里的 instance 走同一个 DTO，无需单独改。

## 4. `GET /skills`

### 4.1 请求

```http
GET /api/smart-factory/v1/skills?workspaceId=<uuid>
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `workspaceId` | 否 | 给了才扫该工作区的智能体技能；不给只返回技能库 |

### 4.2 响应

```json
{
  "root": "/home/u/.cosight-harness/smart-factory/skill-workshop/output/skills",
  "cwd": "/home/u/.cosight-harness/smart-factory/skill-workshop",
  "items": [
    {
      "name": "report-gen",
      "path": "/home/u/.cosight-harness/smart-factory/skill-workshop/output/skills/report-gen",
      "source": "library",
      "ownerAgentId": null,
      "ownerName": null,
      "version": "v1",
      "description": "把周报整理成固定格式",
      "updatedAt": "2026-10-22T05:10:00.000Z"
    },
    {
      "name": "code-review",
      "path": "/ws/.smart-factory/agents/agt_xxx/development/output/skills/code-review",
      "source": "agent",
      "ownerAgentId": "agt_xxx",
      "ownerName": "代码审查",
      "version": "v2",
      "description": "",
      "updatedAt": "2026-10-21T11:00:00.000Z"
    }
  ]
}
```

- `root` 与 `cwd` 一并返回：前端推导不出 `{COSIGHT_HOME}`，也就不用知道、更不要在客户端拼 `dirname`；
  - `root` = 技能库目录，用于展示与「技能所属目录」；
  - `cwd` = 工坊会话的 cwd（`{skillsRoot}`），**创建目录会话时原样传给 `sessions/create`**；
- `source` / `ownerAgentId` / `ownerName` 是**落点判据**（见 §4.4），前端不得靠路径字符串猜；
- `path` 是**技能目录的绝对路径**，不是版本目录 —— 优化时作为目标传给 skill-foundry。

### 4.3 扫描规则

一次请求内完成，不落库：

1. 列 `{skillsRoot}/output/skills/*`：每个目录一项，`source = library`，`ownerAgentId = null`；
2. 给了 `workspaceId` 时：查该工作区 `source = user` 的智能体，逐个扫两个面：
   - `<agent.dir>/development/output/skills/*`；
   - 当前产物 `<agent.dir>/development/output/agents/<name>/<latest vN>/.claude/skills/*`（版本取数字最大的 `vN`；产物缺失或布局不唯一时按空处理，复用 `peekProducedAgent`）。

   两个面的目录不存在都按空处理（ENOENT 忽略，其它错误照常抛）；
3. 每一项：
   - `version`：目录内 `v<数字>` 子目录里最大的一个（字符串形态，如 `v2`）；没有则空串；
   - `description` / `name`：读 `SKILL.md` 的 YAML frontmatter（只读头部 8KB）；解析失败或字段缺失时 `name` 回落为目录名、`description` 为空串 —— **扫描不能因为一个坏文件整体失败**；
   - `updatedAt`：技能目录 mtime（ISO 串）。
4. 排序：`library` 在前、`agent` 在后，组内按 `updatedAt` 倒序。

### 4.4 落点判据（供前端，写在这里免得两头对口径）

| source | 优化的落点 |
|---|---|
| `library` | 技能工坊（目录会话，cwd = `{skillsRoot}`） |
| `agent` | 该智能体的设计页（开发阶段），cwd 由 `(agentId, development)` 推导 |

优化目标一律传 **`path` 绝对路径**，不传名字 —— 两路来源可能同名。

### 4.5 错误

| 码 | 场景 |
|---|---|
| 400 | `workspaceId` 形态非法 |
| 502 | `workspaceId` 给了但框架不可达 / 工作区未绑定目录（与 agents 列表同口径） |

库目录不存在返回 `{ root, items: [] }`，不报错（首次使用前还没有产物）。

## 5. 根目录初始化

启动时 ensure `{skillsRoot}/output/skills/` 存在（`mkdir -p`，连同 `{skillsRoot}` 一起建，失败只记日志不阻断启动）。理由：目录会话的 cwd 必须存在，而 `skill-workshop/` 第一次用时可能还没建过。

## 6. 待验证（实现前先做，约半小时）

**裸 cwd 下 skill-foundry 能不能起来。** `/agent-genesis:skill-foundry` 是插件命令，理论上全局可用、与 cwd 无关；如果 SDK 要求在 cwd 命中 `.claude/` 锚点或 `CLAUDE.md`，则第 5 节要多一步：把插件侧的锚点 seed 进 `{skillsRoot}`。

这个结论决定两件事：

1. 第 5 节是「只建目录」还是「建目录 + seed 锚点」；
2. 如果要 seed，内容从哪来（插件目录里的 `CLAUDE.md` / `.claude/`）、升级时怎么同步。

**优化会话的 cwd 恒为 `{skillsRoot}`**，不往技能目录里下探 —— 库在它的 `output/skills/` 下，再下探会把 `.agent-genesis/work/` 写进技能工程里。所以「这个技能的历史会话」靠会话名区分（优化场固定叫 `优化 <name>`），不给每个技能单独开 cwd。

**验证方法**：`sessions/create { cwd: {skillsRoot}, modelId }` 后发一条 `/agent-genesis:skill-foundry`，看是否进入技能流程。

## 7. 实施清单（按依赖顺序）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `prisma/schema.prisma` | `Instance.agentId` 可空、新增 `cwd String?`；注释写清两种形态 |
| 2 | `prisma/bootstrap.sql` | `uq_instances_cwd` 部分唯一索引 |
| 3 | `src/shared/types/index.ts` | `Instance` 类型加 `cwd`、`agentId` 可空（`InstanceStage` 不加取值） |
| 4 | `src/shared/store/instances.repo.ts` | `getOrCreateByCwd(cwd, stage)`（工坊 `development`、自由对话 `runtime`）；返回类型随之调整 |
| 5 | `src/modules/session/session.service.ts` | `createSession` 分支（入参互斥 + 路径校验）；`resolveRunSetup` 按 `agentId === null` 分流；`listSessions` 加 `cwd` |
| 6 | `src/config/index.ts` | `skillsRoot` |
| 7 | `src/modules/skill/{routes,service}.ts`（新增） | `GET /skills`；模块注册（照 artifact 模块的接法） |
| 8 | 启动入口 | ensure 目录 |
| 9 | `docs/04-api/4.01-接口总览.md` | 端点表加 `/skills` |
| 10 | `docs/04-api/4.03-会话.md` | 加「目录会话」一节：入参、校验、`cwd` 过滤、目录实例的 stage 取值、DTO |
| 11 | `docs/03-architecture/02-data-model.md` | instances 表加 `cwd`、两种形态、新索引 |
| 12 | `docs/04-api/4.12-技能.md`（新增） | §4 的接口契约独立成篇 |

## 8. 测试清单

| 用例 | 期望 |
|---|---|
| `sessions/create { cwd }` 正常 | 200，`instance.agentId === null`、`cwd` 为 realpath |
| 同时给 `agentId` 和 `cwd` / 都不给 | 400 |
| `cwd` 相对路径 / 不存在 / 不是目录 | 400，错误码沿用现有路径类 |
| 同 cwd 建第二个会话 | 200（实例复用，会话新建） |
| 同 cwd 起第二个活跃 run | 409（非 runtime 实例级互斥） |
| `sessions/list?cwd=` | 只返回该目录的会话；与 `stage` 取交集 |
| 目录会话的 `send` | 不触发工作区解析；框架不可达也能跑 |
| `GET /skills` 无 workspaceId | 只返回 library 项，`root` 有值 |
| `GET /skills` 三路来源 | 同名技能各出一项，`source` / `ownerAgentId` 正确 |
| 产物自带技能 | `<product>/.claude/skills/*` 出现在 agent 组，`path` 指向产物目录、`version` 为空串；只扫最新 `vN`；`preview` / `evaluation` 副本不扫 |
| 坏 `SKILL.md` | 该项 `name` 回落目录名、其余项不受影响 |
| 版本识别 | 有 `v1`/`v10` 时取 `v10`（按数字比较，不按字典序） |
| 库目录不存在 | 200 + 空列表 |

## 9. 待决策

1. ~~**`dir` 这个 stage 取值**~~：已定（2026-10-26）—— 不引入专用取值，目录实例用 `development`，形态按 `agent_id` 判。
2. **技能库是否要按工作区隔离**：本文按「全局共享」写。若后续要隔离，只需把 `skillsRoot` 挪进工作区，`GET /skills` 形状不变。
3. **智能体技能被优化后产物会变**：就地改 `<agent.dir>/development/output/skills/...` 意味着已就绪智能体的当前版本被静默更新。本文不引入版本号语义，前端需在技能卡上提示；是否要服务端在优化前校验「该智能体是否有活跃 run」另议。
