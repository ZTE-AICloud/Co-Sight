---
pattern_id: W2
pattern_name: Router
category: workflow
sub_dimension: decomposition
selection_rule: "4选1互斥。顶层只能选一种。子结构可嵌套另一种(最大深度2层)。"
solves: "不同输入类型需要不同的处理路径，需在入口处判断分流"
fills_spec_section: Execution Workflow

variables:
  - name: ROUTE_KEY
    description: "路由判断的依据字段或特征名（如：输入类型、任务类别、用户意图）"
    type: string
    source: user_input
    required: true
  - name: ROUTE_VALUES
    description: "路由键的所有可能取值列表，每个值对应一条分支路径（如：[feature, bugfix, refactor]）"
    type: list
    source: user_input
    required: true
  - name: BRANCH_DESCRIPTIONS
    description: "每条分支路径的简要描述，与ROUTE_VALUES一一对应"
    type: list
    source: user_input
    required: true
  - name: BRANCH_STEPS
    description: "每条分支路径的核心步骤序列（嵌套列表，每个分支一个步骤列表）"
    type: list
    source: user_input
    required: true
  - name: BRANCH_OUTPUTS
    description: "每条分支路径的最终输出，与ROUTE_VALUES一一对应"
    type: list
    source: user_input
    required: true
  - name: DEFAULT_BRANCH
    description: "无法匹配任何路由键时的兜底处理方式（无匹配路径时建议阻断并告知用户）"
    type: string
    source: llm_generate
    required: false
    default: "阻断并告知用户：无法匹配任何已知路径，请提供明确输入"

constraints:
  - "路由键必须可客观判定（不得依赖LLM主观判断）"
  - "所有路径必须覆盖（含默认/兜底路径）"
  - "路由失败时必须阻断而非猜测"
---

# Execution Workflow

## 执行约束
- **路由键必须在执行前可客观判定，禁止模糊匹配或LLM主观猜测**
- **所有分支路径必须覆盖，含兜底路径**
- **路由失败时阻断执行并告知用户**

## Step 1: 路由判断
1. 分析输入特征，提取路由键：[{{ROUTE_KEY}}]
2. 根据 `{{ROUTE_KEY}}` 的值决定执行路径：
{{#each ROUTE_VALUES}}
   - 若 `{{ROUTE_KEY}}` = `{{this}}` → 执行 Path {{@index+1}}（{{BRANCH_DESCRIPTIONS[@index]}}）
{{/each}}
   - 若 `{{ROUTE_KEY}}` 无法匹配任何已知值 → {{DEFAULT_BRANCH}}

{{#each ROUTE_VALUES}}
## Path {{@index+1}}: {{BRANCH_DESCRIPTIONS[@index]}}
{{#each BRANCH_STEPS[@index]}}
### Step {{@index+1}}-{{../@index+1}}.{{@index+1}}: {{this.name}}
1. {{this.action}}
2. 输出：[{{this.output}}]
{{/each}}

**Path {{@index+1}} 最终输出**: [{{BRANCH_OUTPUTS[@index]}}]
{{/each}}

---
# Filled Example

## 执行约束
- **路由键必须在执行前可客观判定，禁止模糊匹配或LLM主观猜测**

## Step 1: 路由判断
1. 分析输入特征，提取路由键：[任务类型]
2. 根据 `任务类型` 的值决定执行路径：
   - 若 `任务类型` = `feature` → 执行 Path 1（新功能开发流程）
   - 若 `任务类型` = `bugfix` → 执行 Path 2（缺陷修复流程）
   - 若 `任务类型` 无法匹配任何已知值 → 阻断并告知用户：请明确任务类型（feature/bugfix）

## Path 1: 新功能开发流程
### Step 1.1: 需求分析
1. 分析功能需求，拆解为子任务
2. 输出：[需求分析报告.md]
### Step 1.2: 实现
1. 按子任务清单逐项实现
2. 输出：[实现代码 + 测试报告.md]

**Path 1 最终输出**: [功能交付包]

## Path 2: 缺陷修复流程
### Step 2.1: 根因分析
1. 复现缺陷，定位根因
2. 输出：[根因分析报告.md]
### Step 2.2: 修复与验证
1. 实施修复，运行回归测试
2. 输出：[修复补丁 + 验证报告.md]

**Path 2 最终输出**: [修复交付包]
