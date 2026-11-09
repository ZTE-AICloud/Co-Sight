# 四能力用户流程与缺口分析

> 状态：**分析稿**（2026-10-23）。本文只审查 smart-factory 前端「智能体创建/优化、智能体评估、技能创建、技能优化」四条能力的**用户流程完整性**，不重定接口契约。
> 入口与页面的设计口径见 [`capability-routing.md`](./capability-routing.md)；接口以后端 [`04-api`](../../server/docs/04-api/) 为正本；未定事项见 [`open-questions.md`](./open-questions.md)。
>
> ⚠️ 口径漂移：`capability-routing.md` 仍写着「不做能力 chip」「技能库页不放创建技能」，但**当前实现已经加了能力 chip、五张能力卡和首页创建技能卡**（`src/features/home/capabilities.ts`、`HomePage.tsx`）。读那篇时请以本文 §1 的现状为准。

## 0. 一句话

四条能力**都能发起、都能跑**，但流程普遍停在「一场对话结束」，缺少后半段：**完成判定 → 验收 → 回流/下一步**。

最严重的两处断点：

1. **评估 → 修复 → 再评估不闭环**：评估会话里的修复改的是隔离沙箱，不会回流到智能体的开发产物。
2. **技能优化没有验收视图**：`skill_optimize` 是评测驱动的，但工坊只呈现聊天和文件树，看不到分数、是否达标、改了什么。

---

## 1. 现状：页面、入口与落点

### 1.1 页面

| 路由 | 页面 | 承担的能力 |
|---|---|---|
| `/` | 首页（能力 chip + 五张能力卡） | 发起四条能力 |
| `/agents` | 专家 · 技能（两个 tab） | 选目标、进设计页、进技能库 |
| `/agents/:agentId/design` | 智能体设计页（生成 / 预览调试 / 评估） | 智能体创建、优化、预览、评估 |
| `/workshop` | 技能工坊（目录会话） | 技能创建、技能优化（库技能） |

### 1.2 入口矩阵

| 能力 | 入口 | 落点 | 首轮是否自动发 |
|---|---|---|---|
| 智能体创建 | 首页「创建智能体」 | `/agents/:id/design`（development） | 是，补发 `harness-create` |
| 智能体优化 | 首页「优化智能体」、专家卡「设计」、智能体技能卡「优化」 | 同一个设计页（development 会话继续聊） | 首页入口**是**：replay + autoSend，发进最近一场 development 会话（带 `harness-create`）；其余入口否 |
| 智能体评估 | 首页「评估智能体」、专家卡「评估」 | `/agents/:id/design?stage=evaluation` | 首页入口**是**：停掉旧一场、重开一场（`resetSandbox` 重建沙箱）并立刻开跑，带 `agent-eval` 命令；阶段内仍点「开始评估」才发 |
| 技能创建 | 首页「创建技能」 | `/workshop` | 是，自动发 `skill-foundry` |
| 技能优化（库技能） | 首页「技能优化」、技能卡「优化」 | `/workshop?target=…&name=…` | 是，自动发 `skill_optimize` |
| 技能优化（智能体技能） | 首页「技能优化」、技能卡「优化」 | 该智能体设计页（replay 进发送框） | 否 |

### 1.3 命令拼装

| 场景 | 实际发出 | 落点代码 |
|---|---|---|
| 智能体创建 | `/agent-genesis:harness-create <正文>` | `HomePage.tsx` 的 `createAgent` |
| 智能体优化（首页入口） | `/agent-genesis:harness-create <正文>`（replay + `autoSend`，到页即发） | `HomePage.tsx` 的 `optimizeAgent`；发送在 `useCreationChat.ts` 的 `kickoffInto` |
| 技能创建 | `/agent-genesis:skill-foundry 创建一个新技能：<正文>` | `compose-prompt.ts:45` |
| 技能优化 | `/skill-optimizer:skill_optimize --mode optimize --skill-path <SKILL.md 绝对路径>` | `compose-prompt.ts:45` |
| 智能体评估 | `/goldeval:agent-eval --agent . --output ..`（首页入口把用户写的要求接在后面） | `evalKickoff.ts`；首页在 `HomePage.tsx` 的 `openAgent` |

