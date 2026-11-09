# build-plan（verify-loop 过程锚, derived）

> derived: true——外部启发过程锚（源自 dexter 重塑）, 非真实构建产物。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼 path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按改造后资产实际字面量书写（R6 双锚约定）。

---
plan_id: golden-verify-loop-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-16"
selected_patterns: [WF6-Circuit-Breaker]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| WF6-Circuit-Breaker | CLAUDE.md, SOUL.md, AGENTS.md |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 迭代验证 Agent 运行时入口——Plan→Execute→Verify→Iterate 闭环 + 每步落盘断点恢复 + 熔断上限（3轮/2次）+ 身份/技术分层索引 + Not for。
deps: [SOUL.md, AGENTS.md]
read_first: [SOUL.md, AGENTS.md]
materializes: [WF6-Circuit-Breaker]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "Plan→Execute→Verify→Iterate 闭环"}
  - {type: content_contains, value: "每步落盘与断点恢复"}
  - {type: content_contains, value: "迭代上限（熔断）"}
  - {type: content_contains, value: "身份层与技术层分离"}
  - {type: content_contains, value: "01-plan.md"}
  - {type: content_contains, value: "03-verify.md"}
  - {type: content_contains, value: "circuit_breaker"}
acceptance:
  - 闭环四步齐全, Verify 是自动条件分支而非独立人审节点
  - 熔断上限显式数字（默认 3 轮 / 2 次）, 超限路径写明交人决策
  - 身份层样例信念 ≥4 条且为软约束表述
anti_patterns: [无上限的"迭代到成功为止"]
```

```yaml
path: SOUL.md
type: doc
brief: 身份层——核心信念（先理解后动手/迭代验证/实质胜表现/知识边界/fresh eyes）+ 模糊场景决策偏好（数据先于观点/反演优先/难度非回避理由）。
deps: []
read_first: []
materializes: [WF6-Circuit-Breaker]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: identity_of}
  - {type: content_contains, value: "迭代验证而非一次性执行"}
  - {type: content_contains, value: "知识边界诚实"}
  - {type: content_contains, value: "数据先于观点"}
acceptance:
  - 信念为软约束（倾向于）而非硬禁令（禁止）表述
  - 标注"按项目改写"的样例属性, 不冒充可直接运行配置
anti_patterns: [身份层写入具体工具/命令等高频变动技术细节]
```

```yaml
path: AGENTS.md
type: doc
brief: 技术层——项目结构/构建测试命令/编码约定/环境变量纪律/版本发布流程/安全基线（样例, 按项目改写）。
deps: []
read_first: []
materializes: [WF6-Circuit-Breaker]
invariants:
  - {type: content_contains, value: "Build, Test, and Development Commands"}
  - {type: content_contains, value: "Environment Variables"}
  - {type: content_contains, value: "Security"}
  - {type: content_contains, value: "永不入库"}
acceptance:
  - 六段齐全; 密钥纪律一条写明"缺失即报错, 不静默降级"
  - 发布段写明"必须用户确认, 不自动 push/publish"
anti_patterns: [技术层混入信念/偏好类身份声明]
```
