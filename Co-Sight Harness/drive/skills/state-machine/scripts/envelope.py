"""Typed envelope — 所有 runtime 命令的统一返回值格式。

设计目的:
- LLM 能 parse (JSON)
- 错误必有 reason + details
- 成功必有 ok=True + data 字段

JSON shape:
    success: {"ok": true, "data": {...}}
    failure: {"ok": false, "reason": "schema_invalid", "details": {...}}

各 skill / hook 各自维护 envelope.py 本地副本，drift 由各责任方自负责。
本文件是 state-machine 单点的全集；其它副本见
skills/{drive,wave-scheduling,wave-barrier}/scripts/envelope.py。
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Envelope:
    """所有 runtime 命令返回的 envelope。不可变。"""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok_envelope(cls, **data: Any) -> "Envelope":
        """构造成功 envelope，data 从 kwargs 收集。"""
        return cls(ok=True, data=data)

    @classmethod
    def fail(cls, reason: str, **details: Any) -> "Envelope":
        """构造失败 envelope，reason 必填，details 从 kwargs 收集。"""
        return cls(ok=False, reason=reason, details=details)

    def to_dict(self) -> dict[str, Any]:
        """返回 dataclass 的普通 dict 视图。"""
        return asdict(self)

    def to_json(self) -> str:
        """序列化 JSON 字符串（紧凑, 无 indent, 适合 stdout）。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def exit_code(self) -> int:
        """失败 → 1, 成功 → 0。供 CLI 进程退出用。"""
        return 0 if self.ok else 1


# ---- 28 个预定义 reason codes ----
# 1. 参数 / 输入校验
REASON_INVALID_ARG = "invalid_arg"
REASON_SCHEMA_INVALID = "schema_invalid"

# 2. 文件 IO
REASON_FILE_MISSING = "file_missing"
REASON_FILE_NOT_FOUND = "file_not_found"  # alias 由 dag_state_cli 引入（实际语义同 FILE_MISSING）
REASON_WRITE_FAILED = "write_failed"
REASON_LOCK_FAILED = "lock_failed"
REASON_JSON_DECODE_ERROR = "json_decode_error"

# 3. 状态机流转
REASON_UNKNOWN_STAGE = "unknown_stage"
REASON_INVALID_TRANSITION = "invalid_transition"

# 4. 并发 / 一致性
REASON_REVISION_CONFLICT = "revision_conflict"
REASON_INCONSISTENT_STATE = "inconsistent_state"

# 5. planning dir 守卫
REASON_PLANNING_DIR_INVALID = "planning_dir_invalid"

# 6. CLI 路由
REASON_UNKNOWN_COMMAND = "unknown_command"
REASON_INTERNAL_ERROR = "internal_error"

# 7. 保护字段 / 显式确认（state_cli / dag_state_cli / confirm_node / confirm_stage）
REASON_CONFIRMATION_REQUIRED = "confirmation_required"
REASON_PROTECTED_FIELD = "protected_field"
REASON_VERDICT_NOT_PASS = "verdict_not_pass"
REASON_ALREADY_CONFIRMED = "already_confirmed"
REASON_UNKNOWN_AGENT = "unknown_agent"
REASON_INVALID_AGENT = "invalid_agent"

# 8. plan 目录初始化（startup/init_planning）
REASON_ALREADY_EXISTS = "already_exists"
REASON_LEGACY_PLANNING_EXISTS = "legacy_planning_exists"
REASON_MISSING_PLAN_DIR = "missing_plan_dir"
REASON_INVALID_PLAN_NAME = "invalid_plan_name"

# 9. wave-barrier 强约束（aggregate.py）
REASON_EMPTY_SUMMARIES = "empty_summaries"
REASON_WRITEBACK_FAILED = "writeback_failed"
REASON_WAVE_MISMATCH = "wave_mismatch"
REASON_WAVES_FILE_MISSING = "waves_file_missing"
REASON_EMPTY_FSDIFF = "empty_fsdiff"

# 10. subprocess 调用（跨脚本 timeout / spawn 失败）
REASON_SUBPROCESS_TIMEOUT = "subprocess_timeout"

# 11. DAG 模式 wave 推进约束（dag_scheduler.advance_to_wave）
REASON_WAVE_SKIP = "wave_skip"


REASON_CODES: frozenset[str] = frozenset({
    REASON_INVALID_ARG,
    REASON_SCHEMA_INVALID,
    REASON_FILE_MISSING,
    REASON_FILE_NOT_FOUND,
    REASON_WRITE_FAILED,
    REASON_LOCK_FAILED,
    REASON_JSON_DECODE_ERROR,
    REASON_UNKNOWN_STAGE,
    REASON_INVALID_TRANSITION,
    REASON_REVISION_CONFLICT,
    REASON_INCONSISTENT_STATE,
    REASON_PLANNING_DIR_INVALID,
    REASON_UNKNOWN_COMMAND,
    REASON_INTERNAL_ERROR,
    REASON_CONFIRMATION_REQUIRED,
    REASON_PROTECTED_FIELD,
    REASON_VERDICT_NOT_PASS,
    REASON_ALREADY_CONFIRMED,
    REASON_UNKNOWN_AGENT,
    REASON_INVALID_AGENT,
    REASON_ALREADY_EXISTS,
    REASON_LEGACY_PLANNING_EXISTS,
    REASON_MISSING_PLAN_DIR,
    REASON_INVALID_PLAN_NAME,
    REASON_EMPTY_SUMMARIES,
    REASON_WRITEBACK_FAILED,
    REASON_WAVE_MISMATCH,
    REASON_WAVES_FILE_MISSING,
    REASON_EMPTY_FSDIFF,
    REASON_SUBPROCESS_TIMEOUT,
    REASON_WAVE_SKIP,
})


def emit(env: Envelope) -> None:
    """Print envelope 到 stdout, 然后按 exit_code 退出进程。"""
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
    "REASON_LOCK_FAILED",
    "REASON_JSON_DECODE_ERROR",
    "REASON_UNKNOWN_STAGE",
    "REASON_INVALID_TRANSITION",
    "REASON_REVISION_CONFLICT",
    "REASON_INCONSISTENT_STATE",
    "REASON_PLANNING_DIR_INVALID",
    "REASON_UNKNOWN_COMMAND",
    "REASON_INTERNAL_ERROR",
    "REASON_CONFIRMATION_REQUIRED",
    "REASON_PROTECTED_FIELD",
    "REASON_VERDICT_NOT_PASS",
    "REASON_ALREADY_CONFIRMED",
    "REASON_UNKNOWN_AGENT",
    "REASON_INVALID_AGENT",
    "REASON_ALREADY_EXISTS",
    "REASON_LEGACY_PLANNING_EXISTS",
    "REASON_MISSING_PLAN_DIR",
    "REASON_INVALID_PLAN_NAME",
    "REASON_EMPTY_SUMMARIES",
    "REASON_WRITEBACK_FAILED",
    "REASON_WAVE_MISMATCH",
    "REASON_WAVES_FILE_MISSING",
    "REASON_EMPTY_FSDIFF",
    "REASON_SUBPROCESS_TIMEOUT",
    "REASON_WAVE_SKIP",
]
