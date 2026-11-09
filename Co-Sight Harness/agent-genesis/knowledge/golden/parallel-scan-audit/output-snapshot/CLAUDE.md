# code-style-auditor

代码规范审查 harness。对任意项目目录做三维度通用文本规则扫描（命名风格 / 注释卫生 / 重复代码），汇总为 audit-report.md。

## 结构
- workflow: phase/02-workflows/main-flow.md
- 扫描技能: .claude/skills/naming-scan / comment-scan / duplication-scan（各含 scripts/scan.sh）
- 汇总技能: .claude/skills/audit-report（scripts/aggregate.sh 合并三路 findings）
- 复核: phase/review/finding-review.md
- 门禁: phase/gates/G003-readiness-score.md 与 phase/gates/G005-no-placeholders.md
- 规则: .claude/rules/security.md

## 使用
告诉 Claude 要审查的目录路径即可（例: "审查 ./src"）。只读扫描，绝不修改被审查目录。
