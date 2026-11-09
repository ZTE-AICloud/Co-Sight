---
pattern_id: IH2
pattern_name: Interactive-Clarify
category: interaction
sub_dimension: human_interaction
selection_rule: "可按执行阶段混合使用。与IH1/IH3可共存(不同阶段)。"
solves: "初始信息可能不完整，需要在执行中主动追问"
fills_spec_section: Interaction Rules

variables:
  - name: QUESTION_TOOL
    description: "使用的提问工具名（如：AskUserQuestion）"
    type: string
    source: user_input
    required: true
    default: "AskUserQuestion"
  - name: CLARIFICATION_DIMENSIONS
    description: "追问覆盖的维度列表，按优先级排序（如：Role → I/O → Workflow → Knowledge → Constraints）"
    type: list
    source: user_input
    required: true
  - name: MAX_QUESTIONS_PER_ROUND
    description: "每轮最多追问的问题数（整数）"
    type: string
    source: user_input
    required: true
    default: "1"
  - name: QUESTION_PRINCIPLES
    description: "提问原则——如：每次聚焦1个维度、给出建议选项、不重复已明确内容"
    type: list
    source: user_input
    required: false

constraints:
  - "每次聚焦1个缺失维度"
  - "给出建议选项，降低用户回答成本"
  - "不重复已明确的内容"
---

# 交互规则

## 适用阶段
初始化/需求澄清阶段

## 执行模式
- **类型**: Interactive-Clarify
- **提问工具**: {{QUESTION_TOOL}}
- **每轮最大问题数**: {{MAX_QUESTIONS_PER_ROUND}}

## 追问维度（按优先级）
{{#each CLARIFICATION_DIMENSIONS}}
{{@index+1}}. **{{this.name}}** — {{this.description}}
{{/each}}

## 提问原则
{{#if QUESTION_PRINCIPLES}}
{{#each QUESTION_PRINCIPLES}}
- {{this}}
{{/each}}
{{else}}
- 每次聚焦1个缺失维度，不一次性抛出所有问题
- 给出2-4个建议选项，降低用户回答成本
- 不重复已明确的内容
- 问题必须具体、可回答，避免开放式模糊提问
{{/if}}

## 追问终止条件
- 所有维度均已明确
- 用户明确表示"不再补充"
- 追问3轮后仍有缺失 → 标注[未明确]并基于默认假设继续

---
# Filled Example

## 适用阶段
初始化/需求澄清阶段

## 执行模式
- **类型**: Interactive-Clarify
- **提问工具**: AskUserQuestion
- **每轮最大问题数**: 1

## 追问维度（按优先级）
1. **Role** — Agent 的角色定位和职责范围
2. **I/O** — 输入文件、输出文件、数据格式
3. **Workflow** — 任务步骤、执行顺序、依赖关系
4. **Knowledge** — 知识来源、参考文档、检索需求
5. **Constraints** — 安全约束、性能要求、禁止操作

## 提问原则
- 每次聚焦1个缺失维度，不一次性抛出所有问题
- 给出2-4个建议选项，降低用户回答成本
- 不重复已明确的内容
- 问题必须具体、可回答，避免开放式模糊提问

## 追问终止条件
- 所有维度均已明确
- 用户明确表示"不再补充"
- 追问3轮后仍有缺失 → 标注[未明确]并基于默认假设继续
