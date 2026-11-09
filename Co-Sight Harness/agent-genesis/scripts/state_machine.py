#!/usr/bin/env python3
"""State machine with IDLE/PROCESSING/REVIEW/DONE states and audit logging."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, StrEnum
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)


class State(StrEnum):
    IDLE = "IDLE"
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    DONE = "DONE"


# Legal transitions: from_state → {allowed to_states}
TRANSITIONS: dict[State, set[State]] = {
    State.IDLE: {State.PROCESSING},
    State.PROCESSING: {State.REVIEW, State.IDLE},
    State.REVIEW: {State.DONE, State.PROCESSING},
    State.DONE: set(),
}


@dataclass(frozen=True)
class AuditEntry:
    timestamp: str
    from_state: str
    to_state: str
    trigger: str
    operator: str | None
    metadata: dict | None


class TransitionError(Exception):
    """Raised when an illegal state transition is attempted."""


class StateMachine:
    """A state machine that records every state transition to a JSON Lines audit log.

    Usage:
        sm = StateMachine(log_dir=Path("work/my-task"))
        sm.transition(State.PROCESSING, trigger="begin work", operator="agent-1")
        sm.transition(State.REVIEW, trigger="submit for review")
        sm.transition(State.DONE, trigger="approved", operator="reviewer-1")
    """

    def __init__(
        self,
        log_dir: Path,
        initial_state: State = State.IDLE,
        *,
        on_transition: Callable[[AuditEntry], None] | None = None,
    ) -> None:
        log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = log_dir / "audit-log.jsonl"
        self._state = initial_state
        self._on_transition = on_transition

    @property
    def state(self) -> State:
        return self._state

    def transition(
        self,
        to_state: State,
        *,
        trigger: str,
        operator: str | None = None,
        metadata: dict | None = None,
    ) -> AuditEntry:
        """Transition to *to_state* if legal, recording an audit entry.

        Raises TransitionError if the transition is not allowed.
        """
        allowed = TRANSITIONS.get(self._state, set())
        if to_state not in allowed:
            raise TransitionError(
                f"Illegal transition: {self._state} → {to_state}. "
                f"Allowed: {allowed or '(none)'}"
            )

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            from_state=str(self._state),
            to_state=str(to_state),
            trigger=trigger,
            operator=operator,
            metadata=metadata,
        )

        self._append_log(entry)
        self._state = to_state

        if self._on_transition:
            self._on_transition(entry)

        return entry

    def can_transition(self, to_state: State) -> bool:
        return to_state in TRANSITIONS.get(self._state, set())

    def _append_log(self, entry: AuditEntry) -> None:
        record = {
            "timestamp": entry.timestamp,
            "from_state": entry.from_state,
            "to_state": entry.to_state,
            "trigger": entry.trigger,
            "operator": entry.operator,
            "metadata": entry.metadata,
        }
        with open(self._log_path, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_audit_log(self) -> list[dict]:
        """Return all audit entries as a list of dicts."""
        if not self._log_path.exists():
            return []
        entries: list[dict] = []
        with open(self._log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
