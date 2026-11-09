---
plan_id: fast-neg-missing-files
plan_version: "2.0"
mode: greenfield
generated_at: 2026-10-15T00:00:00Z
selected_patterns: [G1]
basis: []
---

# 负例: 缺 files 块（无任何 ```yaml 文件块）

## 决策物化

```yaml
materialization:
  - pattern_id: G1
    target_files: [CLAUDE.md]
```
