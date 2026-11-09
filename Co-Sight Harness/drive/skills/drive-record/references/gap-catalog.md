# Gap Catalog

> 9 类完整性 + 一致性 gap 的 source-of-truth。与 `scripts/gaps_detector.py` 一一对应。
> 当 detector 增/改时，同步改本文件。

`drive-record` 检测 `.drive/<plan_dir>/` 运行时记录的完整性 + 一致性问题，结果内嵌在 `REPORT.md §B`。

| 类型 code | 严重度 | 含义 | drive 修复点 |
| --- | --- | --- | --- |
| `missing_file` | HIGH / LOW | Runtime SDK 产物缺失 → HIGH；LLM 契约产物缺失 → LOW | runtime 启动检查 / 对应 agent .md |
| `missing_event` | HIGH/MEDIUM | `run-log.jsonl` 缺关键事件（`drive_startup` / `stage_advanced` / `drive_completed`）或 `stage_advanced` 次数 < 4 | `state_cli.py` 调用点 |
| `missing_summary` | MEDIUM | `task_results.<id>.status=ok` 但 `artifacts/<id>/SUMMARY.md` 不存在 | executor 协议 |
| `revision_gap` | CRITICAL | `executeState.json.revision` 落后于 `run-log.jsonl` 中 `agent_spawned` 记录的 `state_revision_at_spawn` | `state_write.py` 的 fcntl 锁逻辑 |
| `timestamp_anomaly` | MEDIUM | `run-log.jsonl` 中事件时间戳出现倒序（违反 append-only 时间单调） | `audit_append.py` |
| `pending_confirmation_stuck` | HIGH | `pending_confirmation` 字段非空但 `updated_at` 超过 1 小时前未推进 | drive 调度逻辑 |
| `unmapped_state_field` | LOW | `executeState.json` 含 drive-2.3 schema 未声明的字段（schema drift 信号） | runtime 版本管理 |
| `stale_running_agent` | HIGH | `agent_invocations.<task_id>.<reviewer>.status=running` + `started_at` 距今 > 30min（reviewer 卡死）；HITL 决策路径，不自动改 state | review 流程 / drfit detector 阈值 |

## 严重度判定原则

- **CRITICAL**：data correctness 受影响（`revision_gap` 表明状态机锁可能失效，后续 update 走错基础）
- **HIGH**：Runtime SDK 通道产物缺失，或 `pending_confirmation` 卡住 — 用户可见的 record 不完整
- **MEDIUM**：可能影响调试但不阻断审计（`missing_summary` / `timestamp_anomaly` / 关键事件缺 / stage_advanced 次数不足）
- **LOW**：LLM 契约产物缺失（agent 没自觉写）或 schema drift 早期信号 — 无需立即修

## 排序

`detect_gaps()` 返回时按 `(severity_rank, type)` 排序，便于 reviewer 自上而下扫。rank 顺序：

```
CRITICAL → HIGH → MEDIUM → LOW
```

## 加新 gap 类型的流程

1. 在 `gaps_detector.py` 写 detector（返回 `Iterable[Gap>`，命名 `_detect_<type>`）
2. 把 detector 加入 `detect_gaps()` 的 extend 链
3. 在本表加一行
4. 加一个对应测试（参考 `test_gaps_detector.py`）

**禁止**不写 detector 只在 catalog 列条目 —— catalog 是真相源的 mirror，不是预想。