# phase 模式派发协议（drive orchestrator 的 mode=phase 分支）

前置：已读过本 skill SKILL.md §1（读编排结构）、§3（控制流委托）、§5（范围）。下方专述 phase 模式。

## Phase 派发协议

| 项目 | 规则 |
|---|---|
| 启动过渡 | `active_stage=None` 时先调 `/state-machine transition --to <wf.phases[0].stage>`，把 active_stage 推到第一 phase |
| 当前 phase 查找 | `wf.phase_for_stage(executeState.json.active_stage)`（找不到 = 状态错乱，停下） |
| spawn 模板 | `Agent(subagent_type=phase.agent, prompt=..., run_in_background=False)` |
| wave 行为 | `phase.wave_barrier=true`：每个 task 一次（wave 内同消息并发），收齐 summary 后跑 review 子流程 |
| 收尾分流 | `phase.terminal_stage=true` → 调 `extract_verdict.py` 写 verdict；否则 → 等用户放行 |
| agent 寻址 | scoped 地址：`drive:<name>` / 裸名 / 内置类型（详见 `agent-catalog.md`），引用不存在则 fail-closed |
| plan-review gate | plan 阶段完成后：写 `pending_plan_review=true` → 等用户 `proceed` / `revise`；proceed 调 `/state-machine confirm-stage --stage plan` → `/state-machine transition --to execute`；revise 回到 plan agent 重跑 |

## See also

- 主 SKILL.md §3 控制流委托 —— state 推进、wave barrier 记账、verdict 提取的归属 skill/hook
- `references/dag-mode.md` —— DAG 模式分支（互斥，mode 切换时换 Read）
- `state-machine/SKILL.md` §2 —— 阶段流转表权威定义

