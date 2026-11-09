# Smart Factory 智能体

> 状态：**待评审**。本文定义智能体与工作区、产物目录、实例的关系，以及创建 / 删除 / 启动收养的机制与顺序。
> 代码落点：`server/src/modules/agent/*`、`server/src/shared/store/agents.repo.ts`、`server/src/shared/workspace/dir-resolver.ts`、`server/src/shared/workspace/builtin-agents.ts`、`server/src/index.ts`。验收测试：`server/tests/agents.test.ts`、`server/tests/builtin-agents.test.ts`。
> 相关篇：表结构与不变量见 [`02-data-model.md`](./02-data-model.md)；目录布局与四阶段沙箱见 [`03-session-run.md`](./03-session-run.md)；接口形状见 [`../05-openapi/5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml)；为什么把智能体管理收回本仓见 [`../99-adr/0002-agents-table-in-server.md`](../99-adr/0002-agents-table-in-server.md)。

## 1. 智能体的两半

一个智能体 = **一行元数据** + **一个工作区内的产物目录（agentRoot）**，`id` 是两者之间唯一的纽带。

| 半边 | 在哪 | 谁写 |
|---|---|---|
| 元数据行 | `agents` 表（含 `workspace_id`） | `agents/*` 端点（见 [`../05-openapi/5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml)） |
| 产物目录 | `<workspace.directory>/.smart-factory/agents/{id}/` | `agents/create` 建出空目录，内容由 development 会话写入（见 [`03-session-run.md`](./03-session-run.md) §1.2） |

- **`id` 由服务端生成、不可变，且目录名就是它。** 没有独立的 slug 或展示名目录；于是「改名」不会搬目录，「换 id」就等于换目录（所以没有 `rename` 端点）。
- **智能体归属工作区**：`agents.workspace_id` 是框架工作区 id（uuid 字符串），建 agent 时必填，建后不可改。
- **`dir` 不入库**：先取 `agents.workspace_id`，再调框架 `GET /api/framework/v1/workspaces/{id}` 拿 `directory`，agentRoot = `<directory>/.smart-factory/agents/{id}`。`directory` 为 `null` 或框架不可达时明确报错，不猜路径、不回退到默认目录。
- **表是智能体存在的唯一权威**：`instances.agent_id` 是本库唯一的引用点（字符串，无外键），`sessions` 只存 `instanceId`、不直接引智能体。因此 `sessions/create` 必须先查表，未知 `agentId` 一律 404；而 `sessions/list?agentId=` 是**过滤**不是取数，面对未知 id 返回空页。
- **`id` 的两种形态长期并存**：新建的是 `agt_<uuid>`，收养来的历史行是原目录名（§5）。两者都满足 [`03-session-run.md`](./03-session-run.md) §1.3 的形态校验，因此路径拼接的安全边界不需要放宽 - 这也是选 uuid 而非 slug 的直接收益之一（不引入 Unicode 归一与大小写不敏感文件系统两个坑）。
- **四阶段目录、`(agentId, stage)` get-or-create 实例、活跃顶层 run 的并发不变量** - 全部沿用 [`03-session-run.md`](./03-session-run.md) §1 与 [`02-data-model.md`](./02-data-model.md) §6，本域不改任何一条。

**没有的东西**（不是遗漏）：智能体元数据层的版本管理（`output/agents/{name}/vN` 只是开发产物目录约定，见 [`03-session-run.md`](./03-session-run.md) §1.2，不是 `agents` 表的版本层）、发布态、启用 / 禁用开关、图标可选集合（归前端）、模型绑定、技能清单、`assets` 这类创建链路的资产载荷、软删除与回收站、git。（创建时的需求原文 `initial_input` 与附件清单 `initial_attachments` 是已有的，见 §3.1。）

## 2. status 是派生字段

`agents` 表**没有** status 列。`Agent.status`（列表与详情）由服务端读 `development/` 下的
过程状态、交付门禁与产物现算，与 `GET /agents/{id}/production` **同源**（同一个
`readProductionStatus`）：

- 取值 `not_started` / `building` / `blocked` / `failed` / `completed`；
- 「开过工」看 `.agent-genesis/work/`：有工作目录但状态 / 产物 / 门禁全缺（服务重启中断等）→ `failed`，不报 `not_started`；
- 内置智能体没有生产流程（`/production` 对它们返回 409），但开箱即用，状态恒为 `completed`；
  `null` 只出现在普通行读取磁盘状态失败的那一条上（降级，不拖垮列表）；
- 只读、不落库：`agents/update` 不接受 status（传了按多余字段忽略）；列表的 `?status=` 是**筛选**不是写入
  ——取值只认枚举内的五个，空串视为未传，其余 400（`null` 那个降级值也不在枚举里）；
- 列表逐条现算，条数受 `pageSize` 约束；要拿 `reasons` / `pipeline` / `delivery` 明细仍走 `/production`。
- **按状态筛选时先取全量再切页**：status 不是列，SQL 里筛不了，所以 `?status=` 会先把其余条件命中的行
  全部取出、现算状态、在内存里过滤后切页 —— 这样 `total` 与页数才是过滤后的全量。代价是这条路径
  为每个候选行读一次盘；其余列表路径仍只读一页。端侧本地、按工作区展示，量级可控；
  真涨到读盘受不了时，该给 `agents` 加一列状态由生产流程写，而不是把分页改回「先切页再过滤」。

为什么删掉落库的 `draft | ready | archived`：那三态没有任何消费方，写入只有「新建/收养恒
draft、内置 seed 恒 ready」两种恒定值，与「能不能进入预览 / 评估」完全无关。留着就是第二套真值。
## 3. 创建：先落行、后建目录

```
校验 name / description / tags / icon / workspaceId → 解析工作区目录 → 生成 id → 插行（工作区内重名 409 在此判定）→ mkdir -p <agentRoot>/development → 返回
```

- **`workspaceId` 必填**：必须是框架里存在、且已绑定 `directory` 的工作区；框架不可达或 `directory` 为 `null` 返回 `502`，不建行也不建目录。
- **`workspaceId` 建后不可改**：`agents/update` 的可改字段只有 `name` / `description` / `tags` / `icon` / `knowledgeWorkflowId`，传 `workspaceId` 按多余字段忽略。
- **重名判定为工作区内唯一**：`@@unique([workspaceId, name])`，不同工作区可以同名，同一工作区重名返回 `409`。

**为什么是这个顺序**：目录是个空壳，失败只需删掉它；反过来「先建目录、后插行」，一旦重名 409 就留下一个永远没人认领的孤儿目录（`id` 是新 uuid，谁也指不到它）。把可回收的一步放在后面，失败面就是封闭的。

### 3.1 可选初始化：create 带 `init` 时连会话一起建

首页已经拿到了用户选的模型和第一句需求，`POST /agents` 可以用 `init` 一次带过来：

```
校验 agent 字段与 init（白名单 input / modelId / attachments，modelId 必填非空）→ 解析附件路径（400/404）
→ 解析工作区目录 → 校验 modelId 可运行（400/502）
→ 插行（initial_input / initial_attachments 随行落库）→ mkdir -p <agentRoot>/development
→ get-or-create (agentId, 'development') 实例 → 建会话（modelId = init.modelId）
→ 返回 Agent + initSessionId
```

- **会话固定走 `development`**（不是旧的 `production`），与前端「在设计页按 `(agentId, 'development')` 找最近会话」的读法一致。
- **后端落 `input` / `attachments`、但不落消息、不自动起 run**：`init.input` 写进 `agents.initial_input`（原文、不截断），`init.attachments` 解析成真实绝对路径后写进 `agents.initial_attachments`（JSON 数组串，同 `tags` 的存法）；前端路由 state 丢了还能找回来。首轮仍由前端在设计页触发 - 后台直接启动的话，用户打开页面时初始化过程已经跑完，看不到流式输出。两列都是创建时的快照，建后不可改；真正发出的首轮另在会话里落一条带 `content.files` 的 user 消息，两者允许不一致（用户可能在发送前改过字 / 增删过附件）。
- **为什么必须落库**：原话与附件原先只活在首页 `navigate` 的 `location.state` 里，刷新页面 / 从列表再次进入就没了，智能体永远不知道自己为什么被创建、当时带了哪几份文件。两列让设计页在「路由 state 不存在且会话为空」时能恢复首轮。
- **附件的校验与 `messages/send` 完全一致**：共用 `shared/workspace/local-path` 的 `resolveAttachmentPaths` —— 绝对路径、真实存在、是文件（不限制目录）；形态非法 400，合法但不存在 404，最多 20 项，去重保序。存的是解析后的真实路径，不是前端原样传的字符串。
- **`initial_input` ≠ `description`**：`description` 是卡片摘要（≤120 字、可被 update 改写），`initial_input` 是需求原文（建后不可改）。即使当前文案一样也不能互相顶替。
- **知识检索另存一列 `knowledge_workflow_id`**：创建时从 `init.input` 里的 `--knowledge-workflow-id` 参数解析落库（首条消息仍带这个参数，harness-create 靠它执行注入），之后可经 update 改 / 取消（空串 = 取消）。它**不是** `initial_input` 的派生视图 —— 用户改了以后不能由原文复活。本列引入前的存量行库里是 NULL，读取时按 `initial_input` 现推一次；update 写过即固化。
- **配置 ≠ 产物**：取消只改这一列，不会动已经生成好的产物。详情里的 `knowledgeInjected`（按 `runtimeDir/.claude/skills/rag-knowledge-search` 现扫）回答「产物里现在有没有」；要移除必须让 agent-genesis 重建（发一条按 create 重建的自然语言请求），因为知识章节已经织进 CLAUDE.md / workflow / rules，单删技能会留下断链。
- **`init.input` 不进 `description`**：两者语义不同（卡片摘要 vs 首轮对话），即使当前文案一样也不能互相顶替。
- **`init` 是固定字段白名单**：未知字段、`input` / `modelId` 非字符串、`attachments` 非数组一律 400，不静默转空串 / 空数组。
- **全有或全无**：初始化（建会话）同步失败时，先删 `<agentRoot>`、再 `deleteCascade` 删行，然后返回 500。不留「有 agent、没有会话」的半成品。
- **模型只存框架模型 uuid**：`init.modelId` 必填非空，创建前校验可运行（存在、`anthropic` 协议、已配密钥；不可用 `400`，框架不可达 `502`），没有工作区默认 / 框架生效 / 本机配置回退。run 级切换仍走 `POST /sessions/{sessionId}/update` 或 WS `model.switch`，同样只能换成另一个非空模型。

### 3.2 创建后的元数据自动刷新

创建响应发出后，服务端顺手起一个**后台任务**（`agent-metadata.ts`）：拿 `init.input`（剥掉首页拼的 `/…:harness-create` 命令）、附件文件名与同工作区已有标签，调一次无工具的模型，产出 `name / description / tags` 并落库。它替代首页的正则兜底名与需求截断。

- **不是端点、不由前端触发**：前端只在设计页按创建响应的 `updatedAt` 轮询详情，把新值显示出来；
- **只跑一次**，失败只记日志、保持兜底值；`AUTO_META=0` 整体关闭（测试默认关闭）；
- **不覆盖手改**：落库是 `updatedAt` 条件更新，生成期间用户改过任何字段就放弃；
- 名字撞同工作区时挂 4 位短码（与首页同一约定），唯一索引兜底；三字段与现值相同则不写库。

## 4. 删除：先停运行、再删盘、后删库

```
查行（无则 404）→ 解析工作区目录（不可解析则失败，不删库）
→ 停掉该智能体名下全部实例的活跃 run（四个阶段都算），等驱动链收尾（引擎退出）
→ 删整个 <workspace.directory>/.smart-factory/agents/{id}/（存在才删）
→ 一个事务：messages → runs → sessions → instances → agents
```

**为什么与创建相反**：目录**缺失不可自愈**。删盘是整个服务里唯一会丢数据的动作，一旦它失败而库已删，就是「行没了、目录还在」，而下次启动的收养会把这个目录**登记成一个新智能体** - 等于删不掉，还把用户以为删掉的东西还回来。按先盘后库，最坏情况是「目录已删、行还在」，用户可以再删一次；目录缺失不会被收养回来。

四条与之配套的不变量：

- **运行中的会话由删除动作自己停掉**：`development` / `preview` / `runtime` / `evaluation` 任一有活跃顶层 run，先按 `runs/abort` 同一路径中止（连同子 run 与挂起审批），等引擎真正退出再删盘 —— 不能出现「行已删、引擎仍阻塞在挂起上」，也不能让引擎在收尾里把刚删掉的产物目录写回来。适配器不响应中止时等待有上限（`STOP_RUNS_TIMEOUT_MS`），不把删除请求吊死。
- **级联是应用层显式完成的**：零外键，没有数据库级联兜底，五张表在同一个事务里删，范围是该智能体名下**四个阶段的全部会话历史**。
- **不幂等**：目标不存在返回 `404`，不复用「已达成即成功」的语义。
- **工作区不可解析时不删库**：拿不到 `directory` 就不知道该删哪棵树，宁可报错也不改数据库。

## 5. 启动收养

启动时（`index.ts` 的启动收口旁）执行一次**幂等**收养：把表里没有、盘上却有的目录补登记成行。收养**按工作区扫描**。

| 项 | 规则 |
|---|---|
| 工作区清单 | 框架 `GET /api/framework/v1/workspaces` 的 `items`；`directory` 为 `null` 的工作区跳过 |
| 扫描范围 | 每个工作区下 `<workspace.directory>/.smart-factory/agents/` 的**直接子目录** |
| 跳过 | 非目录项、以 `.` 开头的隐藏目录、过不了 `agentId` 形态校验的目录名（手建的 `我的笔记`、`tmp dir` 不会被误收成智能体）、`name` 截断到 40 字符后与**同一工作区**内已有行重名的目录 |
| 补出的行 | `id` = 原目录名、`workspaceId` = 扫描到的工作区 id、`name` = 原目录名截断到 40 字符、`description` = `""`、`icon` = `""` |
| 幂等依据 | `id` 是否已在表里；重复启动不重复插入 |
| 反向 | 表里有行、目录不存在时**不动**（宁留空壳，不误删数据） |
| 框架不可达 | 整轮跳过并打日志，**不阻塞启动**，也不猜路径 |
| 日志 | 收养条数非 0 时打一行 |

两条容易被顺手改错的约束：

1. **`id` 保留原目录名，不重发 uuid。** `instances.agent_id` 是字符串引用，重发 uuid 会让历史智能体的全部会话指向不存在的行（全线 404）。代价是库里长期并存两种 `id` 形态（§1），这是刻意接受的，不是欠债。`id` 仍是全局主键：不同工作区出现同名目录时先到先得，后来者跳过并打日志。
2. **`name` 只能拿目录名凑。** 这些历史目录多半是旧版 `sessions/create` 顺手建的空目录，盘上没有任何可读的展示名。名字丑是诚实的；不要为此发明「从 `CLAUDE.md` 里猜个名字」这类启发式 - 收养的职责只是补登记，任何会改写用户数据的动作都不属于它。

## 6. 前端为什么不能失去重名 409

重名返回 `409` 而不是静默加后缀，是接口契约（[`../05-openapi/5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml) 里 `create` / `update` 的 `409` 响应）；背后的用法约束在这里：**首页从一句话取名**（`web/src/features/home/create-agent.ts`），撞名后自己顺位成「天气智能体 2」再试，**只有 `409` 才顺位**。改成静默加后缀，用户会拿到一个跟别人重名的展示名，而 `name` 是工作区内唯一的展示键 - 409 是这个顺位重试机制的唯一信号。

同理，`agents/update` 改 `name` 走同一套唯一判定，撞了同样 409、同样不加后缀。不同工作区可以同名，不触发 409。

## 7. 标签

标签是**一行 JSON 数组串**（`agents.tags`，`String @default("[]")`，与 `messages.content` 同一种存法），
不是关联表、也不是 Prisma 的 `Json` 类型。形状与校验的权威在契约
[`../05-openapi/5.01-agent-openapi.yaml`](../05-openapi/5.01-agent-openapi.yaml) 的 `Agent.tags`，这里只记规则与它为什么长这样。

| 规则 | 值 | 由来 |
|---|---|---|
| 单个标签长度 | trim 后 **1–10 字** | 展示面倒推：卡片标签行只有一行，还要给「+N」留位置（§7.1） |
| 数量 | ≤ 10 个 | 再多一行摆不下，筛选也失去意义 |
| 去重 | 按字节精确、保序 | 与 `name` 的唯一性同口径（大小写敏感、不做 Unicode 归一） |
| 禁用字符 | `"` `\` `%` `_` | 每一个都对应一个具体的坏法（§7.2） |
| 空值 | 不传 = 空数组；update 传 `[]` = 清空 | 与 `description` / `icon` 的空串同构 |

做的是**机械约束，不是受控词表** - 可选集合归前端（同 `icon` 的口径），后端不维护一份标签字典。

### 7.1 为什么是 10 字

字数上限唯一的约束方是**卡片**：卡面上标签行固定一行、不换行，装不下的收成 `+N`。
前端实测：一颗 20 字标签宽 250px，`+N` 按钮 34px、间距 6px，合计 290px；
而栅格最窄的一列（`minmax(300px, 1fr)` 减左右内边距）内容宽只有 268px -
`+N` 会被挤出可视区，那个标签的浮层就点不开了。10 字标签约 145px，和 `+N` 一起放得下还有余量。

所以这个数字不是「感觉短一点好」，是**从最窄的卡倒推出来的**。要放宽它，得先改卡片的标签行
（允许换行、或给「+N」钉住位置），不能只改这一行常量。

### 7.2 为什么禁这四个字符

- `"` - 破坏过滤据以定界的引号（见下条）；
- `\` - 破坏 JSON 转义；
- `%` 与 `_` - 会被 SQLite 的 `LIKE` 当成通配符，而后端**不发 `ESCAPE` 子句**，无法转义。

过滤是 `GET /agents?tag=`：**精确匹配一个标签、不是子串**（`tag=天气` 不命中「天气2」），
实现上靠引号定界（`LIKE '%"天气"%'`） - 这正是第一个字符被禁的原因。
只收一个参数；重复参数（`?tag=a&tag=b`）按「没给」处理；没有智能体带这个标签时是空页而不是 404。

筛选下拉的候选由 `GET /agents/tags` 提供：全表读 `tags` 列，在服务层按智能体去重计数，
排序 `count` 降序、`tag` 升序。它不参与分页，也不解析工作区目录。
当前规模下这是一次内存聚合；智能体量级涨到全表扫不可接受时，按 §7.3 换关联表。

### 7.3 什么时候该改成 `agent_tags` 关联表

现在这套（一列 JSON 串 + `LIKE` 定界）在「标签只是展示 + 单标签筛选」下够用，且省掉两张表的连接。
出现下面任一条就该换：

1. **要按多个标签做 AND / OR 筛选** - `LIKE` 拼不出「同时带 A 和 B」的索引友好查询；
2. **标签统计的量级大到不能再全表扫** - `GET /agents/tags` 目前就是全表读 `tags` 列在内存里数，
   规模可接受时无需关联表；需要索引化聚合或标签云分页时再换；
3. 标签数量级涨到需要**独立的标签字典与重命名**（改一个标签要扫全表）。

换的时候是一次迁移 + `readTags` / `agents.repo.ts` / 契约三处，前端不动（接口形状不变，仍是 `string[]`）。

## 8. 内置智能体（source=builtin）

> 决策记录见 [`../99-adr/0003-builtin-agents.md`](../99-adr/0003-builtin-agents.md)。代码落点：`server/src/shared/workspace/builtin-agents.ts`（定义目录与清单）、`agent.service.seedBuiltinAgents`（seed）。验收测试：`server/tests/builtin-agents.test.ts`。

由部署方提供、不经用户登记的智能体。形态是**「目录即专家」**：定义目录就是一个自包含的专家项目
（`CLAUDE.md` + `.claude/skills` + `runtime/` + `data/`），引擎（claude-cli）从 cwd 发现这些内容，
所以 **runtime cwd = 定义目录本身**，装完即用。

- **定义根**：`{COSIGHT_HOME}/smart-factory/builtin-agents/{id}/`，与工作区产物目录完全分离；`id` 就是目录名
  （如 `example-builtin-agent`，与 `agt_<uuid>` 形态并存，都过同一份形态校验）。
- **来源字段**：`agents.source`（`user` | `builtin`）是唯一权威。它是事实，不是标签 —— 只读、仅 runtime、
  无工作区都由它派生；`tags` 只放用户标签，来源不写进去。`内置` / `自定义` 是保留字，写进 `tags` 一律 400。
- **清单**：目录根部 `agent.json`（`name` / `description` / `tags` / `icon` 白名单，多一个字段即脏清单）是元数据权威。
  清单里的 `tags` 原样落库；若作者把保留标签写进去，读清单时剥掉并告警（不因此丢掉整个专家）。
- **boot seed**（`main()` 里紧跟收养之后、listen 之前）：扫描定义根，无行则登记（
  `workspaceId=null`、`source='builtin'`）；已有内置行且清单漂移则按清单刷新（值没变不写，updatedAt 是排序键）；
  id 被非内置行占用则告警跳过；**定义目录消失的内置行级联删除**（连带实例 / 会话 / 运行史）。
  全程零框架调用——框架不可达不影响内置智能体；单目录失败只告警不挡启动。
- **只读**：`update` / `delete` 一律 `409`（`error.conflict.builtin_agent`）。元数据只随定义目录的清单走。
- **仅 runtime**：`sessions/create` 非 runtime（含缺省 `development`）`409`；`resolveRunSetup` 里 cwd 直接取定义目录，
  跳过 `stageDir` / 产物定位 / 物化；`production` / `artifacts`（非 runtime）/ `evaluations` 一律 `409`。
  runtime 多会话仍按 session 仲裁并发，**共享定义目录 cwd**——写边界就是专家目录自己的 `data/` 约定，
  与「目录即专家」的直接用法相同。
- **列表混入**：`GET /agents`（含带 `workspaceId` 筛选的查询）恒返回内置行，scope 是
  `OR: [{workspaceId}, {source:'builtin'}]`；`dir` = 定义目录本身，不经工作区解析。`GET /agents/tags` 同口径。
  `?source=user|builtin` 直接按来源过滤（枚举外 400，空串视为未传）。
- **文件面**：内置定义根进入 `/fs` 浏览白名单（`local-path.localRoots`）；裸 `COSIGHT_HOME`
  （`.module-token`、数据库所在）不进白名单。
- **观测面**：`GET /workspaces/directories/list` 在框架工作区之外补一条 `kind=default`、`directory` 指向
  `{COSIGHT_HOME}/smart-factory` 的「默认工作区」条目。内置专家 runtime cwd（`builtin-agents/{id}`）
  与技能工坊（`skill-workshop`）、自由对话（`chat`）都在其下，观测端按前缀归属即可；
  框架不可达时与 `/workspaces/list` 同口径 `502`（见 [`4.01-接口总览.md`](../04-api/4.01-接口总览.md) §4.6）。
- **分发**：内置专家的定义**随模块分发**——源目录 `server/builtin-agents/{id}/` 进产物包（`bundle.include`），
  server boot 在 seed 之前调用 `syncBundledBuiltinAgents` 同步到定义根（dev 与产物同一份代码、同一路径规则）。
  同步只刷新定义文件：目标端由专家自己维护的 `data/` / `workspace/` / `.drive/` 不覆盖、不删除，
  部署方另放的专家目录也不受影响；内容相同不重写（`tsx watch` 热重启不刷 mtime）。
  同步后仍由 boot seed 按 `agent.json` 登记。薄壳专家只放 `agent.json` + `CLAUDE.md` + `.claude/settings.json`
  （声明 `enabledPlugins`），能力在插件载荷里，不往定义目录复制技能。
  当前随包专家：`software-rd-team`（软件研发团队，默认携带 `drive:drive`）、
  `enterprise-knowledge-assistant`（企业知识助手，薄壳，能力由机器上另行安装的 `cosightbot@cosight-bot` 插件提供：
  `/cosightbot:pkm` 与 `/cosightbot:soc` 两个模式入口；插件未安装时如实降级，不随产品打包）。
