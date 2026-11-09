"""Unit tests for hooks/hooks_protocol — planning write guard decisions."""
from __future__ import annotations

import pytest

from hooks_protocol import (
    HOOK_NAMES,
    SDK_MANAGED_SUBPATHS,
    HookResult,
    artifact_owner,
    check_planning_write,
    check_state_transition,
    invoke_hook,
    is_write_whitelisted,
    parse_transition_command,
    planning_subpath,
)


pytestmark = pytest.mark.unit


class TestHookResult:
    def test_allow_action(self):
        r = HookResult.allow()
        assert r.action == "allow"
        assert r.is_denied is False
        assert r.exit_code() == 0

    def test_deny_action_carries_message(self):
        r = HookResult.deny("nope")
        assert r.is_denied is True
        assert r.message == "nope"
        assert r.exit_code() == 2

    def test_is_frozen(self):
        r = HookResult.allow()
        with pytest.raises(Exception):
            r.action = "deny"  # type: ignore[misc]


class TestPlanningSubpath:
    def test_extracts_subpath(self):
        assert planning_subpath("/proj/.drive/plan-test/summary.md") == "summary.md"

    def test_nested_subpath(self):
        assert (
            planning_subpath("/proj/.drive/plan-test/inputs/proposal.md")
            == "inputs/proposal.md"
        )

    def test_non_planning_path_is_none(self):
        assert planning_subpath("/proj/src/main.py") is None

    def test_empty_path_is_none(self):
        assert planning_subpath("") is None

    def test_bare_planning_dir_is_none(self):
        assert planning_subpath("/proj/.drive/plan-test") is None


class TestWhitelist:
    @pytest.mark.parametrize(
        "subpath",
        [
            "continue-here.md",
            "summary.md",
            "plan-summary.md",
            "manifest.md",
            "manifest.yaml",
            # evaluate 产物（.md / .yaml 两种后缀都允许）
            "verification.md",
            "verification-report.md",
            "verification.yaml",
            "inputs/proposal.md",
            # 流程子目录 —— 任意子目录都放行，不逐个枚举
            "bootstrap/diagnosis.json",
            "bootstrap/completion-spec.yaml",
            "bootstrap/patches/proposal-prompt.yaml",
            # 扁平 dispatcher 路径
            "artifacts/plan-001-T01/SUMMARY.md",
            "artifacts/plan-001-T01/resumption.log",
            "artifacts/T-probe/analysis.json",
            "tasks/plan-001-T01.yaml",
            # 顶层 taskRecord（planner 写细粒度 task 列表进 `.drive/<plan_dir>/` 根, 不走 tasks/ 子目录）
            "taskRecord.yaml",
            # 流程自加子目录 + .yaml 后缀
            "continue-here.yaml",
            # 状态标记位
            ".pause",
        ],
    )
    def test_whitelisted_paths(self, subpath):
        assert is_write_whitelisted(subpath) is True

    @pytest.mark.parametrize(
        "subpath",
        [
            "manifest.json",
            # 任意新建子目录都放行 ≠ 任意名字在 `.drive/<plan_dir>/` 根下都放行
            "intake/spec.md",
            "weirdname.md",
        ],
    )
    def test_yaml_succeeds_but_json_fails(self, subpath):
        assert is_write_whitelisted(subpath) is False

    @pytest.mark.parametrize(
        "subpath",
        ["executeState.json", "run-log.jsonl", "random.txt"],
    )
    def test_non_whitelisted_paths(self, subpath):
        assert is_write_whitelisted(subpath) is False


class TestCheckPlanningWrite:
    def test_non_write_tool_allowed(self):
        r = check_planning_write("Read", {"file_path": "/p/.drive/plan-test/executeState.json"}, current_plan_dir="plan-test")
        assert r.is_denied is False

    def test_non_planning_path_allowed(self):
        r = check_planning_write("Write", {"file_path": "/p/src/main.py"}, current_plan_dir="plan-test")
        assert r.is_denied is False

    def test_whitelisted_write_allowed(self):
        r = check_planning_write("Write", {"file_path": "/p/.drive/plan-test/summary.md"}, current_plan_dir="plan-test")
        assert r.is_denied is False

    def test_state_file_write_denied_with_sdk_hint(self):
        r = check_planning_write(
            "Write",
            {"file_path": "/p/.drive/plan-test/executeState.json"},
            current_plan_dir="plan-test",
        )
        assert r.is_denied is True
        assert "SDK" in r.message

    @pytest.mark.parametrize("subpath", sorted(SDK_MANAGED_SUBPATHS))
    def test_all_sdk_managed_files_denied(self, subpath):
        r = check_planning_write("Write", {"file_path": f"/p/.drive/plan-test/{subpath}"}, current_plan_dir="plan-test")
        assert r.is_denied is True

    def test_arbitrary_planning_path_denied(self):
        r = check_planning_write("Write", {"file_path": "/p/.drive/plan-test/secret.txt"}, current_plan_dir="plan-test")
        assert r.is_denied is True
        assert "BLOCKED" in r.message

    def test_edit_tool_also_guarded(self):
        r = check_planning_write("Edit", {"file_path": "/p/.drive/plan-test/run-log.jsonl"}, current_plan_dir="plan-test")
        assert r.is_denied is True

    def test_multiedit_tool_also_guarded(self):
        r = check_planning_write("MultiEdit", {"file_path": "/p/.drive/plan-test/foo.txt"}, current_plan_dir="plan-test")
        assert r.is_denied is True

    def test_missing_file_path_allowed(self):
        # No file_path -> subpath None -> allow (not this guard's concern).
        r = check_planning_write("Write", {}, current_plan_dir="plan-test")
        assert r.is_denied is False

    def test_none_tool_input_allowed(self):
        r = check_planning_write("Write", None)  # type: ignore[arg-type]
        assert r.is_denied is False


