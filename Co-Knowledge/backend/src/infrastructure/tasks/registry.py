"""按 ``task_type`` 登记领域取消回调。

任务引擎只负责队列状态；取消一条排队中的任务后，文件行/图谱库状态还需要
领域代码同步。登记表让 HTTP 管理面不需要反向依赖文件/图谱运行时。
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

CancelHook = Callable[[dict], None]

_LOCK = threading.Lock()
_CANCEL_HOOKS: dict[str, CancelHook] = {}
_RETRY_HOOKS: dict[str, CancelHook] = {}


def register_cancel_hook(task_type: str, hook: Optional[CancelHook]) -> None:
    if not task_type or hook is None:
        return
    with _LOCK:
        _CANCEL_HOOKS[str(task_type)] = hook


def cancel_hook_for(task_type: str) -> Optional[CancelHook]:
    with _LOCK:
        return _CANCEL_HOOKS.get(str(task_type))


def unregister_cancel_hook(task_type: str) -> None:
    with _LOCK:
        _CANCEL_HOOKS.pop(str(task_type), None)


def register_retry_hook(task_type: str, hook: Optional[CancelHook]) -> None:
    if not task_type or hook is None:
        return
    with _LOCK:
        _RETRY_HOOKS[str(task_type)] = hook


def retry_hook_for(task_type: str) -> Optional[CancelHook]:
    with _LOCK:
        return _RETRY_HOOKS.get(str(task_type))


def unregister_retry_hook(task_type: str) -> None:
    with _LOCK:
        _RETRY_HOOKS.pop(str(task_type), None)


def clear_cancel_hooks() -> None:
    """测试用：清空登记表，避免用例之间互相污染。"""
    with _LOCK:
        _CANCEL_HOOKS.clear()
        _RETRY_HOOKS.clear()
