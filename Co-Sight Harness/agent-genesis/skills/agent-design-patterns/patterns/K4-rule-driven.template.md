---
pattern_id: K4
pattern_name: Rule-Driven
category: knowledge
sub_dimension: knowledge_sources
selection_rule: "多选。至少选一个知识来源。"
solves: "Agent行为受外部业务规则文件约束——命名标准、判断阈值、分类标准等"
fills_spec_section: Knowledge Contract

variables:
  - name: RULE_FILES
    description: "业务规则文件路径列表，每项包含路径、描述和优先级"
    type: list
    source: user_input
    required: true
  - name: RULE_PRIORITY_ORDER
    description: "规则间的优先级顺序说明（如：命名标准 > 分类标准 > 格式约定）"
    type: string
    source: user_input
    required: true
  - name: UNDEFINED_BEHAVIOR_ACTION
    description: "遇到规则文件未定义的行为时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "阻断并告知用户：该行为在规则文件中未定义，无法判定"
  - name: RULE_VIOLATION_ACTION
    description: "违反规则时的处理方式"
    type: string
    source: llm_generate
    required: false
    default: "阻断并引用具体规则条目，告知用户违反了什么规则"

constraints:
  - "违反规则时必须阻断并引用具体规则条目"
  - "规则文件中未定义的行为 → 阻断并告知用户"
---

# Knowledge Contract

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 |
|---------|------|---------|:---:|
{{#each RULE_FILES}}
| 业务规则 | `{{this.path}}` | 启动时加载，执行中引用 | ✅ |
{{/each}}

## 规则优先级
{{RULE_PRIORITY_ORDER}}

## 规则文件清单
{{#each RULE_FILES}}
### {{this.path}}
- **用途**：{{this.description}}
- **优先级**：{{this.priority}}
{{/each}}

## 违规处理
- 违反已定义规则 → {{RULE_VIOLATION_ACTION}}
- 规则文件未定义的行为 → {{UNDEFINED_BEHAVIOR_ACTION}}

---
# Filled Example

## 知识依赖总览

| 知识类型 | 来源 | 获取方式 | 是否必须 |
|---------|------|---------|:---:|
| 业务规则 | `data/standard_scenarios.csv` | 启动时加载，执行中引用 | ✅ |
| 业务规则 | `data/naming_conventions.yaml` | 启动时加载，执行中引用 | ✅ |

## 规则优先级
1. 命名标准(naming_conventions.yaml) — 最高优先级
2. 标准场景表(standard_scenarios.csv) — 中等优先级

## 规则文件清单
### data/standard_scenarios.csv
- **用途**：定义所有合法场景名称及其属性，任何场景名必须来源于此表
- **优先级**：2

### data/naming_conventions.yaml
- **用途**：定义输出文件的命名规范，所有生成的文件名必须符合此规范
- **优先级**：1

## 违规处理
- 违反已定义规则 → 阻断并引用具体规则条目，告知用户违反了什么规则
- 规则文件未定义的行为 → 阻断并告知用户：该行为在规则文件中未定义，无法判定
