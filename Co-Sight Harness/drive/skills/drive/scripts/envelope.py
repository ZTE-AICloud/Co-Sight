"""drive skill 脚本的返回协议 — stdout JSON + exit code。

success: {"ok": true, "data": {...}}
failure: {"ok": false, "reason": "...", "details": {...}}
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


# ---- REASON 子集：覆盖 drive/scripts/ 下所有脚本所需 ----

# 1. 参数 / 输入校验
REASON_INVALID_ARG = "invalid_arg"
REASON_SCHEMA_INVALID = "schema_invalid"

# 2. 文件 IO
REASON_FILE_MISSING = "file_missing"
REASON_FILE_NOT_FOUND = "file_not_found"
REASON_WRITE_FAILED = "write_failed"
REASON_JSON_DECODE_ERROR = "json_decode_error"

# 3. 并发 / 一致性
REASON_REVISION_CONFLICT = "revision_conflict"

# 4. planning dir 守卫
REASON_PLANNING_DIR_INVALID = "planning_dir_invalid"

# 5. subprocess 调用（跨脚本 timeout / spawn 失败）
REASON_SUBPROCESS_TIMEOUT = "subprocess_timeout"

# 6. 保护字段 / 显式确认（dag_state_cli / confirm_node）
REASON_CONFIRMATION_REQUIRED = "confirmation_required"
REASON_VERDICT_NOT_PASS = "verdict_not_pass"
REASON_ALREADY_CONFIRMED = "already_confirmed"
REASON_UNKNOWN_AGENT = "unknown_agent"
REASON_INVALID_AGENT = "invalid_agent"

# 7. DAG 模式 wave 推进约束（dag_scheduler.advance_to_wave）
REASON_WAVE_SKIP = "wave_skip"


REASON_CODES: frozenset[str] = frozenset({
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
    REASON_FILE_MISSING,
    REASON_FILE_NOT_FOUND,
    REASON_WRITE_FAILED,
    REASON_JSON_DECODE_ERROR,
    REASON_REVISION_CONFLICT,
    REASON_PLANNING_DIR_INVALID,
    REASON_SUBPROCESS_TIMEOUT,
    REASON_CONFIRMATION_REQUIRED,
    REASON_VERDICT_NOT_PASS,
    REASON_ALREADY_CONFIRMED,
    REASON_UNKNOWN_AGENT,
    REASON_INVALID_AGENT,
    REASON_WAVE_SKIP,
})


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
    "REASON_CODES",
    "REASON_INVALID_ARG",
    "REASON_SCHEMA_INVALID",
    "REASON_FILE_MISSING",
    "REASON_FILE_NOT_FOUND",
    "REASON_WRITE_FAILED",
    "REASON_JSON_DECODE_ERROR",
    "REASON_REVISION_CONFLICT",
    "REASON_PLANNING_DIR_INVALID",
    "REASON_SUBPROCESS_TIMEOUT",
    "REASON_CONFIRMATION_REQUIRED",
    "REASON_VERDICT_NOT_PASS",
    "REASON_ALREADY_CONFIRMED",
    "REASON_UNKNOWN_AGENT",
    "REASON_INVALID_AGENT",
    "REASON_WAVE_SKIP",
]
