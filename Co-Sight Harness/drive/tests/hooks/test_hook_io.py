"""hook 读状态的方式 —— 必须能看见 state-machine skill 实际写入的地方。

阶段信息唯一载体：`executeState.json`（state_cli 实际写的地方）。
"""
from __future__ import annotations

import json

import pytest

import hook_io


def write_execute_state(planning_dir, stage: str, revision: int = 1) -> None:
    (planning_dir / "executeState.json").write_text(
        json.dumps({"active_stage": stage, "revision": revision}), encoding="utf-8"
    )


@pytest.fixture
def planning(tmp_path):
    d = tmp_path / ".drive" / "plan-test"
    d.mkdir(parents=True)
    return d


class TestReadActiveStage:
    def test_reads_from_execute_state_json(self, planning):
        """state_cli 写的是 executeState.json —— 这是唯一来源。"""
        write_execute_state(planning, "plan")
        assert hook_io.read_active_stage(planning) == "plan"

    def test_returns_none_when_nothing_readable(self, planning):
        assert hook_io.read_active_stage(planning) is None

    def test_returns_none_for_none_input(self):
        assert hook_io.read_active_stage(None) is None

    def test_corrupt_execute_state_returns_none(self, planning):
        (planning / "executeState.json").write_text("{ not json", encoding="utf-8")
        assert hook_io.read_active_stage(planning) is None

    def test_empty_stage_value_treated_as_missing(self, planning):
        write_execute_state(planning, "")
        assert hook_io.read_active_stage(planning) is None


class TestReadStateRevision:
    def test_reads_revision(self, planning):
        write_execute_state(planning, "plan", revision=7)
        assert hook_io.read_state_revision(planning) == 7

    def test_missing_file_returns_none(self, planning):
        assert hook_io.read_state_revision(planning) is None

    def test_corrupt_json_returns_none(self, planning):
        (planning / "executeState.json").write_text("{{{", encoding="utf-8")
        assert hook_io.read_state_revision(planning) is None

    def test_non_int_revision_returns_none(self, planning):
        (planning / "executeState.json").write_text(
            json.dumps({"revision": "seven"}), encoding="utf-8"
        )
        assert hook_io.read_state_revision(planning) is None


class TestRunLog:
    def test_reads_events_in_order(self, planning):
        hook_io.append_run_log(planning, "a", n=1)
        hook_io.append_run_log(planning, "b", n=2)
        events = hook_io.read_run_log(planning)
        assert [e["event"] for e in events] == ["a", "b"]

    def test_every_event_has_timestamp(self, planning):
        hook_io.append_run_log(planning, "a")
        assert hook_io.read_run_log(planning)[0]["ts"]

    def test_reserved_fields_cannot_be_overridden(self, planning):
        """details 里的 ts/event 不能顶掉真实的时间戳与事件名。"""
        hook_io.append_run_log(planning, "a", **{"ts": "fake", "note": "keep"})
        entry = hook_io.read_run_log(planning)[0]
        assert entry["event"] == "a"
        assert entry["ts"] != "fake"
        assert entry["note"] == "keep"

    def test_corrupt_lines_are_skipped(self, planning):
        (planning / "run-log.jsonl").write_text(
            '{"event":"ok","ts":"t"}\nnot json\n{"event":"also_ok","ts":"t"}\n',
            encoding="utf-8",
        )
        assert [e["event"] for e in hook_io.read_run_log(planning)] == ["ok", "also_ok"]

    def test_missing_file_returns_empty(self, planning):
        assert hook_io.read_run_log(planning) == []

    def test_append_rejects_missing_dir(self, tmp_path):
        assert hook_io.append_run_log(tmp_path / "nope", "e") is False

    def test_append_rejects_empty_event(self, planning):
        assert hook_io.append_run_log(planning, "") is False


class TestFindPlanningDir:
    def test_finds_in_current_dir(self, tmp_path, monkeypatch):
        drive_root = tmp_path / ".drive"
        plan_dir = drive_root / "plan-test"
        plan_dir.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        assert hook_io.find_active_plan_dir() == plan_dir

    def test_walks_up_to_parent(self, tmp_path, monkeypatch):
        drive_root = tmp_path / ".drive"
        plan_dir = drive_root / "plan-test"
        plan_dir.mkdir(parents=True)
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)
        assert hook_io.find_active_plan_dir() == plan_dir

    def test_returns_none_when_absent(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert hook_io.find_active_plan_dir() is None

    def test_falls_back_to_latest_plan_when_no_marker(self, tmp_path, monkeypatch):
        drive_root = tmp_path / ".drive"
        older = drive_root / "plan-20260817-0930-old"
        older.mkdir(parents=True)
        newer = drive_root / "plan-20260817-1530-foo"
        newer.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        import os
        import time
        now = time.time()
        os.utime(older, (now - 100, now - 100))
        os.utime(newer, (now, now))
        assert hook_io.find_active_plan_dir() == newer

    def test_current_plan_marker_wins(self, tmp_path, monkeypatch):
        drive_root = tmp_path / ".drive"
        (drive_root / "plan-20260817-0930-old").mkdir(parents=True)
        marker_target = drive_root / "plan-20260817-1530-foo"
        marker_target.mkdir(parents=True)
        (drive_root / "plan-20260817-1800-bar").mkdir(parents=True)
        (drive_root / ".current-plan").write_text("plan-20260817-1530-foo", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        assert hook_io.find_active_plan_dir() == marker_target
