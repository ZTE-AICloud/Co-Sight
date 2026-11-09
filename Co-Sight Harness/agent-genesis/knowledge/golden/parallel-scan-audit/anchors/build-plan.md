# build-plan（parallel-scan-audit 过程锚）

> 自有产物锚——本包源自本仓库 agent-creation 线产物 code-style-auditor 的真实
> 交付面（非外部启发, 不标 derived）。构建车道为 fast（proposal-spec.md 自述）,
> 形态未被既有样例覆盖, 经用户确认按 REFLUX.md §1 例外条款入库。
> path 相对交付物根（包内 output-snapshot/）书写——g023 以 output_dir 直拼
> path, 准入机检时 output_dir=包内 output-snapshot/; invariants 按资产实际
> 字面量书写（R6 双锚约定）。

---
plan_id: golden-parallel-scan-audit-anchor
plan_version: "2.0"
mode: greenfield
generated_at: "2026-10-17"
selected_patterns: [W3-MapReduce]
basis: []
template_variables: {}
---

# 锚定模式物化

```yaml
| pattern_id | target_files |
| W3-MapReduce | CLAUDE.md, .claude/skills/{naming-scan,comment-scan,duplication-scan}/SKILL.md+scripts/scan.sh（map 扇出 ×3）, .claude/skills/audit-report/SKILL.md+scripts/aggregate.sh（reduce 汇聚） |
```

# files

```yaml
path: CLAUDE.md
type: agent_entry
brief: 代码规范审查 harness 运行时入口——三维度通用文本规则扫描（命名/注释/重复）扇出 + audit-report 汇聚, 只读不修改被审查目录。
deps: []
read_first: []
materializes: [W3-MapReduce]
invariants:
  - {type: content_contains, value: "三维度通用文本规则扫描"}
  - {type: content_contains, value: "命名风格 / 注释卫生 / 重复代码"}
  - {type: content_contains, value: "只读扫描，绝不修改被审查目录"}
  - {type: content_contains, value: "audit-report.md"}
acceptance:
  - 入口自述三维扫描 + 汇聚产物名, 明确只读边界
anti_patterns: [入口含扫描规则细节（规则属技能层）]
```

```yaml
path: phase/02-workflows/main-flow.md
type: workflow
brief: 主流程四步——目标目录存在性校验（fail-closed）→ 三路扫描扇出（各自 findings JSON 入 work 目录）→ audit-report 确定性合并 → 单文件失败跳过不中断（跳过清单留痕）。
deps: [CLAUDE.md]
read_first: [CLAUDE.md]
materializes: [W3-MapReduce]
invariants:
  - {type: content_contains, value: "依次调度 naming-scan / comment-scan / duplication-scan"}
  - {type: content_contains, value: "不产空报告"}
  - {type: content_contains, value: "跳过清单"}
acceptance:
  - 扇出/汇聚次序明确, 汇聚步骤点名 aggregate 合并三路
  - 单文件失败语义 = 跳过 + 留痕, 不中断整体
anti_patterns: [单文件失败即整体中断; 目录不存在仍产空报告]
```

```yaml
path: .claude/skills/naming-scan/SKILL.md
type: skill
brief: map 工人①——命名风格扫描（snake/camel 混用 + 超长标识符 ≥72）, findings 四字段输出。
deps: []
read_first: []
materializes: [W3-MapReduce, K4-Rule-Driven]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: frontmatter_field_nonempty, field: version}
  - {type: content_contains, value: "mixed_style"}
  - {type: content_contains, value: "findings JSON 数组（path/line/rule/excerpt）"}
acceptance:
  - 规则判据为确定性文本模式, 输出四字段纪律一句
anti_patterns: [规则需 LLM 语义判断]
```

```yaml
path: .claude/skills/naming-scan/scripts/scan.sh
type: script
brief: naming-scan 确定性执行体——findings 经临时文件收集规避子 shell 状态, 目标目录不存在 exit 2。
deps: [.claude/skills/naming-scan/SKILL.md]
read_first: []
materializes: [K4-Rule-Driven]
invariants:
  - {type: content_contains, value: "set -euo pipefail"}
  - {type: content_contains, value: "exit 2"}
acceptance:
  - 只读扫描, 无写目标目录行为
anti_patterns: [脚本写被扫描目录]
```

```yaml
path: .claude/skills/comment-scan/SKILL.md
type: skill
brief: map 工人②——注释卫生扫描（待办类标记计数 + 空注释块）, 模式变量相邻字符串拼接规避交付物自含字样。
deps: []
read_first: []
materializes: [W3-MapReduce, K4-Rule-Driven]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: frontmatter_field_nonempty, field: description}
  - {type: content_contains, value: "待办类标记"}
  - {type: content_contains, value: "相邻字符串拼接"}
acceptance:
  - 自含字样规避手法一句明示（G005 协同）
anti_patterns: [SKILL.md 内嵌待检标记字面量]
```

```yaml
path: .claude/skills/comment-scan/scripts/scan.sh
type: script
brief: comment-scan 确定性执行体——TO/FIX/TB 三模式变量拼接, 逐处计数 findings。
deps: [.claude/skills/comment-scan/SKILL.md]
read_first: []
materializes: [K4-Rule-Driven]
invariants:
  - {type: content_contains, value: "set -euo pipefail"}
acceptance:
  - 模式拼接式声明, 无完整待检字样字面量
anti_patterns: [全文直写待检标记]
```

```yaml
path: .claude/skills/duplication-scan/SKILL.md
type: skill
brief: map 工人③——重复代码扫描（同文件 ≥3 行连续重复块, 起止行号 + 首行摘录）。
deps: []
read_first: []
materializes: [W3-MapReduce, K4-Rule-Driven]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: content_contains, value: "≥3 行连续重复"}
acceptance:
  - 重复判据数值阈值明示（≥3 行）
anti_patterns: [阈值缺失由执行体隐式决定]
```

