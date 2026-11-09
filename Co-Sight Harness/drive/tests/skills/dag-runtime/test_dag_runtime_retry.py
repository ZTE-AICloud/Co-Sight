"""dag-runtime/scripts/dag_runtime.py mark-retry-attempted 单测。

覆盖 cmd_mark_retry_attempted 的关键分支：
1. retry_count 累加
2. last_retry_at 写当前时间戳
3. last_retry_reason 记录
4. retry 后清除 state.verdicts[agent_id]（verdict 不应跨 retry 复用）
5. retry 不改 agent status（orchestrator 决定后续 mark-*）
6. run-log 写 node_retry_attempted 事件
7. 未知 agent → REASON_UNKNOWN_AGENT
8. 缺 --agent-id → REASON_INVALID_ARG
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

import dag_runtime as dr  # noqa: E402  (sys.path via conftest)


def _seed_state(
    planning_dir: Path,
    *,
    active_agents: list | None = None,
    verdicts: dict | None = None,
) -> None:
    planning_dir.mkdir(parents=True, exist_ok=True)
    state: dict = {
        "schema_version": "drive.runtime.state.v1",
        "revision": 0,
        "active_stage": None,
        "status": "executing",
        "current_wave": 1,
        "waves_total": 1,
        "task_results": {},
        "wave_summaries": {},
        "next_action": None,
        "confirmed_stages": [],
        "confirmed_nodes": [],
        "pending_confirmation": None,
        "verdict": None,
        "verdicts": verdicts or {},
        "active_agents": active_agents or [],
        "agent_invocations": {},
        "created_at": "2026-09-23T08:00:00+00:00",
        "updated_at": "2026-09-23T08:00:00+00:00",
    }
    (planning_dir / "executeState.json").write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )


def _read_state(planning_dir: Path) -> dict:
    return json.loads((planning_dir / "executeState.json").read_text(encoding="utf-8"))


def _agent(agent_id: str, status: str = "failed", retry_count: int = 0) -> dict:
    return {
        "id": agent_id,
        "wave": 1,
        "status": status,
        "started_at": "2026-09-23T08:01:00+00:00",
        "updated_at": "2026-09-23T08:05:00+00:00",
        "retry_count": retry_count,
    }


def _args(planning_dir: Path, agent_id: str | None = None, reason: str | None = None) -> argparse.Namespace:
    return argparse.Namespace(
        planning_dir=planning_dir,
        agent_id=agent_id,
        reason=reason,
    )


# ---------- happy path ----------


def test_retry_increments_retry_count(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth", retry_count=2)])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="transient"))
    assert env.ok
    state = _read_state(p)
    a = state["active_agents"][0]
    assert a["retry_count"] == 3
    assert a["status"] == "failed", "retry should not change agent status"


def test_retry_records_last_retry_at_and_reason(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth")])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="bad input"))
    assert env.ok
    state = _read_state(p)
    a = state["active_agents"][0]
    assert "last_retry_at" in a
    assert a["last_retry_reason"] == "bad input"


def test_retry_clears_existing_verdict(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(
        p,
        active_agents=[_agent("impl-auth")],
        verdicts={"impl-auth": "pass"},
    )
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="resubmit"))
    assert env.ok
    state = _read_state(p)
    assert "impl-auth" not in state["verdicts"], \
        "retry must clear stale verdict; verdict not carried across attempts"


def test_retry_writes_audit_event(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth")])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="transient"))
    assert env.ok
    log_path = p / "run-log.jsonl"
    assert log_path.exists(), "retry must append to run-log"
    events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    retry_events = [e for e in events if e.get("event") == "node_retry_attempted"]
    assert len(retry_events) == 1
    e = retry_events[0]
    assert e["agent_id"] == "impl-auth"
    assert e["retry_count"] == 1
    assert e["reason"] == "transient"


# ---------- failure cases ----------


def test_retry_unknown_agent_returns_reason(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth")])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="ghost", reason="x"))
    assert not env.ok
    assert env.reason == dr.REASON_UNKNOWN_AGENT


def test_retry_missing_agent_id_returns_reason(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth")])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id=None, reason="x"))
    assert not env.ok
    assert env.reason == dr.REASON_INVALID_ARG


def test_retry_no_active_agents_returns_reason(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="x"))
    assert not env.ok
    assert env.reason == dr.REASON_UNKNOWN_AGENT


# ---------- budget ----------


def test_retry_budget_default_3_blocks_4th(tmp_path: Path):
    """retry_count 已有 3 → 第 4 次 retry 默认拒绝。"""
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth", retry_count=3)])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="again"))
    assert not env.ok
    assert env.reason == dr.REASON_RETRY_BUDGET_EXCEEDED
    assert env.details["retry_count"] == 3
    assert env.details["max_retries"] == 3


def test_retry_budget_blocks_does_not_increment(tmp_path: Path):
    """budget 拒绝时不递增 retry_count，不写 audit。"""
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth", retry_count=3)])
    env = dr.cmd_mark_retry_attempted(_args(p, agent_id="impl-auth", reason="x"))
    assert not env.ok
    state = _read_state(p)
    a = state["active_agents"][0]
    assert a["retry_count"] == 3, "budget reject must not mutate retry_count"
    assert "last_retry_at" not in a
    log_path = p / "run-log.jsonl"
    if log_path.exists():
        events = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        assert not any(e.get("event") == "node_retry_attempted" for e in events)


def test_retry_budget_custom_max_retries(tmp_path: Path):
    """--max-retries 覆盖默认。retry_count 已达 max → 拒绝。"""
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth", retry_count=2)])
    args = argparse.Namespace(
        planning_dir=p,
        agent_id="impl-auth",
        reason="x",
        max_retries=2,
    )
    env = dr.cmd_mark_retry_attempted(args)
    assert not env.ok
    assert env.reason == dr.REASON_RETRY_BUDGET_EXCEEDED
    assert env.details["max_retries"] == 2


def test_retry_budget_custom_allows_under(tmp_path: Path):
    """--max-retries=10 且 retry_count=5 → 放行。"""
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth", retry_count=5)])
    args = argparse.Namespace(
        planning_dir=p,
        agent_id="impl-auth",
        reason="x",
        max_retries=10,
    )
    env = dr.cmd_mark_retry_attempted(args)
    assert env.ok
    state = _read_state(p)
    assert state["active_agents"][0]["retry_count"] == 6


def test_retry_negative_max_retries_fails(tmp_path: Path):
    p = tmp_path / "plan"
    _seed_state(p, active_agents=[_agent("impl-auth")])
    args = argparse.Namespace(
        planning_dir=p,
        agent_id="impl-auth",
        reason="x",
        max_retries=-1,
    )
    env = dr.cmd_mark_retry_attempted(args)
    assert not env.ok
    assert env.reason == dr.REASON_INVALID_ARG