---

## 2. 四条用户流程（按当前实现）

### 2.1 智能体创建 / 优化

```text
首页
  ├─ 写需求（可挂附件）→ 发送
  ├─ POST /agents 登记身份
  ├─ /agents/:id/design
  ├─ development 会话自动补发 harness-create 首轮
  ├─ 生成阶段：左对话 / 右文件树
  └─ 产物 ready → 预览 / 评估变为可进入（步骤条不再标锁定）
```

- 入口分发：`HomePage.tsx:549` 的 `submit()`，创建分支在 `:648`。
- 阶段准入：设计页在切到预览 / 评估前现拉产物状态，未 ready 时整块显示锁定原因（`AgentCreatePage.tsx:294`、`:466`）。
- 「优化」首页有独立入口（2026-10-27 起）但没有独立状态：落到目标智能体的同一个设计页，
  在 development 会话里继续对话（replay 里带 `harness-create`，到页即发进最近一场会话）。

### 2.2 智能体评估

```text
首页「评估智能体」/ 专家卡「评估」
  ├─ 目标解析：正文点名 → 直接命中；认不出 / 多义 → 选择器
  ├─ /agents/:id/design?stage=evaluation
  │    （原话与附件走 replay，只放进发送框，不自动发）
  ├─ 产物门禁 → 未 ready 时显示 StageLocked
  ├─ 空会话点「开始评估」
  ├─ 发 /goldeval:agent-eval --agent . --output ..
  ├─ 右栏 useEvalResults 轮询 /evaluations/* 读最新报告
  ├─ 未过用例「让助手修复」→ 在评估会话里发一条修复请求
  └─ 「重新评估」→ 重建评估沙箱 + 新会话 + 立刻重跑
```

- 入口：`HomePage.tsx:702`、`AgentListPage.tsx:290`。
- 启动：`EvaluateStage.tsx:132` 的 `EvaluateStart`；重跑在 `:83`。
- 修复：`EvaluatePanel` 的 `onRetry` → `AgentCreatePage.tsx:339` 的 `handleCaseRetry`。

### 2.3 技能创建

```text
首页「创建技能」→ 写需求 → 发送
  ├─ navigate('/workshop', { state: { firstPrompt, attachments } })
  ├─ GET /skills 拿到 root / cwd
  ├─ 自动建目录会话（名字取正文前 20 字）
  ├─ 自动发 skill-foundry 首条
  └─ 对话 + 右侧技能库文件树；一轮结束重拉文件树
```

- 自动发送：`useWorkshopSession.ts:282` 的上电序列。
- 首条拼装：`compose-prompt.ts:45`；会话名：`:54`。

### 2.4 技能优化

```text
首页「技能优化」/ 技能卡「优化」
  ├─ 库技能 → /workshop?target=<技能目录>&name=<技能名>
  │    ├─ 自动建会话（名为「优化 <name>」）
  │    └─ 自动发 skill_optimize --mode optimize --skill-path <SKILL.md>
  ├─ 智能体技能 → /agents/<ownerAgentId>/design
  │    └─ replay「/skill-optimizer:skill_optimize --mode optimize --skill-path …」进发送框，不自动发
  └─ 工坊「历史」抽屉按 cwd + 会话名筛这一场
```

- 目标解析：`HomePage.tsx:677` 的 `openSkill()`。
- 技能卡入口：`SkillLibraryPanel.tsx:92`。
- 技能库展示：进页面拉一次 + 手动刷新，不轮询不推送（`SkillLibraryPanel.tsx:32`）。

---

## 3. 缺口清单

### P0-1 评估 → 修复 → 回归闭环断裂

**现象**

用户在评估报告里点「让助手修复」，助手在评估会话里改文件；下一次「重新评估」后，同样的问题还在。

**证据链**

