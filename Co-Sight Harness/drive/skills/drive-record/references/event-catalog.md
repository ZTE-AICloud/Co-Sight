# run-log.jsonl Event Catalog

> `run-log.jsonl` 已知事件类型清单。与 `scripts/timeline_builder.py` 的 `_EVENT_TAG_MAP` 同步。
> 当 drive runtime 新增事件类型时，同步改本文件 + `_EVENT_TAG_MAP`。

每个事件 1 行 JSON：`{"ts": "<iso8601>", "event": "<type>", ...}`。

## 已知事件类型

| event | 触发时机 | 关键字段 | timeline tag |
| --- | --- | --- | --- |
| `drive_startup` | drive 启动 plan 时 | `plan_name`, `plan_dir`, `pid` | `startup` |
| `stage_advanced` | stage 转换时 | `from`, `to` | `stage` |
| `agent_spawned` | subagent 启动时 | `subagent_type`, `description`, `session_id`, `state_revision_at_spawn` | `agent` |
| `agent_completed` | subagent 完成时 | `subagent_type` | `agent` |
| `gate_triggered` | 等待用户输入时 | `gate`, `name` | `gate` |
| `gate_resolved` | 用户响应 gate 时 | `gate`, `name`, `decision`, `response` | `gate` |
| `transition_with_verdict` | 含 verdict 的 stage 转换时 | `from`, `to`, `verdict` | `verdict` |
| `drive_completed` | drive 完成 plan 时 | `verdict` | `end` |

## 关键事件（缺失 = HIGH gap）

`gaps_detector.py` 的 `KEY_EVENT_TYPES` 含 3 个：

- `drive_startup` —— 缺 = 没开始记录
- `stage_advanced` —— 缺 = 阶段流转未追踪
- `drive_completed` —— 缺 = 结束未追踪

`stage_advanced` 次数 < 4 触发 MEDIUM gap（一次正常完成含 4 次：start→analyze→plan→execute→evaluate）。

## 关联字段

- `session_id` 仅在 `agent_spawned` 出现 → 用于 §5 session 定位
- `state_revision_at_spawn` 仅在 `agent_spawned` 出现 → 用于 §B `revision_gap` 检测

## 加新事件类型的流程

1. 在 `_EVENT_TAG_MAP` 加映射（驱动 timeline 显示）
2. 在本表加一行
3. 如果是关键事件（缺则阻断审计），同步加到 `KEY_EVENT_TYPES`

**禁止**不写 mapper 只在 catalog 列条目 —— catalog 是 timeline_builder.py 的 mirror。