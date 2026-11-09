"""hooks/audit_events.py 单元测试（subprocess 驱动）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "audit_events.py"


def _run_hook(project_dir: Path, hook_input: dict) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=project_dir,
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _project_with_planning(tmp_path: Path, stage: str = "plan") -> tuple[Path, Path]:
    project = tmp_path / "project"
    planning = project / ".drive" / "plan-test"
    planning.mkdir(parents=True)
    (planning / "executeState.json").write_text(
        json.dumps({"active_stage": stage, "revision": 1}), encoding="utf-8"
    )
    # .current-plan 标记供 hook_io.find_active_plan_dir 找到当前 plan
    (project / ".drive" / ".current-plan").write_text("plan-test", encoding="utf-8")
    return project, planning


def _read_log(planning: Path) -> list[dict]:
    log = planning / "run-log.jsonl"
    if not log.is_file():
        return []
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_agent_spawn_recorded(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    proc = _run_hook(
        project,
        {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "planner", "description": "plan it", "prompt": "x" * 500},
            "session_id": "sess-1",
        },
    )
    assert proc.returncode == 0
    assert "Traceback" not in proc.stderr
    events = _read_log(planning)
    assert len(events) == 1
    ev = events[0]
    assert ev["event"] == "agent_spawned"
    assert ev["subagent_type"] == "planner"
    assert ev["active_stage"] == "plan"
    assert ev["session_id"] == "sess-1"
    assert ev["prompt_excerpt"].endswith("...")
    assert len(ev["prompt_excerpt"]) <= 203
    # PROP-20260817-001 机制 E：audit 字段扩展
    assert ev["plan_dir"] == "plan-test"
    assert ev["plan_name"] is None  # plan-test 不含 ts 前缀
    assert isinstance(ev["pid"], int) and ev["pid"] > 0


def test_audit_includes_plan_name_when_ts_prefix(tmp_path):
    """plan_dir 含 ts 前缀时 audit 自动提取 plan_name。"""
    import subprocess
    project = tmp_path / "project"
    plan = project / ".drive" / "plan-20260817-1530-add-user-auth"
    plan.mkdir(parents=True)
    (project / ".drive" / ".current-plan").write_text(
        "plan-20260817-1530-add-user-auth", encoding="utf-8"
    )
    (plan / "executeState.json").write_text(
        json.dumps({"active_stage": "plan", "revision": 1}), encoding="utf-8"
    )
    proc = _run_hook(
        project,
        {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": "s"},
    )
    assert proc.returncode == 0
    log = plan / "run-log.jsonl"
    events = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert events[0]["plan_dir"] == "plan-20260817-1530-add-user-auth"
    assert events[0]["plan_name"] == "add-user-auth"


def test_agent_tool_name_variant(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    _run_hook(project, {"tool_name": "Agent", "tool_input": {"subagent_type": "executor"}})
    events = _read_log(planning)
    assert events[0]["event"] == "agent_spawned"


def test_skill_recorded(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    _run_hook(project, {"tool_name": "Skill", "tool_input": {"skill": "startup"}})
    events = _read_log(planning)
    assert events[0]["event"] == "skill_tool_called"
    assert events[0]["skill_name"] == "startup"


def test_bash_recorded(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    _run_hook(project, {"tool_name": "Bash", "tool_input": {"command": "python -m lib.runtime.cli"}})
    events = _read_log(planning)
    assert events[0]["event"] == "bash_called"
    assert "lib.runtime.cli" in events[0]["command"]


def test_unaudited_tool_ignored(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    proc = _run_hook(project, {"tool_name": "Read", "tool_input": {"file_path": "/x"}})
    assert proc.returncode == 0
    assert _read_log(planning) == []


def test_never_blocks_returns_empty_json(tmp_path):
    project, _ = _project_with_planning(tmp_path)
    proc = _run_hook(project, {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}})
    assert proc.returncode == 0
    assert json.loads(proc.stdout.strip()) == {}


def test_no_planning_dir_passes_through(tmp_path):
    project = tmp_path / "bare"
    project.mkdir()
    proc = _run_hook(project, {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    assert proc.returncode == 0
    assert json.loads(proc.stdout.strip()) == {}


def test_empty_stdin_passes_through(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=project,
        input="",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0
    assert _read_log(planning) == []


def test_ts_precision_seconds(tmp_path):
    project, planning = _project_with_planning(tmp_path)
    _run_hook(project, {"tool_name": "Bash", "tool_input": {"command": "ls"}})
    ts = _read_log(planning)[0]["ts"]
    assert "." not in ts  # seconds precision, no microseconds
