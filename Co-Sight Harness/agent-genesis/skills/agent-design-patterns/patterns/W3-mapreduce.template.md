---
pattern_id: W3
pattern_name: Map-Reduce
category: workflow
sub_dimension: decomposition
selection_rule: "4选1互斥。顶层只能选一种。子结构可嵌套另一种(最大深度2层)。"
solves: "多个同类子任务相互独立，可并行执行，结果需要汇总"
fills_spec_section: Execution Workflow

variables:
  - name: SUB_TASKS
    description: "子任务清单，每项包含id、描述、输入文件。子任务间必须无依赖关系。"
    type: list
    source: user_input
    required: true
  - name: SPLIT_DIMENSION
    description: "拆分维度——按数据分片(by-data) / 按关注点(by-concern) / 按角色(by-role)"
    type: string
    source: user_input
    enum: ["by-data", "by-concern", "by-role"]
    default: "by-data"
  - name: MAX_PARALLEL
    description: "最大并行子任务数（整数），防止资源耗尽"
    type: string
    source: user_input
    required: true
  - name: SUB_TASK_TEMPLATE
    description: "每个子任务的执行模板/调用的SubAgent类型，所有子任务使用相同模板"
    type: string
    source: user_input
    required: true
  - name: REDUCE_LOGIC
    description: "汇总阶段的核心逻辑——如何收集、去重、排序、合并所有子任务输出"
    type: markdown
    source: user_input
    required: true
  - name: REDUCE_OUTPUT
    description: "汇总后的最终输出文件路径"
    type: string
    source: user_input
    required: true
  - name: REDUCE_VALIDATION
    description: "汇总前如何校验所有子任务已完成且输出完整"
    type: string
    source: llm_generate
    required: true
    default: "逐一检查每个子任务输出文件存在且非空"

constraints:
  - "子任务必须真正独立（无读写冲突）"
  - "必须声明最大并行数"
  - "Reduce阶段必须校验所有子任务已完成"
---

# Execution Workflow

## 执行约束
- **所有子任务必须相互独立，禁止子任务之间有数据依赖**
- **拆分维度：{{SPLIT_DIMENSION}}**（by-data: 按数据分片 / by-concern: 按关注点 / by-role: 按角色）
- **最大并行数：{{MAX_PARALLEL}}**
- **Reduce 阶段必须校验所有子任务输出完整性，缺失则阻断**

## Step 1: Map — 并行派发
对以下子任务并行执行：

| 子任务ID | 描述 | 输入 | 执行模板 |
|----------|------|------|---------|
{{#each SUB_TASKS}}
| {{this.id}} | {{this.description}} | [{{this.input}}] | {{SUB_TASK_TEMPLATE}} |
{{/each}}

**并行约束**: 各子任务使用独立 worktree/输出文件路径，最大并行数：{{MAX_PARALLEL}}

**每子任务输出**: [{{SUB_TASK_TEMPLATE}}_output_{{this.id}}.md]

## Step 2: Reduce — 结果汇总
1. 校验所有子任务已完成：{{REDUCE_VALIDATION}}
2. {{REDUCE_LOGIC}}
3. 输出汇总结果：[{{REDUCE_OUTPUT}}]

---
# Filled Example

## 示例 1: 按数据分片 (by-data)

### 执行约束
- **所有子任务必须相互独立，禁止子任务之间有数据依赖**
- **拆分维度：by-data**（按数据分片）
- **最大并行数：3**

### Step 1: Map — 并行派发
对以下子任务并行执行：

| 子任务ID | 描述 | 输入 | 执行模板 |
|----------|------|------|---------|
| T1 | 协议层分析 | [3GPP_38.214.md] | SubAgent-ProtocolAnalyst |
| T2 | 场景覆盖分析 | [需求描述.md] | SubAgent-ScenarioAnalyst |
| T3 | 接口一致性分析 | [接口定义.yaml] | SubAgent-InterfaceAnalyst |

**并行约束**: 各子任务使用独立 worktree/输出文件路径，最大并行数：3

**每子任务输出**: [SubAgent_output_{id}.md]

### Step 2: Reduce — 结果汇总
1. 校验所有子任务已完成：逐一检查 T1/T2/T3 输出文件存在且非空
2. 收集所有子任务输出 → 去重合并 → 按领域归类 → 冲突标注 → 生成综合报告
3. 输出汇总结果：[综合分析报告.md]

## 示例 2: 按关注点 (by-concern)

### 执行约束
- **所有子任务必须相互独立，禁止子任务之间有数据依赖**
- **拆分维度：by-concern**（按关注点）
- **最大并行数：5**

### Step 1: Map — 并行派发
对以下子任务并行执行（出处: code-review.md Step4 5审查维度）：

| 子任务ID | 描述 | 输入 | 执行模板 |
|----------|------|------|---------|
| T1 | 正确性检查 | [待审查代码] | SubAgent-CodeReviewer |
| T2 | 安全性检查 | [待审查代码] | SubAgent-CodeReviewer |
| T3 | 性能检查 | [待审查代码] | SubAgent-CodeReviewer |
| T4 | 可维护性检查 | [待审查代码] | SubAgent-CodeReviewer |
| T5 | 规范遵循检查 | [待审查代码] | SubAgent-CodeReviewer |

**并行约束**: 各子任务使用独立 worktree/输出文件路径，最大并行数：5

**每子任务输出**: [review_{id}.md]

### Step 2: Reduce — 结果汇总
1. 校验所有子任务已完成：逐一检查 T1-T5 输出文件存在且非空
2. 按维度归类所有发现 → 去重（跨维度相同问题合并）→ 按严重程度排序 → 生成综合审查报告
3. 输出汇总结果：[综合审查报告.md]
