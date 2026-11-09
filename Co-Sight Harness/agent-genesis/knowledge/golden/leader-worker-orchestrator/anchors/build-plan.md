# build-plan（leader-worker-orchestrator 过程锚, derived）

> derived: true——外部启发过程锚（源自 claude-orchestrator 重塑）, 非真实构建产物。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼 path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按改造后资产实际字面量书写（R6 双锚约定）。

---
plan_id: golden-leader-worker-orchestrator-anchor
plan_version: "1.0"
mode: greenfield
generated_at: "2026-10-17"
selected_patterns: [WF5-Contract-Lock]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| WF5-Contract-Lock | CLAUDE.md, prompts/plan.instruction.md, prompts/execute.instruction.md, prompts/verify.instruction.md |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 领导者-工作者责任链编排运行时入口——五节链契约（Plan→Build→Verify→Review→Accept）+ 判定协议五变体 + 工作者八步执行序列 + 协调后端外部件位 + 目录记忆规则 + Not for。
deps: []
read_first: []
materializes: [WF5-Contract-Lock]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "When to Use"}
  - {type: content_contains, value: "Not for"}
  - {type: content_contains, value: "责任链"}
  - {type: content_contains, value: "判定协议"}
  - {type: content_contains, value: "五选一"}
  - {type: content_contains, value: "协调后端"}
  - {type: content_contains, value: "外部件位"}
acceptance:
  - 五节链每节标注固定输入/输出产物名与下游读者, 产物名全局唯一且不可改
  - 判定协议恰好五变体, 领导者只按判定机械路由不做语义重评
  - 工作者自评必须用独立 fork 会话, 禁自评自产
  - 协调后端呈现为可替换外部件位（内存消息/分布式锁/用户自备）, 契约不随后端漂移
anti_patterns: [领导者对产物做语义重评而非机械路由]
```

```yaml
path: prompts/plan.instruction.md
type: doc
brief: 规划链节指令——需求重述（做/不做显式清单）+ 拆链定产物名 + blueprint.md 固定三段输出 + 超契约范围判 escalate。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [WF5-Contract-Lock]
invariants:
  - {type: content_contains, value: "# plan — 规划链节指令"}
  - {type: content_contains, value: "blueprint.md"}
  - {type: content_contains, value: "escalate"}
acceptance:
  - blueprint.md 三段固定结构（范围/链定义/依赖）, 产物名与责任链表逐字一致
  - 指令自包含可独立执行, 不做实现只做事拆解
anti_patterns: [规划链节顺手做实现]
```

```yaml
path: prompts/execute.instruction.md
type: doc
brief: 执行链节指令——追溯（需求项对实现位置）+ 实现 + 逐项证据存 evidence/ + traceability-map.md 映射表 + fork 会话自评。
deps: [CLAUDE.md, prompts/plan.instruction.md]
read_first: [CLAUDE.md]
materializes: [WF5-Contract-Lock]
invariants:
  - {type: content_contains, value: "# execute — 执行链节指令"}
  - {type: content_contains, value: "traceability-map.md"}
  - {type: content_contains, value: "evidence/"}
acceptance:
  - 输出两件缺一不可: 映射表 + 证据目录, 一项一证据文件
  - 只做实现不做质量验证（验证是 verify 链节职责）
anti_patterns: [执行链节自我验证即交付]
```

```yaml
path: prompts/verify.instruction.md
type: doc
brief: 验证链节指令——逐项重放证据（不采信表面存在）+ 三级分级（confirmed/denied/not_verifiable）+ verification-map.md + 判定映射表。
deps: [CLAUDE.md, prompts/execute.instruction.md]
read_first: [CLAUDE.md]
materializes: [WF5-Contract-Lock]
invariants:
  - {type: content_contains, value: "# verify — 验证链节指令"}
  - {type: content_contains, value: "verification-map.md"}
  - {type: content_contains, value: "confirmed"}
acceptance:
  - 验证行数与上游需求项数一致不漏项, denied 项全附期望 vs 实际
  - 判定映射规则显式（全 confirmed→pass, 有 denied→needs_rework）
anti_patterns: [未重放证据即标 confirmed]
```
