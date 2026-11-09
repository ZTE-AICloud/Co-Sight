---
pattern_id: W1
pattern_name: Pipeline
category: workflow
sub_dimension: decomposition
selection_rule: "4选1互斥。顶层只能选一种。子结构可嵌套另一种(最大深度2层)。"
solves: "任务可分解为固定、有序的步骤序列，每步职责单一且不可跳过"
fills_spec_section: Execution Workflow

variables:
  - name: STEP_NAMES
    description: "步骤名称列表，从用户需求中提取的步骤划分"
    type: list
    source: user_input
    required: true
  - name: input_files
    description: "Step 1 需要的输入文件列表"
    type: list
    source: user_input
    required: true
  - name: step_1_core_action
    description: "Step 1 的核心动作——做什么、怎么做"
    type: markdown
    source: user_input
    required: true
  - name: step_1_output
    description: "Step 1 的输出文件路径或数据实体名"
    type: string
    source: user_input
    required: true
  - name: STEP_N_ACTIONS
    description: "后续步骤的核心动作列表（与 STEP_NAMES 一一对应）"
    type: list
    source: user_input
    required: true
  - name: STEP_N_OUTPUTS
    description: "每个步骤的输出文件路径或数据实体名"
    type: list
    source: user_input
    required: true
    note: "每个步骤的输出将成为下一步的输入(除非是最后一步)"
  - name: final_output
    description: "最后一个步骤的最终输出"
    type: string
    source: derived
    derive_from: "取 STEP_N_OUTPUTS 的最后一项"
    required: true

constraints:
  - "步骤间必须声明输入/输出依赖"
  - "禁止跳过步骤或回退（除非配合SM1-FSM）"
  - "每步结束前验证输出完整性"
---

# Execution Workflow

## 执行约束
- **严格按以下步骤顺序执行，禁止跳过、合并或并行**
- **每步完成后必须校验输出完整性**
- **上一步的输出文件是下一步的输入前提，不可跳过**

## Step 1: {{STEP_NAMES[0]}}
1. 校验输入文件存在性：[{{input_files}}]
2. {{STEP_1_ACTIONS[0]}}
3. 输出：[{{STEP_1_OUTPUTS[0]}}]

## Step 2: {{STEP_NAMES[1]}}
1. 读取上一步输出：[{{STEP_1_OUTPUTS[0]}}]
2. {{STEP_2_ACTIONS[1]}}
3. 输出：[{{STEP_2_OUTPUTS[1]}}]

<!-- 更多步骤按相同模式追加 -->
{{#each remaining_steps}}
## Step {{@index+3}}: {{this.name}}
1. 读取上一步输出：[{{previous_output}}]
2. {{this.action}}
3. 输出：[{{this.output}}]
{{/each}}

---
# Filled Example

## 执行约束
- **严格按以下步骤顺序执行，禁止跳过、合并或并行**
- **每步完成后必须校验输出完整性**

## Step 1: 需求澄清
1. 校验输入文件存在性：[市场需求.md, 算法思路.md]
2. 分析用户需求中的模糊点，逐维度追问澄清（Role/I/O/Workflow/Knowledge/Constraints）
3. 输出：[需求澄清记录.md]

## Step 2: 任务规划
1. 读取上一步输出：[需求澄清记录.md]
2. 基于澄清后的需求，生成SubAgent清单和执行计划
3. 输出：[执行计划.json]

## Step 3: 分析执行
1. 读取上一步输出：[执行计划.json]
2. 按计划串行调用各SubAgent执行分析
3. 输出：[分析结果汇总.md]

## Step 4: 结果汇总
1. 读取上一步输出：[分析结果汇总.md]
2. 汇总全部SubAgent输出，生成最终分析报告
3. 输出：[最终分析报告.md]
