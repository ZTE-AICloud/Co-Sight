---
pattern_id: M1
pattern_name: Model Selection
category: workflow
sub_dimension: model_selection
selection_rule: "可选基础设施。可叠加到任意执行步骤上，为每个 step/subagent 标注推荐模型。"
solves: "不同步骤的推理深度、延迟容忍度不同，需要为每步选择合适的模型而非全流程统一模型"
fills_spec_section: Execution Workflow (per-step model attribute)

variables:
  - name: MODEL_PREFERENCE
    description: "用户指定的模型偏好"
    type: string
    source: user_input
    enum: ["opus", "sonnet", "haiku", "auto"]
    default: "auto"
  - name: STEPS_WITH_MODELS
    description: "每个执行步骤的模型分配"
    type: list
    source: decision_table
    required: true
    schema:
      - field: step_name
        type: string
        description: "步骤名称"
      - field: model
        type: string
        enum: ["opus", "sonnet", "haiku"]
        description: "推荐模型"
      - field: rationale
        type: string
        source: llm_generate
        description: "选择该模型的理由"

model_tiers:
  opus:
    label: "深度推理"
    suitable_for:
      - "架构决策与系统设计"
      - "复杂多因素分析与权衡"
      - "安全审查与风险评估"
      - "模式匹配中的歧义消解"
      - "W5 adaptation_decision（拓扑切换决策）"
    latency: "高"
    cost: "高"
  sonnet:
    label: "平衡"
    suitable_for:
      - "主要编码与实现"
      - "SubAgent 编排与调度"
      - "代码审查与质量门禁"
      - "Spec 拼装与模板填充"
      - "常规验证与检查"
    latency: "中"
    cost: "中"
  haiku:
    label: "快速"
    suitable_for:
      - "格式检查与 Schema 校验"
      - "文件存在性与引用完整性验证"
      - "简单数据转换与解析"
      - "高频轻量任务"
      - "进度汇报与状态更新"
    latency: "低"
    cost: "低"

  - name: MODEL_PARALLEL_GROUPS
    description: "同步骤多模型并行组——同一输入驱动多个不同模型并行执行，取最优或投票决定"
    type: list
    source: user_input
    required: false
    schema:
      - field: group_id
        type: string
        description: "并行组编号"
      - field: step_name
        type: string
        description: "所属步骤名称"
      - field: model
        type: string
        enum: ["opus", "sonnet", "haiku"]
        description: "使用的模型"
      - field: parallel_count
        type: number
        description: "并行实例数"
      - field: aggregation
        type: string
        description: "结果聚合方式（voting / best-score / merge）"
      - field: rationale
        type: string
        source: llm_generate
        description: "使用该并行配置的理由"

constraints:
  - "M1 是推荐性基础设施（非强制性），Agent 运行时可选择不同模型"
  - "W5 adaptation_decision 步骤推荐使用 opus（拓扑切换涉及架构变更）"
  - "默认模型为 sonnet，仅在有明确理由时偏离"
  - "haiku 不应用于涉及安全、合规、或关键业务决策的步骤"
  - "MODEL_PARALLEL_GROUPS 与 STEPS_WITH_MODELS 不冲突——前者是单步骤内的多实例并行，后者是跨步骤的模型分配"
---

# Model Selection

## 模型分配总览

| 步骤 | 推荐模型 | 理由 |
|------|:---:|------|
{{#each STEPS_WITH_MODELS}}
| {{this.step_name}} | **{{this.model}}** | {{this.rationale}} |
{{/each}}

## Tiered Model Parallel

同一步骤使用多个模型并行执行，不同模型用不同并行宽度补偿能力差异，结果通过投票/最优/合并方式聚合：

| 并行组 | 步骤 | 模型 | 并行数 | 聚合方式 | 理由 |
|--------|------|:---:|:---:|:---:|------|
{{#each MODEL_PARALLEL_GROUPS}}
| {{this.group_id}} | {{this.step_name}} | **{{this.model}}** | {{this.parallel_count}} | {{this.aggregation}} | {{this.rationale}} |
{{/each}}

> **与 STEPS_WITH_MODELS 的关系**: STEPS_WITH_MODELS 是跨步骤的模型分配（每步一个模型），MODEL_PARALLEL_GROUPS 是单步骤内的多实例并行（同一步多个模型同时执行）。两者不冲突——一个步骤可以在 STEPS_WITH_MODELS 中声明推荐模型，同时在 MODEL_PARALLEL_GROUPS 中声明该步骤的并行实例配置。

## 模型选择原则

1. **默认 sonnet** — 除非步骤明确需要更深推理（opus）或可接受更轻处理（haiku）
2. **安全决策必用 opus** — 涉及 CD2(Safety-First) 约束的步骤不得使用 haiku
3. **高频简单任务用 haiku** — 格式校验、文件检查、状态更新等低风险操作

## 运行时模型降级

当 opus 不可用或延迟要求严格时：
- opus → sonnet（保留推理能力，降低延迟）
- sonnet → haiku（仅限非关键步骤）
- haiku → 不可进一步降级

---
# Filled Example

## 模型分配总览

| 步骤 | 推荐模型 | 理由 |
|------|:---:|------|
| 需求分析与模式匹配 | **opus** | 需求中的歧义消解和多模式权衡需要深度推理 |
| 审查门禁 | **sonnet** | 审查维度结构化，平衡推理质量与延迟 |
| Spec 拼装 | **sonnet** | 模板填充为主，偶尔需要跨章节一致性判断 |
| Schema 校验 | **haiku** | 纯格式检查，低延迟优先 |
| 运行时拓扑切换 | **opus** | W5 adaptation_decision 涉及架构变更，需深度推理 |

## Tiered Model Parallel

同一步骤使用多个模型并行执行，不同模型用不同并行宽度补偿能力差异（出处: code-review.md Step4+Step5）：

| 并行组 | 步骤 | 模型 | 并行数 | 聚合方式 | 理由 |
|--------|------|:---:|:---:|:---:|------|
| MP-01 | 代码审查 | **sonnet** | 5 | voting | 5个sonnet实例从5个维度并行审查，投票聚合发现 |
| MP-02 | 格式校验 | **haiku** | 5 | merge | 5个haiku实例并行检查格式，合并所有发现 |

> **与 STEPS_WITH_MODELS 的关系**: STEPS_WITH_MODELS 中声明了"审查门禁→sonnet"，此处 MP-01 进一步声明该步骤使用5个sonnet实例并行执行。两者不冲突——前者定义步骤的推荐模型，后者定义该步骤的并行实例配置。
