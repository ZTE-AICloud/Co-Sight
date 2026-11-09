# DAG 模式派发协议（drive orchestrator 的 mode=dag 分支）

前置：已读过本 skill SKILL.md §1（读编排结构）、§3（控制流委托）、§5（范围）。下方专述 DAG 模式与 phase 模式的差异。

## DAG 派发协议

**触发条件**：项目 workflow.yaml 的 `mode: dag`。

DAG 模式由本 skill 直接派发，不再走 phase 模式调度。drive 在 DAG mode 下保持纯 flow driver：state 读写一律委托给 `/dag-runtime` skill。

| 项目 | 规则 |
|---|---|
| mode 缺省处理 | workflow.yaml 无 mode 字段 → 默认 `mode=phase` + 警告"建议显式标注"；内置 workflow.yaml 已改为显式 `mode: phase` |
| orchestration 缺省 | 无 `orchestration` 块 → read_workflow.py 注入默认（`max_concurrent_agents=16`, `wave_dispatch=barrier`），浅合并 `{**defaults, **user_provided}` |
| wave 划分 | 委托 `/wave-scheduling` skill 的 `topo-sort-from-tasks` 子命令算 Kahn BFS + wave 分配；drive 通过 `agents_to_tasks.py` 把 `agents[]` 转换为 tasks JSON，再经 `apply_concurrency_cap.py` 按 `max_concurrent_agents` 切分 |
| 当前 wave 查找 | `/dag-runtime read-active-agents`（DAG mode 字段） |
| spawn 模板 | `Agent(subagent_type=agent.agent, prompt=..., run_in_background=False)` —— 所有 subagent 一律 `run_in_background=False`，并发靠"同消息多个 Agent() 调用" |
| wave barrier（barrier）| wave 内全部 Agent 返回（同一 turn 内同步）→ 调 `/dag-runtime advance-wave` |
| 中间失败 cascade | 任一 agent `status=failed` → 调 `/dag-runtime mark-skipped` 把其直接下游 agent 标 skipped（不再 spawn）；wave barrier 检测 failed/skipped 都视为结束 |
| verdict 失败处理 | `verdict=partial/fail` → workflow 结束，由用户决定是否重启 |
| 收尾闸门 | 末 wave 全部 completed → 调 `/dag-runtime check-terminal-verdict`；verdict=pass 才放行 |
| 收尾分流 | 当前 wave 含 terminal agent，全部 completed 且 verdict=pass → 调 `extract_verdict.py` 写 verdict |
| 并发度 | 由 `orchestration.max_concurrent_agents` 控制（默认 16）；超过则排队等下个 slot |
| mode 切换 | DAG 模式跳过 analyzer / planner / executor / evaluator 内置 agent；不走 `taskRecord.yaml` / `waves.yaml` 路径 |

**关键纪律**：

- **所有 Agent() 调用一律 `run_in_background=False`**
  - 用户在自定义 agent frontmatter 写 `background: true` → read_workflow.py 校验时**报错**（除非 `wave_dispatch: fire_and_forget`）
  - 用户在 `orchestration` 设 `wave_dispatch: fire_and_forget` → 改用 `run_in_background=True`（仅当确有合法长任务用例）
- **DAG 模式 plan-review 独立 gate-human**：不复用 phase 模式的 plan-review 机制；用就在 DAG 里挂 `drive:gate-human` 节点
- **每个 agent 节点完成前必须经用户放行**：gate-human 节点按 `/dag-runtime confirm-node`（不在任何 allowed-tools 内）+ `/dag-runtime mark-completed` 两步走。`auto_mode` 是唯一旁路，DAG 不认 `complexity`（trivial 也要确认）。`mark-failed` / `mark-skipped` 不设门。
- **state 写入只走 `/dag-runtime` skill**：active_agents / current_wave / confirmed_nodes 的读改都不直接 Edit executeState.json；drive 在 DAG mode 下不写 state，只调 read-only 命令 + 决策。
- **复杂度策略**：`complexity_rules.trivial.skip_agents` 列出的 agent 在 trivial 场景下跳过
- **节点 retry 协议**：orchestrator 看到 `active_agents[id].status == failed` → 先调 `/dag-runtime mark-retry-attempted --agent-id <id> --reason <why>`，再走通常的 `Agent(subagent_type=..., ...)` 的 spawn 路径。`--max-retries` 默认 3，返回 `retry_budget_exceeded` 即 escalate 用户或 cascade skip。详见 dag-runtime SKILL.md §retry 流程。
- **verifier 节点必填**：`verdict_required: true` 的 agent 必须由 `drive:evaluator`（或用户自定义 verifier agent）承担。verifier 收尾节点必须落在最后一 wave 且 `terminal: true`，自行写 `.drive/<plan_dir>/evaluation/verification-report.md` 并产生 `## Verdict: <value>` 行。orchestrator **不**自己写 verdict 文件。

