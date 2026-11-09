---
review_id: matching-decision-review
review_type: standard
name: "模式匹配决策审查"
reviewer: agent
agent_type: code-reviewer
scope_files: ["phase1-matching-decision.md"]
blocking: true
---

## Checklist
- [ ] 所有子维度都有匹配决策（无遗漏维度）
- [ ] 每个决策 confidence ∈ {high, medium, low}，有非空 rationale
- [ ] 模式间无不兼容组合（incompatible_with 无一命中）
- [ ] Tier 0 MN 判定与 Tier 2 模式组合自洽
- [ ] 结构决策节齐全（build_type_decision: subagents[] 含 split_trigger / skills[] 含 scope_trigger）
- [ ] 决策物化表覆盖每个 selected pattern（每 ID 恰一行，role 级 target）
- [ ] 构建类型与模式组合一致