1. 「让助手修复」把请求发给当前**评估阶段**的会话：`AgentCreatePage.tsx:339` → `chat.send(...)`；
2. 评估会话的 cwd 是 `<agentRoot>/evaluation/agent`，是从预览沙箱整体拷贝出来的隔离副本：`server/docs/03-architecture/03-session-run.md:40`；
3. 同一文档 `:43`：**preview 与 evaluation 是隔离副本，沙箱里改文件不影响开发产物**；
4. 「重新评估」会按最新开发产物重新物化评估沙箱（`EvaluateStage.tsx:83`），沙箱里的修复随之被清掉；开发产物一变，旧报告也作废（`03-session-run.md:45`）。

**影响**

评估能力看起来有「修复」这个闭环动作，实际是死路：用户以为问题被修了，智能体本身没有变好。这是四条能力里最伤信任的一处。

**建议**

- 报告里把「修复」改成明确的两条路：
  - **回生成阶段修复**（推荐）：跳 `/agents/:id/design`（development），replay 一段包含「报告路径 + 未过用例」的修复请求；修复轮跑完后给「重新评估」入口。
  - 保留「在评估沙箱里试改」，但文案要说清「只影响本轮评估副本，不会更新智能体」。
- 不要在评估会话里继续假装修复会生效。

**验收标准**

- 从评估报告点「回生成阶段修复」→ 落在 development，发送框已有带报告路径的修复话术；
- 修复轮结束后，页面出现「重新评估」；
- 重新评估的报告能反映开发产物的新版本；
- 「在评估沙箱试改」不再被描述成正式修复。

---

### P0-2 技能优化没有验收视图与收敛控制

**现象**

`skill_optimize` 的语义是「评测 → 缺口 → 优化 → 再评测直到达标」，但工坊里只看到：

- 聊天文本；
- 右侧技能库文件树（`SkillFilesPanel`）。

看不到评分、是否达标、优化了几轮、改了什么。

**影响**

- 用户无法判断这一轮优化是否成功，只能读聊天；
- 无法决定「继续优化」还是「到此为止」；
- 智能体线有完整评估报告面板（`EvaluatePanel`），技能线没有，两条线的体验落差很大；
- 技能优化后没有 diff / 回滚，用户不敢让它改生产技能。

**建议**

- 工坊右侧加一个「本轮结果」入口（tab 或可折叠块），至少呈现：是否达标、轮次、关键缺口、评测结论。
- **优先走后端契约**：让 `skill_optimize` 把结构化摘要写到技能目录或工坊 cwd 下的固定文件，由新端点读取；不要在前端解析自然语言。
- 有版本目录时给 diff；没有版本目录（原地改 `v1`）时，至少给「改动文件列表」。
- 给「继续优化」「已达标，完成」两个动作；完成态再给「回技能库」。

**待确认**

- `skill_optimize` 优化时是否新建版本目录（`v2`）还是原地改；这决定 diff / 回滚能否只靠扫描实现。
- 评测产物是否复用 `goldeval` 的 `e2e-test-*` 结构；复用的话可以直接接 `/evaluations/*` 的读取层。

---

### P1-3 创建完成没有交接

**智能体侧**

- 产物 ready 只表现为步骤条不再显示锁定标记；页面没有「产物已就绪，去预览 / 评估」的完成态或 CTA。
- 用户容易停在生成对话里，不知道下一步是预览还是评估。

**技能侧**

- skill-foundry 跑完后，工坊没有「查看新技能 / 去技能库 / 立即优化」任何出口。
- 技能库进页面拉一次 + 手动刷新（`SkillLibraryPanel.tsx:32`），工坊产出后必须由用户自己回去点刷新再找。
- 顶栏「新会话」直接回首页，不在工坊收尾，进一步放大「做完就散了」。

**建议**

- 智能体：production ready 时在生成阶段顶部给一条完成态 + 「去预览」「去评估」。
- 技能：一轮 run 结束后对比技能库根，检测新增/变更目录，给「在技能库查看」「立即优化」。
- 技能库至少支持从工坊带 `?highlight=<path>` 回来时定位到那张卡。

---

