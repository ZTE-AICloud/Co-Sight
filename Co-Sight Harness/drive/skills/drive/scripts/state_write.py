"""状态存储 — executeState.json 的并发安全读写。

并发模型:
- fcntl.LOCK_EX 排他锁（锁在 <planning_dir>/runtime/state.lock 上，与数据文件分离）
- 事务性写入：写临时文件 → os.replace 原子 rename
- read-modify-write 在单次持锁内完成，避免 lost update
- revision 单调递增，供乐观并发检测

路径约定（PROP-20260817-001）：
- planning_dir 入参是 .drive/plan-<UTC-YYYYMMDD-HHMM>-<name>/ 完整路径
- executeState.json 落在此目录下；锁文件在 <planning_dir>/runtime/state.lock
- 历史 .planning/ 路径已被废弃，drive runtime 不再识别
"""
from __future__ import annotations

import copy
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from envelope import (
    Envelope,
    REASON_FILE_MISSING,
    REASON_INVALID_ARG,
    REASON_JSON_DECODE_ERROR,
    REASON_REVISION_CONFLICT,
    REASON_SCHEMA_INVALID,
    REASON_WRITE_FAILED,
)

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX 平台
    fcntl = None  # type: ignore[assignment]

STATE_FILENAME = "executeState.json"
LOCK_SUBPATH = ("runtime", "state.lock")

# 点号是路径分隔符：`custom_agents.a.status` 指向嵌套结构而非字面量 key。
PATH_SEPARATOR = "."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _state_path(planning_dir: Path) -> Path:
    return Path(planning_dir) / STATE_FILENAME


def _lock_path(planning_dir: Path) -> Path:
    return Path(planning_dir).joinpath(*LOCK_SUBPATH)


def default_state() -> dict[str, Any]:
    """新 executeState.json 的默认结构。"""
    now = _now()
    return {
        "schema_version": "drive.runtime.state.v1",
        "revision": 0,
        "active_stage": None,
        "status": "executing",
        "current_wave": 1,
        "waves_total": 1,
        "task_results": {},
        "wave_summaries": {},
        "next_action": None,
        # HITL：人工已签字的阶段。默认拒绝 —— 阶段不在这里就不能流转出去。
        # 只能由 confirm_stage.py 追加，该脚本不在任何 skill 的 allowed-tools 里，
        # 模型跑它会触发 harness 授权提示，那个提示即人工确认本身。
        "confirmed_stages": [],
        # 当前在等谁签字（阶段名）。None 表示没有待确认项。
        "pending_confirmation": None,
        "created_at": now,
        "updated_at": now,
    }


@contextmanager
def _exclusive_lock(planning_dir: Path) -> Iterator[None]:
    """持有 planning_dir 的排他锁。锁文件与数据文件分离，避免 rename 丢锁。"""
    lock_file_path = _lock_path(planning_dir)
    lock_file_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_file_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_unlocked(path: Path) -> dict[str, Any]:
    """读文件（假定已持锁）。文件缺失返回默认；解析失败抛 ValueError。"""
    if not path.exists():
        return default_state()
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("state 顶层必须是 JSON object")
    return raw


