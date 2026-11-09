"""record_reader 测试 —— Phase 0 RED→GREEN 验证。"""
from __future__ import annotations

from pathlib import Path

import pytest

from record_reader import (
    EXECUTE_STATE,
    ExecuteState,
    LogEvent,
    Record,
    RunMeta,
    TaskRecord,
    Waves,
    parse_execute_state,
    parse_log_events,
    parse_run_meta,
    parse_task_record,
    parse_waves,
    read_record,
)


class TestParseRunMeta:
    def test_parses_all_fields(self):
        data = {
            "plan_name": "foo",
            "plan_dir": "plan-20260818-foo",
            "git_head": "abc1234",
            "git_branch": "main",
            "workflow_hash": "sha256:deadbeef",
            "started_at": "2026-08-18T09:30:00Z",
            "worktree": "/abs/path",
        }
        meta = parse_run_meta(data)
        assert meta.plan_name == "foo"
        assert meta.git_branch == "main"
        assert meta.workflow_hash == "sha256:deadbeef"

    def test_returns_empty_on_none(self):
        meta = parse_run_meta(None)
        assert meta == RunMeta()


class TestParseExecuteState:
    def test_parses_revision_and_active_stage(self):
        data = {
            "schema_version": "drive.runtime.state.v1",
            "revision": 12,
            "active_stage": "completed",
            "status": "completed",
            "verdict": "pass",
            "confirmed_stages": ["start", "analyze", "plan", "execute", "evaluate"],
            "mode": "phase",
            "task_results": {"t1": {"status": "ok"}},
        }
        state = parse_execute_state(data)
        assert state is not None
        assert state.revision == 12
        assert state.active_stage == "completed"
        assert state.verdict == "pass"
        assert state.mode == "phase"
        assert state.task_results == {"t1": {"status": "ok"}}

    def test_returns_none_on_none(self):
        assert parse_execute_state(None) is None

    def test_default_mode_is_phase(self):
        state = parse_execute_state({"active_stage": "execute"})
        assert state is not None
        assert state.mode == "phase"


class TestParseTaskRecord:
    def test_parses_tasks_list(self):
        data = {
            "plan_id": "plan-1",
            "tasks": [
                {"task_id": "t1", "title": "foo"},
                {"task_id": "t2", "title": "bar"},
            ],
        }
        record = parse_task_record(data)
        assert record is not None
        assert record.plan_id == "plan-1"
        assert len(record.tasks) == 2

    def test_returns_none_on_none(self):
        assert parse_task_record(None) is None


class TestParseWaves:
    def test_parses_waves_list(self):
        data = {
            "plan_id": "plan-1",
            "waves": [{"wave": 1, "tasks": ["t1"]}],
        }
        waves = parse_waves(data)
        assert waves is not None
        assert waves.plan_id == "plan-1"
        assert len(waves.waves) == 1

    def test_returns_none_on_none(self):
        assert parse_waves(None) is None


class TestParseLogEvents:
    def test_parses_valid_events(self):
        text = (
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "drive_startup"}\n'
            '{"ts": "2026-08-18T09:30:05+00:00", "event": "stage_advanced", "from": "start", "to": "analyze"}\n'
        )
        events = parse_log_events(text)
        assert len(events) == 2
        assert events[0].event == "drive_startup"
        assert events[1].details["to"] == "analyze"

    def test_skips_invalid_json_lines(self):
        text = (
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "drive_startup"}\n'
            'not valid json\n'
            '{"ts": "2026-08-18T09:30:05+00:00", "event": "stage_advanced"}\n'
        )
        events = parse_log_events(text)
        assert len(events) == 2

    def test_skips_lines_without_event_field(self):
        text = '{"ts": "2026-08-18T09:30:00+00:00"}\n'
        events = parse_log_events(text)
        assert events == ()


class TestReadRecord:
    def test_reads_phase_completed_real_sample(self, phase_completed_plan: Path):
        record = read_record(phase_completed_plan)
        assert isinstance(record, Record)
        assert record.run_meta is not None
        assert record.run_meta.plan_name == "fix-import-deadlock"
        assert record.execute_state is not None
        assert record.execute_state.active_stage == "completed"
        assert record.execute_state.verdict == "pass"
        assert len(record.log_events) >= 5
        assert "plan-20260818-0930-T01" in record.artifacts

    def test_reads_phase_executing_real_sample(self, phase_executing_plan: Path):
        record = read_record(phase_executing_plan)
        assert record.execute_state is not None
        assert record.execute_state.active_stage in ("execute", "executing")

    def test_reads_dag_synthetic_sample(self, dag_plan_dir: Path):
        record = read_record(dag_plan_dir)
        assert record.execute_state is not None
        assert record.execute_state.mode == "dag"
        assert len(record.log_events) >= 5

    def test_missing_files_listed(self, missing_record_dir: Path):
        record = read_record(missing_record_dir)
        assert "executeState.json" in record.missing_files
        assert "run-log.jsonl" in record.missing_files
        assert record.execute_state is None
        assert record.log_events == ()

    def test_residual_plan_has_no_artifacts(self, residual_plan: Path):
        record = read_record(residual_plan)
        assert record.artifacts == {}

    def test_raises_on_nonexistent_dir(self, tmp_path: Path):
        with pytest.raises(ValueError, match="plan_dir"):
            read_record(tmp_path / "does-not-exist")