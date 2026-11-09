---
gate_id: G005
gate_type: condition_check
name: "无残留占位符"
condition: "placeholder_count == 0"
blocking: true
retry_count: 3
retry_strategy: fixed
scope: plan
---

## 检查项
- 无 `{{PLACEHOLDER}}` / `{{...}}` 模板变量残留
- 无 `TODO` / `TBD` / `FIXME` / `待定` 标记

## 失败行为
发现占位符 → AUTO_FIX ≤ 3 轮。超限 → REPORT_TO_USER。
