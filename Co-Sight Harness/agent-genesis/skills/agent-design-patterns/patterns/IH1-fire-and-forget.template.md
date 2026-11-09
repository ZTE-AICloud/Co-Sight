---
pattern_id: IH1
pattern_name: Fire-and-Forget
category: interaction
sub_dimension: human_interaction
selection_rule: "可按执行阶段混合使用。与IH2/IH3可共存(不同阶段)。"
solves: "输入完整，执行过程不需要中断对话"
fills_spec_section: Interaction Rules

variables:
  - name: INTERRUPT_CONDITIONS
    description: "允许中断执行的条件列表（仅在这些条件触发时才可中断）"
    type: list
    source: user_input
    required: true
  - name: APPLICABLE_PHASES
    description: "此交互模式适用的执行阶段列表（如：Phase 2 SubAgent执行阶段）"
    type: list
    source: user_input
    required: true

constraints:
  - "仅在输入缺失/校验失败等硬错误时中断"
  - "禁止在Fire-and-Forget阶段主动发起对话"
---

# 交互规则

## 适用阶段
{{#each APPLICABLE_PHASES}}
- {{this}}
{{/each}}

## 执行模式
- **类型**: Fire-and-Forget
- **行为**: 读取输入 → 执行全部步骤 → 输出结果。执行过程中不暂停等待用户反馈。
- **中断条件**：仅在以下条件触发时中断执行：
{{#each INTERRUPT_CONDITIONS}}
  - {{this}}
{{/each}}

## 禁止行为
- **禁止**在执行过程中主动向用户发起确认或追问
- **禁止**在无硬错误的条件下暂停等待用户

---
# Filled Example

## 适用阶段
- SubAgent 执行阶段（每个 SubAgent 内部）
- 格式校验阶段
- 最终报告生成阶段

## 执行模式
- **类型**: Fire-and-Forget
- **行为**: 读取输入 → 执行全部步骤 → 输出结果。执行过程中不暂停等待用户反馈。
- **中断条件**：仅在以下条件触发时中断执行：
  - 输入文件缺失或无法读取
  - Schema 校验失败（格式硬错误）
  - 工具/Skill 调用返回致命错误
  - 知识库检索返回空且无替代来源

## 禁止行为
- **禁止**在执行过程中主动向用户发起确认或追问
- **禁止**在无硬错误的条件下暂停等待用户