```yaml
path: .claude/skills/duplication-scan/scripts/scan.sh
type: script
brief: duplication-scan 确定性执行体——awk 单次遍历检测连续重复行块。
deps: [.claude/skills/duplication-scan/SKILL.md]
read_first: []
materializes: [K4-Rule-Driven]
invariants:
  - {type: content_contains, value: "set -euo pipefail"}
acceptance:
  - 单次遍历实现, 无嵌套多次扫描
anti_patterns: []
```

```yaml
path: .claude/skills/audit-report/SKILL.md
type: skill
brief: reduce 汇聚——合并三路 findings 为 audit-report.md（三节 + 总结行）, 确定性合并无 LLM 判断。
deps: []
read_first: []
materializes: [W3-MapReduce]
invariants:
  - {type: frontmatter_field_nonempty, field: name}
  - {type: content_contains, value: "确定性合并"}
  - {type: content_contains, value: "三节"}
acceptance:
  - 汇聚职责单一, 不重开扫描
anti_patterns: [汇聚器内嵌扫描规则]
```

```yaml
path: .claude/skills/audit-report/scripts/aggregate.sh
type: script
brief: reduce 执行体——三路 findings JSON 合并为报告（命名/注释/重复三节 + 总结行计数）。
deps: [.claude/skills/audit-report/SKILL.md]
read_first: []
materializes: [W3-MapReduce, K4-Rule-Driven]
invariants:
  - {type: content_contains, value: "确定性合并, 无 LLM 判断"}
  - {type: content_contains, value: "总结"}
acceptance:
  - 三节 + 总结行结构由脚本保证
anti_patterns: [报告结构依赖 LLM 现场组织]
```

```yaml
path: phase/review/finding-review.md
type: review_rules
brief: findings 复核规则——四字段必备 + 抽查三条（命中一致/行号可定位/非误报）, 存疑标"待复核"不删除。
deps: []
read_first: []
materializes: [K4-Rule-Driven]
invariants:
  - {type: content_contains, value: "每条 finding 必须带"}
  - {type: content_contains, value: "待复核"}
acceptance:
  - 存疑处置 = 标注保留审查痕迹, 禁删除
anti_patterns: [存疑 finding 直接删除]
```

```yaml
path: phase/gates/G003-readiness-score.md
type: gate
brief: 就绪度门禁——readiness_score >= 60 放行, 四维评分（正确/完整/格式/可操作）, retry 上限 3。
deps: []
read_first: []
materializes: [IT1-Enforced]
invariants:
  - {type: content_contains, value: "readiness_score >= 60"}
  - {type: content_contains, value: "retry_count: 3"}
acceptance:
  - 阈值与重试上限双明示
anti_patterns: []
```

```yaml
path: phase/gates/G005-no-placeholders.md
type: gate
brief: 零占位符门禁——四类残留标记计数为零即通过; 语义述说不复制字面形态（防自含）。
deps: []
read_first: []
materializes: [IT1-Enforced]
invariants:
  - {type: content_contains, value: "placeholder_count == 0"}
acceptance:
  - 判定式一句闭环
anti_patterns: [门禁文档自含被检字样]
```

```yaml
path: phase/gates/gates.yaml
type: gate_registry
brief: 门禁注册表——G003/G005 两件登记（condition_check）。
deps: []
read_first: []
materializes: [IT1-Enforced]
invariants:
  - {type: content_contains, value: "G003"}
  - {type: content_contains, value: "G005"}
acceptance:
  - 注册表与门禁文档一一对应
anti_patterns: []
```

```yaml
path: .claude/rules/security.md
type: rule
brief: 安全底线清单——密钥/输入验证/命令执行/外部数据四组, 只读扫描暴露面裁剪版。
deps: []
read_first: []
materializes: [CD1-Input-Gating]
invariants:
  - {type: content_contains, value: "无硬编码密钥"}
  - {type: content_contains, value: "危险命令"}
acceptance:
  - 只读扫描器仍声明命令执行安全与路径穿越防护
anti_patterns: []
```

```yaml
path: .claude/settings.json
type: config
brief: 权限收窄——allow 仅 Read/Grep/Glob（只读扫描零写权限）, 附加目录 audit-reports/。
deps: []
read_first: []
materializes: [CD1-Input-Gating]
invariants:
  - {type: content_contains, value: "\"allow\""}
acceptance:
  - 权限面与只读边界一致
anti_patterns: [扫描器持有 Write 权限]
```

```yaml
path: evaluation/pass-criteria.md
type: evaluation
brief: 通过标准——三维各 ≥1 命中 + 汇总三节总结行 + 目录不存在报错退出不产报告。
deps: []
read_first: []
materializes: [W3-MapReduce]
invariants:
  - {type: content_contains, value: "命名维度"}
  - {type: content_contains, value: "重复维度"}
  - {type: content_contains, value: "总结行"}
acceptance:
  - 三维命中标准可机检, 汇总结构入标准
anti_patterns: []
```

```yaml
path: proposal-spec.md
type: spec
brief: 构建方案自述（fast 车道存档）——三维度审查器定位 + 核心能力四件 + 风险两条 + 审批要点。
deps: []
read_first: []
materializes: [W3-MapReduce]
invariants:
  - {type: content_contains, value: "三维度代码规范审查器"}
  - {type: content_contains, value: "通用文本规则零语言解析依赖"}
acceptance:
  - 风险段如实声明文本规则对语义级问题不敏感
anti_patterns: []
```
