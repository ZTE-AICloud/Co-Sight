# build-plan（skill-router 过程锚, derived）

> derived: true——外部启发过程锚（源自 waza 重塑）, 非真实构建产物。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼 path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按改造后资产实际字面量书写（R6 双锚约定）。

---
plan_id: golden-skill-router-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-16"
selected_patterns: [W2-Router]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| W2-Router | SKILL.md, references/routing-table.md, references/disambiguation-rules.md, references/fat-vs-script.md |
```

# files

```yaml
path: SKILL.md
type: skill
brief: 路由与分发主 Skill——四机制（阶段分路路由表/特异性消歧/手动链式/fat-vs-script 决策框架）+ When to Use + Execution Steps + Not for。
deps: []
read_first: []
materializes: [W2-Router]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "references/routing-table.md"}
  - {type: content_contains, value: "references/disambiguation-rules.md"}
  - {type: content_contains, value: "references/fat-vs-script.md"}
acceptance:
  - 四机制各有一段专述且互相不重复
  - 链式调用默认手动, 仅明确授权时例外
anti_patterns: [路由写成语义猜测而非查表]
```

```yaml
path: references/routing-table.md
type: doc
brief: 阶段分路路由表 L3 参考——四段骨架（动手前/交付前/出问题/内容进出）+ 触发列写法与维护规则。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "### 动手前（Pre-build）"}
  - {type: content_contains, value: "### 交付前（Post-build）"}
  - {type: content_contains, value: "### 出问题（Diagnostic）"}
  - {type: content_contains, value: "### 内容进出（Content）"}
acceptance:
  - 四段骨架齐全, 每段含触发/目标两列表
anti_patterns: [内部术语当触发词]
```

```yaml
path: references/disambiguation-rules.md
type: doc
brief: 消歧规则集 L3 参考——IF-THEN 格式、特异性排序、五条经典规则类型、兜底规则（排除法+追问, 禁猜测）。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "IF <具体可观察条件> THEN route to <具体能力>"}
  - {type: content_contains, value: "兜底规则（永远最后）"}
  - {type: content_contains, value: "误路由的代价高于不路由"}
acceptance:
  - 规则按特异性从高到低排列, 兜底规则位于末尾
anti_patterns: [抽象条件（如"如果比较复杂"）]
```

```yaml
path: references/fat-vs-script.md
type: doc
brief: 能力边界决策框架 L3 参考——决策树、两个反模式（全 Skill 化/全脚本化）、判据表、混合形态边界声明。
deps: [SKILL.md]
read_first: [SKILL.md]
materializes: [W2-Router]
invariants:
  - {type: content_contains, value: "同入同出 / 只是校验和列举？"}
  - {type: content_contains, value: "全 Skill 化"}
  - {type: content_contains, value: "全脚本化"}
acceptance:
  - 决策树两分支各配正例, 反模式各有一句代价说明
anti_patterns: [把判断塞进脚本规则组合爆炸]
```
