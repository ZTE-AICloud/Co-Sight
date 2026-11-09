# build-plan（plan-approval 过程锚, derived）

> derived: true——外部启发过程锚（源自 clnode 重塑）, 非真实构建产物。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼 path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按改造后资产实际字面量书写（R6 双锚约定）。

---
plan_id: golden-plan-approval-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-16"
selected_patterns: [IH3-Plan-Approval]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| IH3-Plan-Approval | CLAUDE.md, .claude/agents/implementer.md, .claude/agents/reviewer.md, .claude/rules/team-workflow.md |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 计划审批多 Agent 运行时入口——三角色拓扑 + 双点人审（计划批准/重审确认）+ 任务看板六态 + 上下文精简三级纪律 + Not for。
deps: [.claude/agents/implementer.md, .claude/agents/reviewer.md, .claude/rules/team-workflow.md]
read_first: [.claude/rules/team-workflow.md]
materializes: [IH3-Plan-Approval]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "双点人审（计划批准 + 重审确认）"}
  - {type: content_contains, value: "AskUserQuestion: 批准执行?"}
  - {type: content_contains, value: "AskUserQuestion: 修复完成, 重审?"}
  - {type: content_contains, value: "5-7 个文件"}
  - {type: content_contains, value: "Idea → Planned → Pending → In Progress → Needs Review → Completed"}
acceptance:
  - 两处人审均为显式 AskUserQuestion, 非静默默认通过
  - 实现者规模约束（5-7 文件）写明超界处理（回报拆分, 不硬扛）
  - 上下文精简三级纪律表格化（角色/回报内容/禁项）
anti_patterns: [修复后自动重审的无限循环]
```

```yaml
path: .claude/agents/implementer.md
type: agent_def
brief: 实现者 Agent 定义——任务块执行 + 结构化报告（变更清单/关键决策/自验/遗留）+ 5-7 文件规模约束。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [IH3-Plan-Approval]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: tools}
  - {type: frontmatter_field_nonempty, field: forbidden_inputs}
  - {type: content_contains, value: "5-7 个文件"}
  - {type: content_contains, value: "## 实现报告"}
acceptance:
  - frontmatter 四字段齐（name/description/tools/forbidden_inputs）
  - 回报格式段含变更文件/关键决策/自验结果/已知遗留四小节
anti_patterns: [回报里回放执行过程叙事]
```

```yaml
path: .claude/agents/reviewer.md
type: agent_def
brief: 审查者 Agent 定义——三档优先级审查清单 + Review Loop Protocol（修复后不自动重审, 用户显式确认）+ 独立上下文。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [IH3-Plan-Approval]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: tools}
  - {type: frontmatter_field_nonempty, field: forbidden_inputs}
  - {type: content_contains, value: "Review Loop Protocol"}
  - {type: content_contains, value: "### critical（合并前必修）"}
  - {type: content_contains, value: "不自动重审"}
acceptance:
  - 审查清单六项覆盖（逻辑/错误处理/安全/性能/命名/测试）
  - Review Loop Protocol 段写明两分支（重审/收尾）及不可绕过声明
anti_patterns: [审查报告缺优先级分档]
```

```yaml
path: .claude/rules/team-workflow.md
type: rule
brief: 团队协作规则——角色拓扑 + 并行/串行判定 + 上下文精简三级纪律表 + 成本分层 + 进度汇报节奏。
deps: []
read_first: []
materializes: [IH3-Plan-Approval]
invariants:
  - {type: content_contains, value: "并行 vs 串行"}
  - {type: content_contains, value: "上下文精简纪律（三级）"}
  - {type: content_contains, value: "Leader → 用户"}
  - {type: content_contains, value: "成本分层"}
acceptance:
  - 并行/串行各 ≥2 条判定标准
  - 三级纪律表含角色/回报内容/禁项三列
anti_patterns: [规则件写实现细节而非协作纪律]
```