def _write_unlocked(path: Path, document: dict[str, Any]) -> None:
    """事务性写入（假定已持锁）：写临时文件 → os.replace 原子 rename。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def read_state(planning_dir: Path) -> Envelope:
    """读 executeState.json，返回 state dict。文件缺失返回默认 state。"""
    path = _state_path(planning_dir)
    try:
        with _exclusive_lock(planning_dir):
            document = _read_unlocked(path)
    except json.JSONDecodeError as exc:
        return Envelope.fail(
            REASON_JSON_DECODE_ERROR,
            error=str(exc),
            path=str(path),
        )
    except (OSError, ValueError) as exc:
        return Envelope.fail(
            REASON_WRITE_FAILED,
            error=str(exc),
            path=str(path),
        )
    return Envelope.ok_envelope(state=document, path=str(path))


def require_state(planning_dir: Path) -> Envelope:
    """读 state，但文件不存在时返回 file_missing 而非默认值。"""
    path = _state_path(planning_dir)
    if not path.exists():
        return Envelope.fail(REASON_FILE_MISSING, path=str(path))
    return read_state(planning_dir)


def write_state(planning_dir: Path, state: dict[str, Any]) -> Envelope:
    """全量覆盖写 executeState.json。revision 自增，updated_at 刷新。

    单次持锁内 read（取当前 revision）→ merge → write，保证 revision 单调。
    """
    if not isinstance(state, dict):
        return Envelope.fail(REASON_WRITE_FAILED, error="state 必须是 dict")
    path = _state_path(planning_dir)
    try:
        with _exclusive_lock(planning_dir):
            try:
                current = _read_unlocked(path)
            except (json.JSONDecodeError, ValueError):
                current = default_state()
            document = copy.deepcopy(state)
            document["revision"] = int(current.get("revision", 0)) + 1
            document["updated_at"] = _now()
            document.setdefault("created_at", current.get("created_at", document["updated_at"]))
            _write_unlocked(path, document)
    except OSError as exc:
        return Envelope.fail(REASON_WRITE_FAILED, error=str(exc), path=str(path))
    return Envelope.ok_envelope(state=document, revision=document["revision"], path=str(path))


def update_state(
    planning_dir: Path,
    mutator: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    expected_revision: int | None = None,
) -> Envelope:
    """并发安全的 read-modify-write。

    mutator 接收当前 state 的深拷贝，返回新 state；整个过程在单次持锁内完成，
    因此 10 个进程并发调用不会 lost update（每次都读最新再改）。

    Args:
        expected_revision: 若提供，与当前 revision 不符则拒绝（乐观并发）。
    """
    path = _state_path(planning_dir)
    try:
        with _exclusive_lock(planning_dir):
            try:
                current = _read_unlocked(path)
            except (json.JSONDecodeError, ValueError):
                current = default_state()

            if expected_revision is not None:
                actual = int(current.get("revision", 0))
                if expected_revision != actual:
                    return Envelope.fail(
                        REASON_REVISION_CONFLICT,
                        expected=expected_revision,
                        actual=actual,
                        path=str(path),
                    )

            new_state = mutator(copy.deepcopy(current))
            if not isinstance(new_state, dict):
                return Envelope.fail(
                    REASON_WRITE_FAILED,
                    error="mutator 必须返回 dict",
                    path=str(path),
                )
            new_state["revision"] = int(current.get("revision", 0)) + 1
            new_state["updated_at"] = _now()
            new_state.setdefault("created_at", current.get("created_at", new_state["updated_at"]))
            _write_unlocked(path, new_state)
    except OSError as exc:
        return Envelope.fail(REASON_WRITE_FAILED, error=str(exc), path=str(path))
    return Envelope.ok_envelope(state=new_state, revision=new_state["revision"], path=str(path))


class _PathError(Exception):
    """点号路径落不了地。携带构造 Envelope 所需的 reason 与 details。"""

    def __init__(self, reason: str, **details: Any) -> None:
        super().__init__(details.get("error", reason))
        self.reason = reason
        self.details = details


def split_path(key: str) -> list[str]:
    """把点号 key 切成路径段。任一段为空即非法。"""
    segments = key.split(PATH_SEPARATOR)
    if any(not segment for segment in segments):
        raise _PathError(REASON_INVALID_ARG, error=f"路径段不能为空: {key!r}", key=key)
    return segments


def set_path(state: dict[str, Any], key: str, value: Any) -> None:
    """按点号路径写入，逐段建 dict。同层已有的兄弟键保留。

    中途遇到非 dict 的既存值就拒绝 —— 继续走会把它静默覆盖掉。
    """
    segments = split_path(key)
    cursor = state
    for depth, segment in enumerate(segments[:-1]):
        existing = cursor.get(segment)
        if existing is None:
            existing = {}
            cursor[segment] = existing
        elif not isinstance(existing, dict):
            walked = PATH_SEPARATOR.join(segments[: depth + 1])
            raise _PathError(
                REASON_SCHEMA_INVALID,
                error=(
                    f"{walked!r} 已是 {type(existing).__name__}，"
                    f"不能作为 {key!r} 的父节点"
                ),
                key=key,
                conflict_at=walked,
            )
        cursor = existing
    cursor[segments[-1]] = value


def root_segment(key: str) -> str:
    """取点号 key 的第一段。授权检查比对这一段，不比整串。"""
    return key.split(PATH_SEPARATOR, 1)[0]


def update_fields(planning_dir: Path, **fields: Any) -> Envelope:
    """并发安全地合并字段（read-modify-write）。

    key 含点号时按路径展开成嵌套结构：`custom_agents.a.status` 落到
    state["custom_agents"]["a"]["status"]。同层兄弟键不受影响，因此多个
    agent 各写自己的命名空间不会互相抹掉。

    路径非法或与既存标量冲突时不落盘，revision 不变。
    """
    def _merge(state: dict[str, Any]) -> dict[str, Any]:
        for key, value in fields.items():
            if PATH_SEPARATOR in key:
                set_path(state, key, value)
            else:
                state[key] = value
        return state

    try:
        return update_state(planning_dir, _merge)
    except _PathError as exc:
        return Envelope.fail(exc.reason, **exc.details)


def reset_state(planning_dir: Path) -> Envelope:
    """重置为默认 state（危险操作，显式调用）。"""
    path = _state_path(planning_dir)
    try:
        with _exclusive_lock(planning_dir):
            _write_unlocked(path, default_state())
    except OSError as exc:
        return Envelope.fail(REASON_WRITE_FAILED, error=str(exc), path=str(path))
    return Envelope.ok_envelope(reset=True, path=str(path))


__all__ = [
    "STATE_FILENAME",
    "PATH_SEPARATOR",
    "default_state",
    "read_state",
    "require_state",
    "write_state",
    "update_state",
    "update_fields",
    "reset_state",
    "split_path",
    "set_path",
    "root_segment",
]
