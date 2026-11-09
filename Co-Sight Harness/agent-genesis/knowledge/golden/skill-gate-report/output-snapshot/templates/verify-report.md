# 验证报告 — gate-suite-report

<!--
  固定三段结构: ①总判定 ②逐套件结果表 ③失败明细。
  落盘路径: .agent-genesis/verify-report.md（仓库根相对）。
  所有占位符 <...> 在产出时替换为实际值; 禁止增删段落或改变段落顺序。
-->

## 1. 总判定

- 生成时间: <ISO 8601 时间戳, 格式 YYYY-MM-DDTHH:MM:SSZ>
- 总判定: <ALL PASS | FAIL>
- 统计: <pass=N fail=N error=N> / 7

## 2. 逐套件结果表

| # | 类型 | 脚本路径 | 状态 | exit code | ✓ 数 | ✗ 数 | 原始日志 |
|---|------|----------|------|-----------|------|------|----------|
| 1 | 套件 | tests/gates/g028-static-verify.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |
| 2 | 套件 | tests/gates/legacy-compat-verify.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |
| 3 | 套件 | tests/gates/runner-assets-verify.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |
| 4 | 套件 | tests/gates/stage1-verify.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |
| 5 | 套件 | tests/gates/stage3-verify.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |
| 6 | 机检 | scripts/check-gate-registry.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |
| 7 | 机检 | scripts/check-legacy-names.sh | <PASS\|FAIL\|ERROR> | <n> | <n> | <n> | <runs/<ts>/...log> |

注: 状态=ERROR 仅在脚本文件缺失时出现（fail-closed, 计入总判定 FAIL）。

## 3. 失败明细

<!-- 每条失败按以下格式逐条列出, ✗ 行保持原文不转述; 全部通过时写"无失败项" -->

### <套件名> (<n> 项失败)

- 套件: <被执行脚本的仓库根相对路径>
- 失败行原文:
  - ✗ <原文逐字收录>
  - ✗ <原文逐字收录>
<!-- 机检项的 BAN/FAIL 行同样逐字收录于此段 -->
