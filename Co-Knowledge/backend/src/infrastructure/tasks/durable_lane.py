"""DB 队列车道：worker 从 ``task_center.task`` 认领任务，而不是消费内存队列。

与 :class:`infrastructure.tasks.lane.TaskLane` 的区别只在「怎么拿任务」：
本类每个 worker 调一次 ``claim(worker_id)``，拿到记录就执行，拿不到就短轮询/等待
唤醒事件。任务状态、租约、重试都在数据库里，进程重启不会丢排队任务。

``claim`` / ``execute`` 由引擎注入；车道本身不关心任务类型和 SQL。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from infrastructure.logging.logutil import log
from infrastructure.tasks.types import TaskRecord

#: 无 NOTIFY 时的兜底轮询间隔；正常唤醒走 LISTEN/NOTIFY + 本实例 wake。
DEFAULT_POLL_SECONDS = 5.0


class DurableTaskLane:
    """固定 worker 数 + DB 认领的车道。"""

    def __init__(self, name: str, *, workers: int = 1,
                 poll_seconds: float = DEFAULT_POLL_SECONDS):
        if workers < 1:
            raise ValueError('workers must be >= 1')
        self.name = name
        self.workers = workers
        self.poll_seconds = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._running = 0
        self._claim: Optional[Callable[[str], Optional[TaskRecord]]] = None
        self._execute: Optional[Callable[[TaskRecord], None]] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self, claim: Callable[[str], Optional[TaskRecord]],
              execute: Callable[[TaskRecord], None]) -> None:
        """起 worker；幂等且线程安全。"""
        with self._lock:
            if self._claim is not None:
                return
            self._claim = claim
            self._execute = execute
        for index in range(1, self.workers + 1):
            thread = threading.Thread(
                target=self._worker_loop,
                args=(index,),
                name=f'task-{self.name}-{index}',
                daemon=False,
            )
            thread.start()
            self._threads.append(thread)

    def wake(self) -> None:
        """有新任务时唤醒本实例的 worker（跨实例仍靠 DB 轮询）。"""
        self._wake.set()

    def shutdown(self, drain_seconds: float = 0.0) -> None:
        if drain_seconds > 0:
            deadline = time.monotonic() + drain_seconds
            while time.monotonic() < deadline and self.running > 0:
                time.sleep(0.01)
        self._stop.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout=self.poll_seconds + 1.0)
        self._threads.clear()

    # ------------------------------------------------------------------
    # 观测
    # ------------------------------------------------------------------

    @property
    def running(self) -> int:
        with self._lock:
            return self._running

    @property
    def is_shutdown(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _worker_loop(self, index: int) -> None:
        worker_id = f'{self.name}-{index}'
        while not self._stop.is_set():
            try:
                record = self._claim(worker_id)          # type: ignore[misc]
            except Exception:                            # noqa: BLE001
                log.exception('durable lane %s: claim failed', self.name)
                record = None
                time.sleep(self.poll_seconds)
            if record is None:
                self._wake.wait(timeout=self.poll_seconds)
                self._wake.clear()
                continue
            with self._lock:
                self._running += 1
            try:
                self._execute(record)                    # type: ignore[misc]
            except Exception:                            # noqa: BLE001
                log.exception('durable lane %s: execute crashed on %s',
                              self.name, record.task_id)
            finally:
                with self._lock:
                    self._running -= 1
