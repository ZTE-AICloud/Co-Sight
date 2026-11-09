"""PROP-20260817-001 P0-1 · 跨 plan 写拦截测试。

- 在当前 plan-dir 内的白名单 subpath → allow
- 在当前 plan-dir 内的 SDK 托管文件 → deny
- 跨 plan 写（subpath 在别的 plan- 目录）→ deny
- 当前 plan 内非白名单 → deny
- 非 plan 路径 → allow
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hooks_protocol import (
    check_planning_write,
    check_state_transition,
    HookResult,
)


def _file_input(file_path: str) -> dict:
    """PROP-20260817-001 P0-1：返回 tool_input 字典（不含 tool_name 包装层）。"""
    return {"file_path": file_path}


class TestPlanningWriteAllow:
    def test_non_plan_path_allowed(self, tmp_path):
        """非 .drive/plan-*/ 路径放行。"""
        result = check_planning_write(
            "Write",
            _file_input(str(tmp_path / "src/foo.py")),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert not result.is_denied

    def test_within_plan_whitelisted_artifact(self, tmp_path):
        """在当前 plan 内写 artifacts/.../SUMMARY.md 放行。"""
        result = check_planning_write(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/artifacts/plan-...-T01/SUMMARY.md")
            ),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert not result.is_denied

    def test_within_plan_manifest_md(self, tmp_path):
        result = check_planning_write(
            "Write",
            _file_input(str(tmp_path / ".drive/plan-20260817-1530-foo/manifest.md")),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert not result.is_denied

    def test_non_write_tool_passes(self, tmp_path):
        result = check_planning_write(
            "Read",
            {"tool_name": "Read", "tool_input": {"file_path": str(tmp_path / ".drive/plan-x/foo.txt")}},
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert not result.is_denied


class TestPlanningWriteDeny:
    def test_within_plan_sdk_managed_file(self, tmp_path):
        """当前 plan 内的 executeState.json 拒绝（SDK 托管）。"""
        result = check_planning_write(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/executeState.json")
            ),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "SDK" in result.message

    def test_within_plan_run_log(self, tmp_path):
        result = check_planning_write(
            "Write",
            _file_input(str(tmp_path / ".drive/plan-20260817-1530-foo/run-log.jsonl")),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "SDK" in result.message

    def test_within_plan_non_whitelisted_path(self, tmp_path):
        """当前 plan 内的非白名单路径拒绝。"""
        result = check_planning_write(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/random.txt")
            ),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "BLOCKED" in result.message

    def test_cross_plan_write_blocked(self, tmp_path):
        """PROP-20260817-001 P0-1 核心：写别的 plan 子目录拒绝。"""
        result = check_planning_write(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260818-1045-other/manifest.md")
            ),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "跨 plan" in result.message
        assert "plan-20260818-1045-other" in result.message

    def test_cross_plan_write_to_artifact_blocked(self, tmp_path):
        """跨 plan 写 artifacts/.../SUMMARY.md 也拒绝（不受白名单保护）。"""
        result = check_planning_write(
            "Write",
            _file_input(
                str(tmp_path
                    / ".drive/plan-20260818-1045-other/artifacts/plan-...-T01/SUMMARY.md")
            ),
            current_plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "跨 plan" in result.message

    def test_no_plan_dir_arg_does_not_block(self, tmp_path):
        """不传 plan_dir → 保守放行（不挡非 plan 路径）。"""
        result = check_planning_write(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/manifest.md")
            ),
            current_plan_dir=None,
        )
        # 没有 plan_dir 时 planning_subpath 返 None → 放行
        assert not result.is_denied


class TestStateTransitionWritePlanGuard:
    def test_cross_plan_write_blocked(self, tmp_path):
        """state_transition_guard 中 Write/Edit 路径同步拦截跨 plan 写。"""
        result = check_state_transition(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260818-1045-other/manifest.md")
            ),
            active_stage="execute",
            plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "跨 plan" in result.message

    def test_within_plan_non_owner_stage_blocked(self, tmp_path):
        """当前 plan 内跨阶段写仍然拦截（execute 阶段写 plan 产物）。"""
        result = check_state_transition(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/plan-summary.md")
            ),
            active_stage="execute",
            plan_dir="plan-20260817-1530-foo",
        )
        assert result.is_denied
        assert "污染" in result.message

    def test_within_plan_owner_stage_allowed(self, tmp_path):
        """当前 plan 内同阶段写放行。"""
        result = check_state_transition(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/plan-summary.md")
            ),
            active_stage="plan",
            plan_dir="plan-20260817-1530-foo",
        )
        assert not result.is_denied

    def test_no_plan_dir_arg_skips_cross_plan_check(self, tmp_path):
        """不传 plan_dir → 跨 plan 拦截不触发；但跨阶段拦截（artifact_owner）仍生效。

        plan_dir 只影响跨 plan 检查，不影响跨阶段检查。
        """
        result = check_state_transition(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260817-1530-foo/plan-summary.md")
            ),
            active_stage="execute",
            plan_dir=None,
        )
        # 跨阶段检查仍生效：execute 阶段写 plan-summary.md 拒绝
        assert result.is_denied
        assert "污染" in result.message

    def test_no_plan_dir_arg_other_plan_dir(self, tmp_path):
        """不传 plan_dir：写别的 plan 目录不被拦截（plan_dir 缺失时不强行跨 plan 判）。"""
        result = check_state_transition(
            "Write",
            _file_input(
                str(tmp_path / ".drive/plan-20260818-1045-other/manifest.md")
            ),
            active_stage="execute",
            plan_dir=None,
        )
        # 跨 plan 检查需要 plan_dir 才能 detect；不传则放行
        assert not result.is_denied