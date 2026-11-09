---
plan_id: fast-neg-bad-invariants
plan_version: "2.0"
mode: greenfield
generated_at: 2026-10-15T00:00:00Z
selected_patterns: [G1]
basis: []
---

# 负例: invariants 非 DSL（type 不在枚举内）

```yaml
path: CLAUDE.md
type: claude_md
generation: generate
deps: []
read_first: []
materializes: [G1]
brief: >
  非 DSL 样例——invariants.type 用了枚举外的自定义检查名，g023 应拒绝而非静默跳过。
invariants:
  - {type: llm_should_judge_by_feeling}
acceptance: []
anti_patterns: []
```
