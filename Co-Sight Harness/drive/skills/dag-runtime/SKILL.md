---
name: dag-runtime
description: DAG-mode state holder and HITL gate. Read or write active_agents[] and current_wave, mark a node's status (completed / failed / skipped), confirm a DAG node via HITL, record a retry attempt, check terminal verdict gate. Use when drive spawns a DAG workflow and needs to initialize or advance state, when gate-human handles user approval on a DAG node, when an agent reads which DAG nodes are active, when a subagent needs to record its terminal status in active_agents, or when an agent needs to log a retry attempt with an updated counter and cleared verdict. Does not handle phase-mode state (state-cli owns that), does not compute wave topology (wave-scheduling owns that), does not drive workflow forward (drive owns that).
user-invocable: false
allowed-tools: Bash(python3 *dag_runtime.py*)
---

# dag-runtime skill

## 职责边界

DAG 模式三个专属 state 字段的读写 + HITL 确认入口。

| 字段 | 唯一写入口 | 读入口 |
|---|---|---|
| `active_agents[]` | `dag_runtime init plan-waves` / `mark-completed` / `mark-failed` / `mark-skipped` / `mark-retry-attempted` | `read-active-agents` |
| `current_wave` | `dag_runtime advance-wave` | `read-active-agents` |
| `state.verdicts[id]` | `extract_verdict.py write_verdict` / `dag_runtime mark-retry-attempted` | `check-terminal-verdict` |
| `confirmed_nodes[]` | `confirm_node`（harness default-deny 保护） | `read-active-agents` |

## 调用的命令

| 命令 | 作用 | 写/读 |
|---|---|---|
| `init plan-waves` | 初始化 `active_agents[]`，设 `current_wave=1` | 写 |
| `mark-completed` | 标节点 completed（harness + CLI 双重闸门要求该 agent 已在 `confirmed_nodes`） | 写 |
| `mark-failed` | 标节点 failed（不设门，cascade） | 写 |
| `mark-skipped` | 标节点 skipped（不设门，cascade skip 必须能走） | 写 |
| `advance-wave` | 推 `current_wave += 1`（wave barrier fail-closed：current_wave 仍有 running 节点时拒绝） | 写 |
| `read-active-agents` | 读 `active_agents[]` + `current_wave` + `confirmed_nodes` | 读 |
| `confirm-node` | HITL 写 `confirmed_nodes[]`（**不在任何 allowed-tools 内**，靠权限弹窗） | 写 |
| `revoke-node` | 从 `confirmed_nodes[]` 摘除（重派时用） | 写 |
| `check-terminal-verdict` | 验 `verdict_required` agent 的 `state.verdict == pass` | 读 |
| `mark-retry-attempted` | 累加 `retry_count` / 清 `state.verdicts[id]` / append `node_retry_attempted` 事件（`--max-retries` 阈值，默认 3） | 写 |

每个命令的入参 / 输出 envelope / 失败 mode 详见 `references/commands.md`。

## 跨 skill 调用契约

**drive 调本 skill**（prose + `/dag-runtime`）：

- 初始化：`/dag-runtime init plan-waves --planning-dir .drive/<dir> --workflow <yaml> --waves-json @<waves>`
- wave 推进：`/dag-runtime advance-wave --planning-dir <dir>`（wave barrier 全部 agent 终态后）
- 收尾判定：`/dag-runtime check-terminal-verdict --planning-dir <dir> --verdict-required-agents '<JSON>'`

**gate-human 调本 skill**：

- approve：先 `/dag-runtime confirm-node --agent-id <id>`（权限弹窗即确认），再 `/dag-runtime mark-completed --agent-id <id>`（harness + CLI 双重闸门）
- revise：`/dag-runtime mark-skipped --agent-id <id>`（无门，cascade skip 必须能走）
- 自身失败：`/dag-runtime mark-failed --agent-id <id>`

## confirm-node + mark-completed 必须分两次 Bash tool 调用

**不要** 在同一个 Bash tool 调用里同时跑 `confirm-node` 和 `mark-completed`（即便用 `&&` / `;` / 换行串联）。

原因：`hooks_protocol.check_dag_node_confirmation` 是 PreToolUse hook ——它在每次 Bash tool 调用开始时拿到整条命令字符串解析。`confirm_node.py && mark-completed` 在同一 Bash 调用里时，hook 看到的是"开始一次 bash 调用"，但内层 `confirm_node.py` 还没写 `confirmed_nodes`；hook 校验"agent 不在 confirmed_nodes 里"就 block。

**正确做法**：两次独立的 Bash 调用
```bash
# 第一次：Bash tool 调用，仅 confirm-node（触发权限弹窗 + 写 confirmed_nodes）
/dag-runtime confirm-node --agent-id foo
# 第二次：另一次 Bash tool 调用，仅 mark-completed（hook 这次看到 foo 已在 confirmed_nodes）
/dag-runtime mark-completed --agent-id foo
```

如果发现 `mark-completed` 被 block，确认是否走的是两次独立 Bash tool 调用（不是两次同 bash 进程内的串联）。

## retry 流程

orchestrator 看到 `active_agents[id].status == failed` 时，**先** 调 `/dag-runtime mark-retry-attempted --agent-id <id> --reason <why> [--max-retries N]`，**再** 走通常的 spawn 路径（`Agent(subagent_type=..., prompt=..., ...)`）。

`mark-retry-attempted` 一次完成三件事：

- 累加 `retry_count`、写 `last_retry_at` / `last_retry_reason`
- 清除 `state.verdicts[id]`
- append run-log `node_retry_attempted` 事件

不自动做：`status` 字段保留 `failed`；不触碰人工确认记录。

retry budget：`--max-retries` 默认 3。当前 `retry_count >= max-retries` 时拒绝本次重试，返回 `REASON_RETRY_BUDGET_EXCEEDED`，调用方应 escalate 或 `mark-failed` + cascade。

## 与 harness 的对齐

- `hooks_protocol._CONFIRM_ENTRYPOINTS = ("confirm_stage.py", "confirm_node.py")` —— 本 skill 的 `confirm_node.py` 是唯一写 `confirmed_nodes` 的入口
- `hooks_protocol.check_dag_node_confirmation` —— PreToolUse 闸门，校验 `mark-completed` 命令的 agent id 已出现在 `confirmed_nodes`
- `dag_runtime.cmd_mark_status` —— CLI 内部二次校验，与 harness 闸门互不依赖（单独绕过任一道都不够）

## Gotchas

- **`confirm_node.py` 不在任何 skill 的 allowed-tools 内**：执行时由 Claude Code 弹授权请求作为人工确认。
- **`mark-completed` 有双重闸门**，`mark-failed` / `mark-skipped` 不设门。
- **节点重派为 running 时（`init plan-waves` 二次调用）会自动从 `confirmed_nodes` 里摘掉**。
- **DAG 不认 `complexity`**——trivial plan 也走 confirm。
- **`auto_mode=true` 是唯一全局旁路**——开了就跳过 confirm，hook 不挡。
- **`status` 字段五值**：`pending`（待 spawn）/ `running`（已 spawn 未完成）/ `completed` / `failed` / `skipped`。plan-waves init 后所有节点 = `pending`。
- **`advance-wave` 必须一次放一个 wave**——跳 wave 会被 `wave_skip` fail-closed；当前 wave 仍有 running 节点会被 `wave_barrier_not_ready` fail-closed。
