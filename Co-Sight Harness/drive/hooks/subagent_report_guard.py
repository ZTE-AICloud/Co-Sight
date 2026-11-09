#!/usr/bin/env python3
"""subagent_report_guard.py — SubagentStop 兜底。

履职完毕的 agent 自己汇报状态。若它异常退出没来得及汇报，state 会停在旧值，
编排层可能误以为工作已完成 —— 这种失败不报错、不中断，只是静默停滞，比崩溃
更难发现。本 hook 在 subagent 结束时比对 state revision，未变则标记异常。

判定范围只含**持有阶段的 agent**（workflow.yaml 里 phases[].agent 声明的那些）。
会计、worker 这类被雇佣的 agent 本就不推进阶段，把它们算进来只会制造误报。

stdin JSON: {"subagent_type": "...", ...}
exit: 恒 0 —— 兜底只标记不阻断，agent 已经结束了，拦也拦不住什么。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import hook_io

# 无 workflow.yaml 时的默认阶段责任人。
# scoped 地址形式：plugin 阶段 agent 现在写为 drive:<name>（见 PROP-20260806-001）
DEFAULT_PHASE_AGENTS: frozenset[str] = frozenset(
    {"drive:analyzer", "drive:planner", "drive:executor", "drive:evaluator"}
)


# workflow_runtime 单点解析用户态 workflow.yaml。hooks/ 不在 sys.path，
# 通过 spec_from_file_location 显式加载，与 SHARED_MODULES 豁免配套。
_REAL_WORKFLOW_RUNTIME = (
    Path(__file__).resolve().parent.parent
    / "skills" / "state-machine" / "scripts" / "workflow_runtime.py"
)
_MODULE_NAME = "_drive_workflow_runtime_singleton"

_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _REAL_WORKFLOW_RUNTIME)
_workflow_runtime = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules[_MODULE_NAME] = _workflow_runtime
_spec.loader.exec_module(_workflow_runtime)  # type: ignore[union-attr]


def phase_agents(planning_dir) -> frozenset[str]:
    """从 user workflow.yaml 读各 phase 的责任人；读不到 / 非 phase mode 回 DEFAULT。

    调 workflow_runtime 拿合法阶段集合，回退 DEFAULT_PHASE_AGENTS：
    - 无 workflow.yaml → DEFAULT
    - workflow.yaml 是 DAG mode → DEFAULT（subagent_report_guard 只关心 phase mode
      "持有阶段"概念；DAG mode 下没有这个语义，与 audit C5/C6 经验一致）
    - workflow.yaml 损坏 / 非 dict → DEFAULT（与原 yaml.safe_load fail-soft 语义一致）
    - phase mode 正常解析 → 返合法 stage 集合
    """
    if planning_dir is None or not Path(planning_dir).is_dir():
        return DEFAULT_PHASE_AGENTS
    try:
        phases, source = _workflow_runtime.resolve_workflow_phases(Path(planning_dir))
    except _workflow_runtime.WorkflowRuntimeError:
        return DEFAULT_PHASE_AGENTS
    if source != _workflow_runtime.SOURCE_USER_YAML:
        return DEFAULT_PHASE_AGENTS
    if not phases.phase_agents:
        return DEFAULT_PHASE_AGENTS
    return phases.phase_agents


def last_spawn(events: list[dict]) -> dict | None:
    """取最近一条 agent_spawned 事件。"""
    for event in reversed(events):
        if event.get("event") == "agent_spawned":
            return event
    return None


def already_flagged(events: list[dict], spawn_ts: str | None) -> bool:
    """同一次 spawn 只标记一次，避免重复告警。"""
    if spawn_ts is None:
        return False
    for event in reversed(events):
        if event.get("event") == "agent_no_state_report":
            return event.get("spawn_ts") == spawn_ts
        if event.get("event") == "agent_spawned" and event.get("ts") == spawn_ts:
            return False
    return False


def main() -> int:
    hook_io.read_hook_input()  # 消费 stdin，避免上游阻塞

    planning_dir = hook_io.find_active_plan_dir()
    if planning_dir is None:
        return 0

    events = hook_io.read_run_log(planning_dir)
    spawn = last_spawn(events)
    if spawn is None:
        return 0

    agent = str(spawn.get("subagent_type", ""))
    if agent not in phase_agents(planning_dir):
        return 0  # 被雇佣的 agent 不负责推进阶段，不判漏报

    baseline = spawn.get("state_revision_at_spawn")
    current = hook_io.read_state_revision(planning_dir)
    if baseline is None or current is None:
        return 0  # 基线或现值缺失，无从比对，不瞎猜

    if current > baseline:
        return 0  # 汇报过了

    if already_flagged(events, spawn.get("ts")):
        return 0

    hook_io.append_run_log(
        planning_dir,
        "agent_no_state_report",
        subagent_type=agent,
        spawn_ts=spawn.get("ts"),
        state_revision=current,
        detail=(
            f"{agent} 持有阶段但结束时未汇报状态（revision 仍为 {current}）。"
            f"该阶段可能未真正完成，续跑前请人工确认。"
        ),
    )
    print(json.dumps({}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
