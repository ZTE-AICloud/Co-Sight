"""一条任务车道：有界队列 + 固定数量的 worker 线程。

车道是**隔离单位**：长任务（抽图、图谱导入）和短任务（文件入库）各占一条车道，
互不抢 worker。车道本身不解释任务语义，只负责把记录交给引擎的执行回调。
"""

from __future__ import annotations

import queue as queue_module
import threading
import time
from typing import Callable, Optional

from infrastructure.logging.logutil import log
from infrastructure.tasks.types import TaskRecord

DEFAULT_POLL_TIMEOUT_SECONDS = 1.0


class TaskLane:
    """固定 worker 数 + 可选容量上限的进程内队列。"""

    def __init__(self, name: str, *, workers: int = 1, capacity: int = 0,
                 poll_timeout: float = DEFAULT_POLL_TIMEOUT_SECONDS):
        if workers < 1:
            raise ValueError('workers must be >= 1')
        if capacity < 0:
            raise ValueError('capacity must be >= 0')
        self.name = name
        self.workers = workers
        self.capacity = capacity
        self.poll_timeout = poll_timeout
        self._queue: queue_module.Queue = queue_module.Queue(maxsize=capacity)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._running = 0
        self._handler: Optional[Callable[[TaskRecord], None]] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, handler: Callable[[TaskRecord], None]) -> None:
        """起 worker；``handler`` 由引擎注入（执行 + 重试决策）。

        幂等且线程安全：多个提交线程可能同时触发懒启动。
        """
        with self._lock:
            if self._handler is not None:
                return
            self._handler = handler
        for index in range(1, self.workers + 1):
            thread = threading.Thread(
                target=self._worker_loop,
                name=f'task-{self.name}-{index}',
                daemon=False,
            )
            thread.start()
            self._threads.append(thread)

    def shutdown(self, drain_seconds: float = 0.0) -> None:
        """停止接收新任务并等 worker 退出。

        ``drain_seconds > 0`` 时先等队列排空与在跑任务结束；默认 0 与现有文件队列
        一致：worker 跑完手上这一条就退出，队列里的剩余项留在原处。
        """
        if drain_seconds > 0:
            deadline = time.monotonic() + drain_seconds
            while time.monotonic() < deadline:
                if self._queue.empty() and self.running == 0:
                    break
                time.sleep(0.01)
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=self.poll_timeout + 1.0)
        self._threads.clear()

    # ------------------------------------------------------------------
    # 提交 / 观测
    # ------------------------------------------------------------------

    def submit(self, record: TaskRecord) -> bool:
        """入队。队满或车道已关停时返回 False（由引擎按 kind 的策略处理）。"""
        if self._stop.is_set():
            return False
        try:
            self._queue.put_nowait(record)
            return True
        except queue_module.Full:
            return False

    @property
    def running(self) -> int:
        with self._lock:
            return self._running

    @property
    def queued(self) -> int:
        return self._queue.qsize()

    @property
    def is_shutdown(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        # 与原有文件任务执行器相同的语义：关停标志置位后，跑完手上这一条就退出，
        # 不把队列里剩余的项取出来。
        while not self._stop.is_set():
            try:
                record = self._queue.get(timeout=self.poll_timeout)
            except queue_module.Empty:
                continue
            with self._lock:
                self._running += 1
            try:
                self._handler(record)                     # type: ignore[misc]
            except Exception:                             # noqa: BLE001
                log.exception('task lane %s: worker crashed on %s',
                              self.name, record.task_id)
            finally:
                with self._lock:
                    self._running -= 1
                self._queue.task_done()
