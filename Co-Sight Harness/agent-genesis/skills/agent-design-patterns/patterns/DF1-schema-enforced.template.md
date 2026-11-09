---
pattern_id: DF1
pattern_name: Schema-Enforced
category: data
sub_dimension: format
selection_rule: "可选。叠加到任意数据拓扑(DT1/DT2)之上。"
solves: "数据格式要求严格，每步输入输出必须通过JSON Schema校验"
fills_spec_section: Data Flow (数据校验规则)

variables:
  - name: ENTITIES_WITH_SCHEMA
    description: "需要Schema校验的数据实体列表，每项包含实体名和Schema文件路径"
    type: list
    source: user_input
    required: true
  - name: SCHEMA_VALIDATION_TIMING
    description: "Schema校验的执行时机——每步执行前/后/两者都校验"
    type: string
    source: user_input
    required: true
    default: "每步执行前校验上游输入Schema，每步执行后校验本步输出Schema"
  - name: SCHEMA_FAIL_ACTION
    description: "Schema校验失败时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "阻断执行，输出差异报告（指出哪个字段不符合Schema中的哪条规则）"

constraints:
  - "每步输出必须符合对应的JSON Schema定义"
  - "Schema校验失败 → 阻断并输出差异报告"
---

# Data Flow — 数据校验规则

## Schema 校验约束
- **校验时机**：{{SCHEMA_VALIDATION_TIMING}}
- **校验失败处理**：{{SCHEMA_FAIL_ACTION}}

## Schema 文件清单

| 数据实体 | Schema 文件 | 校验时机 |
|---------|------------|:---:|
{{#each ENTITIES_WITH_SCHEMA}}
| {{this.name}} | `{{this.schema_path}}` | {{this.timing}} |
{{/each}}

## Schema 校验流程
1. 数据产出方生成输出文件
2. 立即对输出文件执行 Schema 校验
3. 校验通过 → 标记为就绪，下游可消费
4. 校验失败 → {{SCHEMA_FAIL_ACTION}}

## Schema 文件要求
- 每个 Schema 文件必须声明 `required` 字段列表
- 每个字段必须声明 `type` 和 `description`
- 枚举字段必须声明 `enum` 允许值列表

---
# Filled Example

## Schema 校验约束
- **校验时机**：每步执行前校验上游输入Schema，每步执行后校验本步输出Schema
- **校验失败处理**：阻断执行，输出差异报告（指出哪个字段不符合Schema中的哪条规则）

## Schema 文件清单

| 数据实体 | Schema 文件 | 校验时机 |
|---------|------------|:---:|
| 需求澄清记录 | `schemas/clarification.schema.json` | 产出时 |
| 执行计划 | `schemas/plan.schema.json` | 产出时 + 消费前 |
| 分析结果汇总 | `schemas/analysis_result.schema.json` | 产出时 |

## Schema 校验流程
1. 数据产出方生成输出文件
2. 立即对输出文件执行 Schema 校验
3. 校验通过 → 标记为就绪，下游可消费
4. 校验失败 → 阻断执行，输出差异报告（指出哪个字段不符合Schema中的哪条规则）

## Schema 文件要求
- 每个 Schema 文件必须声明 `required` 字段列表
- 每个字段必须声明 `type` 和 `description`
- 枚举字段必须声明 `enum` 允许值列表
