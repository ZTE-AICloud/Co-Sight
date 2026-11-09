#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""进度上报 —— stdout 后端。

无后台常驻进程，
且 Claude Code 常运行在 SSH/headless/tmux 环境，GUI 弹窗没有投递对象。
进度改为输出到 stdout：前台执行时随命令结果返回，后台执行时实时写入任务
输出文件（Claude Code 会增量捕获），由 Claude 在会话中向用户汇报。

调用面：``global_progress.*`` 一组模块级函数；
所有方法防御性容错，绝不因进度上报影响主流程。
"""

from __future__ import annotations

import sys
import threading


def _emit(msg: str) -> None:
    """单行进度输出，flush 保证后台任务输出文件实时可见。"""
    try:
        line = f"[progress] {msg}"
        print(line, flush=True)
    except Exception:
        pass


def _format_busy_title(processing_count: int = 0, waiting_count: int = 0, **_: object) -> str:
    return f"正在处理 {processing_count} 个文件（等待 {waiting_count} 个）"


def _format_failure_retry_hint() -> str:
    return "存在失败文件，修复后重新构建即可（指纹增量，只处理变更文件）"


def _compute_done_units(*_: object, **__: object) -> int:
    """原实现用于弹窗百分比；stdout 后端不消费，保留签名兼容。"""
    return 0


class GlobalProgressPopup:
    """类名保留（调用方/import 兼容），实际为 stdout 进度记录器。"""

    def __init__(self, enable_ui: bool = False, **_: object) -> None:
        # enable_ui 参数保留兼容；stdout 后端无 UI 可开关
        self._lock = threading.Lock()
        self._current: str | None = None

    # ---- 系统状态 ----
    def set_system_status(self, status: str) -> None:
        if status:
            _emit(status)

    def reset_all(self) -> None:
        with self._lock:
            self._current = None

    # ---- 队列 ----
    def add_waiting(self, count: int = 1) -> None:
        if count:
            _emit(f"新增 {count} 个待处理文件")

    # ---- 文件级 ----
    def start_processing(self, filename: str, is_delete: bool = False) -> None:
        with self._lock:
            self._current = filename
        action = "删除" if is_delete else "处理"
        _emit(f"开始{action}: {filename}")

    def finish_processing(self, filename: str) -> None:
        with self._lock:
            self._current = None
        _emit(f"完成: {filename}")

    def fail_processing(self, filename: str, filepath: str, error_msg: str) -> None:
        with self._lock:
            self._current = None
        _emit(f"失败: {filename} — {error_msg}")

    # ---- 文件内子进度（分页/分块） ----
    def start_file_subprogress(self, filename: str, total: int, stage: str = "") -> None:
        stage_txt = f"（{stage}）" if stage else ""
        _emit(f"{filename}{stage_txt}: 共 {total} 个单元")

    def update_file_subprogress(self, filename: str, current: float) -> None:
        # 子进度较密，按 10% 粒度降频输出，避免刷爆日志
        try:
            pct = int(float(current) * 10) * 10
        except Exception:
            return
        if pct > 0 and pct != getattr(self, "_last_pct", None):
            self._last_pct = pct  # noqa: SLF001 — 单进程内最佳努力降频
            _emit(f"{filename}: {pct}%")

    def finish_file_subprogress(self, filename: str) -> None:
        self._last_pct = None
        _emit(f"{filename}: 子任务完成")

    # ---- 聊天侧告警（原弹窗气泡） ----
    def chat_warning(self, message: str) -> None:
        _emit(f"警告: {message}")


# 模块级单例，签名与原实现一致（enable_ui 在 stdout 后端下无副作用）
global_progress = GlobalProgressPopup(enable_ui=False)

__all__ = [
    "GlobalProgressPopup",
    "_compute_done_units",
    "_format_busy_title",
    "_format_failure_retry_hint",
    "global_progress",
]
