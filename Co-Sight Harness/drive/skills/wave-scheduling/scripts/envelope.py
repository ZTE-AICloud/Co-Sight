"""会计脚本的返回协议 — stdout JSON + exit code。

success: {"ok": true, "data": {...}}
failure: {"ok": false, "reason": "...", "details": {...}}

本 skill 副本只覆盖 wave-scheduling 自己用得到的 REASON 子集。drift
风险由本 skill 自负责，不与其它 skill 共享定义。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any

REASON_INVALID_ARG = "invalid_arg"
REASON_SCHEMA_INVALID = "schema_invalid"
REASON_FILE_MISSING = "file_missing"


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


def emit(env: Envelope) -> None:
    """Print envelope 到 stdout，按 exit_code 退出进程。"""
    print(env.to_json())
    sys.exit(env.exit_code())


__all__ = [
    "Envelope",
    "emit",
    "REASON_INVALID_ARG",
    "REASON_SCHEMA_INVALID",
    "REASON_FILE_MISSING",
]
