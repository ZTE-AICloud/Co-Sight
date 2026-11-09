---
pattern_id: W5
pattern_name: Adaptive
category: workflow
sub_dimension: decomposition
type: "meta-decomposition-overlay"
selection_rule: "元分解叠加层。非第5个互斥选项——包装W1-W4，声明运行时拓扑切换规则。与base_topology共存。"
solves: "执行路径/步骤数量在运行时根据中间结果动态选择，而非构建时完全确定"
fills_spec_section: "Execution Workflow (adaptation_rules) + Runtime Adaptation"
wraps: [W1, W2, W3, W4]

variables:
  - name: BASE_TOPOLOGY
    description: "默认拓扑模式（W1|W2|W3|W4 选一）"
    type: string
    source: decision_table
    required: true
  - name: ADAPTATION_RULES
    description: "拓扑切换规则列表"
    type: list
    source: user_input
    required: true
    schema:
      - field: rule_id
        type: string
        description: "规则编号 (AR-01, AR-02, ...)"
      - field: condition
        type: string
        description: "触发条件——必须可客观判定（如：文件数 > 50，非 LLM 主观判断）"
      - field: target_topology
        type: string
        description: "切换到的目标拓扑（W1|W2|W3|W4）"
      - field: transition_action
        type: string
        description: "切换时执行的动作（如：保留已完成步骤的结果、重新分配Worker）"
  - name: METRIC_BRANCHES
    description: "基于度量的轻量级分支规则——不切换拓扑，仅改变同一拓扑内的执行路径"
    type: list
    source: user_input
    required: false
    schema:
      - field: branch_id
        type: string
        description: "分支规则编号 (MB-01, MB-02, ...)"
      - field: metric
        type: string
        description: "度量指标名称（如 score, coverage, complexity）"
      - field: threshold
        type: number
        description: "阈值"
      - field: operator
        type: string
        enum: ["<", "<=", ">", ">=", "==", "!="]
        description: "比较运算符"
      - field: action
        type: string
        description: "触发后的动作——仅重路由到同拓扑内的子步骤，不切换拓扑"
  - name: MAX_SWITCHES
    description: "最大切换次数硬限制"
    type: number
    source: decision_table
    default: 3
  - name: AUDIT_TRAIL_FORMAT
    description: "每次拓扑切换的审计记录格式"
    type: string
    source: derived
    default: "reason + 切换前状态 + 切换后状态 + timestamp"

constraints:
  - "必须声明 base_topology（默认走哪个拓扑）"
  - "adaptation_rules 条件必须可客观判定（不依赖 LLM 主观判断）"
  - "每次拓扑切换必须记录 audit_trail"
  - "最大切换次数硬限制（默认3次）"
  - "禁止循环切换（A→B→A），audit_trail 中检测到循环立即阻断"
  - "adaptation_decision 步骤推荐使用 opus 模型（M1）"
  - "与 OpenSage 的本质区别：规则在设计时预定义，运行时按规则执行（非 LLM 自由决定）"
---

# Runtime Adaptation

## 自适应拓扑声明

**默认拓扑**: {{BASE_TOPOLOGY}}
**最大切换次数**: {{MAX_SWITCHES}}

## 自适应规则表

