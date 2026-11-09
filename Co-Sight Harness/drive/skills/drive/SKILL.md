---
name: drive
description: Use when the user wants structured multi-step execution with quality gates ("用 drive 做 X" / "/drive [arg]" / "梳理一下需求" / "开始动工"). Optional first arg is the PR-name (kebab-case English summary, e.g. `add-user-auth` / `fix-import-deadlock`).
user-invocable: true
allowed-tools: Bash(python3 *read_workflow.py*), Bash(python3 *review_flow.py *), Bash(python3 *extract_verdict.py*), Read(references/**)
---

## 1. 初始化

Run the `/startup` skill with the user's intent. The startup skill takes care of `plan_dir` / `plan_name` allocation and persists `envelope.data = {plan_name, plan_dir, intent}` for downstream phases. Default `auto_mode = false` (HITL gate); only set true when the user explicitly says "auto" / "自动".

## 2. 解析工作流

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/read_workflow.py" --work-dir <work_dir> --plugin-root "${CLAUDE_PLUGIN_ROOT}"
```

返回 `mode` + `phases[]` / `agents[]`。解析失败一律停下。

## 3. 调度

| mode | 加载 |
|---|---|
| `phase`（含缺省）| `references/phase-mode.md` |
| `dag` | `references/dag-mode.md` |

按当前 mode 加载对应 references 文件，里面有真实的 spawn 模板 `Agent(subagent_type=phase.agent, prompt=..., run_in_background=False)` / `Agent(subagent_type=agent.agent, prompt=..., run_in_background=False)`（drive 全局策略：`run_in_background=False`，并发靠"同消息多次 Agent() 调用"）。
phase 模式按 `phases[i].agent` 选 agent；
dag 模式按 `agents[i].agent`（或 `agents[i].id`）选。
mode 切换：重 Read 另一文件。

## 4. 辅助

| 资源 | 用途 |
|---|---|
| `startup` | §1 |
| `state-machine` | 状态 / gate / verdict |
| `workflow-builder` | workflow.yaml 生成 |
| `references/phase-mode.md` | phase 派发 |
| `references/dag-mode.md` | dag 派发 |

## 5. Gotchas

- `envelope.data` 是 plan_name / plan_dir 唯一来源
- worker 回报：summary JSON；wave barrier 由 executor aggregate.py 记账
- 不变量由 hook 强制（write_guard / state_transition_guard / subagent_report_guard / audit_events）
- 见到 `pending_plan_review=true` 必须停——调 `/state-machine` 走 HITL（harness 弹权限即人工确认）；用户回 proceed/revise 后再 `DRIVE_TRUSTED=1 python3 state_cli.py transition --to execute` 推进
- `state_cli.py transition` 子命令必须由 orchestrator 调用，前缀 `DRIVE_TRUSTED=1`（hook 与 state_cli.py 自身均校验）
