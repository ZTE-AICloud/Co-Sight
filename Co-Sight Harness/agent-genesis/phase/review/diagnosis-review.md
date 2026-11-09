---
review_id: diagnosis-review
review_type: standard
name: "Skill 诊断报告审查"
reviewer: agent
agent_type: code-reviewer
scope_files: ["phase1-diagnosis-report.md"]
blocking: true
---

## Checklist
- [ ] 7 个维度全部显式声明 PASS/FAIL（无跳过）
- [ ] FAIL 维度有 SKILL.md 具体行号引用（证据）
- [ ] 根因假设可操作（非泛泛的"质量不好"）
- [ ] 优先级排序正确（CRITICAL > HIGH > MEDIUM > LOW）
- [ ] 边界判定明确（Skill 内 / 部分超出 / 完全超出）
- [ ] 无"姐妹 Skill 结构对齐"反模式