### P1-4 技能产出没有消费方

**库技能**（技能库里的、由技能创建/优化产出的技能）目前只能「看」和「优化」，不能导入某个智能体使用（`backlog.md` #14「技能导入智能体」仍是待办）。智能体自己的技能是在其产物目录里、随开发对话更新的，不受这条影响。

**影响**

四条能力里两条技能线是**资产的公共生产线**，但产出的库技能与智能体线没有接上：创建了技能，只能等某个智能体自己在产物里再写一遍，或者手工复制。这是能力之间最大的流程断点。

**建议**

按 backlog #14 的规格推进；在它落地前，至少不要让技能卡暗示「已经可用于智能体」。

---

### P1-5 「智能体优化」在入口和状态上都是隐性的

- ~~首页没有「优化智能体」能力或目标选择，只有「创建智能体」；优化只能从专家卡「设计」进。~~
  2026-10-27 已补：首页新增「优化智能体」能力（`target: 'agent'`，与创建同用 `harness-create`），
  落到目标智能体的设计页并自动发进最近一场 development 会话。下面三条仍在。
- 进去后页面仍叫「生成」，没有「我在优化一个已有智能体」的上下文。
- 智能体没有版本概念，也没有优化前后对比 / 回滚。
- 唯一能证明「优化有效」的评估，又受 P0-1 影响。

**建议**

- 二选一：
  - 首页新增「优化智能体」能力（`target: 'agent'`），盘活目标选择器；或
  - 明确把「优化」定义成「设计页里的继续对话」，在专家卡与页面标题上把「设计 / 优化」说清。
- 优化场从技能卡或评估报告进入时，replay 里带上当前状态（最近一次评估结论 / 要改的点），不要只给一句空话术。

---

### P2-6 目标选择会把用户带进死路

- 首页「评估智能体」的目标清单调用 `agentsApi.list({ pageSize: 200, workspaceId })`（`HomePage.tsx:150`），**没有过滤 source**。
- 服务端按工作区查询时会把 `builtin` 内置智能体一并返回（`agents.repo.ts:200-202`）。
- 用户选中内置智能体后，设计页走 `builtin` 分支，只显示「内置智能体只读」，评估进不去（`AgentCreatePage.tsx:402`）。
- `pageSize: 200` 是硬上限，智能体超过 200 个时，较早的智能体在首页选择器里选不到。

**建议**

- 评估目标只列 `source=user`；或内置项置灰并说明「内置智能体只读，不可评估」。
- 目标选择器补搜索 / 分页，不要依赖一次拉 200。

---

### P2-7 恢复与历史可见性

| 问题 | 现状 | 影响 |
|---|---|---|
| 首轮交接依赖路由 state | 智能体创建有 `initialInput` 落库兜底；工坊没有，刷新 / 新标签页会丢 | 工坊自动发送失败后再刷新，用户那句话没了（对应 `backlog.md` #8） |
| 评估只显示最新一轮 | `useEvalResults.ts:43` 只取 `items[0]`，`/evaluations/list` 有历史但 UI 不用 | 「修复后有没有变好」无法对比 |
| 设计页没有会话历史 / 切换 | 每阶段复用最近一场；「重新评估」新开会话 | 旧的评估会话在 UI 上不可回看（这是本期刻意不做，见 `backlog.md`） |
| 没有跨能力任务中心 | 生成 / 评估 / 优化都可能跑几分钟 | 离开页面后没有统一的运行中 / 已完成入口 |

**建议**

- 工坊首轮至少把 `firstPrompt` 落到会话或草稿，刷新可恢复。
- 评估报告加历史列表 + 两次报告对比（接口已具备）。
- 任务中心另立议题；短期内至少在离开页面时提示「任务还在跑」。

---

### P2-8 工坊的目标不聚焦

优化场右侧文件树展示的是整个技能库根，目标技能没有自动展开或高亮；用户要从一堆目录里自己找「我刚在改的那个」。

**建议**

- `SkillFilesPanel` 接收 `?target=`，默认展开到目标技能目录并选中 `SKILL.md`。

