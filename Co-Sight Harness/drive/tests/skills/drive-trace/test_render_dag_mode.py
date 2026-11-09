"""drive-trace/scripts/render.py 单测。

回归点（用户实际报告的现象）：
- 之前：DAG 模式只显 "wave 4 / 8"，看不到 wave 内的 agents、看不到 inputs / outputs
- 现在：active_agents[] 全部按 wave 分组渲染；每个 agent 卡片含
  input (prompt_excerpt) / skills called / commands run / output (artifacts/W{wave}_{id}_*)

覆盖：
1. DAG 模式（state.active_agents 非空）触发 _render_dag_stream
2. 每个 active_agents.id 都出现在 HTML
3. 按 wave 分组（"wave 1" / "wave 2"...）
4. agent_spawned 事件的 prompt_excerpt 进入 input 字段
5. artifact 文件名匹配 W{wave}_{id}_* 进入 output 字段
6. phase 模式（无 active_agents）走原路径 — 不破回归
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import render as rt  # noqa: E402  (sys.path via conftest)


def _make_data(tmp_path: Path, *, mode: str, active_agents: list | None = None,
               events: list | None = None, artifacts: dict | None = None,
               current_wave: int = 0):
    """Build a minimal `data` dict for render_html()."""
    # Create artifact files
    plan_dir = tmp_path / "plan-x"
    art_dir = plan_dir / "artifacts"
    if artifacts:
        art_dir.mkdir(parents=True, exist_ok=True)
        for fname in artifacts:
            (art_dir / fname).write_text("x", encoding="utf-8")

    state: dict = {"schema_version": "drive.runtime.state.v1"}
    if active_agents is not None:
        state["active_agents"] = active_agents
        state["current_wave"] = current_wave
        state["waves_total"] = max((a.get("wave", 0) for a in active_agents), default=0)

    return {
        "plan_name": "plan-x",
        "mode": mode,
        "plan_dir_path": str(plan_dir),
        "run_meta": {},
        "state": state,
        "events": events or [],
        "workflow_yaml": "",
    }


def _agent(agent_id: str, wave: int, status: str = "completed",
           started_at: str = "2026-09-23T08:53:16+00:00",
           updated_at: str = "2026-09-23T08:53:52+00:00") -> dict:
    return {
        "id": agent_id,
        "wave": wave,
        "status": status,
        "started_at": started_at,
        "updated_at": updated_at,
    }


def test_dag_mode_dispatches_to_dag_stream(tmp_path):
    """state.active_agents 非空 → DAG 渲染分支（不再仅显示 "wave 4 / 8"）。"""
    data = _make_data(
        tmp_path,
        mode="phase",  # 模式串用 phase 也行（DAG 由 state 信号触发）
        active_agents=[
            _agent("planner", 1),
            _agent("code-architect", 3, status="running"),
        ],
        current_wave=3,
    )
    html = rt.render_html(data, "phase")

    # 关键：每个 active_agents.id 都要在 HTML 里（不是只显 wave 计数）
    assert "planner" in html, "DAG mode missing 'planner' agent id"
    assert "code-architect" in html, "DAG mode missing 'code-architect' agent id"

    # wave 分组标题
    assert "wave 1" in html, "missing wave 1 header"
    assert "wave 3" in html, "missing wave 3 header"
    assert "← current" in html, "current wave not marked"


def test_dag_mode_shows_prompt_excerpt_in_input(tmp_path):
    """agent_spawned 事件的 prompt_excerpt 进入 input 字段（不再是 '暂无'）。"""
    data = _make_data(
        tmp_path,
        mode="dag",
        active_agents=[_agent("planner", 1)],
        events=[{
            "ts": "2026-09-23T08:53:30+00:00",
            "event": "agent_spawned",
            "subagent_type": "planner",
            "prompt_excerpt": "你是 drive DAG wave 0 · planner",
        }],
    )
    html = rt.render_html(data, "dag")

    assert "你是 drive DAG wave 0 · planner" in html, \
        "input excerpt from agent_spawned not rendered"


def test_dag_mode_shows_output_artifacts(tmp_path):
    """artifacts/W{wave}_{id}_* 文件名进入 output 字段。"""
    data = _make_data(
        tmp_path,
        mode="dag",
        active_agents=[_agent("code-architect", 3, status="completed")],
        artifacts=["W3_code-architect_BLUEPRINT.md", "W3_code-architect_notes.md"],
    )
    html = rt.render_html(data, "dag")

    assert "W3_code-architect_BLUEPRINT.md" in html, "output file BLUEPRINT.md not in HTML"
    assert "W3_code-architect_notes.md" in html, "output file notes.md not in HTML"


def test_dag_mode_counts_skills_and_bash(tmp_path):
    """skill_tool_called / bash_called 计数进入 skills / commands 字段。"""
    events = [
        # 3 bash_called + 1 skill_tool_called during planner's ts range
        {"ts": "2026-09-23T08:53:20+00:00", "event": "bash_called", "command": "ls"},
        {"ts": "2026-09-23T08:53:25+00:00", "event": "bash_called", "command": "pwd"},
        {"ts": "2026-09-23T08:53:30+00:00", "event": "bash_called", "command": "cat x"},
        {"ts": "2026-09-23T08:53:35+00:00", "event": "skill_tool_called",
         "skill_name": "drive:dag-runtime"},
    ]
    data = _make_data(
        tmp_path,
        mode="dag",
        active_agents=[_agent("planner", 1)],
        events=events,
    )
    html = rt.render_html(data, "dag")

    assert "3 次" in html, "bash count 3 not in HTML"
    assert "1 次" in html, "skill count 1 not in HTML"


def test_phase_mode_unchanged_when_no_active_agents(tmp_path):
    """无 active_agents → 走原 phase 渲染（不破旧路径）。"""
    data = _make_data(
        tmp_path,
        mode="phase",
        active_agents=None,  # 缺省：无 active_agents
        events=[{
            "ts": "2026-09-23T08:41:25+00:00",
            "event": "agent_spawned",
            "subagent_type": "drive:analyzer",
            "prompt_excerpt": "analyze this",
        }],
    )
    state = data["state"]
    state["active_stage"] = "analyze"
    state["confirmed_stages"] = []
    html = rt.render_html(data, "phase")

    # phase 模式保留：含 phase-mode 关键标记
    # 不应误触发 DAG 分组
    assert "wave 1" not in html, "phase mode should NOT render DAG wave headers"
    assert "running" in html, "phase mode should still render current running agent"