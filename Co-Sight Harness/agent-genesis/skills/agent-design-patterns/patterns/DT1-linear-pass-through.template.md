---
pattern_id: DT1
pattern_name: Linear-Pass-Through
category: data
sub_dimension: topology
selection_rule: "可混合使用。与DT2可共存。"
solves: "数据在步骤间逐级传递，每一步的输出是下一步的输入"
fills_spec_section: Data Flow

variables:
  - name: DATA_ENTITIES
    description: "数据实体列表，每项包含：名称、概述、Schema文件路径、产生步骤、消费步骤"
    type: list
    source: user_input
    required: true
  - name: INPUT_FILES
    description: "Agent 的外部输入文件列表（数据流起点）"
    type: list
    source: user_input
    required: true
  - name: FINAL_OUTPUT
    description: "Agent 的最终输出文件或数据实体"
    type: string
    source: user_input
    required: true
  - name: SCHEMA_DIR
    description: "Schema 文件存放目录"
    type: string
    source: llm_generate
    required: false
    default: "schemas/"

constraints:
  - "每个中间产物必须同时有生产者和消费者（流转闭合）"
  - "实体名在流转图中必须唯一"
---

# Data Flow

## 数据实体

| 实体名称 | 概述 | Schema | 产生步骤 | 消费步骤 |
|---------|------|--------|---------|---------|
{{#each DATA_ENTITIES}}
| {{this.name}} | {{this.description}} | `{{SCHEMA_DIR}}{{this.name}}.schema.json` | {{this.producer}} | {{this.consumer}} |
{{/each}}

## 数据流转图
```
{{#each INPUT_FILES}}{{this}} {{/each}}
  → 
{{#each DATA_ENTITIES}}
  {{this.producer}} → [{{this.name}}] → {{this.consumer}}
{{/each}}
  → [{{FINAL_OUTPUT}}]
```

## 流转闭合校验
- 每个中间产物必须有明确的**生产者**（产生步骤）和**消费者**（消费步骤）
- 无消费者的产物 → 标记为[最终输出]
- 无生产者的输入 → 标记为[外部输入]

---
# Filled Example

## 数据实体

| 实体名称 | 概述 | Schema | 产生步骤 | 消费步骤 |
|---------|------|--------|---------|---------|
| 需求澄清记录 | 澄清后的需求文档 | `schemas/clarification.schema.json` | Step 1: 需求澄清 | Step 2: 任务规划 |
| 执行计划 | 结构化任务清单 | `schemas/plan.schema.json` | Step 2: 任务规划 | Step 3: 分析执行 |
| 分析结果汇总 | SubAgent输出汇总 | `schemas/analysis_result.schema.json` | Step 3: 分析执行 | Step 4: 结果汇总 |

## 数据流转图
```
市场需求.md 算法思路.md
  →
  Step 1: 需求澄清 → [需求澄清记录.md] → Step 2: 任务规划 → [执行计划.json] → Step 3: 分析执行 → [分析结果汇总.md] → Step 4: 结果汇总
  → [最终分析报告.md]
```

## 流转闭合校验
- 每个中间产物必须有明确的**生产者**和**消费者**
- [最终分析报告.md] 标记为最终输出
- [市场需求.md, 算法思路.md] 标记为外部输入
