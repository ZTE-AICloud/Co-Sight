"""Typed envelope — drive-record scripts 的统一返回协议。

设计沿用 `skills/state-machine/scripts/envelope.py`：JSON-friendly，
失败必有 reason + details，成功必有 data。同一进程内不跨目录 import
state-machine 的 envelope（避免 sibling 冲突），协议相同即可。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Envelope:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok_envelope(cls, **data: Any) -> "Envelope":
        return cls(ok=True, data=data)

    @classmethod
    def fail(cls, reason: str, **details: Any) -> "Envelope":
        return cls(ok=False, reason=reason, details=details)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def exit_code(self) -> int:
        return 0 if self.ok else 1


REASON_INVALID_ARG = "invalid_arg"
REASON_FILE_MISSING = "file_missing"
REASON_JSON_DECODE_ERROR = "json_decode_error"
REASON_PLANNING_DIR_INVALID = "planning_dir_invalid"
REASON_WRITE_FAILED = "write_failed"
REASON_INTERNAL_ERROR = "internal_error"

REASON_CODES: frozenset[str] = frozenset({
    REASON_INVALID_ARG,
    REASON_FILE_MISSING,
    REASON_JSON_DECODE_ERROR,
    REASON_PLANNING_DIR_INVALID,
    REASON_WRITE_FAILED,
    REASON_INTERNAL_ERROR,
})


def emit(*, ok: bool, data: dict[str, Any] | None = None,
         reason: str | None = None, details: dict[str, Any] | None = None) -> None:
    """打印 envelope 到 stdout 并退出。

    用法：
        emit(ok=True, data={"key": "value"})
        emit(ok=False, reason=REASON_INVALID_ARG, details={"hint": "..."})
    """
    env = Envelope(
        ok=ok,
        data=data or {},
        reason=reason,
        details=details or {},
    )
    print(env.to_json())
    sys.stdout.flush()
    sys.exit(env.exit_code())


__all__ = [
    "Envelope",
    "emit",
    "REASON_CODES",
    "REASON_INVALID_ARG",
    "REASON_FILE_MISSING",
    "REASON_JSON_DECODE_ERROR",
    "REASON_PLANNING_DIR_INVALID",
    "REASON_WRITE_FAILED",
    "REASON_INTERNAL_ERROR",
]