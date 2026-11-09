---
plan_id: fast-neg-truncated
plan_version: "2.0"
mode: greenfield
generated_at: 2026-10-15T00:00:00Z
selected_patterns: [G1]
basis: []
---

# 负例: 截断 YAML（文件块中途截断）

```yaml
path: CLAUDE.md
type: claude_md
generation: generate
deps: []
read_first: []
materializes: [G1]
brief: >
  截断样例——此块在 invariants 处中
invariants:
  - {type: content_contains, pattern:
