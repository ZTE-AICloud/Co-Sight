# 9 个 Runtime 记录文件的 Schema

> drive-2.3 当前 schema。与 `scripts/record_reader.py` + `scripts/gaps_detector.py:KNOWN_STATE_FIELDS` 同步。
> 当 drive runtime 改字段时，同步改本文件 + `KNOWN_STATE_FIELDS` 常量。

drive-record 只读这些字段，**不**强依赖；字段缺失 = 兼容（用默认空值）+ 可能触发 `unmapped_state_field` LOW gap。

按写入方分两组：

- **Runtime SDK 通道**（6 个，drive runtime 保证一定有，除非 runtime 中断）：
  `run-meta.json` / `intent.md` / `waves.yaml` / `topo-state.json` / `executeState.json` / `run-log.jsonl`
- **LLM 契约**（3 个，靠 agent 自觉写）：
  `manifest.md` / `taskRecord.yaml` / `evaluation/verification-report.md`

外加每 task 一份的 `artifacts/<task_id>/SUMMARY.md`（executor agent 写）。

## 1. run-meta.json

```json
{
  "schema_version": "drive.runtime.run_meta.v1",
  "plan_name": "fix-import-deadlock",
  "plan_dir": "plan-20260818-0930-...",
  "git_head": "abc1234",
  "git_branch": "main",
  "workflow_hash": "sha256:...",
  "input_digests": {},
  "started_at": "2026-08-18T09:30:00Z",
  "worktree": "/path/to/worktree"
}
```

写入方：`init_planning.py`。

## 2. intent.md

自然语言 markdown，描述这次 drive 的意图。drive-record 仅展示首行。

写入方：`init_planning.py`。

## 3. manifest.md

```markdown
# Manifest
complexity: standard
## Requirements
- R1: ...
- R2: ...
```

drive-record 仅展示首行。

写入方：`analyzer` agent（LLM）。

## 4. taskRecord.yaml

```yaml
plan_id: plan-...
tasks:
  - id: plan-...-T01
    title: ...
    agent: executor
    depends_on: []
    spec_ref: ...
```

写入方：`planner` agent（LLM）。

## 5. waves.yaml

```yaml
plan_id: plan-...
waves:
  - wave_idx: 1
    agents: [researcher]
  - wave_idx: 2
    agents: [summarizer]
    depends_on: [1]
```

DAG mode 专属。phase mode 文件可空。

写入方：`topo_sort.py schedule-waves`（确定性脚本）。

## 6. topo-state.json

```json
{
  "plan_id": "plan-...",
  "waves": [{"wave_idx": 1, "tasks": ["..."]}],
  "budget": {...}
}
```

写入方：`topo_sort.py schedule-waves`（与 waves.yaml 同次写）。

## 7. executeState.json

drive-2.3 schema（不是 stale 的 `state-machine/SKILL.md`）：

```json
{
  "schema_version": "drive.runtime.state.v1",
  "revision": 12,
  "active_stage": "execute",
  "status": "executing",
  "current_wave": 2,
  "waves_total": 3,
  "next_action": null,
  "confirmed_stages": ["start", "analyze", "plan"],
  "pending_confirmation": null,
  "created_at": "...",
  "updated_at": "...",
  "verdict": "pass",
  "active_agents": [
    {"id": "...", "status": "running", "started_at": "..."}
  ],
  "task_results": {
    "plan-...-T01": {"status": "completed", "files_changed": ["src/foo.ts"], "duration_sec": 412}
  },
  "wave_summaries": {
    "1": {"status": "ok", "completed_at": "..."}
  },
  "mode": "phase"
}
```

### `KNOWN_STATE_FIELDS`（drive-record 列出的合法字段）

> 修改本表时，同步改 `gaps_detector.py:KNOWN_STATE_FIELDS`。

```
schema_version, revision, active_stage, status,
current_wave, waves_total, task_results,
wave_summaries, next_action, confirmed_stages,
pending_confirmation, created_at, updated_at,
verdict, active_agents, mode, agent_invocations
```

### 注意

- **stale doc fields**（`pending_plan_review` / `hits_paused` / `progress`）来自旧版 state-machine/SKILL.md；当前 drive-2.3 不再用。出现 → `unmapped_state_field` LOW gap。
- `task_results.<id>.status` ∈ `ok` / `fail` / `skipped` / 其他（其他 → `other`）
- `mode` ∈ `phase` / `dag`

写入方：`state_write.py`（经 fcntl 锁）。

## 8. run-log.jsonl

每行 1 个事件：`{"ts": "<iso>", "event": "<type>", ...}`。详见 [event-catalog.md](./event-catalog.md)。

写入方：`audit_append.py`（PreToolUse hook）。

## 9. evaluation/verification-report.md

`evaluator` agent 输出的 markdown，含 verdict + AC 评估明细。

写入方：`evaluator` agent（LLM）。

## Per-task: artifacts/<task_id>/SUMMARY.md

executor 在 code 模式 task ok 时必写。缺失 → `missing_summary` MEDIUM gap（仅当 `task_results.<id>.status=ok` 时检查）。

写入方：`executor` agent（LLM，每个 task 一份）。

## Schema drift 检测

drive-record 把 `executeState.json` 中 `KNOWN_STATE_FIELDS` 之外的字段标记为 `unmapped_state_field` LOW gap（仅作 schema drift 早期信号，不阻断）。