**调用的子脚本**（drive 同目录依赖；wave 计算委托给 wave-scheduling skill；state 读写委托给 dag-runtime skill）：

| 脚本 | 职责 |
|------|------|
| `scripts/agents_to_tasks.py` | workflow.yaml `agents[]` → `[{task_id, depends_on}]` tasks JSON |
| `scripts/apply_concurrency_cap.py` | 按 `max_concurrent_agents` 切分超量 wave |
| 委托 `/dag-runtime` skill | `/dag-runtime init plan-waves`（初始化）/ `/dag-runtime read-active-agents`（读）/ `/dag-runtime check-terminal-verdict`（读）/ `/dag-runtime confirm-node`（HITL 写 confirmed_nodes） |
| 状态校验 | `state_machine/scripts/state_schema.py::validate_dag_state`（可选 hook 调用） |

**完整 DAG 调度流程**：

1. 读 workflow.yaml：`read_workflow.py --work-dir <dir>`（自动按 mode 分支）
2. 计算 wave：
   - `python3 scripts/agents_to_tasks.py --workflow <yaml> | python3 topo_sort.py topo-sort-from-tasks` 直接 pipe（agents_to_tasks 输出裸 JSON 数组）
   - 委托 `/wave-scheduling` skill（`topo-sort-from-tasks` 子命令）从 tasks JSON 算 Kahn BFS + wave 分配
   - `python3 scripts/apply_concurrency_cap.py --max-concurrent $N` 按 `max_concurrent_agents` 切分超量 wave
3. 初始化 state：委托 `/dag-runtime` skill 跑 `init plan-waves --workflow <yaml> --planning-dir <dir> --waves-json @<waves.json>`（dag-runtime 内部构造 agents_payload 写 active_agents[]）
4. wave 1：调 spawn 列表里每个 agent `Agent(subagent_type=..., prompt=..., run_in_background=False)`（同消息并发）
5. 等所有 agent 返回；**逐个节点走 HITL**（orchestrator 即主对话）：
   - 主对话用 `AskUserQuestion` 真问用户对该节点产出是否放行
   - 放行：gate-human 节点先 `/dag-runtime confirm-node --agent-id <id>` → 再 `/dag-runtime mark-completed --agent-id <id>`
   - 不放行：`/dag-runtime mark-skipped --agent-id <id>`（mark-skipped 不设门，cascade skip 必须能走）
   - 节点自身失败：`/dag-runtime mark-failed --agent-id <id>`
6. 若任一 failed → gate-human 节点 `/dag-runtime mark-failed --agent-id <id>` + `/dag-runtime mark-skipped --agent-id <id>` 其直接下游（cascade）
7. 推进 wave：调 `/dag-runtime advance-wave --planning-dir <dir>` 写 current_wave（wave barrier fail-closed：当前 wave 仍有 pending / running 节点时拒绝）
8. 重复 4-7 直到所有 wave 完成
9. 末 wave 全部 completed → 从 workflow.yaml `agents[].verdict_required` 取 verdict 列表；调 `extract_verdict.py --planning-dir <dir> --all-verdict-required '<JSON>'` 一次批量写入 `state.verdicts[id]`；再调 `/dag-runtime check-terminal-verdict --verdict-required-agents '<JSON>'` 验 verdict gate；gate 通过才能宣告收工

wave barrier 记账走 `skills/wave-barrier/scripts/aggregate.py`；DAG 模式 state 字段读写走 `/dag-runtime` skill 的 `dag_runtime.py` / `dag_init.py` / `confirm_node.py`。
