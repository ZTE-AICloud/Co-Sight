---
pattern_id: SM1
pattern_name: FSM (Finite State Machine)
category: workflow
sub_dimension: state_management
selection_rule: "可选。可叠加到W1-W4任意分解模式之上。推荐搭配DT1+DF1。"
solves: "执行路径不固定，中间结果可能触发不同后续步骤；失败需回溯到之前状态重试"
fills_spec_section: Execution Workflow (状态管理子章节)

variables:
  - name: STATES
    description: "状态节点列表，每项包含：状态名、说明、进入条件、挂载工具。必须包含初始状态和终止状态(FAILED)"
    type: list
    source: user_input
    required: true
  - name: TRANSITIONS
    description: "状态转换表，每项包含：当前状态、下一状态、转换条件（必须可客观判定）、失败回溯目标状态"
    type: list
    source: user_input
    required: true
  - name: MAX_TRACEBACK_DEPTH
    description: "最大回溯深度（整数），防止无限回溯"
    type: string
    source: user_input
    required: true
    default: "3"
  - name: RETAIN_ARTIFACTS
    description: "回溯时保留的中间产物列表（其他产物丢弃）"
    type: list
    source: user_input
    required: true
  - name: DISCARD_ARTIFACTS
    description: "回溯时丢弃的中间产物列表"
    type: list
    source: user_input
    required: false
  - name: STATE_FILE
    description: "持久化当前状态的文件路径，用于断点恢复"
    type: string
    source: llm_generate
    required: false
    default: "fsm_state.json"

constraints:
  - "每个状态必须声明明确的进入/退出条件"
  - "回溯深度必须有限"
  - "回溯时声明哪些中间产物保留、哪些丢弃"
---

# FSM 状态机定义

## 状态管理约束
- **每个状态的进入/退出条件必须可客观判定**
- **最大回溯深度：{{MAX_TRACEBACK_DEPTH}}**
- **当前状态持久化至 [{{STATE_FILE}}]，支持断点恢复**

## 状态节点

| 状态 | 说明 | 进入条件 | 挂载工具/Skill |
|------|------|---------|---------------|
{{#each STATES}}
| {{this.name}} | {{this.description}} | {{this.entry_condition}} | {{this.tools}} |
{{/each}}
| FAILED | 终止状态 | 回溯次数超限(>{{MAX_TRACEBACK_DEPTH}}) | - |

## 状态转换

| 当前状态 | 下一状态 | 转换条件 | 失败回溯目标 |
|---------|---------|---------|------------|
{{#each TRANSITIONS}}
| {{this.from}} | {{this.to}} | {{this.condition}} | {{this.on_failure_goto}} |
{{/each}}

## 回溯规则
- 最大回溯深度：{{MAX_TRACEBACK_DEPTH}}
- 回溯时保留：[{{RETAIN_ARTIFACTS}}]
- 回溯时丢弃：[{{DISCARD_ARTIFACTS}}]
- 回溯计数器持久化至 [{{STATE_FILE}}]

---
# Filled Example

## 状态节点

| 状态 | 说明 | 进入条件 | 挂载工具/Skill |
|------|------|---------|---------------|
| IDLE | 等待输入 | 初始状态 / 用户触发 | - |
| ANALYZING | 分析输入需求 | 收到有效输入 | SubAgent-Analyst |
| REVIEWING | 审查分析结果 | ANALYZING产出完整 | ReviewAgent-QA |
| APPROVED | 审查通过 | REVIEWING结果为PASS | - |
| FAILED | 终止状态 | 回溯次数超限(>3) | - |

## 状态转换

| 当前状态 | 下一状态 | 转换条件 | 失败回溯目标 |
|---------|---------|---------|------------|
| IDLE | ANALYZING | 输入校验通过 | IDLE |
| ANALYZING | REVIEWING | 分析结果产出完整 | ANALYZING(重试) |
| REVIEWING | APPROVED | 审查PASS | ANALYZING(修正重分析) |
| APPROVED | IDLE | 用户确认接收 | IDLE |

## 回溯规则
- 最大回溯深度：3
- 回溯时保留：[需求澄清记录.md, 标准场景表.md]
- 回溯时丢弃：[当次分析结果.md]
- 回溯计数器持久化至 [fsm_state.json]
