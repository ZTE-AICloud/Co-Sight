"""agent 漏报 state 的兜底。

P6 把 state 写入责任交给 agent 后出现一类新风险：agent 异常退出没来得及汇报，
state 停在旧值，编排层可能误以为工作已完成。这种失败不报错、不中断，只是静默
停滞 —— 比崩溃更难发现，故需兜底标记。

误报比漏报更糟：会计、worker 这类被雇佣的 agent 本就不推进阶段，若把它们算进
判定范围，每轮执行都会刷一堆假告警，真问题会被淹掉。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.script_loader import scripts_dir

HOOKS = scripts_dir("hooks")
GUARD = HOOKS / "subagent_report_guard.py"
AUDIT = HOOKS / "audit_events.py"
STATE_CLI = scripts_dir("state-machine") / "state_cli.py"


TEST_PLAN_DIR = "plan-test"


@pytest.fixture
def workspace(tmp_path):
    planning = tmp_path / ".drive" / TEST_PLAN_DIR
    planning.mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(STATE_CLI), "update",
         "--planning-dir", str(planning), "--set", "active_stage=plan"],
        capture_output=True, check=True,
    )
    return tmp_path


def spawn(workspace: Path, agent: str) -> None:
    """模拟 agent 被派发（走真实的 audit hook，记下 revision 基线）。"""
    payload = json.dumps({
        "tool_name": "Task",
        "tool_input": {"subagent_type": agent, "description": "d"},
        "session_id": "s",
    })
    subprocess.run(
        [sys.executable, str(AUDIT)], input=payload,
        capture_output=True, text=True, cwd=workspace, check=True,
    )


def subagent_stop(workspace: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(GUARD)], input="{}",
        capture_output=True, text=True, cwd=workspace,
    )


def report_state(workspace: Path, to_stage: str) -> None:
    """模拟 agent 正常汇报状态。流转默认要求人工确认，故先放行当前阶段。"""
    planning = workspace / ".drive" / TEST_PLAN_DIR
    subprocess.run(
        [sys.executable, str(HOOKS.parent / "skills" / "state-machine" / "scripts"
                             / "confirm_stage.py"),
         "--planning-dir", str(planning), "--stage", "plan"],
        capture_output=True,
    )
    subprocess.run(
        [sys.executable, str(STATE_CLI), "transition",
         "--planning-dir", str(workspace / ".drive" / TEST_PLAN_DIR), "--to", to_stage],
        capture_output=True, check=True,
        env={**os.environ, "DRIVE_TRUSTED": "1"},
    )


def flags(workspace: Path) -> list[dict]:
    path = workspace / ".drive" / TEST_PLAN_DIR / "run-log.jsonl"
    if not path.is_file():
        return []
    return [
        e for e in (
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
        if e["event"] == "agent_no_state_report"
    ]


def clear_log(workspace: Path) -> None:
    (workspace / ".drive" / TEST_PLAN_DIR / "run-log.jsonl").write_text("", encoding="utf-8")


# =============================================================================
# 该标记的情形
# =============================================================================

class TestFlagsMissingReport:
    def test_phase_agent_that_did_not_report_is_flagged(self, workspace):
        spawn(workspace, "drive:planner")
        subagent_stop(workspace)
        assert len(flags(workspace)) == 1

    def test_flag_names_the_agent(self, workspace):
        spawn(workspace, "drive:evaluator")
        subagent_stop(workspace)
        assert flags(workspace)[0]["subagent_type"] == "drive:evaluator"

    def test_flag_explains_the_risk_to_a_human(self, workspace):
        spawn(workspace, "drive:planner")
        subagent_stop(workspace)
        detail = flags(workspace)[0]["detail"]
        assert "未汇报" in detail
        assert "人工确认" in detail

    def test_flag_records_revision(self, workspace):
        spawn(workspace, "drive:analyzer")
        subagent_stop(workspace)
        assert isinstance(flags(workspace)[0]["state_revision"], int)

    @pytest.mark.parametrize("agent", ["drive:analyzer", "drive:planner", "drive:executor", "drive:evaluator"])
    def test_all_default_phase_agents_are_covered(self, workspace, agent):
        clear_log(workspace)
        spawn(workspace, agent)
        subagent_stop(workspace)
        assert len(flags(workspace)) == 1, f"{agent} 应被纳入判定范围"


# =============================================================================
# 不该标记的情形 —— 误报比漏报更糟
# =============================================================================

class TestAvoidsFalsePositives:
    def test_agent_that_reported_is_not_flagged(self, workspace):
        spawn(workspace, "drive:planner")
        report_state(workspace, "execute")
        subagent_stop(workspace)
        assert flags(workspace) == []

    @pytest.mark.parametrize("agent", ["accountant", "dispatcher", "some-helper"])
    def test_hired_agents_are_out_of_scope(self, workspace, agent):
        """被雇佣的 agent 不持有阶段，不该因"没推进阶段"被告警。"""
        clear_log(workspace)
        spawn(workspace, agent)
        subagent_stop(workspace)
        assert flags(workspace) == []

    def test_same_spawn_flagged_only_once(self, workspace):
        spawn(workspace, "drive:planner")
        for _ in range(3):
            subagent_stop(workspace)
        assert len(flags(workspace)) == 1

    def test_no_spawn_history_is_silent(self, workspace):
        subagent_stop(workspace)
        assert flags(workspace) == []

    def test_missing_planning_dir_is_silent(self, tmp_path):
        result = subagent_stop(tmp_path)
        assert result.returncode == 0

    def test_missing_state_is_silent(self, tmp_path):
        (tmp_path / ".drive" / TEST_PLAN_DIR).mkdir(parents=True)
        spawn(tmp_path, "drive:planner")
        result = subagent_stop(tmp_path)
        assert result.returncode == 0
        assert flags(tmp_path) == []


# =============================================================================
# 判定范围随 workflow.yaml 声明走
# =============================================================================

class TestScopeFollowsDeclaration:
    def _write_workflow(self, workspace: Path, body: str) -> None:
        (workspace / "workflow.yaml").write_text(body, encoding="utf-8")

    def test_custom_phase_agent_is_in_scope(self, workspace):
        self._write_workflow(workspace, """
