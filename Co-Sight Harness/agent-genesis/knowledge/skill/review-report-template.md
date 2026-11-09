# Phase 2 审查报告: {skill-name}

> 审查者: skill-reviewer-agent (mode=optimize)
> 上游: skill-planner-agent 的诊断报告
> 下游: Main Agent (Plan Mode 方案设计)

## 审查元数据

| 字段 | 值 |
|------|-----|
| 审查时间 | {ISO8601-timestamp} |
| Skill 名称 | {skill-name} |
| 诊断报告路径 | work/{skill-name}/optimize-skill/phase1-diagnosis-report.md |
| Agent CLAUDE.md 路径 | {path}/CLAUDE.md |
| 阻断检查结果 | PASS / FAIL |

## 审查判决

| 字段 | 值 |
|------|-----|
| **verdict** | PASS / FAIL |
| **Review Quality Score** | {X.X} / 5.0 |
| CRITICAL 发现数 | {N} |
| HIGH 发现数 | {N} |

> **PASS 条件**: CRITICAL == 0 AND HIGH == 0 AND Review Quality Score >= 3.0

## 逐维审查结果

| 维度 | 诊断判决 | 审查确认 | 置信度 | 发现摘要 |
|------|---------|---------|:------:|---------|
| Decomposition | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |
| Information | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |
| State | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |
| Verification | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |
| Logic Consistency | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |
| Design Form | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |
| Global Context | {PASS/FAIL} | {PASS/FAIL/WARN} | {high/medium/low} | {一句话} |

## 结构化检查清单 (R-01 ~ R-12)

| 检查项 | 类型 | 判决 | 发现 |
|--------|:----:|:----:|------|
| R-01 7 维全覆盖 | CRITICAL | {PASS/FAIL} | {描述} |
| R-02 证据可追溯 | CRITICAL | {PASS/FAIL} | {描述} |
| R-03 证据与结论一致性 | CRITICAL | {PASS/FAIL} | {描述} |
| R-04 根因可操作 | CRITICAL | {PASS/FAIL} | {描述} |
| R-05 严重级别合理性 | HIGH | {PASS/FAIL} | {描述} |
| R-06 Design Form 优先执行 | CRITICAL | {PASS/FAIL} | {描述} |
| R-07 Global Context 原文验证 | HIGH | {PASS/FAIL} | {描述} |
| R-08 边界判定合规 | CRITICAL | {PASS/FAIL} | {描述} |
| R-09 多 Skill 功能冲突检测 | HIGH | {PASS/FAIL} | {描述} |
| R-10 禁止内容检查 | HIGH | {PASS/FAIL} | {描述} |
| R-11 黄金案例对照 | MEDIUM | {PASS/FAIL} | {描述} |
| R-12 跨维度关联分析 | MEDIUM | {PASS/FAIL} | {描述} |

## 关键发现详情

> 仅列出 CRITICAL 和 HIGH 级别的发现。

### [CRITICAL/HIGH] {发现标题}

- **检查项**: R-XX
- **证据**: {诊断报告中的具体引用，含行号}
- **问题**: {为什么这是个问题}
- **建议修正**: {具体可执行的修正方向}

---

（重复以上格式列出所有 CRITICAL/HIGH 发现）

## 审查质量评分详情

| 检查项 | 权重 | 得分 (0-1) | 加权分 |
|--------|:----:|:----------:|:------:|
| R-01 ~ R-04 (CRITICAL) | 各 0.15 | {0.X} | {0.XX} |
| R-06 (CRITICAL) | 0.10 | {0.X} | {0.XX} |
| R-08 (CRITICAL) | 0.10 | {0.X} | {0.XX} |
| R-05, R-07, R-09, R-10 (HIGH) | 各 0.05 | {0.X} | {0.XX} |
| R-11, R-12 (MEDIUM) | 各 0.025 | {0.X} | {0.XX} |
| **合计** | **1.00** | — | **{X.XX} / 5.0** |

> 评分公式: 原始分 (0-1) x 权重 x 5.0 = 最终分。≥ 3.0 才可 PASS。

## REWORK 反馈（仅 verdict=FAIL 时填写）

> 以下条目需要 skill-planner-agent 在重诊断时逐条修正。

| # | 需要修正的条目 | 修正建议 |
|:--:|--------------|---------|
| 1 | {具体描述，如 "Design Form 维度缺少 DF-M2 证据引用"} | {具体修正方向} |
| 2 | ... | ... |

## 签名

| 字段 | 值 |
|------|-----|
| 审查引擎 | skill-reviewer-agent v1 (mode=optimize) |
| 审查规则 | skill-reviewer-agent/optimize/workflow.md §4.1-4.5 |
| 审查依据 | skill-diagnosis-rules.md, escalation-decision-rules.md, skill-design-guide.md |
