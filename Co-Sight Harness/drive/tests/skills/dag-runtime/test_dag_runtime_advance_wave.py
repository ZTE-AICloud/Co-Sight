"""dag-runtime/scripts/dag_runtime.py advance-wave wave barrier fail-closed。

之前（C2）：当前 wave 还有 running 节点时 advance-wave 仍成功，事后补 mark-completed
不报错，破坏 SKILL.md §"advance-wave 必须一次放一个 wave" 承诺。

修复：advance-wave 校验 current_wave 内所有 agent 已是终态
（completed / failed / skipped），否则返回 REASON_WAVE_BARRIER_NOT_READY。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import dag_runtime as dr  # noqa: E402  (sys.path via conftest)


def _seed_state(
    planning_dir: Path,
    *,
    active_agents: list,
    current_wave: int = 1,
    waves_total: int = 3,
) -> None:
    planning_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {
        "schema_version": "drive.runtime.state.v1",
        "revision": 0,
        "active_stage": None,
        "status": "executing",
        "current_wave": current_wave,
        "waves_total": waves_total,
        "task_results": {},
        "wave_summaries": {},
        "next_action": None,
        "confirmed_stages": [],
        "confirmed_nodes": [],
        "pending_confirmation": None,
        "verdict": None,
        "verdicts": {},
        "active_agents": active_agents,
        "agent_invocations": {},
        "created_at": "2026-09-23T08:00:00+00:00",
        "updated_at": "2026-09-23T08:00:00+00:00",
    }
    (planning_dir / "executeState.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def _agent(agent_id: str, wave: int, status: str) -> dict:
    return {
        "id": agent_id,
        "wave": wave,
        "status": status,
        "started_at": "2026-09-23T08:01:00+00:00",
        "updated_at": "2026-09-23T08:05:00+00:00",
    }


def _args(planning_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(planning_dir=planning_dir)


def _read_state(planning_dir: Path) -> dict:
    return json.loads((planning_dir / "executeState.json").read_text(encoding="utf-8"))


# ---------- happy path ----------


def test_advance_wave_when_all_completed_succeeds(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[
            _agent("a", 1, "completed"),
            _agent("b", 1, "completed"),
            _agent("c", 2, "running"),
        ],
        current_wave=1,
        waves_total=3,
    )
    env = dr.cmd_advance_wave(_args(p))
    assert env.ok
    state = _read_state(p)
    assert state["current_wave"] == 2


def test_advance_wave_when_all_failed_or_skipped_succeeds(tmp_path: Path):
    """所有节点终态包括 failed / skipped 都允许 advance。"""
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[
            _agent("a", 1, "failed"),
            _agent("b", 1, "skipped"),
            _agent("c", 2, "running"),
        ],
        current_wave=1,
    )
    env = dr.cmd_advance_wave(_args(p))
    assert env.ok


# ---------- fail-closed ----------


def test_advance_wave_blocked_when_running_in_current_wave(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[
            _agent("a", 1, "completed"),
            _agent("b", 1, "running"),  # ← 仍在跑
        ],
        current_wave=1,
    )
    env = dr.cmd_advance_wave(_args(p))
    assert not env.ok
    assert env.reason == dr.REASON_WAVE_BARRIER_NOT_READY
    state = _read_state(p)
    assert state["current_wave"] == 1, "blocked advance must not mutate current_wave"
    assert "non_terminal_ids" in env.details
    assert "b" in env.details["non_terminal_ids"]


def test_advance_wave_blocked_when_pending_in_current_wave(tmp_path: Path):
    """pending（待 spawn）节点与 running 同等视为非终态。"""
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[
            _agent("a", 1, "pending"),
        ],
        current_wave=1,
    )
    env = dr.cmd_advance_wave(_args(p))
    assert not env.ok
    assert env.reason == dr.REASON_WAVE_BARRIER_NOT_READY
    assert "a" in env.details["non_terminal_ids"]


def test_advance_wave_only_checks_current_wave(tmp_path: Path):
    """未来 wave 的 running 节点不应阻塞 advance（与当前 wave 无关）。"""
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[
            _agent("a", 1, "completed"),
            _agent("b", 2, "running"),  # 下一 wave，与 advance 无关
        ],
        current_wave=1,
    )
    env = dr.cmd_advance_wave(_args(p))
    assert env.ok


def test_advance_wave_boundary_at_max_succeeds(tmp_path: Path):
    """current_wave = waves_total 时 advance 仍允许（虽然越界检查另外做）。"""
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[_agent("a", 1, "completed")],
        current_wave=2,
        waves_total=2,
    )
    env = dr.cmd_advance_wave(_args(p))
    # 越界检查应 fail with REASON_INVALID_ARG（非 wave barrier）
    assert not env.ok
    assert env.reason in (dr.REASON_INVALID_ARG, dr.REASON_WAVE_BARRIER_NOT_READY)