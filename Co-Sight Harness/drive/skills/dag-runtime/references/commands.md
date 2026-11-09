# dag-runtime 命令表

`dag_runtime.py` 全部子命令的入参 / 输出 / 失败 reason。

## 全局参数

所有子命令前置要求：

| 参数 | 必填 | 作用 |
|---|---|---|
| `--planning-dir` | 是 | 规划目录（含 `executeState.json`） |

子命令本身的参数见下表。

## 子命令

### set-active-agents

覆盖式写 `state.active_agents[]`。

| 参数 | 必填 | 形式 | 说明 |
|---|---|---|---|
| `--json` | 是 | JSON 字符串 | agent 数组，元素 `{"id", "wave", "status", "started_at"}` |

**行为**：写入 `state.active_agents`；当任一节点 status=`running` 时，从 `state.confirmed_nodes` 中摘除同名节点（旧确认失效）。

### mark-completed

标 `state.active_agents[id].status = completed`。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--agent-id` | 是 | 节点 id |

**行为**：双重闸门（harness `check_dag_node_confirmation` + CLI `_gate_node_completed`）——节点必须在 `state.confirmed_nodes` 内。`auto_mode=true` 是唯一旁路。

**失败 reason**：`unknown_agent` / `confirmation_required` / `invalid_agent` / `invalid_arg` / `revision_conflict`。

### mark-failed

标 `state.active_agents[id].status = failed`。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--agent-id` | 是 | 节点 id |

**行为**：不设门。

**失败 reason**：`unknown_agent` / `invalid_agent` / `invalid_arg` / `revision_conflict`。

### mark-skipped

标 `state.active_agents[id].status = skipped`。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--agent-id` | 是 | 节点 id |

**行为**：不设门，cascade skip 必须能走。

**失败 reason**：`unknown_agent` / `invalid_agent` / `invalid_arg` / `revision_conflict`。

### advance-wave

`state.current_wave += 1`。

无额外参数。

**行为**：wave barrier fail-closed——current_wave 内仍有非终态节点（`pending` / `running`）拒绝 advance，写 `state.current_wave`。越界（new_wave > waves_total）也拒绝。

**失败 reason**：`wave_barrier_not_ready`（仍有非终态节点）/ `invalid_arg`（越界）/ `revision_conflict`。

### set-waves-total

写 `state.waves_total`。

| 参数 | 必填 | 说明 |
|---|---|---|
| `--total` | 是 | int，总 wave 数 |

### read-active-agents

读 `state.active_agents + state.current_wave + state.confirmed_nodes`。

无额外参数。

### check-terminal-verdict

校验 `verdict_required` agent 是否全部 `state.verdicts[id] == pass`。

| 参数 | 必填 | 形式 | 说明 |
|---|---|---|---|
| `--verdict-required-agents` | 是 | JSON 字符串 | agent id 数组 |

**行为**：任一缺失 verdict 或 verdict ≠ pass → fail。

**失败 reason**：`verdict_not_pass` / `invalid_arg`。

### mark-retry-attempted

记录一次 retry 尝试。

| 参数 | 必填 | 形式 | 说明 |
|---|---|---|---|
| `--agent-id` | 是 | 字符串 | 节点 id |
| `--reason` | 否 | 字符串 | retry 原因 |
| `--max-retries` | 否 | int | retry 上限（默认 3） |

**行为**：
- `state.active_agents[id].retry_count += 1`，写 `last_retry_at` / `last_retry_reason`
- 从 `state.verdicts` 摘除该 agent
- append `run-log.jsonl` 事件 `node_retry_attempted`

**失败 reason**：`unknown_agent` / `retry_budget_exceeded`（retry_count 已 ≥ max-retries）/ `invalid_arg`。

## 通用返回协议

所有子命令通过 `Envelope` 输出到 stdout：

成功：
```json
{"ok": true, "data": {...}, "reason": null, "details": {}}
```

失败：
```json
{"ok": false, "data": {}, "reason": "<reason_code>", "details": {...}}
```

退出码：`0` 成功 / `1` 失败。