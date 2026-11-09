---
pattern_id: E1
pattern_name: Self-Evaluation
category: evolution
sub_dimension: self_evaluation
selection_rule: "可选。自进化模式链的第一步。E2 依赖 E1，E3 依赖 E2+E1。不可跳跃选择。"
solves: "Agent 执行完成后自动评估输出质量，识别改进空间和退化风险"
fills_spec_section: Evolution Contract

variables:
  - name: EVAL_DIMENSIONS
    description: "自评维度列表（复用 Phase 5 4维框架）"
    type: list
    source: decision_table
    required: true
    schema:
      - field: dimension
        type: string
        enum: ["correctness", "completeness", "format_compliance", "actionability"]
      - field: weight
        type: number
        description: "维度权重（总和=1.0）"
      - field: threshold
        type: number
        description: "该维度的最低通过分数（1-5）"
  - name: EVAL_TRIGGER
    description: "自评触发时机"
    type: string
    source: user_input
    required: true
    enum: ["every_execution", "scheduled", "on_demand"]
  - name: PASS_THRESHOLD
    description: "加权总分通过阈值"
    type: number
    source: decision_table
    default: 3.5
  - name: SELF_EVAL_REPORT_PATH
    description: "自评报告输出路径"
    type: string
    source: derived
    default: "work/_self/self-eval-report.md"

constraints:
  - "评分必须基于客观 checkpoints（非纯主观判断）"
  - "低分（<3.0）必须附具体证据和改进方向"
  - "自评报告不可覆盖或删除（累积历史记录）"
  - "评分维度与 Phase 5 外部评估一致，确保内外评估可比对"
---

# Evolution Contract — Self-Evaluation

## 自评框架

**触发时机**: {{EVAL_TRIGGER}}
**通过阈值**: 加权总分 ≥ {{PASS_THRESHOLD}}，且 correctness ≥ 3.0，completeness ≥ 3.0

## 评分维度

| 维度 | 权重 | 最低阈值 | 评估方法 |
|------|:---:|:---:|------|
{{#each EVAL_DIMENSIONS}}
| {{this.dimension}} | {{this.weight}} | {{this.threshold}} | 对照 expected_output checklist 逐项检查，证据必须来自原始输出 |
{{/each}}

## 自评输出

每次执行完成后输出 `{{SELF_EVAL_REPORT_PATH}}`：

```yaml
self_eval:
  timestamp: "ISO 8601"
  execution_id: "唯一执行标识"
  scores:
    correctness: {score: N, evidence: "..."}
    completeness: {score: N, evidence: "..."}
    format_compliance: {score: N, evidence: "..."}
    actionability: {score: N, evidence: "..."}
  weighted_total: N.N
  verdict: PASS | FAIL
  gap_analysis:
    - dimension: "低分维度名"
      gap: "具体差距描述"
      probable_cause: "可能原因"
      suggested_fix: "建议修正方向"
```

## 与 Phase 5 的关系

- E1（内部自评）与 Phase 5（工厂外部评估）使用相同的 4 维评分框架
- 触发时机不同：E1 是 Agent 每次执行后自评，Phase 5 是工厂生成后评估
- E1 FAIL 触发 E2 受控进化，Phase 5 FAIL 触发 REVISE

---
# Filled Example

## 自评框架

**触发时机**: every_execution
**通过阈值**: 加权总分 ≥ 3.5，且 correctness ≥ 3.0，completeness ≥ 3.0

## 评分维度

| 维度 | 权重 | 最低阈值 | 评估方法 |
|------|:---:|:---:|------|
| correctness | 0.40 | 3.0 | 对照检查清单逐项验证检测结果准确性 |
| completeness | 0.30 | 3.0 | 验证所有要求项是否全部覆盖 |
| format_compliance | 0.15 | 2.0 | 验证输出格式是否含必需字段 |
| actionability | 0.15 | 2.0 | 验证修复建议是否可直接执行 |

## 自评输出（示例）

```yaml
self_eval:
  timestamp: "2026-05-07T15:30:00+08:00"
  execution_id: "exec-20260507-001"
  scores:
    correctness: {score: 4, evidence: "6/6 要求项正确检测，1 误报(E226由LLM判断非工具输出)"}
    completeness: {score: 5, evidence: "6/6 要求项全部覆盖，含额外修复建议"}
    format_compliance: {score: 5, evidence: "违规明细表+统计+修复建议+Summary 四段完整"}
    actionability: {score: 5, evidence: "每条修复建议含 before/after 代码对比"}
  weighted_total: 4.6
  verdict: PASS
  gap_analysis: []
```
