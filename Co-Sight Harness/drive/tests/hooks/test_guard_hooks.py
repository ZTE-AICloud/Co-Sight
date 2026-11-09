"""hooks/planning_write_guard.py + state_transition_guard.py 单元测试（subprocess 驱动）。

守卫脚本被 Claude Code 以独立进程执行（stdin JSON → exit 0 放行 / 2 阻断）。
本测试从进程边界验收，覆盖 hooks_protocol 决策规则在脚本层的正确落地。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
WRITE_GUARD = ROOT / "hooks" / "planning_write_guard.py"
TRANSITION_GUARD = ROOT / "hooks" / "state_transition_guard.py"

# PROP-20260817-001：.planning/ → .drive/plan-<ts>-<name>/
TEST_PLAN_DIR = "plan-test"


def _run(hook: Path, project_dir: Path, hook_input) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    stdin = "" if hook_input is None else json.dumps(hook_input)
    return subprocess.run(
        [sys.executable, str(hook)],
        cwd=project_dir,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _project(tmp_path: Path, stage: str = "execute") -> Path:
    project = tmp_path / "project"
    planning = project / ".drive" / TEST_PLAN_DIR
    planning.mkdir(parents=True)
    (planning / "executeState.json").write_text(
        json.dumps({"active_stage": stage, "revision": 1}), encoding="utf-8"
    )
    # .current-plan 标记供 hook_io.find_active_plan_dir 找到当前 plan
    (project / ".drive" / ".current-plan").write_text(TEST_PLAN_DIR, encoding="utf-8")
    return project


def _p(project: Path, *parts: str) -> str:
    """造一个 plan 子目录下的子路径。"""
    return str(project / ".drive" / TEST_PLAN_DIR / "/".join(parts))


class TestPlanningWriteGuard:
    def test_non_whitelist_planning_write_blocked(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(
            WRITE_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": _p(project, "foo.txt")}},
        )
        assert proc.returncode == 2
        assert "BLOCKED" in proc.stderr

    def test_state_file_write_blocked(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(
            WRITE_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": _p(project, "executeState.json")}},
        )
        assert proc.returncode == 2
        assert "SDK" in proc.stderr

    def test_whitelisted_write_allowed(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(
            WRITE_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": _p(project, "summary.md")}},
        )
        assert proc.returncode == 0

    def test_non_planning_write_allowed(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(
            WRITE_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": str(project / "src/main.py")}},
        )
        assert proc.returncode == 0

    def test_read_tool_ignored(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(
            WRITE_GUARD,
            project,
            {"tool_name": "Read", "tool_input": {"file_path": _p(project, "foo.txt")}},
        )
        assert proc.returncode == 0

    def test_empty_stdin_allowed(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(WRITE_GUARD, project, None)
        assert proc.returncode == 0


class TestStateTransitionGuard:
    def test_illegal_transition_blocked(self, tmp_path):
        project = _project(tmp_path, stage="start")
        proc = _run(
            TRANSITION_GUARD,
            project,
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "DRIVE_TRUSTED=1 python3 state_cli.py transition --from start --to execute"
                },
            },
        )
        assert proc.returncode == 2
        assert "BLOCKED" in proc.stderr

    def test_legal_transition_allowed(self, tmp_path):
        project = _project(tmp_path, stage="start")
        proc = _run(
            TRANSITION_GUARD,
            project,
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "DRIVE_TRUSTED=1 python3 state_cli.py transition --from start --to analyze"
                },
            },
        )
        assert proc.returncode == 0

    def test_non_transition_bash_allowed(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(
            TRANSITION_GUARD,
            project,
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        )
        assert proc.returncode == 0

    def test_cross_stage_write_blocked(self, tmp_path):
        project = _project(tmp_path, stage="execute")
        proc = _run(
            TRANSITION_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": _p(project, "plan-summary.md")}},
        )
        assert proc.returncode == 2
        assert "污染" in proc.stderr

    def test_same_stage_write_allowed(self, tmp_path):
        project = _project(tmp_path, stage="plan")
        proc = _run(
            TRANSITION_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": _p(project, "plan-summary.md")}},
        )
        assert proc.returncode == 0

    def test_no_state_file_write_allowed(self, tmp_path):
        # 无 executeState.json → active_stage 未知 → 跨阶段判定放行。
        project = tmp_path / "bare"
        (project / ".drive" / TEST_PLAN_DIR).mkdir(parents=True)
        (project / ".drive" / ".current-plan").write_text(TEST_PLAN_DIR, encoding="utf-8")
        proc = _run(
            TRANSITION_GUARD,
            project,
            {"tool_name": "Write", "tool_input": {"file_path": _p(project, "plan-summary.md")}},
        )
        assert proc.returncode == 0

    def test_empty_stdin_allowed(self, tmp_path):
        project = _project(tmp_path)
        proc = _run(TRANSITION_GUARD, project, None)
        assert proc.returncode == 0


class TestHooksJson:
    def test_valid_json_and_registers_guards(self):
        data = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        commands = json.dumps(data)
        assert "planning_write_guard.py" in commands
        assert "state_transition_guard.py" in commands
        assert "PreToolUse" in data["hooks"]