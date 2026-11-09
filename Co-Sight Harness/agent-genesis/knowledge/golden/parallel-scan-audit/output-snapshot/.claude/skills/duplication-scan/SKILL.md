---
name: duplication-scan
description: "重复代码扫描。检测连续重复行块, 输出 findings。"
version: "1.0.0"
---
# duplication-scan

规则: 同文件内 ≥3 行连续重复的块记为候选重复代码（起止行号 + 摘录首行）。

用法: bash scripts/scan.sh <目标目录> <输出路径>; 输出 findings JSON 数组（path/line/rule/excerpt）。
