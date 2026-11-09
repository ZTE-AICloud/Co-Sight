---
name: wave-scheduling
description: Use when a plan's taskRecord.yaml needs wave topology and budget allocation across depends_on. Activated by planner after taskRecord.yaml is written.
user-invocable: false
---

# Wave Scheduling

## 调用的命令

| 命令 | 作用 | 入参 | 输出 | 失败模式 |
|---|---|---|---|---|
| `topo-sort` | Kahn BFS 拓扑排序 + 环检测 | `--planning-dir` (required) | Envelope `data.tasks` 拓扑序数组 | `cycle_detected`（附 `cycle_path`） / `schema_invalid` |
| `topo-sort-from-tasks` | 从 stdin JSON tasks 列表拓扑排序（不落盘） | stdin `[{task_id, depends_on}]` | Envelope `data.waves` | `cycle_detected` / `schema_invalid` |
| `schedule-waves` | budget 分配 + 并行度决策，写 `waves.yaml` + `topo-state.json` | `--planning-dir` (required), `--budget` (default 100000) | Envelope `data.{wave_count, total_tasks}` | `cycle_detected` / `schema_invalid` / `invalid_agent_ref` |

## 命令契约

### topo-sort

调用前：`<planning-dir>/taskRecord.yaml` 已写好。

入参：

- `--planning-dir <dir>`（必填）：`.drive/<plan_dir>/` 路径

调用后：stdout 打印 Envelope JSON。Exit 0 表示成功。

失败模式：

- `cycle_detected` → `details.cycle_path` 列出环上节点，回写 taskRecord 修 `depends_on` 再跑。
- `schema_invalid` → `details` 含出错字段名（缺 `tasks` / 缺 `task_id` / `depends_on` 不是列表等）。

### topo-sort-from-tasks

调用前：caller 已有 `[{task_id, depends_on}, ...]` 形态的 tasks 列表。

入参：

- stdin：JSON 数组，每项至少含 `task_id` (str) 与 `depends_on` (list of str)

调用后：stdout 打印 Envelope JSON。Exit 0 表示成功。`data.waves` 是 `[[task_id, ...], ...]`，每条 wave 内部 task 无相互依赖可并行。

失败模式：

- `cycle_detected` → `details.cycle_path` 列出环上节点
- `schema_invalid` → stdin 不是 list / 缺 `task_id` / `task_id` 重复 / `depends_on` 不是 list

### schedule-waves

调用前：`<planning-dir>/taskRecord.yaml` 已写好；本 skill 的 `topo-sort` 已确认无环（`schedule-waves` 内部也跑一遍，但单独调时不算替代）。

入参：

- `--planning-dir <dir>`（必填）
- `--budget <int>`（可选，默认 100000）：所有 task 的 context token 预算总和；按 `estimated_tokens` 加权均摊

调用后：落盘 `<planning-dir>/waves.yaml`（权威 wave + depends + budget + upstream_artifacts）+ `<planning-dir>/topo-state.json`（运行中间态，供后续 query）。stdout 打印 Envelope JSON。

失败模式：

- `cycle_detected` / `schema_invalid` 同上。
- `invalid_agent_ref` → `details.unknown_agents` 列出非法引用。`drive:` 前缀查插件 agents/；裸名查项目 `.claude/agents/`。修 `taskRecord.yaml` 的 `agent_name` 再跑。

## Gotchas

- 本 skill 是 **deterministic calculator**——不调 LLM、不做业务判断。wave 拓扑 100% 由 `taskRecord.yaml` 的 `depends_on` 决定。
- `estimated_tokens` 是**可选加权项**；不填 → 默认均摊。**不要瞎猜写大数**——会挤占别的 task 预算。
- `waves.yaml` 是执行阶段的**权威依赖账**。执行端不再回读 `taskRecord.yaml` 推导依赖。
- `drive:` 前缀的 agent 名（`drive:executor` 等）查插件内置 agents/；裸名查项目 `.claude/agents/`。不要在 `agent_name` 里写 `drive:` 前缀但裸名是项目自定义的 agent——会校验失败。
- `topo-state.json` 不是人读的，是给后续 query 用的中间态。
- `topo-sort-from-tasks` 是 **无 planning_dir 的轻量入口**——专为调用方已有 tasks JSON、不希望落盘 `taskRecord.yaml` 的场景。caller 把 `[{task_id, depends_on}]` 通过 stdin 喂入，stdout 直接拿到 envelope。

## 调用前 Checklist

- [ ] `<planning-dir>/taskRecord.yaml` 存在且 `tasks` 列表非空
- [ ] 每个 task 有 `task_id`（全局唯一，格式 `<plan_id>-TNN`）+ `depends_on`（列表）+ `agent_name`
- [ ] `depends_on` 只引用本 plan 内存在的 `task_id`
- [ ] 决定 `budget`（默认 100000）和是否按 `estimated_tokens` 加权