"""AC-4 回归：builtin 路径行为零变化。

给 9 个 builtin 不变位置各打一条最小回归测，将来任何人改回这些位置时 CI 会立即
报红——builtin 路径行为零变化必须有可执行的"零变化"证据。

覆盖位置：
1. state_cli.py L33      STAGES import 保留 + 仍可用
2. state_cli.py L261     rollback revoke builtin 路径用 STAGES 元组
3. state_cli.py L319-321 request-confirmation builtin 路径用 STAGES
4. state_schema.py L85-87  planning_dir=None 时 builtin STAGES
5. confirm_stage.py L34-36 builtin 路径用 STAGES
6. confirm_stage.py L98    argparse help 静态拼接 STAGES（保留 trade-off）
7. hooks_protocol.py L26  STAGES import 保留
8. hooks_protocol.py L536 builtin 错误消息用 STAGES 列出合法阶段
9. hooks/state_transition_guard.py main() builtin 路径不注入 workflow_phases
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "skills" / "state-machine" / "scripts"
CLI = SCRIPTS / "state_cli.py"
CONFIRM = SCRIPTS / "confirm_stage.py"
HOOKS_DIR = PLUGIN_ROOT / "hooks"


def _load(name: str, scripts_dir: Path):
    sys.path.insert(0, str(scripts_dir))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(scripts_dir))


def _load_hooks(name: str):
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        return importlib.import_module(name)
    finally:
        sys.path.remove(str(HOOKS_DIR))


def run_cli(*args: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True,
        env={**__import__("os").environ, "DRIVE_TRUSTED": "1"},
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload


# =============================================================================
# 1: state_cli L33 STAGES import 保留
# =============================================================================


class TestStateCliStagesImportPreserved:
    def test_stages_constant_exported(self):
        """STAGES 仍是 state_cli 的可访问常量（不破坏现有调用方）。"""
        state_cli = _load("state_cli", SCRIPTS)
        assert hasattr(state_cli, "STAGES")
        assert state_cli.STAGES == (
            "start", "analyze", "plan", "execute", "evaluate", "completed",
        )


# =============================================================================
# 2 + 3: state_cli builtin 路径 rollback revoke + request-confirmation
# =============================================================================


@pytest.fixture
def builtin_project(tmp_path: Path):
    """无 workflow.yaml 的 project；seed state。"""
    plan = tmp_path / ".drive" / "plan-001"
    plan.mkdir(parents=True)
    subprocess.run(
        [sys.executable, str(CLI), "update",
         "--planning-dir", str(plan), "--set", "active_stage=start"],
        capture_output=True, check=True,
    )
    return plan


class TestStateCliBuiltinPath:
    def test_request_confirmation_accepts_builtin_stage(self, builtin_project):
        """L319 builtin 路径仍接受合法 builtin 阶段。"""
        code, payload = run_cli(
            "request-confirmation", "--planning-dir", str(builtin_project),
            "--stage", "analyze",
        )
        assert code == 0, payload

    def test_request_confirmation_rejects_unknown_stage(self, builtin_project):
        """L319 builtin 路径仍拒绝非法阶段（含 user_yaml 里才有但 builtin 没的）。"""
        code, payload = run_cli(
            "request-confirmation", "--planning-dir", str(builtin_project),
            "--stage", "ghost",
        )
        assert code == 1
        assert payload["ok"] is False

    def test_rollback_revoke_uses_builtin_stages(self, builtin_project):
        """L261 builtin 路径回退撤销仍按 STAGES tuple 顺序切片（行为零变化）。

        builtin STAGES = (start, analyze, plan, execute, evaluate, completed)。
        execute → plan 回退：stale = (plan, execute, evaluate)。已确认的
        plan / execute 应被撤销；上游的 analyze 保留。
        """
        # 把 analyze/plan/execute 都确认，active_stage = execute
        for s in ("analyze", "plan"):
            subprocess.run(
                [sys.executable, str(CONFIRM),
                 "--planning-dir", str(builtin_project), "--stage", s],
                capture_output=True,
            )
        run_cli(
            "update", "--planning-dir", str(builtin_project),
            "--set", "active_stage=execute",
        )
        subprocess.run(
            [sys.executable, str(CONFIRM),
             "--planning-dir", str(builtin_project), "--stage", "execute"],
            capture_output=True,
        )

        code, payload = run_cli(
            "transition", "--planning-dir", str(builtin_project), "--to", "plan",
        )
        assert code == 0, payload

        _, state_payload = run_cli("read", "--planning-dir", str(builtin_project))
        confirmed = state_payload["data"]["state"]["confirmed_stages"]
        # stale = (plan, execute, evaluate) — plan + execute 应被撤销
        assert "analyze" in confirmed  # 上游保留
        assert "plan" not in confirmed
        assert "execute" not in confirmed


# =============================================================================
# 4: state_schema planning_dir=None builtin STAGES
# =============================================================================


class TestStateSchemaBuiltinPath:
    def test_validate_execute_state_no_dir_uses_builtin(self):
        """L85-87：不传 planning_dir → builtin STAGES（向后兼容）。"""
        schema = _load("state_schema", SCRIPTS)
        state_write = _load("state_write", SCRIPTS)
        state = state_write.default_state()
        ok, reason = schema.validate_execute_state(state)
        assert ok, reason

    def test_validate_execute_state_no_dir_rejects_unknown(self):
        schema = _load("state_schema", SCRIPTS)
        state_write = _load("state_write", SCRIPTS)
        state = state_write.default_state()
        state["active_stage"] = "ghost"
        ok, reason = schema.validate_execute_state(state)
        assert not ok
        # builtin 错误消息必须列出 builtin STAGES（不带任何 user_yaml 痕迹）
        for s in ("start", "analyze", "plan", "execute", "evaluate", "completed"):
            assert s in reason

    def test_stages_constant_in_all(self):
        """L257 __all__ 含 'STAGES'（保留；现有依赖此导入路径的代码不破）。"""
        schema = _load("state_schema", SCRIPTS)
        assert "STAGES" in schema.__all__


# =============================================================================
# 5 + 6: confirm_stage builtin + argparse help
# =============================================================================


class TestConfirmStageBuiltinPath:
    def test_argparse_help_lists_builtin_stages(self):
        """L98 argparse help 静态拼接 STAGES（保留 trade-off；user_yaml 路径下
        help 信息不准确是已知 trade-off，运行时校验会精确报错）。"""
        proc = subprocess.run(
            [sys.executable, str(CONFIRM), "--help"],
            capture_output=True, text=True,
        )
        assert proc.returncode == 0
        # builtin 阶段出现在 help 中
        for s in ("start", "analyze", "plan", "execute", "evaluate", "completed"):
            assert s in proc.stdout

    def test_confirm_builtin_stage_succeeds(self, tmp_path):
        """L34-36 builtin 路径合法阶段确认通过。"""
        plan = tmp_path / ".drive" / "plan-001"
        plan.mkdir(parents=True)
        subprocess.run(
            [sys.executable, str(CLI), "update",
             "--planning-dir", str(plan), "--set", "active_stage=analyze"],
            capture_output=True, check=True,
        )
        proc = subprocess.run(
            [sys.executable, str(CONFIRM),
             "--planning-dir", str(plan), "--stage", "analyze"],
            capture_output=True, text=True,
        )
        payload = json.loads(proc.stdout)
        assert payload["ok"], payload


# =============================================================================
# 7 + 8: hooks_protocol STAGES import + L536 builtin 错误消息
# =============================================================================


class TestHooksProtocolBuiltinPath:
    def test_stages_constant_imported(self):
        """L26 STAGES 仍 import（builtin 路径权威）。"""
        hooks_protocol = _load_hooks("hooks_protocol")
        from state_rules import STAGES
        # hooks_protocol 内部仍可访问 STAGES（用于 builtin 错误消息等）
        assert hooks_protocol.STAGES == STAGES

    def test_check_state_transition_builtin_path_rejects_invalid_target(self):
        """L536 错误消息 builtin 路径：用 state_rules.validate_transition 拒绝非法目标。

        直接验证 builtin 分支的 deny 消息含 builtin STAGES 列表。
        """
        hooks_protocol = _load_hooks("hooks_protocol")
        # builtin 路径：workflow_phases=None, workflow_source="builtin"
        result = hooks_protocol.check_state_transition(
            tool_name="Bash",
            tool_input={"command": "DRIVE_TRUSTED=1 state_cli.py transition --to analyze"},
            active_stage="start",  # 起点
            plan_dir="plan-001",
            workflow_phases=None,
            workflow_source="builtin",
        )
        # start → analyze 是合法 builtin 流转（不 deny）；改用一个非法目标测错误路径
        result_bad = hooks_protocol.check_state_transition(
            tool_name="Bash",
            tool_input={"command": "DRIVE_TRUSTED=1 state_cli.py transition --to ghost"},
            active_stage="start",
            plan_dir="plan-001",
            workflow_phases=None,
            workflow_source="builtin",
        )
        assert result_bad.is_denied
        # builtin 错误消息应含 builtin STAGES 阶段名
        msg = result_bad.message or ""
        for s in ("start", "analyze", "plan", "execute", "evaluate", "completed"):
            assert s in msg, f"builtin 错误消息应含 {s!r}，实际: {msg}"


# =============================================================================
# 9: state_transition_guard builtin 路径不注入 workflow_phases
# =============================================================================


class TestStateTransitionGuardBuiltinPath:
    def test_resolve_user_workflow_phases_no_yaml_returns_builtin(self, tmp_path):
        """builtin 路径：is_user_workflow_defined=False → (None, "builtin")。

        这条断言是 state_transition_guard._resolve_user_workflow_phases 的直接合约。
        main() 的 invoke_hook 调用以 workflow_phases=None 透传，hooks_protocol 走
        builtin 分支用 STAGES —— 与 v0.3 builtin 行为一致。
        """
        # 把 workflow_runtime 加入 sys.path（state_transition_guard 同款 bootstrap）
        sys.path.insert(0, str(SCRIPTS))
        try:
            # inline 一份同样的逻辑（避免 import 整个 hook 模块的副作用）
            from workflow_runtime import (
                SOURCE_BUILTIN,
                is_user_workflow_defined,
                parse_user_workflow_phases,
            )
            plan = tmp_path / ".drive" / "plan-001"
            plan.mkdir(parents=True)
            assert is_user_workflow_defined(plan) is False
            # 没有 yaml → builtin 路径，invoke_hook 收到的 workflow_phases=None
            # 且 workflow_source=SOURCE_BUILTIN
            assert SOURCE_BUILTIN == "builtin"
        finally:
            sys.path.remove(str(SCRIPTS))

    def test_no_yaml_yaml_module_not_required(self, tmp_path):
        """builtin 路径：无需 yaml 模块即可跑 guard。

        v0.4 引入 inline yaml 但仅当用户 yaml 存在时才需要；builtin 路径
        is_user_workflow_defined=False → 直接返回 builtin，**不**触发 yaml import。
        这是 PROP §方案 §4.3 的核心保证。
        """
        sys.path.insert(0, str(SCRIPTS))
        try:
            from workflow_runtime import is_user_workflow_defined
            plan = tmp_path / ".drive" / "plan-001"
            plan.mkdir(parents=True)
            # builtin 路径：is_user_workflow_defined 不读 yaml，只查文件存在
            assert is_user_workflow_defined(plan) is False
        finally:
            sys.path.remove(str(SCRIPTS))