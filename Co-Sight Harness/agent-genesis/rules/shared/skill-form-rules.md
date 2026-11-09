# Skill 形态判定规则 — 什么时候该（不该）是 skill

> 适用: 新建能力/重构时判定"是否沉淀为 skill"，以及 optimize pipeline 诊断 skill 形态问题
> 关联: `docs/plan/merge-exclusive-skills-into-subagents.md`（反模式 1 的治理方案）
> 风格: 判定框架 + 反模式登记，不描述具体实现

---

## 一、四问判定框架（按顺序，有一票否决）

| # | 问题 | 通过条件 |
|---|------|---------|
| Q1 触发者 | 谁调用这个工序？ | 用户对话式触发（main agent 是消费者，Skill description 路由有价值）→ 通过；CI/定时任务/人工 SOP → **否决，走 scripts + 文档** |
| Q1 边界 | **Pipeline 编排调用算不算 Q1 通过？不算** | contract `executor: "skill:X"` 是编排硬连线，description 路由价值为零。此类共享工序的默认形态 = **共享 SubAgent**（forbidden_inputs 可参数化，还能拿上下文隔离红利）；skill 仅当存在对话/命令式入口（如 `/e2e-test-ci`）时保留 |
| Q2 确定性比例 | 工序里多少是确定性操作？ | 确定性部分（解析/索引更新/校验/格式转换）必须进 scripts/，skill 只做编排与判断（DF-M4）；想把这些塞进 skill 让 LLM 做 → **该部分否决** |
| Q3 功能重叠 | 与既有 pipeline/skill 重叠？ | 是既有单元的输入变体 → 扩展既有单元，不新建（否则触发词歧义）；独立能力 → 通过 |
| Q4 消费者数 | 工序被几个调用点消费？ | ≥2 个消费者，或 Q1 的 main agent 消费者 → 通过；单消费者且是 SubAgent → **否决，流程进 agent def 本体** |

四问全过 → 建 skill（轻壳 + scripts 的混合形态优先）。
任一否决 → 按否决指向的形态落地（agent def / scripts / 扩展既有单元）。

## 二、核心区分与价值维度

**产物复用 ≠ 工序复用**。某工序产出的资产被多个 agent 消费（skill 被复用、知识文件被检索），
论证不了工序本身该是什么形态。判定时锁定"工序本身"的消费者与触发方式。

**价值维度 V0 — 推理路径预编译（Skill 的核心价值）**: 把高频固定任务的【思考推理流程】
提前固化为可执行指令——拆解步骤、决策分支、判断标准都已写好，LLM 从**探索模式**（每次从头
思考/拆解/决策，烧推理 token、慢、结果飘）转为**执行模式**（照做）。三重收益: 省推理 token /
降耗时 / 降不准度。注意两点:
- 预编译论证的是"**工序应固化为指令**"，不是"必须是 skill 壳"——固化的工序放在 agent def 本体
  同样有 V0 价值（本仓库 merge 方案即此实践）；skill 壳在 Q1（对话/命令触发）成立时叠加
  description 路由收益
- 预编译价值不要求"已有多个复用者"，要求的是**高频 + 固定 + 单次的推理成本高**——
  同一入口被反复触发时，第一次固化就回本

## 三、反模式登记（诊断时逐条比对）

| # | 反模式 | 判定 | 治理 |
|---|--------|------|------|
| 1 | **1:1 skill 壳**: SubAgent 的私有流程包一层 skill，agent def 只剩"按 X/SKILL.md 执行"指针 | 违反 Q4（skill 层的路由/渐进加载/复用价值全为零，纯间接层） | 合并进 agent def，删 skill 目录。方案见 merge-exclusive-skills-into-subagents.md |
| 2 | **运维工序 skill 化**: 资产导入/索引更新/周训类工序包 skill，实际触发者是 cron/CI | 违反 Q1（Skill 路由无人消费） | scripts + cron + SOP 文档。先例: knowledge/golden-examples/scripts/（auto-update.sh + regenerate.py） |
| 3 | **确定性操作塞 LLM**: 解析/索引/校验让 LLM 在 skill 流程里做 | 违反 Q2（幻觉入口 + 不可回归） | 脚本先行；LLM 只做判断与生成 |
| 4 | **产物复用偷换工序复用**: "产出的 skill 会被很多 agent 用，所以生成工序该是 skill"——产物复用论证不了工序形态 | 违反第二节"产物复用≠工序复用" | 回到四问重新判定。**但注意**: 若该工序高频固定且推理成本高，V0 预编译价值可独立支撑固化——此时错的是"拿产物复用当论据"，不是"固化本身" |
| 5 | **门禁执行层缺失**: gate 有文档声明、有 verdict 等待逻辑，但无触发器（hook 未配置/事件不可见），等待逻辑每次走超时 WARN 分支——"调用了门禁≠门禁生效" | 判定法: 查执行器（hook 配置/调用点）+ 查产出物（gate-results 是否真实存在过）+ 负例自测（注入违规必被抓） | 修复: 等待者改为执行者（先跑后读，确定性可测）; 本仓库实锤见 executor-generation-quality 方案 S0 |

## 四、真 skill 的正面形态（当前仓库实例）

满足 Q1（对话/命令式触发，description 路由必需）:

- `skills/harness-create` — pipeline 入口（用户命令触发）
- `skills/requirement-clarifier` — agent 线 Step 1 / skill-foundry create 模式 Step 0（v0.18 起; 旧名 agent-requirement-clarifier）
- `skills/e2e-test-runner` — `/selftest` 命令入口（pipeline 产物验证模式已移交 product-tester SubAgent）

**曾误判案例（教训）**: test-generator/e2e-test-runner 曾被归类"main 直调真 skill"——
实际其 pipeline 消费是契约编排调用（Q1 不成立）。test-generator 已并入共享 SubAgent
`product-tester`（零对话入口）；e2e-test-runner 因命令入口保留。判定须区分
"编排消费者"与"路由消费者"。

**Skill 的核心价值（判定时的正向问法）**: 这个任务是否高频、固定、单次推理成本高？
是 → 把它的思考推理流程预编译成指令（skill 或 agent def 内的工序），让 LLM 从探索转执行——
省 token / 降耗时 / 降不准度。V0 价值独立成立，不以"已有多复用者"为前提。

形态纪律: 轻 skill + scripts 混合——skill 内确定性操作必须 Bash 调 scripts/，
description 用 SF-6 描述公式（做什么+何时触发+输入+输出）。

## 五、待定案例的判定状态

| 场景 | 状态 | 依据 |
|------|------|------|
| 测试生成+执行（三线共享） | ✅ 已裁决: 共享 SubAgent `product-tester`（product-tester-subagent 方案） | Q1 边界规则首例 |
| API → skill 生成 | 条件满足才建: 对话式入口（Q1）+ openapi 抽取归脚本（Q2）+ 与 skill-creation pipeline 边界先裁决（Q3） | 四问待定 Q3 |
| 知识 → knowledge/ + INDEX | scripts 优先（复用 golden-examples 模式）；INDEX 更新必须确定性；仅在对话式入口真实存在时加薄 skill | Q1 取决于触发者（CI? 对话?），这是落地前必须回答的事实 |
