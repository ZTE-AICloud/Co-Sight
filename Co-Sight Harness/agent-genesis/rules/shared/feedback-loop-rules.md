# AgentGenesis 反馈闭环规则

> 适用范围: Phase 5 运行时评估未通过 → REVISE → Phase 1 重匹配
> 加载者: evaluator-agent (诊断阶段) + Main Agent (REVISE 协调)

---

## 1. REVISE 状态

### 1.1 进入条件

Phase 5 评估报告 verdict = FAIL，即：
- 加权总分 < 3.5，或
- correctness < 3.0，或
- completeness < 3.0

### 1.2 退出条件

- Phase 1 重匹配完成（新的 matching_decision.md 生成）
- Phase 2 审查通过（delta 变更通过 Reviewer 审查）
- 用户批准新的 construction-plan.md

### 1.3 路由

```
PHASE_5 (FAIL) → REVISE → PHASE_1
                           │
                           ├── Phase 1 读取反馈上下文 YAML
                           ├── 调整受影响维度的模式决策
                           ├── 生成新的 matching_decision.md (标注 REVISED)
                           │
                           ▼
                      PHASE_2 (审查 delta)
                           │
                           ▼
                      PLAN_MODE (用户审批 delta)
                           │
                           ▼
                      正常 PHASE_3 → PHASE_4 → PHASE_5
```

---

## 2. 反馈上下文格式

`work/{agent-name}/agent-creation/runtime-feedback-context.yaml`:

```yaml
feedback_context:
  source: "runtime-eval-{agent-name}.md"
  generated_at: "{timestamp}"
  low_dimensions:
    - dimension: "correctness"
      score: 2.0
      probable_causes:
        - cause: "IT1-Enforced 缺失"
          suggest: "升级为 Enforced"
          affected_patterns: [IT1-Enforced, CD3]
    - dimension: "completeness"
      score: 2.5
      probable_causes:
        - cause: "W1 Pipeline 步骤粒度不足"
          suggest: "拆分执行步骤"
          affected_patterns: [W1]
  original_matching_decision: "work/{agent-name}/agent-creation/phase1-matching-decision.md"
  suggested_changes:
    - pattern: "IT1-Enforced"
      original: null
      suggested: "IT1-Enforced"
      rationale: "runtime correctness=2.0，Agent 自行判断导致误报，需强制工具检查"
```

---

## 3. 增量修正协议

### 3.1 原则

- **仅修正受影响维度** — 不改动通过维度（如 correctness 低只修 IT1+CD3，不碰 workflow）
- **标注 REVISED** — matching_decision.md 头部添加 `> 修正版本: REVISED from runtime feedback`
- **记录 delta** — 每次修正生成 `work/{agent-name}/agent-creation/revision-delta.md`，含修正前后对比

### 3.2 Delta 格式 (3 段式)

```markdown
## Delta: {pattern_id}

**维度**: {dimension}
**原始决策**: {original_value} (confidence: {original_confidence})
**建议决策**: {suggested_value}
**依据**: runtime-eval 评分 {score}/5.0 + {probable_cause}
**风险**: {引入新决策可能带来的风险}
```

### 3.3 修正粒度

| 修正类型 | 说明 | 重建范围 |
|---------|------|---------|
| pattern 变更 | 增/删/改一个模式 | 受影响章节 + 相关 rules/ 文件 |
| confidence 调整 | 仅改置信度 | 不重建，仅更新 matching_decision.md |
| L2/L3 增删 | 规则文件或 Skill 变更 | 新建/删除指定文件 + CLAUDE.md 引用 |
| SubAgent 增删 | Multi-Agent 角色变更 | 新增/删除 SubAgent spec + Main Agent 调度表 |

---

## 4. REVISE vs REWORK

| 维度 | REWORK | REVISE |
|------|--------|--------|
| 触发源 | Phase 2 静态审查 | Phase 5 运行时评估 |
| 证据类型 | 模式冲突、覆盖缺失 | 实际行为数据（误报/遗漏/格式差） |
| 修改依据 | 审查者建议 | 反馈映射诊断 |
| 重建范围 | 通常需要重新装配 | 增量修正（仅受影响部分） |
| 上下文 | 无运行时数据 | 携带 feedback-context YAML |

---

## 5. REVISE vs Self-Evolution 职责边界

REVISE（AgentGenesis 工厂修复）和 Self-Evolution（Agent 自修复，E1/E2/E3）是两种不同的修复机制，必须明确区分：

| 维度 | REVISE (工厂修复) | Self-Evolution (自修复, E1→E2→E3) |
|------|--------|------|
| 执行者 | AgentGenesis Planner+Creator | Agent 自身（E2 决策 + E3 执行） |
| 触发源 | Phase 5 外部评估 FAIL | E1 内部自评 FAIL |
| 修复范围 | 可修改任何 Spec 章节（全量重建） | 仅 allowed_scopes 内（增量修正） |
| 重建方式 | Phase 1 重匹配 → Plan Mode → Phase 3 重建 | E2 gap_analysis → E3 Delta → G1 自审查 |
| 轮次限制 | 最多 2 轮 REVISE | 最多 EVOLUTION_CYCLE_MAX 周期 |
| 超出范围 | REPORT_TO_USER | Escalation Gate → AgentGenesis 工厂 REVISE |
| 审计 | revision-delta-{name}.md | evolution-log.yaml + work/_self/snapshots/ |

### Self-Evolution 到 REVISE 的升级路径

```
E1 FAIL
  │
  ├── 根因在 allowed_scopes 内 → E2 → E3 Delta → E1 重评
  │                                              │
  │                                        PASS → 进化成功
  │                                        FAIL → 周期+1 → 重试 (≤max)
  │
  └── 根因在 allowed_scopes 外 → Escalation Gate
                                    │
                                    ▼
                            AgentGenesis 工厂 REVISE
                            (Phase 1 重匹配 → ... → Phase 5)
```

## 6. 轮次控制

| 参数 | 默认值 | 说明 |
|------|:-----:|------|
| REVISE 最大轮次 | 2 | 第 3 次 Phase 5 FAIL → REPORT_TO_USER |
| 每轮评估超时 | 5 分钟 | 被测 Agent 执行上限 |
| Delta 审查 | 强制 | 每次 REVISE 必须通过 Phase 2 审查 |

---

## 7. 反馈上下文传递给 Phase 1 的方式

Main Agent 在进入 REVISE 时：
1. 读取 `work/{agent-name}/agent-creation/phase5-runtime-eval.md` 的诊断建议章节
2. 生成 `work/{agent-name}/agent-creation/runtime-feedback-context.yaml`
3. Spawn planner-agent 时，在 prompt 中包含：
   - 原始用户需求
   - **反馈上下文**：低分维度 + probable_causes + suggested pattern changes
   - 指令：重新评估 {low_dimensions} 的模式决策，其他维度保持不变

Planner-agent 在生成 matching_decision.md 时：
- 受影响维度标注 `confidence: revised`（非原始 high/medium/low）
- rationale 中包含 "基于 runtime feedback: {score}/5.0"
