"""timeline_builder 测试 —— Phase 1。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from record_reader import LogEvent, Record, read_record
from timeline_builder import (
    TimelineEntry,
    _format_agent_invocations,
    _format_event,
    _format_findings,
    _format_ts,
    _git_log,
    _invocation_to_entries,
    _is_phase_mode,
    build_timeline,
)


class TestFormatTs:
    def test_iso_with_z_suffix(self):
        assert _format_ts("2026-08-18T09:30:00Z") == "09:30:00"

    def test_iso_with_offset(self):
        assert _format_ts("2026-08-18T09:30:05+00:00") == "09:30:05"

    def test_empty_returns_placeholder(self):
        assert _format_ts("") == "??:??:??"

    def test_invalid_returns_truncated(self):
        assert _format_ts("garbageT12:34:56") == "12:34:56"


class TestFormatEvent:
    def test_drive_startup(self):
        ev = LogEvent(
            ts="2026-08-18T09:30:00Z",
            event="drive_startup",
            details={"plan_name": "foo"},
        )
        entry = _format_event(ev)
        assert entry is not None
        assert "[startup]" in entry.text
        assert "foo" in entry.text

    def test_stage_advanced(self):
        ev = LogEvent(
            ts="2026-08-18T09:30:05Z",
            event="stage_advanced",
            details={"from": "start", "to": "analyze"},
        )
        entry = _format_event(ev)
        assert entry is not None
        assert "[stage]" in entry.text
        assert "start → analyze" in entry.text

    def test_agent_spawned(self):
        ev = LogEvent(
            ts="2026-08-18T09:35:00Z",
            event="agent_spawned",
            details={"subagent_type": "drive:executor", "description": "exec T01"},
        )
        entry = _format_event(ev)
        assert entry is not None
        assert "[agent]" in entry.text
        assert "spawn drive:executor" in entry.text
        assert "exec T01" in entry.text

    def test_unknown_event_returns_none(self):
        ev = LogEvent(ts="2026-08-18T09:30:00Z", event="some_random_event", details={})
        assert _format_event(ev) is None


class TestGitLog:
    def test_returns_commits_in_git_repo(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@drive"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "test"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        (tmp_path / "a.txt").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "first"],
            cwd=tmp_path, capture_output=True, check=True,
        )

        commits = _git_log(tmp_path, since="")
        assert len(commits) >= 1
        assert commits[0].subject == "first"

    def test_returns_empty_for_non_git_dir(self, tmp_path: Path):
        assert _git_log(tmp_path, since="") == []

    def test_returns_empty_for_nonexistent_dir(self, tmp_path: Path):
        assert _git_log(tmp_path / "nope", since="") == []


class TestBuildTimeline:
    def test_phase_completed_real_sample(self, phase_completed_plan: Path):
        record = read_record(phase_completed_plan)
        lines = build_timeline(record, worktree=None)
        assert len(lines) >= 5
        joined = "\n".join(lines)
        assert "[startup]" in joined
        assert "[stage]" in joined
        assert "[end]" in joined
        # 时间线按 ts 非递减
        timestamps = [l[:8] for l in lines]
        assert timestamps == sorted(timestamps)

    def test_dag_synthetic_sample(self, dag_plan_dir: Path):
        record = read_record(dag_plan_dir)
        lines = build_timeline(record, worktree=None)
        joined = "\n".join(lines)
        assert "[startup]" in joined
        assert "[stage]" in joined
        assert "[agent]" in joined
        assert "researcher" in joined
        assert "summarizer" in joined

    def test_commits_merged_when_worktree_given(self, tmp_path: Path, phase_completed_plan: Path):
        # 用 phase_completed_plan 但 worktree 是真实 git 仓库
        record = read_record(phase_completed_plan)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@drive"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "test"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        (tmp_path / "a.txt").write_text("hi")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "demo-commit"],
            cwd=tmp_path, capture_output=True, check=True,
        )
        # 禁用 since 过滤（since 可能让 commit 落不进窗口）
        record_no_since = Record(
            plan_dir=record.plan_dir,
            run_meta=None,  # None run_meta → since 为空
            intent=record.intent,
            manifest=record.manifest,
            task_record=record.task_record,
            waves=record.waves,
            topo_state=record.topo_state,
            execute_state=record.execute_state,
            log_events=record.log_events,
            evaluation_report=record.evaluation_report,
            artifacts=record.artifacts,
            missing_files=record.missing_files,
        )
        lines = build_timeline(record_no_since, worktree=tmp_path)
        joined = "\n".join(lines)
        assert "[commit]" in joined
        assert "demo-commit" in joined

    def test_no_commits_when_worktree_none(self, phase_completed_plan: Path):
        record = read_record(phase_completed_plan)
        lines = build_timeline(record, worktree=None)
        joined = "\n".join(lines)
        assert "[commit]" not in joined

    def test_empty_log_returns_empty(self, missing_record_dir: Path):
        record = read_record(missing_record_dir)
        lines = build_timeline(record, worktree=None)
        assert lines == []


# =============================================================================
# agent_invocations — phase mode reviewer 时间线
# =============================================================================


class TestFormatFindings:
    def test_full_dict(self):
        assert _format_findings({"critical": 1, "high": 2, "medium": 3, "low": 4}) == "c:1/h:2/m:3/l:4"

    def test_all_zeros(self):
        assert _format_findings({"critical": 0, "high": 0, "medium": 0, "low": 0}) == "c:0/h:0/m:0/l:0"

    def test_missing_keys_default_zero(self):
        assert _format_findings({}) == "c:0/h:0/m:0/l:0"

    def test_non_dict_returns_empty(self):
        assert _format_findings("high") == ""
        assert _format_findings(None) == ""
        assert _format_findings([0, 0, 0, 1]) == ""

    def test_non_int_value_returns_empty(self):
        assert _format_findings({"critical": "many"}) == ""


class TestInvocationToEntries:
    def _inv(self, **kw) -> dict:
        base = {"status": "completed"}
        base.update(kw)
        return base

    def test_running_only_emits_spawn(self):
        entries = _invocation_to_entries(
            "plan-T01", "code-reviewer",
            self._inv(status="running", started_at="2026-08-20T09:37:53+00:00", attempt=1),
        )
        assert len(entries) == 1
        assert "[agent]" in entries[0].text
        assert "spawn code-reviewer" in entries[0].text
        assert "plan-T01" in entries[0].text
        assert "attempt=1" in entries[0].text

    def test_completed_emits_spawn_and_complete(self):
        entries = _invocation_to_entries(
            "plan-T04", "code-reviewer",
            self._inv(
                status="completed",
                started_at="2026-08-20T10:00:00+00:00",
                finished_at="2026-08-20T10:01:52+00:00",
                duration_sec=112,
                verdict="warning",
                findings={"critical": 0, "high": 1, "medium": 2, "low": 2},
                attempt=1,
            ),
        )
        assert len(entries) == 2
        # 第一行 spawn
        assert "spawn" in entries[0].text
        # 第二行 complete，含 verdict + findings + duration + attempt
        complete = entries[1].text
        assert "complete" in complete
        assert "verdict=warning" in complete
        assert "findings=c:0/h:1/m:2/l:2" in complete
        assert "dur=112s" in complete
        assert "attempt=1" in complete

    def test_failed_emits_fail_line(self):
        entries = _invocation_to_entries(
            "plan-T02", "security-reviewer",
            self._inv(
                status="failed",
                started_at="2026-08-20T11:00:00+00:00",
                finished_at="2026-08-20T11:00:05+00:00",
                attempt=2,
            ),
        )
        assert len(entries) == 2
        assert "fail security-reviewer" in entries[1].text
        assert "attempt=2" in entries[1].text

    def test_skipped_emits_nothing_finished(self):
        """status=skipped 但有 finished_at → 不发 complete 行（不在 completed/failed 内）。"""
        entries = _invocation_to_entries(
            "plan-T03", "code-reviewer",
            self._inv(
                status="skipped",
                started_at="2026-08-20T12:00:00+00:00",
                finished_at="2026-08-20T12:00:00+00:00",
            ),
        )
        assert len(entries) == 1
        assert "spawn" in entries[0].text

    def test_no_started_at_emits_nothing(self):
        entries = _invocation_to_entries(
            "plan-T01", "code-reviewer",
            self._inv(status="running"),
        )
        assert entries == []


class TestFormatAgentInvocations:
    def _make_record(self, invocations, *, mode=None) -> Record:
        """构造一个只有 execute_state.agent_invocations 的最小 Record。"""
        state_dict = {
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": invocations,
        }
        if mode is not None:
            state_dict["mode"] = mode
        return Record(
            plan_dir=Path("/tmp/fake"),
            run_meta=None,
            intent=None,
            manifest=None,
            task_record=None,
            waves=None,
            topo_state=None,
            execute_state=_FakeExecuteState(state_dict),
            log_events=[],
            evaluation_report=None,
            artifacts={},
            missing_files=set(),
        )

    def test_empty_invocations(self):
        record = self._make_record({})
        assert _format_agent_invocations(record) == []

    def test_completed_produces_two_entries(self):
        record = self._make_record({
            "plan-T04": {
                "code-reviewer": {
                    "status": "completed",
                    "started_at": "2026-08-20T10:00:00+00:00",
                    "finished_at": "2026-08-20T10:01:52+00:00",
                    "verdict": "approve",
                    "findings": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                    "attempt": 1,
                },
            },
        })
        entries = _format_agent_invocations(record)
        assert len(entries) == 2
        assert "spawn code-reviewer" in entries[0].text
        assert "complete code-reviewer" in entries[1].text

    def test_multiple_reviewers(self):
        record = self._make_record({
            "plan-T01": {
                "code-reviewer": {
                    "status": "completed",
                    "started_at": "2026-08-20T09:00:00+00:00",
                    "finished_at": "2026-08-20T09:00:30+00:00",
                    "attempt": 1,
                },
                "security-reviewer": {
                    "status": "completed",
                    "started_at": "2026-08-20T09:00:00+00:00",
                    "finished_at": "2026-08-20T09:00:25+00:00",
                    "attempt": 1,
                },
            },
        })
        entries = _format_agent_invocations(record)
        # 2 reviewer × 2 行 (spawn + complete) = 4
        assert len(entries) == 4

    def test_skips_non_dict_reviewer(self):
        record = self._make_record({
            "plan-T01": {"code-reviewer": "bad"},
        })
        assert _format_agent_invocations(record) == []


class TestIsPhaseMode:
    def test_no_mode_field_is_phase(self):
        record = _make_record_minimal({"active_stage": "execute"})
        assert _is_phase_mode(record) is True

    def test_dag_mode(self):
        record = _make_record_minimal({"active_stage": "execute", "mode": "dag"})
        assert _is_phase_mode(record) is False

    def test_phase_mode_explicit(self):
        """mode='phase' 也视为 phase mode（mode != 'dag' 即 phase）。"""
        record = _make_record_minimal({"active_stage": "execute", "mode": "phase"})
        assert _is_phase_mode(record) is True

    def test_no_execute_state(self):
        record = Record(
            plan_dir=Path("/tmp/fake"), run_meta=None, intent=None,
            manifest=None, task_record=None, waves=None, topo_state=None,
            execute_state=None, log_events=[], evaluation_report=None,
            artifacts={}, missing_files=set(),
        )
        assert _is_phase_mode(record) is True


class TestBuildTimelineAgentInvocationsIntegration:
    """phase mode 下 build_timeline 整合：run-log 过滤 + agent_invocations 注入。"""

    def test_phase_mode_filters_reviewer_runlog_events(self):
        """phase mode：run-log 里 code-reviewer 的 spawn/complete 被过滤，从
        agent_invocations 注入对应行；run-log 里 executor 等非 reviewer 保留。"""
        state_dict = {
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "agent_invocations": {
                "plan-T04": {
                    "code-reviewer": {
                        "status": "completed",
                        "started_at": "2026-08-20T10:00:00+00:00",
                        "finished_at": "2026-08-20T10:01:00+00:00",
                        "verdict": "approve",
                        "attempt": 1,
                    },
                },
            },
        }
        log_events = [
            LogEvent(
                ts="2026-08-20T09:30:00+00:00",
                event="drive_startup",
                details={"plan_name": "x"},
            ),
            LogEvent(
                ts="2026-08-20T09:35:00+00:00",
                event="agent_spawned",
                details={"subagent_type": "drive:executor", "description": "exec T04"},
            ),
            LogEvent(
                ts="2026-08-20T09:50:00+00:00",
                event="agent_spawned",
                details={"subagent_type": "code-reviewer", "description": "review T04"},
            ),
            LogEvent(
                ts="2026-08-20T10:00:00+00:00",
                event="agent_completed",
                details={"subagent_type": "code-reviewer"},
            ),
            LogEvent(
                ts="2026-08-20T10:05:00+00:00",
                event="drive_completed",
                details={"verdict": "pass"},
            ),
        ]
        record = Record(
            plan_dir=Path("/tmp/fake"), run_meta=None, intent=None,
            manifest=None, task_record=None, waves=None, topo_state=None,
            execute_state=_FakeExecuteState(state_dict),
            log_events=log_events, evaluation_report=None,
            artifacts={}, missing_files=set(),
        )
        lines = build_timeline(record, worktree=None)
        joined = "\n".join(lines)

        # 非 reviewer 行保留
        assert "drive:executor" in joined
        # reviewer 行从 agent_invocations 注入（不重复，且是同一 task_id）
        assert "code-reviewer" in joined
        assert "plan-T04" in joined
        # agent_invocations 注入的 spawn 标记 attempt=1
        assert "attempt=1" in joined
        # agent_invocations 注入的 complete 标记 verdict
        assert "verdict=approve" in joined

    def test_dag_mode_does_not_use_agent_invocations(self):
        """DAG mode：agent_invocations 即使存在也不被读取；reviewer run-log 事件保留。"""
        state_dict = {
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            "mode": "dag",
            "agent_invocations": {
                "plan-T04": {
                    "code-reviewer": {
                        "status": "completed",
                        "started_at": "2026-08-20T10:00:00+00:00",
                        "finished_at": "2026-08-20T10:01:00+00:00",
                        "verdict": "approve",
                        "attempt": 1,
                    },
                },
            },
        }
        log_events = [
            LogEvent(
                ts="2026-08-20T09:50:00+00:00",
                event="agent_spawned",
                details={"subagent_type": "code-reviewer", "description": "review T04"},
            ),
            LogEvent(
                ts="2026-08-20T10:00:00+00:00",
                event="agent_completed",
                details={"subagent_type": "code-reviewer"},
            ),
        ]
        record = Record(
            plan_dir=Path("/tmp/fake"), run_meta=None, intent=None,
            manifest=None, task_record=None, waves=None, topo_state=None,
            execute_state=_FakeExecuteState(state_dict),
            log_events=log_events, evaluation_report=None,
            artifacts={}, missing_files=set(),
        )
        lines = build_timeline(record, worktree=None)
        joined = "\n".join(lines)

        # DAG 模式：从 run-log 读，不注入 agent_invocations
        # run-log 里 reviewer 的 spawn 行用 description = "review T04"
        assert "review T04" in joined
        # agent_invocations 注入的特征（"attempt=1" "verdict=approve"）不应出现
        assert "attempt=1" not in joined
        assert "verdict=approve" not in joined

    def test_phase_mode_without_invocations_filters_reviewers(self):
        """phase mode 但 agent_invocations 缺失：reviewer run-log 行被过滤（向下兼容）。"""
        state_dict = {
            "schema_version": "drive.runtime.state.v1",
            "revision": 1,
            "active_stage": "execute",
            # 无 agent_invocations
        }
        log_events = [
            LogEvent(
                ts="2026-08-20T09:35:00+00:00",
                event="agent_spawned",
                details={"subagent_type": "code-reviewer"},
            ),
            LogEvent(
                ts="2026-08-20T09:50:00+00:00",
                event="agent_spawned",
                details={"subagent_type": "drive:executor"},
            ),
        ]
        record = Record(
            plan_dir=Path("/tmp/fake"), run_meta=None, intent=None,
            manifest=None, task_record=None, waves=None, topo_state=None,
            execute_state=_FakeExecuteState(state_dict),
            log_events=log_events, evaluation_report=None,
            artifacts={}, missing_files=set(),
        )
        lines = build_timeline(record, worktree=None)
        joined = "\n".join(lines)

        # reviewer 被过滤 → 不应出现
        assert "code-reviewer" not in joined
        # executor 保留
        assert "drive:executor" in joined


# =============================================================================
# 测试辅助
# =============================================================================


class _FakeExecuteState:
    """最小 ExecuteState 占位：让 Record.execute_state.raw.get(...) 能用。"""
    def __init__(self, raw: dict):
        self.raw = raw


def _make_record_minimal(state_dict: dict) -> Record:
    return Record(
        plan_dir=Path("/tmp/fake"), run_meta=None, intent=None,
        manifest=None, task_record=None, waves=None, topo_state=None,
        execute_state=_FakeExecuteState(state_dict), log_events=[],
        evaluation_report=None, artifacts={}, missing_files=set(),
    )