| 规则ID | 触发条件 | 目标拓扑 | 切换动作 |
|--------|---------|:---:|------|
{{#each ADAPTATION_RULES}}
| {{this.rule_id}} | {{this.condition}} | **{{this.target_topology}}** | {{this.transition_action}} |
{{/each}}

## Metric-Driven Branches

区别于 ADAPTATION_RULES（拓扑级切换——改变整个执行结构），METRIC_BRANCHES 是同一拓扑内的轻量级分支——基于可度量指标改变执行路径，但不切换拓扑：

| 分支ID | 度量指标 | 阈值 | 运算符 | 触发动作（同拓扑内重路由） |
|--------|---------|:---:|:---:|------|
{{#each METRIC_BRANCHES}}
| {{this.branch_id}} | {{this.metric}} | {{this.threshold}} | `{{this.operator}}` | {{this.action}} |
{{/each}}

> **与 ADAPTATION_RULES 的本质区别**: ADAPTATION_RULES 触发拓扑切换（如 W1→W3），METRIC_BRANCHES 仅在同一拓扑内改变执行路径（如同一个 Pipeline 中根据 score 决定是否重新执行某步骤）。前者改变结构，后者改变路由。

## 模型推荐

| 步骤 | 推荐模型 | 理由 |
|------|:---:|------|
| 默认执行步骤 | sonnet | 常规推理足够 |
| adaptation_decision（拓扑切换决策） | **opus** | 拓扑切换涉及架构变更，需深度推理 |

## 审计追踪格式

每次拓扑切换记录以下字段：

```yaml
adaptation_event:
  timestamp: "ISO 8601"
  rule_id: "AR-XX"
  reason: "触发条件具体值（如：文件数=67 > 阈值50）"
  from_topology: "切换前拓扑"
  to_topology: "切换后拓扑"
  state_snapshot:
    completed_steps: ["已完成步骤列表"]
    pending_steps: ["待执行步骤列表"]
    artifacts: {"文件路径": "状态"}
  decision_by: "rule（非LLM自由裁量）"
```

## 安全约束

1. **条件可判定性**: 所有触发条件必须基于可度量指标（计数、大小、类型匹配），禁止用 LLM 主观判断作为切换条件
2. **切换次数限制**: 达到 {{MAX_SWITCHES}} 次后拒绝进一步切换，继续用当前拓扑完成
3. **循环检测**: audit_trail 中检测到 A→B→A 模式时立即阻断
4. **不可回退链**: 禁止退回到已声明为不可逆的步骤之前的状态

---
# Filled Example

## 自适应拓扑声明

**默认拓扑**: W1-Pipeline
**最大切换次数**: 3

## 自适应规则表

| 规则ID | 触发条件 | 目标拓扑 | 切换动作 |
|--------|---------|:---:|------|
| AR-01 | 待检查文件数 > 50 | **W3-MapReduce** | 将已完成步骤的上下文序列化，按文件拆分为并行子任务，汇总后继续Pipeline |
| AR-02 | 发现安全漏洞数量 > 10 | **W4-LeaderWorker** | 暂停Pipeline，Leader分析漏洞类型后按严重级别动态派生Worker |

## Metric-Driven Branches

区别于 AR-01/AR-02（拓扑级切换——改变整个执行结构），以下是同一 Pipeline 拓扑内的轻量级度量分支——基于可度量指标改变执行路径，但不切换拓扑（出处: code-review.md Step5 score<80→filter→re-review）：

| 分支ID | 度量指标 | 阈值 | 运算符 | 触发动作（同拓扑内重路由） |
|--------|---------|:---:|:---:|------|
| MB-01 | review_score | 80 | `<` | 低于阈值 → 过滤低分发现 → 重新执行审查步骤（同Pipeline内回退至Step4） |
| MB-02 | review_score | 90 | `>=` | 达到高分 → 跳过重新审查 → 直接进入报告生成 |

> **与 ADAPTATION_RULES 的本质区别**: ADAPTATION_RULES 触发拓扑切换（如 W1→W3），METRIC_BRANCHES 仅在同一拓扑内改变执行路径。MB-01 让低分审查重新执行，但始终在 W1-Pipeline 内完成——不切换到 W3 或 W4。

## 审计追踪格式（示例）

```yaml
adaptation_event:
  timestamp: "2026-05-07T14:32:00+08:00"
  rule_id: "AR-01"
  reason: "待检查文件数=67 > 阈值50"
  from_topology: "W1-Pipeline(Step 2/5)"
  to_topology: "W3-MapReduce(并行检查67个文件)"
  state_snapshot:
    completed_steps: ["配置文件读取", "依赖分析完成"]
    pending_steps: ["逐文件代码检查", "结果汇总", "报告生成"]
    artifacts: {"work/deps.json": "complete", "work/config.yaml": "complete"}
  decision_by: "rule（文件数达到AR-01阈值）"
```
