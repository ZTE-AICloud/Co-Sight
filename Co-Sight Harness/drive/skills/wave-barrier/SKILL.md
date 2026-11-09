---
name: wave-barrier
description: Use when a wave's worker summaries need aggregation with strict task-id parity check against waves.yaml. Activated by executor after completing the last task in a wave.
user-invocable: false
---

# Wave Barrier

## 调用的命令

| 命令 | 作用 | 入参 | 输出 | 失败模式 |
|---|---|---|---|---|
| `aggregate` | 把 worker summary 聚合成 state 字段，写 `<planning-dir>/executeState.json` | `--planning-dir` (required), `--wave <n>` (required), `--summaries` / `--summaries-file` / `--stdin` (三选一) | Envelope `data.{wave_n, writeback_ok, barrier_enforced, ...}` | `wave_mismatch` / `empty_fsdiff` / `writeback_failed` / `empty_summaries` |

## 命令契约

### aggregate

调用前：本 wave 的 worker 全部已返回 summary；executor 已收到完整 summaries 数组。

入参（三选一传 summaries）：

- `--planning-dir <dir>`（必填）
- `--wave <n>`（必填）：当前 wave 序号
- `--summaries '<json-array>'` / `--summaries-file <path>` / `--stdin`：summary 数组传入方式

调用后：

1. 折 N 条 summary → `task_results`（含 status/duration_sec/files_changed/attempts）+ `wave_summaries`（当前 wave 的聚合统计）
2. 与 `<planning-dir>/waves.yaml` 当前 wave 的 task_id 集合**强比对**：缺 / 多 / 重复 → `wave_mismatch`，**不写 state**
3. fs diff barrier：状态为 done 的 summary 若 `files_changed` 空 → `empty_fsdiff`，**不写 state**
4. 经 state_cli 写进 `executeState.json`（先读旧值合并，避免覆盖前 wave）

stdout 打印 Envelope JSON。Exit 0 = 写成功 + barrier 通过。

失败模式：

- `wave_mismatch` → `details.{missing, extras, duplicates}` 列出不对齐的 task。**不写 state**。主对话据此补派或确认。
- `empty_fsdiff` → worker 报完成但 `files_changed` 空。**不写 state**。重派或确认任务确实不应改文件。
- `writeback_failed` → state_cli 调用失败。`details.{stderr, stdout, exit_code}` 列出原因。**不写 state**。
- `waves_file_missing` → 没 waves.yaml，barrier 不强制（降级通过），响应里 `barrier_enforced: false` 标记。**仍写 state**。
- `empty_summaries` → summaries 列表为空，**不写 state**。

## Gotchas

- 本脚本**不读** `taskRecord.yaml`、**不碰** `current_wave`（主 agent 的活）、**不派** subagent。
- **不重试** barrier 失败——maxTurns 耗尽前的优先级始终是先写 SUMMARY.md / summary JSON / commit，barrier 记账失败是次要，主对话看到失败决定补派谁。
- `attempts` 字段：worker 报完成前的尝试次数（含最后一次成功）。worker 自己计数；orchestrator 收到 `attempts > 1` 时可在 run-log 留一笔便于审计"这个 task 之前挣扎过"。
- `--summaries` 内联参数适合小数据（≤10 task），大数据用 `--summaries-file` 或 `--stdin`。

## 调用前 Checklist

- [ ] 本 wave 所有 worker 已返回 summary
- [ ] summaries 数组非空
- [ ] `--wave` 序号与当前 wave 一致
- [ ] summaries 传入方式已选定（`--summaries` / `--summaries-file` / `--stdin`）
- [ ] barrier 失败的 fallback 路径已知（主对话层决策：补派 vs 重试 vs 跳过）