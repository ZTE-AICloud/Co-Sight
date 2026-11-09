---
plan_id: fast-pr-security-scan
plan_version: "2.0"
mode: greenfield
generated_at: 2026-10-15T00:00:00Z
selected_patterns: [G1]
basis: []
template_variables:
  readiness_threshold: 58
  write_scope_dir: reports/
---

# fast 极简 build-plan（正例 fixture）

> fast-lane-builder 产出形态样例（FA 验证门锚定件）: schema 全字段 + generate/copy/template
> 三类条目。generate 类 = builder 单轮生成; copy/template 类 = g025 物化（零 LLM）。
> 产物基准 = tests/gates/g028-static-verify.sh build_product fixture。

## 决策物化（增量表——唯一增量是路径绑定）

```yaml
materialization:
  - pattern_id: G1
    target_files:
      - CLAUDE.md
      - proposal-spec.md
      - .claude/skills/pr-review/SKILL.md
      - .claude/agents/scan-worker.md
```

## 文件清单

```yaml
path: CLAUDE.md
type: claude_md
generation: generate
deps: []
read_first: []
materializes: [G1]
brief: >
  运行时主交付总览——说明 harness 职责、目录结构与调度入口，供用户 cd 后首个阅读，含自检命令、常见入口速查与故障回退指引。
invariants:
  - {type: content_contains, pattern: "pr-security-scan"}
acceptance:
  - "CLAUDE.md 含结构段且引用 workflow 与 skills 路径"
anti_patterns: []
```

```yaml
path: proposal-spec.md
type: other
generation: generate
deps: []
read_first: []
materializes: [G1]
brief: >
  轻量构建方案——概述、核心能力、交付计划、风险与审批要点，是 fast 交付的方案面文档，供审批人快速裁决与留档追溯。
invariants:
  - {type: content_contains, pattern: "核心能力"}
acceptance:
  - "proposal-spec 含概述与核心能力两节"
anti_patterns: []
```

```yaml
path: .claude/skills/pr-review/SKILL.md
type: skill
generation: generate
deps: [CLAUDE.md]
read_first: []
materializes: [G1]
brief: >
  扫描技能定义——frontmatter 触发描述与用法说明，调用 scripts/run.sh 对 diff 做安全扫描，输出按维度归类的 findings 列表。
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
acceptance:
  - "SKILL.md frontmatter 双字段非空"
anti_patterns: []
```

```yaml
path: .claude/agents/scan-worker.md
type: subagent
generation: generate
deps: [CLAUDE.md]
read_first: []
materializes: [G1]
brief: >
  只读扫描子代理——按规则清单扫描 diff 产出 findings，独立上下文防止读取复核结论，命中即写结构化证据。
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: tools}
  - {type: frontmatter_field_nonempty, field: forbidden_inputs}
acceptance:
  - "subagent 定义四必填字段非空"
anti_patterns: []
```

```yaml
path: phase/gates/G003-readiness-score.md
type: gates_yaml
generation: template
source: assets/templates/gates/G003-readiness-score.md
deps: []
read_first: []
materializes: []
brief: >
  门禁文档（模板物化）——就绪度分数门禁说明，由 g025 渲染 assets/templates 模板产。
invariants: []
acceptance:
  - "模板渲染后 readiness_threshold 已替换为具体数值"
anti_patterns: []
```

```yaml
path: phase/gates/G005-no-placeholders.md
type: gates_yaml
generation: template
source: assets/templates/gates/G005-no-placeholders.md
deps: []
read_first: []
materializes: []
brief: >
  占位符门禁文档（模板物化）——零变量模板; 模板为无字样描述法（自指矛盾修复后形态）,
  物化产物须能过占位符门禁自身（防复发锚定）。
invariants: []
acceptance:
  - "物化产物过 g005 零命中"
anti_patterns: []
```

```yaml
path: .claude/settings.json
type: settings
generation: template
source: assets/templates/settings/settings.json.template
deps: []
read_first: []
materializes: []
brief: >
  工作区设置（模板物化）——写权限范围由 write_scope_dir 变量注入，g025 渲染产。
invariants: []
acceptance:
  - "settings.json 为合法 JSON 且 write_scope_dir 已注入"
anti_patterns: []
```

```yaml
path: .claude/rules/security.md
type: rule
generation: copy
source: knowledge/assets/rules/security.md
deps: []
read_first: []
materializes: []
brief: >
  通用安全规则（确定性直拷）——插件知识资产逐字复制，不进入 LLM 生成循环。
invariants: []
acceptance:
  - "与源文件逐字一致"
anti_patterns: []
```
