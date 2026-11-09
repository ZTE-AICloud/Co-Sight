"""审计日志统一接口 — 追加事件到 `.drive/<plan_dir>/run-log.jsonl`。

run-log.jsonl 是 append-only 的审计轨迹，每行一个 JSON 事件。
所有事件共享统一 schema：
    {"ts": "<iso-seconds>", "event": "<name>", ...details}

时间戳统一为 UTC，精度到秒（isoformat(timespec="seconds")），
使得跨进程 / 跨 hook 的日志格式完全一致。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envelope import (
    Envelope,
    REASON_PLANNING_DIR_INVALID,
    REASON_WRITE_FAILED,
)

RUN_LOG_NAME = "run-log.jsonl"

# run-log.jsonl 里每个事件的保留字段（写入顺序无关，读取时校验用）。
RESERVED_FIELDS = frozenset({"ts", "event"})


def now_ts() -> str:
    """统一时间戳：UTC，精度秒。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_log_path(planning_dir: Path) -> Path:
    return planning_dir / RUN_LOG_NAME


def build_event(event: str, **details: Any) -> dict[str, Any]:
    """构造标准事件 dict（ts 在前，event 次之，details 收尾）。

    details 中若包含保留字段 ts/event，会被丢弃以防覆盖。
    """
    clean = {k: v for k, v in details.items() if k not in RESERVED_FIELDS}
    return {"ts": now_ts(), "event": event, **clean}


def log(planning_dir: str | Path, event: str, **details: Any) -> Envelope:
    """追加一个事件到 run-log.jsonl。

    Args:
        planning_dir: `.drive/<plan_dir>/` 目录
        event: 事件名（如 "agent_spawned" / "stage_advanced"）
        **details: 事件附加字段（保留字段 ts/event 会被忽略）

    Returns:
        成功 → Envelope.ok_envelope(event=..., path=...)
        失败 → Envelope.fail(reason, ...)
    """
    if not event or not isinstance(event, str):
        return Envelope.fail("invalid_arg", field="event", value=repr(event))

    planning_path = Path(planning_dir)
    if not planning_path.is_dir():
        return Envelope.fail(
            REASON_PLANNING_DIR_INVALID,
            planning_dir=str(planning_path),
        )

    payload = build_event(event, **details)
    run_log = _run_log_path(planning_path)
    try:
        with open(run_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as exc:
        return Envelope.fail(
            REASON_WRITE_FAILED,
            path=str(run_log),
            error=str(exc),
        )

    return Envelope.ok_envelope(event=event, ts=payload["ts"], path=str(run_log))


def read_log(planning_dir: str | Path) -> list[dict[str, Any]]:
    """读取 run-log.jsonl 全部事件（解析失败的行跳过）。

    不存在时返回空列表。此函数不返回 Envelope（供内部 / 测试直接消费）。
    """
    run_log = _run_log_path(Path(planning_dir))
    if not run_log.is_file():
        return []

    events: list[dict[str, Any]] = []
    for line in run_log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


__all__ = [
    "log",
    "read_log",
    "build_event",
    "now_ts",
    "RUN_LOG_NAME",
    "RESERVED_FIELDS",
]
