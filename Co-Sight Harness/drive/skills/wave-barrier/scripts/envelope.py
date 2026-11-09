"""执行调度脚本的返回协议 — stdout JSON + exit code。

success: {"ok": true, "data": {...}}
failure: {"ok": false, "reason": "...", "details": {...}}

aggregate.py 自己有一份本地 Envelope（含 6 个 wave-barrier 专有 REASON
常量），本 envelope.py 只覆盖其它 wave-barrier 脚本可能用到的最小子集
（目前无其它调用方，保留为未来扩展位）。drift 风险由本 skill 自负责。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

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


__all__ = [
    "Envelope",
    "REASON_SCHEMA_INVALID",
    "REASON_FILE_MISSING",
]
