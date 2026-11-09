# Agent 模式 Workflow — Requirement Clarifier L3

> 加载者: agent mode 命中后由 L2 SKILL.md 引用
> 内容: 阶段 2 / 阶段 2.5 / 阶段 3 (agent 专属问题清单指引) / 阶段 4 详尽协议
> 唯一权威: 12 类任务模式 = `references/task-modes.md`（已迁入本 Skill 目录, 同包）
> 唯一权威: 5 维 + knowledge_sources 输出 schema = `references/schemas/clarified-agent.schema.yaml`
> 唯一权威: 6 维需求结构 = 本 schema 的 why/what/how/quality/acceptance

## 阶段 2: 模式分类

对照 `references/task-modes.md` 中的 12 类模式分析用户输入。内部判定即可——不要问用户"你属于哪个模式"。

模式: 研发(探索定义/实施构建/验证校验/效能基建/共识传达/路由分发) + 运维(监测响应/故障诊断/变更执行) + 办公(信息处理/安排协调/检索整合)

将已知信息映射到五个维度（Why/What/How/Quality/验收）。标注哪些已清晰, 哪些缺失。

## 阶段 2.5: 知识依赖探测（固定追问, C4）

模式分类之后、模式专属追问之前, 必须问一次 D-Knowledge（不走智能跳过——除非阶段 1 已确认完整知识资产路径）:

> **D-Knowledge — 这个 Agent 需要的外部知识从哪来？**
> 场景: 生成的 Agent 做决策时需要依据。依据来源不同, 设计模式完全不同。
> 选错的代价: 选 K1（只靠模型自带知识）但业务实际有规范文档 → Agent 会编造字段名; 有文档却没声明 → 知识边界缺失, 下游硬约束 HC-01 直接 FAIL。
> 推荐: 按实际选择; 多数企业内部场景已有文档/规则, 优先如实回答。
>
> A) **已有文档/规则文件**（推荐, 如果项目里确实有规范、手册、检查清单类文件）
>    ✅ 走 K2 模式——Agent 每次引用具体段落, 可审计、不编造
>    ❌ 需要维护文档路径, 文档过时 Agent 跟着错
> B) **有可检索的知识库**（wiki、知识平台、数据库——需要按主题检索而非整篇阅读）
>    ✅ 走 K3 模式——按需检索, 不怕文档大
>    ❌ 检索质量依赖索引, 需要定义检索策略
> C) **有可分发的规则文件**（想把规则打包进 Agent 目录, 随 Agent 一起交付/版本化）
>    ✅ 走 K4 模式——规则自包含, Agent 可独立分发
>    ❌ 规则更新需要重新发版
> D) **没有外部知识**——通用任务, 模型自带知识足够
>    ✅ 走 K1 模式——零依赖, 最简单
>    ❌ 领域专业场景下会产生幻觉, 无边界约束

**非 K1 必须追出具体来源**: 选 A → 追问文档/规则文件路径（哪些文件、在哪里）; 选 B → 追问检索入口（什么系统、按什么主题）; 选 C → 追问规则内容归属（现有规则文件路径, 还是需要从经验整理）。追到可以写入 `location` 字段为止。两轮追不出 → 记 `trust_level: 待确认` + open_question, 不阻塞。

结果写入输出的 `knowledge_sources[]`（见阶段 4）。

## 阶段 3: 澄清提问（agent 专属）

**每次只问一个问题**。D1, D2, D3... 从 `references/task-modes.md` 的问题清单中选取。

如果阶段 1 未发现可复用资产（skills/rules/knowledge/hooks）, 在模式专属问题之前先问 D1:

> 当前项目中没有发现已有的 Skill/Rules/Knowledge。你有现成可复用的内容吗? 比如某个 Skill 的代码、已有的审查规则、领域知识文档?
> A) 有, 我稍后提供路径
> B) 没有, 从零开始（推荐）
> C) 不确定, 后续再说

**按模式组的推送力度:**
- 研发(探索定义/故障诊断/实施构建): 强推送——"第一个答案通常是抛光版, 真答案在追问后"
- 运维(监测响应/变更执行/验证校验): 中推送——追问具体阈值和 SLA
- 办公(信息处理/安排协调/检索整合): 弱推送——接受用户偏好

## 阶段 4: 输出（agent 专属）

写入 `.agent-genesis/work/{name}/agent-creation/clarified-agent-requirements.yaml`。
格式: `references/schemas/clarified-agent.schema.yaml`。
这是需求的唯一契约载体（验收标准、业务规则、知识依赖全在此），不写任何 output 交付文件。

如果阶段 1 发现已有 Agent 配置（CLAUDE.md + skills/ + rules/）, 设置 `build_mode: incremental`。
否则 `build_mode: greenfield`。

### 输出示例（好的）

```yaml
task_mode: exploration_definition
why:
  user_role: "支付公司财务对账专员"
  business_scenario: "每日 T+1 收到银行清算文件后需在 2 小时内完成对账"
  core_pain_points: ["手动 Excel 对账, 单渠道 40 分钟", "差异漏检率 2.3%"]
  expected_value: "对账时间降至每个渠道 < 5 分钟, 漏检率 < 0.1%"
  success_metrics: ["日均对账时间 < 30 分钟", "差异检出召回率 > 99.9%"]
knowledge_sources:
  - type: K2
    location: "docs/对账规范.md, docs/差错处理手册.md"
    trust_level: "权威 — 字段名与匹配规则以文档为准"
what:
  core_flow: "定时拉取清算文件 → 格式解析 → 逐笔比对 → 输出差异清单 → 分派工单"
  scope_boundaries: "做 T+1 对账, 不做实时; 做 CSV/XLSX/固定宽度文本; 不做跨境汇率换算"
  priority: must
how:
  normal_flow: "..."
  exception_flow: "清算文件未按时到达 → 告警 + 30 分钟重试 → 仍不到则标记人工补录"
  business_rules: ["三要素匹配: 金额(精确到分)+流水号+时间(误差±5分钟)", "差异分级: ≥1000元=P0, >0且<1000元=P1"]
quality:
  performance: "单渠道 10 万笔 < 5 分钟"
  security: "金额脱敏传输, 审计日志保留 5 年"
acceptance_criteria:
  - given: "银行清算文件按时到达"
    when: "系统自动拉取并执行对账"
    then: "5 分钟内输出差异清单"
open_questions:
  - question: "差异处理工单的自动分派规则是什么?"
    recommendation: "按渠道+金额自动分派到对应财务人员"
    status: pending
confidence: 85
```
