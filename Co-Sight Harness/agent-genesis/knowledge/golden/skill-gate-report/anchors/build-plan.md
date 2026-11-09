# build-plan（skill-gate-report 过程锚）

> 自有产物锚——本包源自本仓库 skill 线收官构建 gate-suite-report 的真实
> build-plan 语义（非外部启发, 不标 derived）。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼
> path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按资产实际
> 字面量书写（R6 双锚约定）。

---
plan_id: golden-skill-gate-report-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-16"
selected_patterns: [IV1-Progress-Streaming]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| IV1-Progress-Streaming | SKILL.md, templates/verify-report.md |
```

# files

```yaml
path: SKILL.md
type: skill
brief: 关键节点验证汇报 Skill——七项固定清单顺序执行（不 fail-fast）+ 确定性计数（禁 LLM 目测）+ 缺失脚本 fail-closed + 三段固定结构报告 + 一行 stdout 总结论。
deps: []
read_first: []
materializes: [IV1-Progress-Streaming]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "七项验证资产（固定清单与顺序，禁止增删或重排）"}
  - {type: content_contains, value: "不 fail-fast"}
  - {type: content_contains, value: "严禁 LLM 目测计数"}
  - {type: content_contains, value: "缺失脚本 fail-closed"}
  - {type: content_contains, value: "ALL PASS 当且仅当"}
  - {type: content_contains, value: "templates/verify-report.md"}
acceptance:
  - 七项清单固定（5 套件 + 2 机检）, 顺序声明且禁止重排
  - 计数只用 grep/wc/awk 确定性工具, 有明令禁 LLM 目测
  - 总判定规则一句闭环: 全 0 且无 ERROR 才 ALL PASS
anti_patterns: [fail-fast 中断收集; LLM 目测计数; 失败明细转述概括]
```

```yaml
path: templates/verify-report.md
type: template
brief: 验证报告固定三段结构模板——①总判定 ②逐套件结果表 ③失败明细; 占位符 <...> 产出时替换, 禁增删段落。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [IV1-Progress-Streaming]
invariants:
  - {type: content_contains, value: "固定三段结构"}
  - {type: content_contains, value: "## 1. 总判定"}
  - {type: content_contains, value: "## 2. 逐套件结果表"}
  - {type: content_contains, value: "## 3. 失败明细"}
  - {type: content_contains, value: "状态=ERROR 仅在脚本文件缺失时出现"}
acceptance:
  - 三段齐全且顺序固定, 失败明细要求原文逐字收录
anti_patterns: [段落增删或换序; 失败行转述]
```
