"""进程级的队列与 worker 单例。

放在这里而不是 ``app.py``：``app.py`` 会拉起完整运行时与数据库连接，而单测与上传链路都要
能拿到同一个队列实例。``register_rkb_api`` 在装配时调 :func:`start`，
并用 ``atexit`` 关停。

**懒启动**：只有真的用到队列时才起 worker 线程 —— 单测里不装配就不会有 5 个后台线程。
"""

from __future__ import annotations

import atexit
import threading

from knowledge_base.task.executor import FileTaskExecutor
from knowledge_base.task.queue import FileTaskQueue
from infrastructure.logging.logutil import log

_queue: FileTaskQueue | None = None
_executor: FileTaskExecutor | None = None
_lock = threading.Lock()


def start() -> FileTaskQueue:
    """起队列 + worker（幂等）。返回队列单例。"""
    global _queue, _executor
    with _lock:
        if _queue is None:
            _queue = FileTaskQueue()
            _executor = FileTaskExecutor()
            _executor.start(_queue)
            atexit.register(shutdown)
            log.info('kb_api file task runtime started')
        return _queue


def get_queue() -> FileTaskQueue:
    """取队列；尚未启动则**先启动**（首次上传时才拉起 worker）。"""
    return start()


def shutdown() -> None:
    """关停 worker 与队列（``atexit`` 会调；重复调用安全）。"""
    global _queue, _executor
    with _lock:
        if _executor is not None:
            _executor.shutdown()
            _executor = None
        if _queue is not None:
            _queue.shutdown()
            _queue = None
