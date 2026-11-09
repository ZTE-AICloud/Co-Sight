---
pattern_id: IT1
pattern_name: Tool-Orchestrated
category: interaction
sub_dimension: tool_strategy
selection_rule: "3选1。Enforced / Optional / Forbidden 互斥。"
solves: "定义Agent使用外部工具/Skill的策略——强制、可选或禁止"
fills_spec_section: Interaction Rules (工具策略)

variables:
  - name: STRENGTH_LEVEL
    description: "强度级别——Enforced(强制使用)、Optional(可选使用)、Forbidden(禁止使用外部工具)"
    type: string
    source: user_input
    required: true
    enum: ["Enforced", "Optional", "Forbidden"]
  - name: SKILL_DEPENDENCIES
    description: "依赖的 Skill 清单（仅在 Enforced 或 Optional 时填写），每项包含名称和用途"
    type: list
    source: user_input
    required: false
  - name: ENFORCED_DOMAINS
    description: "强制使用工具的领域列表（仅在 Enforced 时填写）——这些领域严禁用LLM内嵌知识替代"
    type: list
    source: user_input
    required: false
  - name: SKILL_FAIL_ACTION
    description: "Skill调用失败时的处理方式（仅在 Enforced 时必填）"
    type: string
    source: llm_generate
    required: false
    default: "阻断执行，禁止模拟Skill调用成功。输出Skill错误信息，等待用户介入"

constraints:
  - "Enforced: 严禁不使用Skill而用LLM替代"
  - "Enforced: Skill失败时必须阻断，禁止模拟成功"
---

# 交互规则 — 工具策略

## 强度级别：{{STRENGTH_LEVEL}}

{{#if (eq STRENGTH_LEVEL "Enforced")}}
## 强制约束
以下领域的分析**必须**通过外部工具/Skill完成，**严禁**使用LLM内嵌知识替代：

{{#each ENFORCED_DOMAINS}}
- **{{this.domain}}**：必须调用 `{{this.skill_or_tool}}` — {{this.reason}}
{{/each}}

## Skill 依赖表

| Skill 名称 | 用途 | 调用时机 | 失败处理 |
|-----------|------|---------|---------|
{{#each SKILL_DEPENDENCIES}}
| {{this.name}} | {{this.purpose}} | {{this.trigger}} | {{SKILL_FAIL_ACTION}} |
{{/each}}

## 禁止行为
- **严禁**不使用 Skill 而用 LLM 内嵌知识替代上述领域的分析
- **严禁**模拟 Skill 调用成功（Skill 失败时必须阻断）
- 每次 Skill 调用后必须校验返回结果的完整性

{{else if (eq STRENGTH_LEVEL "Optional")}}
## 可选工具
以下 Skill 可用作辅助，非强制：

{{#each SKILL_DEPENDENCIES}}
| {{this.name}} | {{this.purpose}} | {{this.trigger}} |
{{/each}}

Agent 可自行判断是否需要调用 Skill，也可直接使用 LLM 能力完成。

{{else if (eq STRENGTH_LEVEL "Forbidden")}}
## 工具禁止
- **禁止**调用任何外部工具或 Skill
- **纯推理模式**：仅使用 LLM 内嵌知识和上下文信息完成分析
- 如任务超出 LLM 能力范围 → 阻断并告知用户，说明需要外部工具支持
{{/if}}

---
# Filled Example (Enforced)

## 强度级别：Enforced

## 强制约束
以下领域的分析**必须**通过外部工具/Skill完成，**严禁**使用LLM内嵌知识替代：

- **协议分析**：必须调用 `Skill-ProtocolAnalyst` — 协议细节不属于LLM训练数据，必须从3GPP文档检索
- **场景名标准化**：必须调用 `Skill-NameStandardizer` — 场景名必须来源于标准场景表，不可自创
- **接口一致性校验**：必须调用 `Skill-InterfaceValidator` — 接口定义需与规范对比，不可凭记忆

## Skill 依赖表

| Skill 名称 | 用途 | 调用时机 | 失败处理 |
|-----------|------|---------|---------|
| Skill-ProtocolAnalyst | 3GPP协议分析 | 每个协议相关分析阶段 | 阻断执行，禁止模拟成功。输出错误信息，等待用户介入 |
| Skill-NameStandardizer | 场景名标准化 | 产生场景名的每个步骤后 | 阻断执行，禁止模拟成功。输出错误信息，等待用户介入 |
| Skill-InterfaceValidator | 接口一致性校验 | 分析完成后、报告生成前 | 阻断执行，禁止模拟成功。输出错误信息，等待用户介入 |

## 禁止行为
- **严禁**不使用 Skill 而用 LLM 内嵌知识替代协议/场景名/接口分析
- **严禁**模拟 Skill 调用成功（Skill 失败时必须阻断）
- 每次 Skill 调用后必须校验返回结果的完整性
