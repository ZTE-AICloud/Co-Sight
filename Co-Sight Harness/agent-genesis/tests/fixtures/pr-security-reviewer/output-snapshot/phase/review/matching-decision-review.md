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
- [ ] Q1-Q6 全部判定（含 Q4 按需生成判定）
- [ ] 构建类型与模式组合一致
