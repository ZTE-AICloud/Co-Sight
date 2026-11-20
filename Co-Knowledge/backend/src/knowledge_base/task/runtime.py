"""进程级的队列单例。

放在这里而不是 ``app.py``：``app.py`` 会拉起完整运行时与数据库连接，而单测与上传链路都要
能拿到同一个队列实例。``register_rkb_api`` 在装配时调 :func:`start`，
并用 ``atexit`` 关停。

**懒启动**：车道与 worker 只在第一次提交时创建 —— 单测里不装配就不会有后台线程。
"""

from __future__ import annotations

import atexit
import os
import threading

from knowledge_base.task.queue import FileTaskQueue
from infrastructure.logging.logutil import log

_queue: FileTaskQueue | None = None
_lock = threading.Lock()


def start() -> FileTaskQueue:
    """建队列（幂等）。返回队列单例。

    运行时使用 **DB 队列**：worker 从 ``task_center.task`` 认领，重启后库里
    PENDING/RETRY 的任务会被继续执行。
    """
    global _queue
    with _lock:
        if _queue is None:
            enabled = os.environ.get('RKB_TASK_QUEUE_DB', '1').strip().lower()
            mode = 'db' if enabled not in ('0', 'false', 'no', 'off') else 'memory'
            _queue = FileTaskQueue(queue_mode=mode)
            if mode == 'db':
                _queue.start()
            atexit.register(shutdown)
            log.info('kb_api file task runtime started (%s queue)', mode)
        return _queue


def get_queue() -> FileTaskQueue:
    """取队列；尚未启动则**先启动**（首次上传时才拉起 worker）。"""
    return start()


def shutdown() -> None:
    """关停队列与引擎车道（``atexit`` 会调；重复调用安全）。"""
    global _queue
    with _lock:
        if _queue is not None:
            _queue.shutdown()
            _queue = None
