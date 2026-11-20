"""任务执行的协作式取消信号。

worker 在**当前线程**设置一个 ``threading.Event``；runner 在安全点调用
:func:`raise_if_cancelled`。用 thread-local 是为了不改文件链/图谱服务的
``handle(file_handle)`` 签名 —— 这些函数在 worker 线程里同步执行。
"""

from __future__ import annotations

import threading
from typing import Optional

_LOCAL = threading.local()


class TaskCancelled(Exception):
    """runner 在安全点主动中止；引擎据此把任务置为 CANCELLED，不重试。"""


def set_cancel_event(event: Optional[threading.Event]) -> None:
    _LOCAL.event = event


def clear_cancel_event() -> None:
    _LOCAL.event = None


def is_cancelled() -> bool:
    event = getattr(_LOCAL, 'event', None)
    return bool(event is not None and event.is_set())


def raise_if_cancelled() -> None:
    if is_cancelled():
        raise TaskCancelled('Cancelled by user')
