"""dag_runtime 的 mark-completed 必须被 hook 强制人工确认。

DAG 模式没有阶段，只有节点。推进一个节点等于宣告"这个 agent 的产出可以进下游"，
与 phase 模式流出一个阶段同义，因此同样 default-deny：节点必须先出现在
confirmed_nodes 里。mark-failed / mark-skipped 不设门 —— 失败与 cascade skip 不是绿灯。
"""
from __future__ import annotations

import json

import pytest

from hooks_protocol import (
    check_dag_node_confirmation,
    check_state_transition,
    parse_mark_completed_command,
)

DAG_CLI = "python3 /plugin/skills/dag-runtime/scripts/dag_runtime.py"


def _write_state(
    planning_dir,
    *,
    confirmed_nodes: list[str] | None = None,
    auto_mode: bool = False,
    complexity: str | None = None,
    omit_field: bool = False,
) -> None:
    state: dict = {"mode": "dag", "auto_mode": auto_mode}
    if not omit_field:
        state["confirmed_nodes"] = list(confirmed_nodes or [])
    if complexity is not None:
        state["complexity"] = complexity
    (planning_dir / "executeState.json").write_text(
        json.dumps(state), encoding="utf-8"
    )


@pytest.fixture
def planning(monkeypatch, tmp_path):
    d = tmp_path / ".drive" / "plan-20260902-0000-t"
    d.mkdir(parents=True)
    monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: d)
    return d


# =============================================================================
# 解析
# =============================================================================

class TestParsing:
    def test_parses_agent_id(self):
        cmd = f"{DAG_CLI} mark-completed --planning-dir .drive/p --agent-id impl-auth"
        assert parse_mark_completed_command(cmd) == "impl-auth"

    def test_parses_equals_form(self):
        cmd = f"{DAG_CLI} mark-completed --planning-dir .drive/p --agent-id=impl-auth"
        assert parse_mark_completed_command(cmd) == "impl-auth"

    def test_planning_dir_value_not_mistaken_for_agent_id(self):
        cmd = f"{DAG_CLI} mark-completed --agent-id gate-1 --planning-dir /tmp/x/.drive/p"
        assert parse_mark_completed_command(cmd) == "gate-1"

    def test_mark_failed_is_not_a_completion(self):
        cmd = f"{DAG_CLI} mark-failed --planning-dir .drive/p --agent-id impl-auth"
        assert parse_mark_completed_command(cmd) is None

    def test_mark_skipped_is_not_a_completion(self):
        cmd = f"{DAG_CLI} mark-skipped --planning-dir .drive/p --agent-id impl-auth"
        assert parse_mark_completed_command(cmd) is None

    def test_unrelated_command_ignored(self):
        assert parse_mark_completed_command(f"{DAG_CLI} read-active-agents") is None

    def test_missing_agent_id_ignored(self):
        cmd = f"{DAG_CLI} mark-completed --planning-dir .drive/p"
        assert parse_mark_completed_command(cmd) is None

    def test_malformed_quoting_ignored(self):
        assert parse_mark_completed_command('mark-completed --agent-id "unclosed') is None


# =============================================================================
# 闸门判定
# =============================================================================

class TestGate:
    def test_unconfirmed_node_is_denied(self, planning):
        _write_state(planning, confirmed_nodes=[])
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        result = check_dag_node_confirmation(cmd)
        assert result.is_denied
        assert "impl-auth" in (result.message or "")
        assert "confirm_node.py" in (result.message or "")

    def test_confirmed_node_is_allowed(self, planning):
        _write_state(planning, confirmed_nodes=["impl-auth"])
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert not check_dag_node_confirmation(cmd).is_denied

    def test_other_node_confirmation_does_not_carry_over(self, planning):
        """确认是逐节点的：确认了 A 不等于放行 B。"""
        _write_state(planning, confirmed_nodes=["impl-api"])
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert check_dag_node_confirmation(cmd).is_denied

    def test_auto_mode_bypasses(self, planning):
        _write_state(planning, confirmed_nodes=[], auto_mode=True)
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert not check_dag_node_confirmation(cmd).is_denied

    @pytest.mark.parametrize("complexity", ["trivial", "standard", "complex"])
    def test_complexity_never_bypasses(self, planning, complexity):
        """DAG 不认 trivial —— 每个节点一律要确认。"""
        _write_state(planning, confirmed_nodes=[], complexity=complexity)
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert check_dag_node_confirmation(cmd).is_denied

    def test_mark_failed_not_gated(self, planning):
        _write_state(planning, confirmed_nodes=[])
        cmd = f"{DAG_CLI} mark-failed --planning-dir {planning} --agent-id impl-auth"
        assert not check_dag_node_confirmation(cmd).is_denied

    def test_mark_skipped_not_gated(self, planning):
        """cascade skip 必须能走 —— 上游失败时下游 skip 不需要人点头。"""
        _write_state(planning, confirmed_nodes=[])
        cmd = f"{DAG_CLI} mark-skipped --planning-dir {planning} --agent-id impl-api"
        assert not check_dag_node_confirmation(cmd).is_denied


# =============================================================================
# 容错梯度：判不了就放行，交由 CLI 自校验
# =============================================================================

class TestFallback:
    def test_missing_field_allows(self, planning):
        """旧 state 文件无该字段，不倒查历史项目。"""
        _write_state(planning, omit_field=True)
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert not check_dag_node_confirmation(cmd).is_denied

    def test_no_state_file_allows(self, planning):
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert not check_dag_node_confirmation(cmd).is_denied

    def test_no_plan_dir_allows(self, monkeypatch):
        monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: None)
        cmd = f"{DAG_CLI} mark-completed --planning-dir .drive/p --agent-id impl-auth"
        assert not check_dag_node_confirmation(cmd).is_denied


# =============================================================================
# 篡改拦截
# =============================================================================

class TestTampering:
    @staticmethod
    def _guard(command: str):
        return check_state_transition("Bash", {"command": command}, None)

    def test_set_confirmed_nodes_is_denied(self):
        cmd = (
            "python3 state_cli.py update --planning-dir .drive/p "
            "--set confirmed_nodes=impl-auth"
        )
        assert self._guard(cmd).is_denied

    def test_sed_edit_of_confirmed_nodes_is_denied(self):
        cmd = "sed -i 's/confirmed_nodes/x/' .drive/p/executeState.json"
        assert self._guard(cmd).is_denied

    def test_confirm_node_entrypoint_is_allowed(self):
        cmd = "python3 confirm_node.py --planning-dir .drive/p --agent-id impl-auth"
        assert not self._guard(cmd).is_denied

    def test_reading_confirmed_nodes_is_allowed(self):
        cmd = "grep confirmed_nodes .drive/p/executeState.json"
        assert not self._guard(cmd).is_denied


# =============================================================================
# 完整链路
# =============================================================================

class TestFullChain:
    def test_bash_branch_wires_the_gate(self, planning):
        _write_state(planning, confirmed_nodes=[])
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        result = check_state_transition("Bash", {"command": cmd}, None)
        assert result.is_denied

    def test_bash_branch_allows_after_confirmation(self, planning):
        _write_state(planning, confirmed_nodes=["impl-auth"])
        cmd = f"{DAG_CLI} mark-completed --planning-dir {planning} --agent-id impl-auth"
        assert not check_state_transition("Bash", {"command": cmd}, None).is_denied
