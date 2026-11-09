"""state_cli 的 transition 命令必须被 hook 强制。

新命令只声明目标阶段（起点由 CLI 从 state 读），hook 需用当前 active_stage
补全起点后判定。若解析失配，强制器会静默放行 —— 那比报错更危险，故此覆盖。
"""
from __future__ import annotations

import json

import pytest

from hooks_protocol import check_stage_confirmation, check_state_transition, parse_transition_command

CLI = "python3 /plugin/skills/state-machine/scripts/state_cli.py"


def guard(command: str, active_stage: str | None):
    return check_state_transition("Bash", {"command": command}, active_stage)


# =============================================================================
# 解析
# =============================================================================

class TestParsing:
    def test_parses_target_only_form(self):
        parsed = parse_transition_command(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to analyze"
        )
        assert parsed == (None, "analyze", True)

    def test_parses_explicit_both_ends(self):
        parsed = parse_transition_command(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --from start --to analyze"
        )
        assert parsed == ("start", "analyze", True)

    def test_parses_positional_form(self):
        parsed = parse_transition_command(
            "DRIVE_TRUSTED=1 state_cli.py transition start analyze"
        )
        assert parsed == ("start", "analyze", True)

    def test_planning_dir_value_not_mistaken_for_stage(self):
        parsed = parse_transition_command(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir /tmp/x/.planning --to plan"
        )
        assert parsed == (None, "plan", True)

    def test_non_transition_command_is_ignored(self):
        assert parse_transition_command(f"{CLI} update --set paused=true") is None

    def test_command_without_target_is_ignored(self):
        assert parse_transition_command(f"{CLI} transition --planning-dir .planning") is None

    def test_malformed_quoting_is_ignored(self):
        assert parse_transition_command('transition --to "unclosed') is None


# =============================================================================
# 强制 —— 起点由 active_stage 补全
# =============================================================================

class TestEnforcementWithInferredOrigin:
    @pytest.mark.parametrize(
        "active,target",
        [("start", "analyze"), ("analyze", "plan"), ("plan", "execute"),
         ("execute", "evaluate"), ("execute", "plan"), ("evaluate", "plan")],
    )
    def test_legal_transitions_pass(self, active, target):
        result = guard(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to {target}",
            active,
        )
        assert not result.is_denied

    @pytest.mark.parametrize(
        "active,target",
        [("start", "execute"), ("start", "evaluate"), ("analyze", "execute"),
         ("plan", "evaluate"), ("plan", "analyze"), ("evaluate", "execute")],
    )
    def test_illegal_transitions_are_denied(self, active, target):
        result = guard(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to {target}",
            active,
        )
        assert result.is_denied
        assert target in result.message

    def test_unknown_active_stage_defers_to_cli(self):
        result = guard(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to execute",
            None,
        )
        assert not result.is_denied

    def test_unknown_target_is_denied(self):
        result = guard(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to deploy",
            "plan",
        )
        assert result.is_denied

    def test_explicit_from_overrides_active_stage(self):
        result = guard(
            f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --from start --to execute",
            "plan",
        )
        assert result.is_denied
        assert "start → execute" in result.message


# =============================================================================
# 非流转命令不受影响
# =============================================================================

class TestNonTransitionCommands:
    @pytest.mark.parametrize("cmd", [
        f"{CLI} update --planning-dir .planning --set paused=true",
        f"{CLI} read --planning-dir .planning",
        f"{CLI} log --planning-dir .planning --event x",
        "ls -la",
        "git commit -m 'transition to new arch'",
    ])
    def test_passes_through(self, cmd):
        assert not guard(cmd, "plan").is_denied


def test_deny_message_names_legal_targets():
    result = guard(
        f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to evaluate",
        "plan",
    )
    assert result.is_denied
    assert "execute" in result.message


# =============================================================================
# 防绕过 —— harness 层拦改写确认记录
# =============================================================================