class TestParseTransitionCommand:
    def test_positional_form(self):
        cmd = "DRIVE_TRUSTED=1 python3 state_cli.py transition start analyze"
        assert parse_transition_command(cmd) == ("start", "analyze", True)

    def test_flag_form(self):
        cmd = "DRIVE_TRUSTED=1 python3 state_cli.py transition --from start --to analyze"
        assert parse_transition_command(cmd) == ("start", "analyze", True)

    def test_mixed_flag_and_positional(self):
        cmd = "DRIVE_TRUSTED=1 state_cli.py transition --from execute plan"
        assert parse_transition_command(cmd) == ("execute", "plan", True)

    def test_non_transition_command_is_none(self):
        assert parse_transition_command("git status") is None

    def test_incomplete_transition_is_none(self):
        assert parse_transition_command("... transition start") is None

    def test_unparseable_command_is_none(self):
        assert parse_transition_command("transition 'unclosed") is None

    def test_ignores_unrelated_flags(self):
        cmd = "DRIVE_TRUSTED=1 state_cli.py transition --verbose start analyze"
        assert parse_transition_command(cmd) == ("start", "analyze", True)

    # === --planning-dir 解析 ===

    def test_planning_dir_consumed_as_value(self):
        cmd = (
            "DRIVE_TRUSTED=1 python3 skills/state-machine/scripts/state_cli.py transition "
            "--planning-dir /media/vdc/temp/signal-analyze-demo3/.drive/"
            "plan-20260820-0907-signal-analyzer --to evaluate"
        )
        assert parse_transition_command(cmd) == (None, "evaluate", True)

    def test_planning_dir_with_from(self):
        cmd = (
            "DRIVE_TRUSTED=1 python3 state_cli.py transition --planning-dir .drive/plan-x "
            "--from execute --to evaluate"
        )
        assert parse_transition_command(cmd) == ("execute", "evaluate", True)

    # === shell 控制 / 重定向 token 终止 ===

    def test_stops_at_pipe(self):
        cmd = (
            "DRIVE_TRUSTED=1 python3 state_cli.py transition --planning-dir .drive/plan-x "
            "--to evaluate 2>&1 | tail -5"
        )
        assert parse_transition_command(cmd) == (None, "evaluate", True)

    def test_stops_at_redirect(self):
        cmd = (
            "DRIVE_TRUSTED=1 python3 state_cli.py transition --planning-dir .drive/plan-x "
            "--to evaluate > /tmp/out.log 2>&1"
        )
        assert parse_transition_command(cmd) == (None, "evaluate", True)

    def test_stops_at_semicolon(self):
        cmd = (
            "DRIVE_TRUSTED=1 python3 state_cli.py transition --planning-dir .drive/plan-x "
            "--to evaluate ; echo done"
        )
        assert parse_transition_command(cmd) == (None, "evaluate", True)

    def test_stops_at_and(self):
        cmd = (
            "DRIVE_TRUSTED=1 python3 state_cli.py transition --planning-dir .drive/plan-x "
            "--to evaluate && echo ok"
        )
        assert parse_transition_command(cmd) == (None, "evaluate", True)

    # === --flag=value 紧凑形式 ===

    def test_compact_flag_form(self):
        # 即使没人这么用 state_cli，parser 应该不崩
        cmd = "DRIVE_TRUSTED=1 state_cli.py transition --from=execute --to=evaluate"
        assert parse_transition_command(cmd) == ("execute", "evaluate", True)


class TestArtifactOwner:
    @pytest.mark.parametrize(
        "subpath,owner",
        [
            ("plan-summary.md", "plan"),
            ("evaluation/verdict.md", "evaluate"),
            ("evaluation/l1-checks.md", "evaluate"),
        ],
    )
    def test_owned_artifacts(self, subpath, owner):
        assert artifact_owner(subpath) == owner

    def test_unowned_artifact_is_none(self):
        assert artifact_owner("summary.md") is None