phases:
  - stage: start
  - stage: plan
    agent: my-planner
""")
        spawn(workspace, "my-planner")
        subagent_stop(workspace)
        assert len(flags(workspace)) == 1

    def test_default_agent_not_declared_is_out_of_scope(self, workspace):
        """用户没派 evaluator 管阶段，就别拿默认集合去要求它。"""
        self._write_workflow(workspace, """
phases:
  - stage: start
  - stage: plan
    agent: my-planner
""")
        spawn(workspace, "drive:evaluator")
        subagent_stop(workspace)
        assert flags(workspace) == []

    def test_broken_workflow_falls_back_to_defaults(self, workspace):
        """声明读不了也要能兜底 —— 强制器不能因配置坏了就失效。"""
        self._write_workflow(workspace, "phases: [[[")
        spawn(workspace, "drive:planner")
        subagent_stop(workspace)
        assert len(flags(workspace)) == 1

    def test_phases_without_agents_falls_back_to_defaults(self, workspace):
        self._write_workflow(workspace, "phases:\n  - stage: start\n")
        spawn(workspace, "drive:planner")
        subagent_stop(workspace)
        assert len(flags(workspace)) == 1


# =============================================================================
# 兜底不阻断
# =============================================================================

class TestNeverBlocks:
    def test_exits_zero_when_flagging(self, workspace):
        spawn(workspace, "drive:planner")
        assert subagent_stop(workspace).returncode == 0

    def test_exits_zero_on_corrupt_run_log(self, workspace):
        (workspace / ".drive" / TEST_PLAN_DIR / "run-log.jsonl").write_text(
            "not json\n{也不是}\n", encoding="utf-8"
        )
        assert subagent_stop(workspace).returncode == 0


def test_registered_on_subagent_stop():
    """hook 必须真的注册在 SubagentStop 上，否则永远不会触发。"""
    config = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    entries = config["hooks"]["SubagentStop"]
    commands = [
        h["command"] for entry in entries for h in entry["hooks"]
    ]
    assert any("subagent_report_guard.py" in c for c in commands)