class TestConfirmationTamperGuard:
    """CLI 层已禁写，本层覆盖换路径、直接编辑状态文件等绕法。"""

    def _guard(self, command: str):
        return check_state_transition("Bash", {"command": command}, "plan")

    @pytest.mark.parametrize("command", [
        f"{CLI} update --planning-dir .planning --set-json confirmed_stages=[\"plan\"]",
        f"{CLI} update --planning-dir .planning --set confirmed_stages=plan",
        "python3 -c \"import json; d['confirmed_stages']=['plan']\"",
        "jq '.confirmed_stages=[\"plan\"]' .planning/executeState.json > t",
        "sed -i 's/confirmed_stages\": \\[\\]/confirmed_stages\": [\"plan\"]/' x.json",
        "echo '{\"confirmed_stages\":[\"plan\"]}' >> .planning/executeState.json",
    ])
    def test_write_attempts_denied(self, command):
        result = self._guard(command)
        assert result.is_denied
        assert "confirm_stage.py" in result.message

    @pytest.mark.parametrize("command", [
        f"{CLI} read --planning-dir .planning",
        f"{CLI} require --planning-dir .planning",
        "cat .planning/executeState.json | grep confirmed_stages",
    ])
    def test_read_attempts_allowed(self, command):
        """查看已确认哪些阶段是正当需求。"""
        assert not self._guard(command).is_denied

    def test_official_entry_allowed(self):
        """confirm_stage.py 自身需用户授权，hook 不重复拦。"""
        command = "python3 /p/skills/state-machine/scripts/confirm_stage.py --stage plan"
        assert not self._guard(command).is_denied

    def test_unrelated_commands_unaffected(self):
        assert not self._guard("git commit -m 'confirmed the design'").is_denied


# =============================================================================
# trivial 复杂度 gate 自动跳过
# =============================================================================

class TestTrivialSkipGate:
    """complexity == trivial 时 analyze / plan / execute gate 自动放行，evaluate 仍强制 HITL。"""

    @staticmethod
    def _write_state(planning_dir, complexity, auto_mode: bool = False) -> None:
        state: dict = {"auto_mode": auto_mode, "confirmed_stages": []}
        if complexity is not None:
            state["complexity"] = complexity
        (planning_dir / "executeState.json").write_text(
            json.dumps(state), encoding="utf-8"
        )

    @pytest.mark.parametrize("stage", ["analyze", "plan", "execute"])
    def test_trivial_skips_hitl_stages(self, monkeypatch, tmp_path, stage):
        planning = tmp_path / ".planning"
        planning.mkdir()
        self._write_state(planning, "trivial")
        monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: planning)
        result = check_stage_confirmation(stage)
        assert not result.is_denied

    def test_trivial_does_not_skip_evaluate(self, monkeypatch, tmp_path):
        """evaluate gate 对任何复杂度都强制 HITL —— 质检门禁不绕过。"""
        planning = tmp_path / ".planning"
        planning.mkdir()
        self._write_state(planning, "trivial")
        monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: planning)
        result = check_stage_confirmation("evaluate")
        assert result.is_denied

    @pytest.mark.parametrize("complexity", ["standard", "complex", None])
    def test_non_trivial_requires_confirmation(self, monkeypatch, tmp_path, complexity):
        planning = tmp_path / ".planning"
        planning.mkdir()
        self._write_state(planning, complexity)
        monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: planning)
        result = check_stage_confirmation("analyze")
        assert result.is_denied

    def test_auto_mode_still_overrides_everything(self, monkeypatch, tmp_path):
        """auto_mode=True 时 evaluate gate 也放行（auto_mode 比 trivial 优先级高）。"""
        planning = tmp_path / ".planning"
        planning.mkdir()
        self._write_state(planning, None, auto_mode=True)
        monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: planning)
        result = check_stage_confirmation("evaluate")
        assert not result.is_denied

    def test_full_transition_chain_trivial(self, monkeypatch, tmp_path):
        """完整链路：transition 命令 → check_state_transition → trivial 自动放行。"""
        planning = tmp_path / ".planning"
        planning.mkdir()
        self._write_state(planning, "trivial")
        monkeypatch.setattr("hook_io.find_active_plan_dir", lambda start=None: planning)
        result = check_state_transition(
            "Bash",
            {"command": f"DRIVE_TRUSTED=1 {CLI} transition --planning-dir .planning --to plan"},
            "analyze",
        )
        assert not result.is_denied

