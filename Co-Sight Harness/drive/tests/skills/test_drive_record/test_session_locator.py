"""session_locator 测试 —— Phase 3。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from record_reader import read_record
from session_locator import (
    cwd_hash,
    extract_session_id,
    locate_session,
    _PROJECTS_ROOT,
)


def _make_plan(plan_dir: Path, *, run_log_lines: list[str] | None = None) -> None:
    plan_dir.mkdir(parents=True, exist_ok=True)
    for name, content in {
        "run-meta.json": json.dumps({"started_at": "2026-08-18T09:30:00Z"}),
        "intent.md": "# intent\n",
        "manifest.md": "# manifest\n",
        "taskRecord.yaml": "plan_id: t\ntasks: []\n",
        "waves.yaml": "plan_id: t\nwaves: []\n",
        "executeState.json": json.dumps({
            "schema_version": "drive.runtime.state.v1",
            "revision": 1, "active_stage": "execute",
        }),
    }.items():
        (plan_dir / name).write_text(content, encoding="utf-8")
    if run_log_lines:
        (plan_dir / "run-log.jsonl").write_text(
            "\n".join(run_log_lines) + "\n", encoding="utf-8"
        )


class TestCwdHash:
    def test_deterministic(self, tmp_path):
        h1 = cwd_hash(str(tmp_path))
        h2 = cwd_hash(str(tmp_path))
        assert h1 == h2
        assert len(h1) == 16

    def test_empty_returns_empty(self):
        assert cwd_hash("") == ""

    def test_abs_path_is_stable(self, tmp_path):
        # abspath 归一化由 stdlib 保证；这里只测非空路径 → 非空 hash
        assert cwd_hash(str(tmp_path)) != ""


class TestExtractSessionId:
    def test_extracts_from_agent_spawned(self, tmp_path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "drive_startup"}',
            '{"ts": "2026-08-18T09:30:05+00:00", "event": "agent_spawned", '
            '"subagent_type": "x", "session_id": "sess-abc-123"}',
        ])
        record = read_record(p)
        assert extract_session_id(record) == "sess-abc-123"

    def test_empty_when_no_agent_spawned(self, tmp_path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "drive_startup"}',
        ])
        record = read_record(p)
        assert extract_session_id(record) == ""

    def test_first_wins(self, tmp_path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "agent_spawned", "session_id": "first"}',
            '{"ts": "2026-08-18T09:30:05+00:00", "event": "agent_spawned", "session_id": "second"}',
        ])
        record = read_record(p)
        assert extract_session_id(record) == "first"


class TestLocateSession:
    def test_returns_none_when_no_session_id(self, tmp_path):
        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "drive_startup"}',
        ])
        record = read_record(p)
        assert locate_session(record, cwd=str(tmp_path)) is None

    def test_finds_existing_file(self, tmp_path, monkeypatch):
        # 让 session locator 用临时 _PROJECTS_ROOT
        fake_projects = tmp_path / "projects"
        fake_projects.mkdir()
        monkeypatch.setattr("session_locator._PROJECTS_ROOT", fake_projects)

        h = cwd_hash(str(tmp_path))
        target_dir = fake_projects / h
        target_dir.mkdir()
        (target_dir / "sess-xyz.json").write_text("{}")

        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "agent_spawned", "session_id": "sess-xyz"}',
        ])
        record = read_record(p)
        result = locate_session(record, cwd=str(tmp_path))
        assert result is not None
        assert result.name == "sess-xyz.json"

    def test_override_takes_precedence(self, tmp_path, monkeypatch):
        fake_projects = tmp_path / "projects"
        fake_projects.mkdir()
        monkeypatch.setattr("session_locator._PROJECTS_ROOT", fake_projects)

        h = cwd_hash(str(tmp_path))
        (fake_projects / h).mkdir()
        (fake_projects / h / "override-sid.json").write_text("{}")

        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "agent_spawned", "session_id": "from-log"}',
        ])
        record = read_record(p)
        result = locate_session(record, cwd=str(tmp_path), override="override-sid")
        assert result is not None
        assert result.name == "override-sid.json"

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        fake_projects = tmp_path / "projects"
        fake_projects.mkdir()
        monkeypatch.setattr("session_locator._PROJECTS_ROOT", fake_projects)

        p = tmp_path / "p"
        _make_plan(p, run_log_lines=[
            '{"ts": "2026-08-18T09:30:00+00:00", "event": "agent_spawned", "session_id": "nonexistent"}',
        ])
        record = read_record(p)
        assert locate_session(record, cwd=str(tmp_path)) is None