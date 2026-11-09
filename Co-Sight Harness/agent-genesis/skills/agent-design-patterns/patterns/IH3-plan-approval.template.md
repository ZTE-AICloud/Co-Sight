---
pattern_id: IH3
pattern_name: Plan-Approval
category: interaction
sub_dimension: human_interaction
selection_rule: "可按执行阶段混合使用。与IH1/IH2可共存(不同阶段)。"
solves: "执行方案需要用户预先确认，避免方向性错误"
fills_spec_section: Interaction Rules

variables:
  - name: APPROVAL_NODES
    description: "需要用户审批的关键决策节点列表——每项包含节点名和触发时机"
    type: list
    source: user_input
    required: true
  - name: PLAN_DISPLAY_CONTENT
    description: "审批时展示给用户的内容——执行计划概要+关键决策点+风险提示"
    type: string
    source: llm_generate
    required: false
    default: "展示：执行计划概要 + 关键决策点 + 风险提示 + 预计耗时"
  - name: USER_OPTIONS
    description: "用户可选的审批操作列表"
    type: list
    source: user_input
    required: false

constraints:
  - "关键决策点必须声明用户审批"
  - "审批未通过前禁止执行后续步骤"
---

# 交互规则

## 审批节点

| 节点 | 触发时机 | 展示内容 | 用户操作 |
|------|---------|---------|---------|
{{#each APPROVAL_NODES}}
| {{this.name}} | {{this.trigger}} | {{this.display}} | {{this.options}} |
{{/each}}

## 审批展示格式
{{PLAN_DISPLAY_CONTENT}}

## 用户可选操作
{{#if USER_OPTIONS}}
{{#each USER_OPTIONS}}
- {{this}}
{{/each}}
{{else}}
- ✅ 确认执行 — 按计划继续
- ✏️ 修改方案 — 提供修改意见，重新生成计划
- ❌ 取消 — 终止当前执行
{{/if}}

## 审批约束
- **审批未通过前，禁止执行该节点之后的任何步骤**
- 用户超时未响应 → 暂停等待，不默认执行
- 审批驳回后，修改方案必须重新提交审批

---
# Filled Example

## 审批节点

| 节点 | 触发时机 | 展示内容 | 用户操作 |
|------|---------|---------|---------|
| 执行计划确认 | 需求澄清完成后，生成执行计划时 | 执行计划概要、关键决策点、风险提示 | 确认/修改/取消 |
| 分析结果确认 | 全部 SubAgent 执行完成，汇总分析结果后 | 分析结果摘要、异常发现、待验证项 | 确认/补充/驳回 |
| 最终报告确认 | 最终报告生成后 | 报告预览、关键结论、待验证项清单 | 确认/修改/取消 |

## 审批展示格式
展示：执行计划概要 + 关键决策点 + 风险提示 + 预计耗时

## 用户可选操作
- ✅ 确认执行 — 按计划继续
- ✏️ 修改方案 — 提供修改意见，重新生成计划
- ❌ 取消 — 终止当前执行

## 审批约束
- **审批未通过前，禁止执行该节点之后的任何步骤**
- 用户超时未响应 → 暂停等待，不默认执行
- 审批驳回后，修改方案必须重新提交审批
