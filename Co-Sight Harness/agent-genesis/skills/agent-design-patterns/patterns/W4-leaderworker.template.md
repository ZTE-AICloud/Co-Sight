---
pattern_id: W4
pattern_name: Leader-Worker
category: workflow
sub_dimension: decomposition
selection_rule: "4选1互斥。顶层只能选一种。子结构可嵌套另一种(最大深度2层)。"
solves: "任务在运行时才知道如何拆解，需要Leader先分析再动态派生Worker"
fills_spec_section: Execution Workflow

variables:
  - name: LEADER_INPUT
    description: "Leader Agent 的输入文件列表"
    type: list
    source: user_input
    required: true
  - name: LEADER_ANALYSIS_TASK
    description: "Leader 的分析任务描述——如何分析输入并决定拆解策略"
    type: markdown
    source: user_input
    required: true
  - name: WORKER_TEMPLATE
    description: "Worker Agent 的模板/类型名，Leader 从此模板实例化每个 Worker"
    type: string
    source: user_input
    required: true
  - name: MAX_WORKERS
    description: "最大 Worker 数量上限"
    type: string
    source: user_input
    required: true
    default: "5"
  - name: MAX_DEPTH
    description: "最大递归派生深度（Leader 派生的 Worker 是否还能再派生 SubWorker）"
    type: string
    source: user_input
    required: true
    default: "1"
  - name: AGGREGATE_OUTPUT
    description: "Leader 汇总所有 Worker 输出后的最终输出"
    type: string
    source: user_input
    required: true
  - name: WORKER_VALIDATION
    description: "Leader 如何校验每个 Worker 的输出完整性"
    type: string
    source: llm_generate
    required: false
    default: "逐一检查每个 Worker 输出文件存在、非空、格式符合预期"

constraints:
  - "Worker必须基于模板实例化（不可从零创建）"
  - "必须限制最大派生深度防止无限递归"
  - "Leader必须对所有Worker输出做完整性校验"
---

# Execution Workflow

## 执行约束
- **Worker 必须从模板 [{{WORKER_TEMPLATE}}] 实例化，禁止从零创建**
- **最大 Worker 数：{{MAX_WORKERS}}，最大递归深度：{{MAX_DEPTH}}**
- **Leader 负责校验所有 Worker 输出，不完整则阻断**

## Step 1: Leader 分析
1. 读取输入：[{{LEADER_INPUT}}]
2. {{LEADER_ANALYSIS_TASK}}
3. 生成 Worker 清单：
   | Worker ID | 任务描述 | 输入数据 | 预期输出 |
   |-----------|---------|---------|---------|
   | W1 | ... | ... | ... |
4. 输出 Worker 派发计划：[worker_dispatch_plan.yaml]

## Step 2: Worker 动态派生与执行
对每个 Worker：
1. 从模板 `{{WORKER_TEMPLATE}}` 实例化 SubAgent
2. 创建独立 worktree
3. 下发任务描述 + 输入数据
4. 执行完毕后收集输出
5. Leader 校验输出：{{WORKER_VALIDATION}}

**约束**: 最大 Worker 数不超过 {{MAX_WORKERS}}，Worker 不可再派生 SubWorker（递归深度上限={{MAX_DEPTH}}）

## Step 3: 结果聚合
1. 收集所有 Worker 输出
2. 汇总、去重、冲突检测、一致性校验
3. 输出汇总结果：[{{AGGREGATE_OUTPUT}}]

---
# Filled Example

## 执行约束
- **Worker 必须从模板 [SubAgent-CodeAnalyst] 实例化，禁止从零创建**
- **最大 Worker 数：5，最大递归深度：1**

## Step 1: Leader 分析
1. 读取输入：[大型代码仓库/]
2. 分析代码仓库结构，按模块边界将代码库拆分为独立分析单元。每个模块生成一个 Worker 任务。
3. 生成 Worker 清单：
   | Worker ID | 任务描述 | 输入数据 | 预期输出 |
   |-----------|---------|---------|---------|
   | W1 | 认证模块代码分析 | auth/目录 | auth_analysis.md |
   | W2 | 数据层代码分析 | data/目录 | data_analysis.md |
   | W3 | API层代码分析 | api/目录 | api_analysis.md |
4. 输出 Worker 派发计划：[worker_dispatch_plan.yaml]

## Step 2: Worker 动态派生与执行
对每个 Worker：从模板 `SubAgent-CodeAnalyst` 实例化 SubAgent → 创建独立 worktree → 下发任务 → 执行完毕后收集输出 → Leader 校验输出完整性

## Step 3: 结果聚合
1. 收集所有 Worker 输出
2. 汇总、去重、冲突检测、一致性校验
3. 输出汇总结果：[代码分析总报告.md]
