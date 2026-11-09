# 主流程

步骤 1: 确认目标目录存在且含可扫描文本文件; 不存在则报错退出（不产空报告）。
步骤 2: 依次调度 naming-scan / comment-scan / duplication-scan, 各自产出 findings JSON 到 work 目录。
步骤 3: 调度 audit-report 的 aggregate.sh 合并三路 findings, 写 audit-report.md（命名/注释/重复三节 + 总结行）。
步骤 4: 单文件读取失败的项跳过并在报告"跳过清单"记录, 不中断整体扫描。
