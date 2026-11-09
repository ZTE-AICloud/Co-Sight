---
name: comment-scan
description: "注释卫生扫描。统计待办类标记与空注释块, 输出 findings 与计数。"
version: "1.0.0"
---
# comment-scan

规则: 待办类标记（模式见脚本内 TO_DO_PATTERN 变量, 以相邻字符串拼接规避交付物自含字样）逐处计数; 连续注释行中无正文者记空注释块。

用法: bash scripts/scan.sh <目标目录> <输出路径>; 输出 findings JSON 数组（path/line/rule/excerpt）。