class TestCheckStateTransition:
    def test_legal_transition_allowed(self):
        r = check_state_transition("Bash", {"command": "... transition start analyze"}, plan_dir="plan-test")
        assert r.is_denied is False

    def test_illegal_transition_denied(self):
        r = check_state_transition(
            "Bash",
            {"command": "DRIVE_TRUSTED=1 python3 state_cli.py transition --from=start --to=execute"},
            active_stage="analyze",
            plan_dir="plan-test",
        )
        assert r.is_denied is True
        assert "BLOCKED" in r.message

    def test_non_transition_bash_allowed(self):
        r = check_state_transition("Bash", {"command": "ls -la"}, plan_dir="plan-test")
        assert r.is_denied is False

    def test_cross_stage_artifact_write_denied(self):
        # execute stage writing a plan-owned artifact -> deny.
        r = check_state_transition(
            "Write",
            {"file_path": "/p/.drive/plan-test/plan-summary.md"},
            active_stage="execute",
            plan_dir="plan-test",
        )
        assert r.is_denied is True
        assert "污染" in r.message

    def test_same_stage_artifact_write_allowed(self):
        r = check_state_transition(
            "Write",
            {"file_path": "/p/.drive/plan-test/plan-summary.md"},
            active_stage="plan",
            plan_dir="plan-test",
        )
        assert r.is_denied is False

    def test_write_without_active_stage_allowed(self):
        r = check_state_transition(
            "Write", {"file_path": "/p/.drive/plan-test/plan-summary.md"}
        , plan_dir="plan-test")
        assert r.is_denied is False

    def test_write_non_planning_allowed(self):
        r = check_state_transition(
            "Write", {"file_path": "/p/src/main.py"}, active_stage="execute"
        , plan_dir="plan-test")
        assert r.is_denied is False

    def test_unowned_artifact_write_allowed(self):
        r = check_state_transition(
            "Write",
            {"file_path": "/p/.drive/plan-test/summary.md"},
            active_stage="execute",
            plan_dir="plan-test",
        )
        assert r.is_denied is False

    def test_other_tool_allowed(self):
        r = check_state_transition("Read", {"file_path": "/p/.drive/plan-test/executeState.json"}, plan_dir="plan-test")
        assert r.is_denied is False


class TestInvokeHook:
    def test_registry_names(self):
        assert HOOK_NAMES == frozenset(
            {"planning_write_guard", "state_transition_guard"}
        )

    def test_invoke_planning_write_guard(self):
        r = invoke_hook(
            "planning_write_guard",
            "Write",
            {"file_path": "/p/.drive/plan-test/executeState.json"},
            plan_dir="plan-test",
        )
        assert r.is_denied is True

    def test_invoke_state_transition_guard(self):
        r = invoke_hook(
            "state_transition_guard",
            "Bash",
            {"command": "DRIVE_TRUSTED=1 state_cli.py transition --from=start --to=execute"},
            active_stage="analyze",
            plan_dir="plan-test",
        )
        assert r.is_denied is True

    def test_unknown_hook_fails_closed(self):
        r = invoke_hook("no_such_hook", "Bash", {})
        assert r.is_denied is True
        assert "unknown hook" in r.message

    def test_invoke_passes_active_stage(self):
        r = invoke_hook(
            "state_transition_guard",
            "Write",
            {"file_path": "/p/.drive/plan-test/plan-summary.md"},
            active_stage="execute",
            plan_dir="plan-test",
        )
        assert r.is_denied is True


class TestTrustGate:
    def test_heredoc_body_does_not_trigger(self):
        cmd = (
            "cat > /tmp/x.html << 'EOF'\n"
            "<span>state_cli.py transition --to evaluate</span>\n"
            "EOF"
        )
        assert parse_transition_command(cmd) is None

    def test_bash_c_nesting_does_not_trigger(self):
        cmd = "bash -c 'state_cli.py transition --to evaluate'"
        assert parse_transition_command(cmd) is None

    def test_python_c_nesting_does_not_trigger(self):
        cmd = "python3 -c \\\"import os; os.system('state_cli.py transition --to evaluate')\\\""
        assert parse_transition_command(cmd) is None

    def test_untrusted_state_cli_transition_is_denied(self):
        from hooks_protocol import check_state_transition
        cmd = "python3 state_cli.py transition --planning-dir .drive/plan-x --to evaluate"
        result = check_state_transition(
            tool_name="Bash",
            tool_input={"command": cmd},
            active_stage="execute",
            plan_dir="plan-x",
        )
        assert result.is_denied
        assert "DRIVE_TRUSTED" in (result.message or "")

    def test_trusted_state_cli_transition_passes(self):
        from hooks_protocol import check_state_transition
        cmd = (
            "DRIVE_TRUSTED=1 python3 state_cli.py transition "
            "--planning-dir .drive/plan-x --to evaluate"
        )
        result = check_state_transition(
            tool_name="Bash",
            tool_input={"command": cmd},
            active_stage="execute",
            plan_dir="plan-x",
        )
        assert not result.is_denied, result.message
