#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一日志配置。

目标：所有入口（技能 CLI、构建子进程、resolver、overview_builder）都写同一个
<state_root>/logs/cosightbot.log，并输出足够的阶段/计数/耗时信息，便于排障。

环境变量：
- COSIGHTBOT_LOG_LEVEL：DEBUG / INFO / WARNING / ERROR（默认 INFO）
- COSIGHTBOT_LOG_MAX_BYTES：单文件上限（默认 20MB）
- COSIGHTBOT_LOG_BACKUP_COUNT：轮转保留数（默认 5）

日志格式：
    2026-10-19 14:41:15 [INFO] overview_resolver[pid:thread]: [event] key=value ...
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_CONFIGURED = False
_FORMAT = "%(asctime)s [%(levelname)s] %(name)s[%(process)d:%(threadName)s]: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _default_log_file() -> Path | None:
    try:
        from common.port_resolver import cosight_state_root

        return cosight_state_root() / "logs" / "cosightbot.log"
    except Exception:
        return None


def _level_from_env() -> int:
    raw = (os.environ.get("COSIGHTBOT_LOG_LEVEL") or "INFO").strip().upper()
    return getattr(logging, raw, logging.INFO)


def setup_logging(log_file: str | Path | None = None, *, force: bool = False) -> logging.Logger:
    """配置 root logger；重复调用不叠加 handler。"""
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED and root.handlers and not force:
        return root

    level = _level_from_env()
    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
    handlers: list[logging.Handler] = []

    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    handlers.append(stream)

    path = Path(log_file) if log_file else _default_log_file()
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            max_bytes = int(os.environ.get("COSIGHTBOT_LOG_MAX_BYTES", str(20 * 1024 * 1024)))
            backups = int(os.environ.get("COSIGHTBOT_LOG_BACKUP_COUNT", "5"))
            fh = RotatingFileHandler(
                str(path), maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
            )
            fh.setFormatter(fmt)
            handlers.append(fh)
        except Exception:
            # 日志初始化失败不能阻塞主流程
            pass

    root.setLevel(level)
    if force:
        for handler in list(root.handlers):
            root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    _CONFIGURED = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def _fmt_value(value: Any, max_len: int = 300) -> str:
    text = str(value)
    if len(text) > max_len:
        text = text[:max_len] + "..."
    if any(ch in text for ch in (" ", "=", "\n", "\t")):
        return repr(text)
    return text


def preview_text(value: Any, max_chars: int = 240) -> str:
    """日志用文本预览：保留开头片段 + 总字符数，避免把大文本写进日志。"""
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}…(total {len(text)} chars)"


def preview_items(items: Any, max_items: int = 8, max_item_chars: int = 120) -> str:
    """日志用列表预览：保留前 N 项（每项截断）+ 总数。"""
    try:
        seq = list(items or [])
    except TypeError:
        return preview_text(items)
    shown: list[str] = []
    for item in seq[:max_items]:
        text = str(item)
        if len(text) > max_item_chars:
            text = f"{text[:max_item_chars]}…({len(text)} chars)"
        shown.append(text)
    suffix = "…" if len(seq) > max_items else ""
    return f"[{', '.join(shown)}{suffix}] n={len(seq)}"


def log_event(
    logger: logging.Logger,
    event: str,
    level: int = logging.INFO,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """统一的结构化日志：`[event] key=value ...`。"""
    parts = [f"{key}={_fmt_value(value)}" for key, value in fields.items() if value is not None]
    logger.log(level, "[%s] %s", event, " ".join(parts), exc_info=exc_info)


@contextmanager
def log_stage(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any):
    """记录阶段开始/结束/异常与耗时。"""
    t0 = time.perf_counter()
    log_event(logger, f"{event}:start", level=level, **fields)
    try:
        yield
    except Exception as exc:
        log_event(
            logger,
            f"{event}:error",
            level=logging.ERROR,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            error=f"{type(exc).__name__}: {exc}",
            **fields,
        )
        raise
    else:
        log_event(
            logger,
            f"{event}:done",
            level=level,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            **fields,
        )
