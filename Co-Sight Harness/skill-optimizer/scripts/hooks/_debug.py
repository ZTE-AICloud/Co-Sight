"""
hooks/_debug — 框架侧 hook 统一日志落盘
=========================================

把每次 hook 触发结果写到 {SKILLX_CURRENT_TASK_DIR}/_debug/hooks.log，
与 tools._resolve_debug_dir() 复用同一 _debug 目录约定（不绑业务）。

未设置 SKILLX_CURRENT_TASK_DIR 时静默跳过（不影响主链路）。
"""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_LOG_LOCK = threading.Lock()


def resolve_debug_log_path(filename: str = "hooks.log") -> Optional[Path]:
    """从 SKILLX_CURRENT_TASK_DIR 推断 hook 日志落盘路径。

    返回 None 表示未配置（不抛错，调用方直接跳过）。
    """
    try:
        from tools import _resolve_debug_dir
        debug_dir = _resolve_debug_dir()
    except Exception:
        debug_dir = None
    if debug_dir is None:
        return None
    return Path(debug_dir) / filename


def log_hook_event(
    trigger: str,
    hook_name: str,
    success: bool,
    duration_ms: float = 0.0,
    context: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    log_filename: str = "hooks.log",
) -> None:
    """统一格式写一行到 _debug/hooks.log。

    格式: [ISO 时间] [trigger] hook_name: success/failed (XXms) | context 摘要 | error
    """
    log_path = resolve_debug_log_path(log_filename)
    if log_path is None:
        return

    ts = datetime.now().isoformat(timespec="seconds")
    status = "success" if success else "failed"
    ctx_summary = ""
    if context:
        keys = sorted(context.keys())
        ctx_summary = " | " + ", ".join(f"{k}={context[k]!r}" for k in keys if k in ("round_num", "score", "workspace", "skill_name", "rating"))
    err_summary = f" | error={error}" if error else ""

    line = f"[{ts}] [{trigger}] {hook_name}: {status} ({duration_ms:.0f}ms){ctx_summary}{err_summary}\n"

    try:
        with _LOG_LOCK:
            with open(log_path, "a", encoding="utf-8") as fp:
                fp.write(line)
    except Exception:
        # 落盘失败不能影响 hook 主链路
        pass
