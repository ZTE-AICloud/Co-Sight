---
pattern_id: E2
pattern_name: Controlled-Evolution
category: evolution
sub_dimension: controlled_evolution
selection_rule: "可选。依赖 E1。在 E1 评分 < threshold 且在 allowed_scopes 内时触发受控进化。"
solves: "在允许范围内自动修正 Agent 行为，超出范围升级到人工或工厂重建"
fills_spec_section: Evolution Contract
depends_on: [E1]

variables:
  - name: ALLOWED_SCOPES
    description: "允许自动修改的范围白名单（deny-by-default）"
    type: list
    source: user_input
    required: true
    schema:
      - field: scope
        type: string
        description: "允许修改的 Spec 区域（如 execution_workflow.step_3, knowledge_contract.sources）"
      - field: max_changes_per_cycle
        type: number
        description: "每个进化周期内该 scope 的最大修改次数"
        default: 2
  - name: EVOLUTION_CYCLE_MAX
    description: "最大进化周期数"
    type: number
    source: decision_table
    default: 3
  - name: EVOLUTION_TRIGGER_SCORE
    description: "触发进化的 E1 评分阈值（低于此值触发）"
    type: number
    source: decision_table
    default: 3.5

constraints:
  - "deny-by-default: 未声明的 scope 禁止修改"
  - "每次修改前必须 snapshot 当前状态"
  - "修改后必须经过 E1 重评估"
  - "修改不得绕过 G1 审查门禁（自审查模式）"
  - "每个周期最多修改 allowed_scopes 中声明的每个 scope 的 max_changes_per_cycle 次"
  - "达到 EVOLUTION_CYCLE_MAX 仍 FAIL → Escalation Gate → 升级到 AgentGenesis 工厂"
  - "禁止修改 Safety Constraints 章节（S-13）"
---

# Evolution Contract — Controlled-Evolution

## 进化范围

**deny-by-default**: 仅以下声明的 scope 可在自动进化中修改。其他所有 Spec 区域均为只读。

| Scope | 允许修改区域 | 每周期最大修改次数 |
|-------|------------|:---:|
{{#each ALLOWED_SCOPES}}
| {{this.scope}} | {{this.scope}} | {{this.max_changes_per_cycle}} |
{{/each}}

## 进化触发条件

1. E1 自评加权总分 < {{EVOLUTION_TRIGGER_SCORE}}
2. 低分维度在 allowed_scopes 中有对应可修改区域
3. 当前进化周期数 < {{EVOLUTION_CYCLE_MAX}}

## 进化流程

```
E1 Self-Eval FAIL (score < threshold)
  │
  ▼
Step E2.1: 差距分析
  - 读取 E1 自评报告中的 gap_analysis
  - 检查低分维度的 probable_cause 是否在 allowed_scopes 内
  - 在 scope 外 → Escalation Gate
  - 在 scope 内 → 继续
  │
  ▼
Step E2.2: Snapshot 当前状态
  - 复制当前 Spec 文件到 work/_self/snapshots/{timestamp}/
  - 记录修改前 checksum
  │
  ▼
Step E2.3: 生成 Delta 修改
  - 调用 E3 Delta-Modification 协议
  - 三段式 Diff: Before / After / Reason
  │
  ▼
Step E2.4: 自审查 (G1)
  - 修改后的 Spec 通过内嵌 G1 审查门禁
  - 检查修改未超出 allowed_scopes
  - 检查 Safety Constraints 未被修改
  - FAIL → 回滚到 snapshot
  │
  ▼
Step E2.5: 应用修改
  - 写入修改后的 Spec
  - 记录进化日志: work/_self/evolution-log.yaml
  │
  ▼
Step E2.6: 重评估 (E1)
  - 重新执行 E1 自评
  - PASS → 进化成功，记录改进
  - FAIL + 周期 < max → 回到 Step E2.1
  - FAIL + 周期 >= max → Escalation Gate
```

## Escalation Gate

以下情况触发升级，不继续自动进化：
- 低分根因在 allowed_scopes 外
- 连续 {{EVOLUTION_CYCLE_MAX}} 周期仍未通过 E1
- 自审查 (G1) 连续 2 次 FAIL
- 检测到 Safety Constraints 变更尝试

升级消息格式：
```yaml
escalation:
  timestamp: "ISO 8601"
  reason: "超出 allowed_scopes / 周期耗尽 / 审查失败"
  current_scores: {各维度分数}
  attempted_changes: ["已尝试的修改摘要"]
  recommendation: "建议 AgentGenesis 工厂 REVISE 或人工介入"
```

---
# Filled Example

## 进化范围

**deny-by-default**: 仅以下声明的 scope 可在自动进化中修改。

| Scope | 允许修改区域 | 每周期最大修改次数 |
|-------|------------|:---:|
| execution_workflow.step_3 | 报告生成步骤的工具调用逻辑 | 2 |
| knowledge_contract.sources | 知识来源的检索参数 | 1 |

## 进化流程（示例）

```
E1 Self-Eval: completeness=2.5 (<3.0 threshold)
  │
  ▼ Step E2.1: 差距分析
  gap: "漏检了 E305 违规（函数定义后空行不足）"
  cause: "工具调用未包含 pycodestyle --select=E305"
  scope_check: execution_workflow.step_3 ✓ (在 allowed_scopes 内)
  │
  ▼ Step E2.2: Snapshot
  saved: work/_self/snapshots/2026-05-07T15:30:00/claude.md (checksum: a1b2c3)
  │
  ▼ Step E2.3: Delta (E3)
  Before: "pycodestyle --select=E501,W291,E302"
  After:  "pycodestyle --select=E501,W291,E302,E305"
  Reason: "E1 自评发现缺少 E305 检测，补充工具 select 参数"
  │
  ▼ Step E2.4: 自审查 (G1) → PASS
  │
  ▼ Step E2.5: 应用修改 → 写入
  │
  ▼ Step E2.6: 重评估 (E1) → completeness=4.5 → PASS
```
