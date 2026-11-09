# build-plan（knowledge-reflux 过程锚, derived）

> derived: true——外部启发过程锚（源自 everything-claude-code 重塑）, 非
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼 path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按改造后资产实际字面量书写（R6 双锚约定）。
> （R6 双锚约定）。

---
plan_id: golden-knowledge-reflux-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-16"
selected_patterns: [WF7-Knowledge-Reflux]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| WF7-Knowledge-Reflux | CLAUDE.md |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 知识回流 Agent 运行时入口——四级进化管道（观察→原子模式→聚类→升级）+ 原子模式五属性纪律 + 项目作用域与防污染三条款 + 置信度分级处置表 + 数据边界 + Not for。
deps: []
read_first: []
materializes: [WF7-Knowledge-Reflux]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "四级进化管道"}
  - {type: content_contains, value: "观察（从会话痕迹收原始记录）"}
  - {type: content_contains, value: "原子模式格式"}
  - {type: content_contains, value: "confidence: 0.7"}
  - {type: content_contains, value: "项目作用域与防污染"}
  - {type: content_contains, value: "≥2 个项目独立出现"}
  - {type: content_contains, value: "升级永远不是全自动"}
acceptance:
  - 四级管道完整（观察/原子模式/聚类/升级）, 升级末跳写明人工或显式命令触发
  - 原子模式五属性各有一句纪律说明（原子/置信度/领域标签/证据链/作用域）
  - 置信度处置表四档, 每档有明确处置（只存/建议/聚类/提升）
anti_patterns: [升级全自动无人工闸门; 原始对话原文长期保留]
```
