# G005 — 占位符门禁（默认）

gate_id: G005-no-placeholders
type: condition_check
blocking: true
retry_count: 3

## 判定条件

`placeholder_count == 0`

## 扫描范围

全部产物文件（`output/agents/pr-security-reviewer/v1/` 下）：

- `TODO` / `TBD` / `FIXME` / `XXX`
- `{{placeholder}}` / `{{ }}` / `<<placeholder>>`
- `...待补充` / `...待定` / `待实现`

## 失败回退

定位含占位符的文件与位置 → 替换为实际内容 → 重检 ≤3 轮；超限 → 阻断。