---

## 4. 建议的最小闭环

不做整页重做，只补衔接点：

| 优先级 | 动作 | 落点 | 依赖 |
|---|---|---|---|
| P0 | 评估报告加「回生成阶段修复」+ 修复后「重新评估」 | `EvaluatePanel` / `AgentCreatePage` | 无（纯前端导航 + replay） |
| P0 | 工坊加「本轮结果」：达标 / 轮次 / 缺口 / 改动文件 | `/workshop` 右栏 | `skill_optimize` 输出结构化摘要（需后端） |
| P1 | 智能体产物 ready 后的完成态 + 「去预览 / 去评估」 | `ProductionStage` / 设计页 | 无 |
| P1 | 技能创建完成后的「查看技能 / 立即优化」 | `/workshop` + `SkillLibraryPanel` | 检测新增目录（可先前端做） |
| P1 | 评估目标过滤内置智能体；目标选择补搜索 | `HomePage` | 无 |
| P1 | 技能导入智能体 | 创建 / 设计流程 | backlog #14，等版本语义 |
| P2 | 评估历史与两次报告对比 | 评估右栏 | `/evaluations/list` 已有 |
| P2 | 工坊文件树定位到 `?target=` | `SkillFilesPanel` | 无 |

### 目标闭环

```text
智能体线：
  需求 → 生成 → 产物就绪 → 预览 → 评估
       ↑                         │
       └── 带报告回生成修复 ←── 未达标 ──→ 再评估 → 达标 → 使用 / 继续优化

技能线：
  创建 → 验收（静态检查 + 评测）→ 入技能库
       → 在智能体中使用（导入）→ 评测驱动优化 → 前后对比 / 回滚
```

---

## 5. 刻意不做 / 不属于本次缺口

以下事项是已定的边界，本文不把它们当缺陷：

- **智能体运行页**：运行交给框架会话页，本模块只做「使用」跳转。
- **发布动作**：智能体创建后即可用，没有「固化为正式资产」这一步。
- **设计页会话历史 / 切换 / 新建**：按单会话设计，只认当前这一场。
- **评估汇总页 `/evaluations`**：需要跨智能体 overview 接口，排在四能力入口落地后再看。
- **技能删除 / 重命名 / 标签**：P2。

---

## 6. 待定

1. 评估失败用例的修复，是重跑单条还是整轮？（`open-questions.md` 已列）
2. `skill_optimize` 的结构化输出形态：写文件 + 新端点，还是复用 `/evaluations/*` 的读取层？
3. 技能优化的版本语义：原地改 `v1`，还是每次新建 `vN`？决定 diff / 回滚怎么做。
4. 智能体是否需要「优化」独立能力与版本概念，还是继续用设计页 + 评估报告表达。

---

## 7. 代码索引

| 主题 | 落点 |
|---|---|
| 四能力定义 | `src/features/home/capabilities.ts:38` |
| 首页提交分发 | `src/features/home/HomePage.tsx:549` |
| 创建智能体 / 评估 / 技能入口 | `HomePage.tsx:648` / `:702` / `:677` |
| 设计页阶段门禁 | `src/features/agent-create/AgentCreatePage.tsx:294` |
| 评估修复 | `AgentCreatePage.tsx:339` |
| 评估启动 / 重跑 | `src/features/agent-create/stages/EvaluateStage.tsx:83`、`:132` |
| 评估报告只取最新 | `src/features/agent-create/useEvalResults.ts:43` |
| 工坊首条拼装 | `src/features/skill-workshop/compose-prompt.ts:32` |
| 工坊自动发送 | `src/features/skill-workshop/useWorkshopSession.ts:282` |
| 技能卡入口 | `src/features/skill-library/SkillLibraryPanel.tsx:92` |
| 技能库手动刷新 | `SkillLibraryPanel.tsx:32` |
| 评估沙箱隔离 | `server/docs/03-architecture/03-session-run.md:40-48` |
| 内置智能体混入列表 | `server/src/shared/store/agents.repo.ts:200-202` |
