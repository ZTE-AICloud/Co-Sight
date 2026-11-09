"""dag_flow.py —— DAG 模式 flow 决策。

提供 3 个高层决策 API：
- cascade_skip_downstream: 算 failed agent 的直接下游
- advance_to_wave: 读 active_agents + 算目标 wave 的 spawn spec
- finalize_workflow: 检查 verdict_required 闸门后宣告完成
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from envelope import (
    Envelope,
    REASON_FILE_NOT_FOUND,
    REASON_INVALID_ARG,
    REASON_SUBPROCESS_TIMEOUT,
    REASON_WAVE_SKIP,
    emit,
)

SCRIPT_DIR = Path(__file__).parent
PLUGIN_SKILLS = SCRIPT_DIR.parent.parent
DAG_RUNTIME = PLUGIN_SKILLS / "dag-runtime" / "scripts" / "dag_runtime.py"


def _run_subprocess(cmd: list[str], input_data: str | None = None, timeout: int = 30) -> dict[str, Any]:
    """调子进程，解析 envelope 协议。"""
    try:
        proc = subprocess.run(
            [sys.executable] + cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return Envelope.fail(
            REASON_SUBPROCESS_TIMEOUT, cmd=cmd, timeout=timeout
        ).to_dict()
    except FileNotFoundError as exc:
        return Envelope.fail(
            REASON_FILE_NOT_FOUND, cmd=cmd, error=str(exc)
        ).to_dict()

    if proc.returncode != 0:
        try:
            payload = json.loads(proc.stdout)
            if isinstance(payload, dict) and "ok" in payload:
                return payload
        except json.JSONDecodeError:
            pass
        return Envelope.fail(
            "subprocess_failed",
            cmd=cmd,
            returncode=proc.returncode,
            stderr=proc.stderr[:500],
        ).to_dict()

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return Envelope.fail(
            "subprocess_decode_failed",
            cmd=cmd,
            stdout=proc.stdout[:500],
            error=str(exc),
        ).to_dict()


def _read_active_agents(planning_dir: Path) -> dict[str, Any]:
    return _run_subprocess(
        [str(DAG_RUNTIME), "--planning-dir", str(planning_dir), "read-active-agents"]
    )


def cascade_skip_downstream(
    agents: list[dict[str, Any]],
    failed_agent_id: str,
    waves: list[list[str]],
) -> list[str]:
    """failed agent 的直接下游 agent id 列表（纯计算，无 IO）。

    实际场景可能需要级联到间接下游，但本实现先做直接下游，避免误伤太多。
    """
    failed_wave_idx = None
    for i, wave in enumerate(waves):
        if failed_agent_id in wave:
            failed_wave_idx = i
            break
    if failed_wave_idx is None:
        return []

    direct_downstream: list[str] = []
    for a in agents:
        if failed_agent_id in (a.get("depends_on") or []):
            direct_downstream.append(a["id"])

    return direct_downstream


def advance_to_wave(
    planning_dir: Path,
    workflow: dict[str, Any],
    target_wave: int,
) -> dict[str, Any]:
    """推进到指定 wave 返回 spawn spec（只读 + 决策）。

    增量：从 state 读 active_agents + current_wave，只算目标 wave 的 spawn spec。
    target_wave 必须等于 current_wave+1（barrier 一次放一个 wave），否则 wave_skip fail-closed。
    """
    state_result = _read_active_agents(planning_dir)
    if not state_result.get("ok"):
        return state_result

    state_data = state_result.get("data") or {}
    active = state_data.get("active_agents") or []
    current_wave = int(state_data.get("current_wave") or 0)

    waves_map: dict[int, list[str]] = {}
    for entry in active:
        if not isinstance(entry, dict):
            continue
        try:
            w = int(entry.get("wave", 0))
            aid = str(entry.get("id") or "")
        except (TypeError, ValueError):
            continue
        if w <= 0 or not aid:
            continue
        waves_map.setdefault(w, []).append(aid)
    stored_max_wave = max(waves_map) if waves_map else 0

    if not waves_map:
        return Envelope.fail(
            REASON_INVALID_ARG,
            error="state 里没有 active_agents；先调 dag-init plan-waves 初始化",
        ).to_dict()

    if target_wave < 1 or target_wave > stored_max_wave:
        return Envelope.fail(
            REASON_INVALID_ARG,
            hint=f"target_wave={target_wave} 超出范围",
            total_waves=stored_max_wave,
        ).to_dict()

    if target_wave > current_wave + 1:
        return Envelope.fail(
            REASON_WAVE_SKIP,
            hint="barrier 必须一次放一个 wave",
            current_wave=current_wave,
            target_wave=target_wave,
        ).to_dict()

    wave_agents = waves_map.get(target_wave, [])
    agents_by_id = {a["id"]: a for a in workflow.get("agents", [])}
    spawn_specs = [
        {"agent_id": aid, "subagent_type": agents_by_id[aid]["agent"]}
        for aid in wave_agents
        if aid in agents_by_id
    ]
    return {
        "ok": True,
        "data": {
            "wave": target_wave,
            "agent_ids": wave_agents,
            "spawn_specs": spawn_specs,
        },
    }


def _check_terminal_verdict(
    planning_dir: Path,
    verdict_required_ids: list[str],
) -> dict[str, Any]:
    """委托 dag_runtime.check-terminal-verdict 验 verdict gate（只读）。"""
    return _run_subprocess(
        [
            str(DAG_RUNTIME),
            "--planning-dir",
            str(planning_dir),
            "check-terminal-verdict",
            "--verdict-required-agents",
            json.dumps(verdict_required_ids, ensure_ascii=False),
        ],
        timeout=10,
    )


def finalize_workflow(
    planning_dir: Path,
    workflow: dict[str, Any],
) -> dict[str, Any]:
    """workflow 收尾闸门：检查 verdict_required 闸门后宣告完成（只读）。

    设计：
    - workflow 中 verdict_required=true 的 agent（必同时是 terminal）需要 verdict=pass
    - 无 verdict_required agent → 不检查，直接 done
    - 有但 verdict != pass → fail，orchestrator 不能宣告收工
    - 有且 verdict=pass → done
    """
    verdict_required_ids = [
        a["id"]
        for a in workflow.get("agents", [])
        if a.get("verdict_required")
    ]

    if not verdict_required_ids:
        return {
            "ok": True,
            "data": {
                "done": True,
                "reason": "no_verdict_required",
            },
        }

    result = _check_terminal_verdict(planning_dir, verdict_required_ids)
    if not result.get("ok"):
        return result

    return {
        "ok": True,
        "data": {
            "done": True,
            "reason": "verdict_pass",
            "verdict_required_agents": verdict_required_ids,
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dag_flow",
        description="DAG 模式 flow 决策（不写 state）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_advance = sub.add_parser("advance", help="推进到指定 wave 返回 spawn spec")
    p_advance.add_argument("--workflow", type=Path, required=True)
    p_advance.add_argument("--planning-dir", type=Path, required=True)
    p_advance.add_argument("--target-wave", type=int, required=True)

    p_finalize = sub.add_parser(
        "finalize",
        help="检查 verdict_required 闸门后宣告 workflow 完成",
    )
    p_finalize.add_argument("--workflow", type=Path, required=True)
    p_finalize.add_argument("--planning-dir", type=Path, required=True)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    sys.path.insert(0, str(SCRIPT_DIR))
    from read_workflow import load_workflow

    env = load_workflow(str(args.workflow.parent))
    if not env.ok:
        print(env.to_json())
        sys.exit(1)
    workflow = env.data

    if args.command == "advance":
        result = advance_to_wave(args.planning_dir, workflow, args.target_wave)
    elif args.command == "finalize":
        result = finalize_workflow(args.planning_dir, workflow)
    else:
        result = {"ok": False, "reason": "unknown_command"}

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    sys.exit(0 if result.get("ok") else 1)


__all__ = [
    "cascade_skip_downstream",
    "advance_to_wave",
    "finalize_workflow",
]


if __name__ == "__main__":
    main(sys.argv[1:])
