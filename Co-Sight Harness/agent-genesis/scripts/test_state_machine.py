#!/usr/bin/env python3
"""Tests for state_machine.py."""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.state_machine import (
    AuditEntry,
    State,
    StateMachine,
    TransitionError,
    TRANSITIONS,
)


class TestStateEnum:
    def test_four_states_exist(self) -> None:
        assert set(State) == {State.IDLE, State.PROCESSING, State.REVIEW, State.DONE}

    def test_state_is_string(self) -> None:
        assert State.IDLE == "IDLE"
        assert str(State.IDLE) == "IDLE"


class TestTransitions:
    def test_idle_only_goes_to_processing(self) -> None:
        assert TRANSITIONS[State.IDLE] == {State.PROCESSING}

    def test_processing_goes_to_review_or_idle(self) -> None:
        assert TRANSITIONS[State.PROCESSING] == {State.REVIEW, State.IDLE}

    def test_review_goes_to_done_or_processing(self) -> None:
        assert TRANSITIONS[State.REVIEW] == {State.DONE, State.PROCESSING}

    def test_done_is_terminal(self) -> None:
        assert TRANSITIONS[State.DONE] == set()


class TestStateMachine:
    @pytest.fixture
    def tmp_dir(self) -> Path:
        with tempfile.TemporaryDirectory() as d:
            yield Path(d)

    @pytest.fixture
    def sm(self, tmp_dir: Path) -> StateMachine:
        return StateMachine(log_dir=tmp_dir)

    # --- Initial state ---

    def test_initial_state_is_idle(self, sm: StateMachine) -> None:
        assert sm.state == State.IDLE

    # --- Legal transitions ---

    def test_idle_to_processing(self, sm: StateMachine) -> None:
        entry = sm.transition(State.PROCESSING, trigger="start task")
        assert sm.state == State.PROCESSING
        assert entry.from_state == "IDLE"
        assert entry.to_state == "PROCESSING"
        assert entry.trigger == "start task"

    def test_processing_to_review(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        entry = sm.transition(State.REVIEW, trigger="submit")
        assert sm.state == State.REVIEW
        assert entry.from_state == "PROCESSING"
        assert entry.to_state == "REVIEW"

    def test_processing_to_idle_cancel(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        entry = sm.transition(State.IDLE, trigger="cancelled")
        assert sm.state == State.IDLE

    def test_review_to_done(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        sm.transition(State.REVIEW, trigger="submit")
        entry = sm.transition(State.DONE, trigger="approved")
        assert sm.state == State.DONE
        assert entry.to_state == "DONE"

    def test_review_to_processing_rework(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        sm.transition(State.REVIEW, trigger="submit")
        entry = sm.transition(State.PROCESSING, trigger="rejected, rework needed")
        assert sm.state == State.PROCESSING

    def test_full_happy_path(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin", operator="worker")
        sm.transition(State.REVIEW, trigger="submit for review", operator="worker")
        sm.transition(State.DONE, trigger="approved", operator="reviewer")
        assert sm.state == State.DONE

    # --- Illegal transitions ---

    def test_idle_to_done_is_illegal(self, sm: StateMachine) -> None:
        with pytest.raises(TransitionError, match="IDLE → DONE"):
            sm.transition(State.DONE, trigger="skip")

    def test_idle_to_review_is_illegal(self, sm: StateMachine) -> None:
        with pytest.raises(TransitionError, match="IDLE → REVIEW"):
            sm.transition(State.REVIEW, trigger="skip")

    def test_processing_to_done_is_illegal(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        with pytest.raises(TransitionError, match="PROCESSING → DONE"):
            sm.transition(State.DONE, trigger="skip review")

    def test_done_is_terminal(self, sm: StateMachine) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        sm.transition(State.REVIEW, trigger="submit")
        sm.transition(State.DONE, trigger="approved")
        with pytest.raises(TransitionError, match="DONE → PROCESSING"):
            sm.transition(State.PROCESSING, trigger="reopen")

    def test_no_self_transition(self, sm: StateMachine) -> None:
        with pytest.raises(TransitionError):
            sm.transition(State.IDLE, trigger="stay")

    # --- can_transition ---

    def test_can_transition_legal(self, sm: StateMachine) -> None:
        assert sm.can_transition(State.PROCESSING) is True

    def test_can_transition_illegal(self, sm: StateMachine) -> None:
        assert sm.can_transition(State.DONE) is False

    # --- Audit log ---

    def test_audit_log_written(self, sm: StateMachine, tmp_dir: Path) -> None:
        sm.transition(State.PROCESSING, trigger="begin", operator="agent-1")
        log_path = tmp_dir / "audit-log.jsonl"
        assert log_path.exists()

        with open(log_path) as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert len(lines) == 1
        assert lines[0]["from_state"] == "IDLE"
        assert lines[0]["to_state"] == "PROCESSING"
        assert lines[0]["trigger"] == "begin"
        assert lines[0]["operator"] == "agent-1"

    def test_audit_log_appends(self, sm: StateMachine, tmp_dir: Path) -> None:
        sm.transition(State.PROCESSING, trigger="begin")
        sm.transition(State.REVIEW, trigger="submit")

        entries = sm.read_audit_log()
        assert len(entries) == 2
        assert entries[0]["to_state"] == "PROCESSING"
        assert entries[1]["to_state"] == "REVIEW"

    def test_audit_log_includes_metadata(self, sm: StateMachine) -> None:
        sm.transition(
            State.PROCESSING,
            trigger="begin",
            metadata={"task_id": "T-42", "priority": "high"},
        )
        entries = sm.read_audit_log()
        assert entries[0]["metadata"] == {"task_id": "T-42", "priority": "high"}

    def test_read_audit_log_no_file(self, tmp_dir: Path) -> None:
        sm = StateMachine(log_dir=tmp_dir / "nonexistent")
        entries = sm.read_audit_log()
        assert entries == []

    def test_audit_entry_immutable(self) -> None:
        entry = AuditEntry(
            timestamp="2026-05-12T00:00:00Z",
            from_state="IDLE",
            to_state="PROCESSING",
            trigger="begin",
            operator=None,
            metadata=None,
        )
        with pytest.raises(Exception):
            entry.trigger = "changed"  # type: ignore[misc]

    # --- Callback ---

    def test_on_transition_callback(self, tmp_dir: Path) -> None:
        calls: list[AuditEntry] = []

        def callback(entry: AuditEntry) -> None:
            calls.append(entry)

        sm = StateMachine(log_dir=tmp_dir, on_transition=callback)
        sm.transition(State.PROCESSING, trigger="begin")
        assert len(calls) == 1
        assert calls[0].to_state == "PROCESSING"
