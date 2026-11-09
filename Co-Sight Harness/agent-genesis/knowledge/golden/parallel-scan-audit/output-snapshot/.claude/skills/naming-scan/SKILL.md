---
name: naming-scan
description: "命名风格扫描。对目标目录代码文件做标识符风格混用与超长标识符检测, 输出 findings。"
version: "1.0.0"
---
# naming-scan

规则: 同文件内 snake_case 与 camelCase 标识符并存记混用; 标识符长度 ≥72 记超长。

用法: bash scripts/scan.sh <目标目录> <输出路径>; 输出 findings JSON 数组（path/line/rule/excerpt）。
