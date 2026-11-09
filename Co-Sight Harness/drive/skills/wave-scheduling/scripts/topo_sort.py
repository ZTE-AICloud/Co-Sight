"""topo_sort helper 的确定性计算器 — 拓扑排序与波次核算。

职责:
- topo-sort: Kahn BFS 拓扑排序 + 环检测，从 depends_on 算出权威 waves
- schedule-waves: budget 分配 + 并行度决策，写 waves.yaml + topo-state.json

topo_sort helper 是薄辅助工具外壳——不做 LLM 推理，只做确定性核算。planner 标注逻辑依赖
（depends_on），topo_sort helper 据此算出执行波次与预算账，成为依赖账的唯一权威来源。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from envelope import (
    REASON_FILE_MISSING,
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
    Envelope,
    emit,
)

# agent 校验：内联 read_workflow 的逻辑，保持脚本独立（不跨目录 import）
BUILTIN_AGENT_TYPES: frozenset[str] = frozenset({
    "general-purpose", "Explore", "Plan", "claude",
    "statusline-setup", "claude-code-guide",
})


def _scan_agent_names(agents_dir: Path) -> set[str]:
    """扫描 agents_dir 下所有 .md 读 name: frontmatter。"""
    names: set[str] = set()
    if not agents_dir.exists():
        return names
    for md in agents_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        try:
            fm = yaml.safe_load(parts[1])
        except Exception:
            continue
        if isinstance(fm, dict) and "name" in fm:
            name = str(fm["name"]).strip()
            if name:
                names.add(name)
    return names


def _validate_agent_ref(agent: str, project_agents: set[str], plugin_agents: set[str]) -> tuple[bool, str | None]:
    """校验单个 agent 引用。drive: 前缀查插件，裸名查项目，命中白名单放行。"""
    if not agent:
        return False, "agent 不能为空"
    if agent in BUILTIN_AGENT_TYPES:
        return True, None
    if agent.startswith("drive:"):
        bare = agent[6:]
        if not bare:
            return False, "drive: 前缀后缺少 agent 名称"
        if bare not in plugin_agents:
            return False, f"drive 插件中不存在 agent: {bare!r}"
        return True, None
    if agent not in project_agents:
        return False, f"项目中不存在 agent: {agent!r}"
    return True, None


DEFAULT_BUDGET = 100_000
MIN_TASK_BUDGET = 8_000
DEFAULT_TASK_ESTIMATE = 1_000   # estimated_tokens 缺失时的默认估算
DEFAULT_AGENT_NAME = "drive:executor"
ARTIFACTS_DIR_TEMPLATE = ".drive/{plan_dir}/artifacts"

TASK_RECORD_FILE = "taskRecord.yaml"
WAVES_FILE = "waves.yaml"
STATE_FILE = "topo-state.json"


def artifacts_dir_for(plan_dir: str) -> str:
    """PROP-20260817-001 P0-2：构造 plan_dir 对应的 artifacts 目录模板。

    返回如 '.drive/plan-20260817-1530-foo/artifacts'。
    """
    return ARTIFACTS_DIR_TEMPLATE.format(plan_dir=plan_dir)


def _build_task_entry(
    task_id: str,
    deps_map: dict[str, list[str]],
    agent_map: dict[str, str],
    task_budgets: dict[str, int],
    artifacts_dir: str,
    optional_verification: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """构造 waves.yaml 内单个 task 条目（schema 见 00-docs/interface-contracts.md 的 waves.yaml 节）。

    - depends_on: 只保留 plan 内存在的依赖（未知依赖已在 topo 阶段警告过）
    - agent_name: 从 taskRecord 透传（缺省 executor），主 agent 据此 spawn
    - budget: 该 task 的 context token 预算（均摊或按 estimated_tokens 加权）
    - upstream_artifacts: 按核心目录约定 .drive/<plan_dir>/artifacts/<dep>/ 推导；无依赖则省略
    - optional_verification: 从 taskRecord 透传，只在为真时出现
    """
    deps = [d for d in deps_map.get(task_id, []) if d in deps_map]
    entry: dict[str, Any] = {
        "task_id": task_id,
        "depends_on": deps,
        "agent_name": agent_map.get(task_id, DEFAULT_AGENT_NAME),
        "budget": task_budgets.get(task_id, MIN_TASK_BUDGET),
    }
    if deps:
        entry["upstream_artifacts"] = [f"{artifacts_dir}/{dep}/" for dep in deps]
    if task_id in optional_verification:
        entry["optional_verification"] = True
    return entry


# =============================================================================
# 输入解析
# =============================================================================

def _load_tasks(planning_dir: Path) -> tuple[str, list[dict[str, Any]]] | Envelope:
    """读取 taskRecord.yaml，返回 (plan_id, tasks) 或 Envelope 失败。

    支持两种顶层结构:
    - {plan_id, tasks: [{task_id, depends_on, ...}]}
    - [{task_id, depends_on, ...}]  (裸 list, plan_id 回退为目录名)
    """
    record_path = planning_dir / TASK_RECORD_FILE
    if not record_path.exists():
        return Envelope.fail(
            REASON_FILE_MISSING,
            path=str(record_path),
            hint=f"{TASK_RECORD_FILE} 未找到；planner 应先产出该文件",
        )

    try:
        raw = yaml.safe_load(record_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return Envelope.fail(REASON_SCHEMA_INVALID, path=str(record_path), yaml_error=str(exc))

    if isinstance(raw, list):
        return planning_dir.name, list(raw)
    if isinstance(raw, dict):
        tasks = raw.get("tasks")
        if not isinstance(tasks, list):
            return Envelope.fail(
                REASON_SCHEMA_INVALID,
                path=str(record_path),
                hint="顶层 dict 必须含 tasks: [...] 列表",
            )
        plan_id = str(raw.get("plan_id") or planning_dir.name)
        return plan_id, list(tasks)

    return Envelope.fail(
        REASON_SCHEMA_INVALID,
        path=str(record_path),
        hint="taskRecord.yaml 顶层必须是 dict 或 list",
    )


def _validate_tasks(tasks: list[dict[str, Any]]) -> Envelope | None:
    """校验 task 结构；合法返回 None，非法返回 fail Envelope。"""
    if not tasks:
        return Envelope.fail(REASON_SCHEMA_INVALID, hint="tasks 列表为空")

    seen: set[str] = set()
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            return Envelope.fail(REASON_SCHEMA_INVALID, index=i, hint="task 必须是 dict")
        tid = t.get("task_id")
        if not tid or not isinstance(tid, str):
            return Envelope.fail(REASON_SCHEMA_INVALID, index=i, hint="task 缺少 task_id")
        if tid in seen:
            return Envelope.fail(REASON_SCHEMA_INVALID, task_id=tid, hint="task_id 重复")
        seen.add(tid)
        deps = t.get("depends_on")
        if deps is not None and not isinstance(deps, list):
            return Envelope.fail(REASON_SCHEMA_INVALID, task_id=tid, hint="depends_on 必须是 list")
    return None


# =============================================================================
# 拓扑排序 (Kahn BFS + 环检测)
# =============================================================================

def cmd_topo_sort(tasks: list[dict[str, Any]]) -> Envelope:
    """Kahn BFS 拓扑排序，生成 waves[][]，并检测环。

    输入 tasks 每项含 task_id + depends_on (list of task_id)。
    同一 wave 内的 task 无相互依赖，可并行。

    环检测: 若存在环，返回 fail(REASON_SCHEMA_INVALID)，details 含 cycle_path。
    未知依赖 (depends_on 指向不存在的 task) 记入 warnings，不阻断。

    Returns:
        ok:  data={waves:[[tid,...]], wave_count, total_tasks, warnings}
        fail: reason=schema_invalid, details={cycle_path, ...}
    """
    validation = _validate_tasks(tasks)
    if validation is not None:
        return validation

    task_ids = [t["task_id"] for t in tasks]
    id_set = set(task_ids)
    deps_map: dict[str, list[str]] = {
        t["task_id"]: list(t.get("depends_on") or []) for t in tasks
    }

    warnings: list[str] = []
    in_degree: dict[str, int] = {tid: 0 for tid in task_ids}
    dependents: dict[str, list[str]] = defaultdict(list)
    for tid, deps in deps_map.items():
        for dep in deps:
            if dep not in id_set:
                warnings.append(f"{tid} 依赖未知 task '{dep}'（已忽略）")
                continue
            in_degree[tid] += 1
            dependents[dep].append(tid)

    waves: list[list[str]] = []
    queue = deque(sorted(tid for tid, d in in_degree.items() if d == 0))
    visited_count = 0

    while queue:
        wave = sorted(queue)
        waves.append(wave)
        visited_count += len(wave)
        next_queue: deque[str] = deque()
        for tid in wave:
            for dependent in dependents[tid]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    next_queue.append(dependent)
        queue = next_queue

    if visited_count < len(task_ids):
        remaining = [tid for tid, d in in_degree.items() if d > 0]
        cycle_path = _find_cycle(remaining[0], deps_map, id_set) if remaining else remaining
        return Envelope.fail(
            REASON_SCHEMA_INVALID,
            hint="taskRecord 依赖图存在循环，无法拓扑排序",
            cycle_detected=True,
            cycle_path=cycle_path,
            unresolved=sorted(remaining),
        )

    return Envelope.ok_envelope(
        waves=waves,
        wave_count=len(waves),
        total_tasks=len(task_ids),
        warnings=warnings,
    )


def _find_cycle(start: str, deps_map: dict[str, list[str]], id_set: set[str]) -> list[str]:
    """DFS 从 start 出发找一条环路径。返回 [n1, n2, ..., n1] 或 [start]。"""
    stack: list[str] = []
    visited: set[str] = set()

    def dfs(node: str) -> list[str] | None:
        if node in stack:
            return stack[stack.index(node):] + [node]
        if node in visited:
            return None
        visited.add(node)
        stack.append(node)
        for nxt in deps_map.get(node, []):
            if nxt in id_set:
                found = dfs(nxt)
                if found:
                    return found
        stack.pop()
        return None

    return dfs(start) or [start]


# =============================================================================
# 调度决策 (budget 分配 + 并行度)
# =============================================================================

def _decide_parallel(wave_size: int) -> bool:
    """单 wave 的并行度决策: wave 内 task 数 > 1 即可并行（同 wave 无相互依赖）。"""
    return wave_size > 1


def _compute_task_budgets(
    tasks: list[dict[str, Any]],
    budget: int,
) -> dict[str, int]:
    """按 estimated_tokens 加权分配 budget；无估算字段时均摊。

    任意 task 带 estimated_tokens → 加权模式；全部缺失 → 均摊（与旧版行为一致）。
    每 task 最低 MIN_TASK_BUDGET。
    """
    total = len(tasks)
    if total == 0:
        return {}

    estimates = {t["task_id"]: int(t.get("estimated_tokens") or 0) for t in tasks}
    total_estimated = sum(estimates.values())

    if total_estimated > 0:
        # 加权模式：按估算比例分配，保底 MIN_TASK_BUDGET
        return {
            tid: max(MIN_TASK_BUDGET, round(est / total_estimated * budget))
            for tid, est in estimates.items()
        }
    else:
        # 均摊模式（向后兼容）
        uniform = max(MIN_TASK_BUDGET, budget // total)
        return {t["task_id"]: uniform for t in tasks}


def cmd_schedule_waves(
    tasks: list[dict[str, Any]],
    *,
    plan_id: str = "plan-001",
    budget: int = DEFAULT_BUDGET,
    planning_dir: Path | None = None,
) -> Envelope:
    """拓扑排序 + budget 分配 + 并行度决策，产出结构化 schedule。

    budget 按 estimated_tokens 加权分配到每个 task；无估算字段时均摊。
    每 task 最低 MIN_TASK_BUDGET。并行度按 wave 决策（见 _decide_parallel）。

    Args:
        planning_dir: .planning/ 目录路径，用于向上找 work_dir 和 plugin_root 做 agent 校验

    Returns:
        ok: data={plan_id, waves:[{wave,count,parallel,budget_per_task,tasks:[{task_id,depends_on,budget,...}]}],
                  total_tasks, wave_count, budget, budget_per_task, weighted, warnings}
        fail: 透传 cmd_topo_sort 的失败 (环 / schema) 或 agent 引用校验失败
    """
    # agent 校验：扫描 project 和 plugin 的 agent name
    project_agents: set[str] = set()
    plugin_agents: set[str] = set()

    if planning_dir:
        work_dir = planning_dir.parent  # .planning/ 的父目录是 work_dir
        project_agents = _scan_agent_names(work_dir / ".claude" / "agents")

    # plugin_root: 向上找到 03-drive-core（包含 agents/ 和 skills/）
    plugin_root = Path(__file__).parent.parent.parent.parent
    if (plugin_root / "agents").exists():
        plugin_agents = _scan_agent_names(plugin_root / "agents")

    for t in tasks:
        agent_name = t.get("agent_name")
        if agent_name and agent_name != DEFAULT_AGENT_NAME:  # 默认值不校验（向后兼容）
            is_valid, error_msg = _validate_agent_ref(agent_name, project_agents, plugin_agents)
            if not is_valid:
                return Envelope.fail(
                    REASON_SCHEMA_INVALID,
                    hint=f"taskRecord task_id={t['task_id']} 的 agent_name 引用无效: {error_msg}",
                    task_id=t["task_id"],
                    agent_name=agent_name,
                )

    topo = cmd_topo_sort(tasks)
    if not topo.ok:
        return topo

    wave_lists: list[list[str]] = topo.data["waves"]
    total_tasks: int = topo.data["total_tasks"]

    # planning_dir 是 .drive/<plan_dir>/，取 .name 拿 plan_dir
    plan_dir = planning_dir.name if planning_dir is not None else "plan-unknown"
    artifacts_dir = artifacts_dir_for(plan_dir)

    deps_map = {t["task_id"]: list(t.get("depends_on") or []) for t in tasks}
    agent_map = {t["task_id"]: (t.get("agent_name") or DEFAULT_AGENT_NAME) for t in tasks}
    optional_verification = frozenset(
        t["task_id"] for t in tasks if t.get("optional_verification")
    )
    task_budgets = _compute_task_budgets(tasks, budget)
    weighted = any(t.get("estimated_tokens") for t in tasks)

    # 平均 budget_per_task 用于 topo-state.json（向后兼容字段）
    avg_budget = sum(task_budgets.values()) // total_tasks if total_tasks else 0

    scheduled_waves: list[dict[str, Any]] = []
    for i, wave_ids in enumerate(wave_lists, start=1):
        wave_budgets = [task_budgets.get(tid, MIN_TASK_BUDGET) for tid in wave_ids]
        scheduled_waves.append({
            "wave": i,
            "count": len(wave_ids),
            "parallel": _decide_parallel(len(wave_ids)),
            "budget_per_task": sum(wave_budgets) // len(wave_ids) if wave_ids else 0,
            "tasks": [
                _build_task_entry(
                    tid, deps_map, agent_map, task_budgets, artifacts_dir, optional_verification
                )
                for tid in wave_ids
            ],
        })

    return Envelope.ok_envelope(
        plan_id=plan_id,
        waves=scheduled_waves,
        wave_count=topo.data["wave_count"],
        total_tasks=total_tasks,
        budget=budget,
        budget_per_task=avg_budget,
        weighted=weighted,
        warnings=topo.data.get("warnings", []),
    )


# =============================================================================
# 输出落盘
# =============================================================================

def _write_outputs(planning_dir: Path, schedule: dict[str, Any]) -> dict[str, str]:
    """写 waves.yaml + topo-state.json，返回 {file: path}。"""
    planning_dir.mkdir(parents=True, exist_ok=True)

    waves_doc = {
        "plan_id": schedule["plan_id"],
        "total_tasks": schedule["total_tasks"],
        "waves": schedule["waves"],
    }
    waves_path = planning_dir / WAVES_FILE
    waves_path.write_text(
        yaml.safe_dump(waves_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    state_doc = {
        "plan_id": schedule["plan_id"],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_tasks": schedule["total_tasks"],
        "wave_count": schedule["wave_count"],
        "budget": schedule["budget"],
        "budget_per_task": schedule["budget_per_task"],
        "budget_allocated": schedule["budget_per_task"] * schedule["total_tasks"],
        "weighted": schedule.get("weighted", False),
        "parallel_waves": [w["wave"] for w in schedule["waves"] if w["parallel"]],
        "warnings": schedule["warnings"],
    }
    state_path = planning_dir / STATE_FILE
    state_path.write_text(
        json.dumps(state_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {"waves": str(waves_path), "state": str(state_path)}


def run_topo_sort(planning_dir: Path, *, budget: int = DEFAULT_BUDGET) -> Envelope:
    """端到端: 读 taskRecord.yaml → 调度 → 写 waves.yaml + topo-state.json。"""
    loaded = _load_tasks(planning_dir)
    if isinstance(loaded, Envelope):
        return loaded
    plan_id, tasks = loaded

    schedule = cmd_schedule_waves(tasks, plan_id=plan_id, budget=budget, planning_dir=planning_dir)
    if not schedule.ok:
        return schedule

    files = _write_outputs(planning_dir, schedule.data)
    return Envelope.ok_envelope(
        plan_id=plan_id,
        wave_count=schedule.data["wave_count"],
        total_tasks=schedule.data["total_tasks"],
        budget_per_task=schedule.data["budget_per_task"],
        files_written=files,
        warnings=schedule.data.get("warnings", []),
    )


# =============================================================================
# CLI
# =============================================================================

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="topo_sort", description="topo_sort helper 确定性核算")
    sub = parser.add_subparsers(dest="command", required=True)

    p_topo = sub.add_parser("topo-sort", help="拓扑排序 + 环检测 (不落盘)")
    p_topo.add_argument("--planning-dir", required=True)

    sub.add_parser(
        "topo-sort-from-tasks",
        help="从 stdin JSON tasks 列表拓扑排序（不落盘）",
    )

    p_sched = sub.add_parser("schedule-waves", help="调度 + budget 分配 + 落盘")
    p_sched.add_argument("--planning-dir", required=True)
    p_sched.add_argument("--budget", type=int, default=DEFAULT_BUDGET)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.command == "topo-sort-from-tasks":
        try:
            tasks = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            emit(Envelope.fail(REASON_SCHEMA_INVALID, hint=f"stdin JSON 解析失败: {exc}"))
            return
        if not isinstance(tasks, list):
            emit(Envelope.fail(REASON_SCHEMA_INVALID, hint="stdin 必须是 JSON 数组"))
            return
        emit(cmd_topo_sort(tasks))
        return

    planning_dir = Path(args.planning_dir)

    if args.command == "topo-sort":
        loaded = _load_tasks(planning_dir)
        if isinstance(loaded, Envelope):
            emit(loaded)
            return
        _, tasks = loaded
        emit(cmd_topo_sort(tasks))
        return

    if args.command == "schedule-waves":
        if args.budget <= 0:
            emit(Envelope.fail(REASON_INVALID_ARG, hint="--budget 必须 > 0"))
            return
        emit(run_topo_sort(planning_dir, budget=args.budget))
        return


if __name__ == "__main__":
    main(sys.argv[1:])
