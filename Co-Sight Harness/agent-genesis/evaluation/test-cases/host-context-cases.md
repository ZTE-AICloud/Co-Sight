# host-context 方案评测用例（V2 说法兼容 + V3 交互路由）

> LLM 语义层与交互路由用例——无法纯脚本断言, 由 selftest / 交互式 e2e 执行。
> 静态一致性与门禁行为面: `tests/flow/host-context-verify.sh`（可机检, 已入 CI 面的 selftest 前置）。
> 方案权威: host-context 方案 §2 路由总表 / §3.2 语义判定 / §6 验证方式。

## V2 — 说法兼容矩阵（澄清器语义判定, Step 1 后断言 clarified yaml 三段）

前置: 各用例在对应 fixture 目录内启动 pipeline, 跑 Step 1 澄清（可用固定需求文本注入）。

| # | fixture 目录 | 需求文本 | 断言 intent | 断言 target_match.detected |
|---|---|---|---|---|
| V2-1 | claude 项目（有 CLAUDE.md） | "给我加一个智能体" | host_extend | false |
| V2-2 | claude 项目（已有 output/agents/review-bot） | "加一个类似 review-bot 的助手" | modify_existing | true（matched: review-bot） |
| V2-3 | dsh 项目（有 .dsh/） | "加一个 skill" | host_extend | false |
| V2-4 | claude 项目 | "做一个独立的部署 Agent 项目, 放到别的目录用" | explicit_create | false |
| V2-5 | claude 项目 | "建一个完整 harness" | explicit_create | false |
| V2-6 | 普通代码仓（仅 package.json） | "给我加一个智能体" | （三段省略——零行为变化） | — |
| V2-7 | claude 项目 | "改一下那个审批 agent"（无同名资产, 语义近似） | modify_existing（不确定时访谈内一问） | 按实际命中 |
| V2-8 | 任意 + AG_SUPPRESS_HOST_CONTEXT=1 | 任意 | intent 省略; project_context={in_project:false, project_kind:none, suppressed_by: non_interactive} | — |

## V3 — 交互路由 e2e（交互式执行, 每条含可机检终态断言）

| # | 场景 | 交互脚本 | 终态断言（可机检） |
|---|---|---|---|
| V3-1 | 项目内新增, 零问询 | 需求"加一个代码审查 subagent", 全程不插话 | 全程 AskUserQuestion 次数=0（R-6 判定即执行）; `.claude/agents/{name}.md` 存在; 快照 diff: 宿主已有文件 deletions=0 且 modifications=∅; route-decision.yaml `decided_by: context_execute`; G024/G028(host_extend) PASS |
| V3-2 | 项目内新增+skill 诉求 | "加一个审查 subagent, 顺带把它的规则库做成 skill" | `.claude/agents/{name}.md` 与 `.claude/skills/{name}/SKILL.md` 双落点; 同轮一次构建 |
| V3-3 | 项目内改已有 | 需求命中已有 agent → 确认题出现, 选"优化既有" | AskUserQuestion 恰 1 次; 走 step-f2; 就地修订生效; route-decision `decided_by: context_confirm` |
| V3-4 | 项目外回归护栏 | 空目录同话术 V2-1 | 行为与基线逐字节一致（无 host_project 段消费痕迹、无 route-decision 落盘） |
| V3-5 | dsh 形态④ | dsh 项目内新增 subagent | bundle 结构 G030 直调 PASS; preset 行含 tool-subagent + persona.prefix 身份 |
| V3-6 | 插话改道 | V3-1 中开场明示后立即插话"我要完整工程" | 改道 create 全量; route-decision 更新; 增补轮产物不残留 |

## selftest 注入抑制回归（V5 组成部分）

- 既有 selftest/golden 套件在 `AG_SUPPRESS_HOST_CONTEXT=1` 下全绿（与基线一致）
- agent-genesis 仓内直接跑 selftest（仓有 CLAUDE.md → 探针判 claude_code）→ 产物不受
  本仓语境影响（抑制链路生效的硬证据）
