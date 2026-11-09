---
name: audit-report
description: "审查报告汇总。合并三路扫描 findings 为 audit-report.md。"
version: "1.0.0"
---
# audit-report

输入三份 findings JSON, 按命名/注释/重复三节组织, 末行总结各节计数; 调度方以 scripts/aggregate.sh 承载确定性合并。

用法: bash scripts/aggregate.sh <naming.json> <comment.json> <duplication.json> <report.md>; 确定性合并三路 findings。
