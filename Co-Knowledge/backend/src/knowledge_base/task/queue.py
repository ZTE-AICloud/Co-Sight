"""导入任务的进程内队列。

结构：``queue.Queue(2000)`` + ``task_id -> FileTask`` 内存表 + ``kb_import_task`` 持久化。

**刻意保留「重启不重投」**：只起 worker，
不把库里的 PENDING/RUNNING 重新入队。进程挂掉后那些行变成「查得到但跑不了」的僵尸记录——
改掉它是行为变更。

几个注意的细节：
* 队列容量 **2000**、最大重试 **3**（写死在代码里，yml 覆盖不了）
* ``persistTask`` 只在 submit 时 insert；之后只 update ``status`` + ``updated_at``
* ``related_identifier_id`` 是 ``bpchar(32)``，超长要截断
* 从库里恢复的任务**只有 fileId，没有 file_handle**
"""

from __future__ import annotations

import queue
import threading
from datetime import datetime
from typing import Optional

from infrastructure.db.kb import connection
from knowledge_base.task.wrapper import (
    ACTIVE_STATUSES,
    TASK_TYPE_FILE_IMPORT,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRY,
    STATUS_RUNNING,
    FileTask,
    parse_status,
)
from infrastructure.logging.logutil import log

QUEUE_CAPACITY = 2000
MAX_RETRY_COUNT = 3
POLL_TIMEOUT_SECONDS = 5


def _to_millis(value: Optional[datetime]) -> Optional[datetime]:
    """把微秒截到毫秒。

    只用在**从库恢复**的路径上：毫秒以下的精度在持久化映射时就丢了。
    内存里的任务不截（两边都是各自的 ``now()``，本来就不等值）。
    """
    if value is None:
        return None
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class FileTaskQueue:
    """进程内任务队列 + ``kb_import_task`` 持久化。"""

    def __init__(self, capacity: int = QUEUE_CAPACITY,
                 max_retry_count: int = MAX_RETRY_COUNT):
        self._queue: queue.Queue = queue.Queue(maxsize=capacity)
        self._tasks: dict[str, FileTask] = {}
        self._lock = threading.Lock()
        self._shutdown = False
        self.capacity = capacity
        self.max_retry_count = max_retry_count

    # ------------------------------------------------------------------
    # 提交 / 取任务
    # ------------------------------------------------------------------

    def submit_task(self, file_handle: dict) -> str:
        """入队并落 ``kb_import_task``。队满或已关闭都**显式抛错**。"""
        with self._lock:
            if self._shutdown:
                raise RuntimeError('Queue is shutdown, cannot accept new tasks')
            task = FileTask(task_id=FileTask.new_task_id(), file_handle=file_handle,
                            max_retry_count=self.max_retry_count)
            try:
                self._queue.put_nowait(task)
            except queue.Full as error:
                raise RuntimeError('Task queue is full, cannot accept new task') from error
            self._tasks[task.task_id] = task
        self._persist_task(task)
        return task.task_id

    def poll_task(self, timeout: int = POLL_TIMEOUT_SECONDS) -> Optional[FileTask]:
        """取一个任务并标记 RUNNING。已关闭时直接返回 None。"""
        if self._shutdown:
            return None
        try:
            task = self._queue.get(timeout=timeout)
        except queue.Empty:
            return None
        task.mark_as_running()
        with self._lock:
            self._tasks[task.task_id] = task
        self._persist_task_status(task)
        return task

    def update_task_status(self, task: FileTask) -> None:
        """终态时移出内存表（COMPLETED）；FAILED 保留，供 ``/file-tasks/failed`` 查询。"""
        with self._lock:
            if task.status == STATUS_COMPLETED:
                self._tasks.pop(task.task_id, None)
            else:
                self._tasks[task.task_id] = task
        self._persist_task_status(task)

    def resubmit_task(self, task: FileTask) -> bool:
        """重投队尾。队满或已关闭返回 False。"""
        if self._shutdown:
            return False
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            return False
        task.status = STATUS_PENDING
        with self._lock:
            self._tasks[task.task_id] = task
        self._persist_task_status(task)
        return True

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[FileTask]:
        """内存优先；不在内存则从 ``kb_import_task`` 恢复（**不恢复 file_handle**）。"""
        with self._lock:
            task = self._tasks.get(task_id)
        return task if task is not None else self._load_task_from_db(task_id)

    def statistics(self) -> dict:
        with self._lock:
            tasks = list(self._tasks.values())
        # 键序固定（对 JSON 语义无影响，便于对照）
        return {
            'pendingCount': sum(1 for t in tasks if t.status == STATUS_PENDING),
            'runningCount': sum(1 for t in tasks if t.status == STATUS_RUNNING),
            # 已完成的不在内存表里，只能查库
            'completedCount': self._count_completed_tasks(),
            'failedCount': sum(1 for t in tasks if t.status == STATUS_FAILED),
            'retryCount': sum(1 for t in tasks if t.status == STATUS_RETRY),
            'queueSize': self._queue.qsize(),
            'queueCapacity': self.capacity,
            'shutdown': self._shutdown,
        }

    def failed_tasks(self) -> list[FileTask]:
        """**只统计内存里 FAILED 的**（重启后该接口返回空数组）。"""
        with self._lock:
            return [t for t in self._tasks.values() if t.status == STATUS_FAILED]

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """只置标志 + 记日志，**不改库、不重投**。"""
        with self._lock:
            self._shutdown = True
            pending = [t.task_id for t in self._tasks.values()
                       if t.status in ACTIVE_STATUSES]
            if pending:
                log.warning('%d import task(s) still active at shutdown: %s',
                            len(pending), pending)
        log.info('file task queue shut down')

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    # ------------------------------------------------------------------
    # kb_import_task
    # ------------------------------------------------------------------

    def _persist_task(self, task: FileTask) -> None:
        """只在 submit 时 insert；异常只记日志。"""
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        'INSERT INTO kb_import_task (id, task_type, related_identifier_id, '
                        "status) VALUES (%s, %s, %s, %s) "
                        'ON CONFLICT (id) DO NOTHING',
                        (task.task_id, TASK_TYPE_FILE_IMPORT,
                         task.related_identifier_id, task.status),
                    )
        except Exception:
            log.warning('persist task %s failed', task.task_id, exc_info=True)

    def _persist_task_status(self, task: FileTask) -> None:
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        'UPDATE kb_import_task SET status = %s, updated_at = NOW() WHERE id = %s',
                        (task.status, task.task_id),
                    )
        except Exception:
            log.warning('persist task status %s failed', task.task_id, exc_info=True)

    def _load_task_from_db(self, task_id: str) -> Optional[FileTask]:
        """``load_task_from_db``：已完成任务被移出内存、或应用重启后仍能查到详情。

        三个容易漏的点，都会让 ``/file-tasks/{id}`` 的输出不对：

        * ``fileId`` 是**恢复得出来的**（来自 ``related_identifier_id``），
          只有 ``fileName`` 恢复不出来。早先这里只 select 了三列，``fileId`` 就丢了。
        * ``createTime`` 取库里的 ``created_at``，**不是** ``now()``。
        * 时间要**截到毫秒**：库里那两列是 ``timestamp``（微秒），直接透传会多出
          3 位小数。
        """
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    'SELECT id, status, related_identifier_id, created_at, '
                    'updated_at FROM kb_import_task WHERE id = %s',
                    (task_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        _task_id, raw_status, related_id, created_at, last_updated = row
        task = FileTask(
            task_id=_task_id,
            # 只有 fileId，没有 fileName
            file_handle={'fileId': related_id} if related_id else None,
            status=parse_status(raw_status),
            create_time=_to_millis(created_at),
            max_retry_count=0,     # 恢复出来的任务不重试
        )
        # 只有终态才把 updated_at 当 endTime
        if task.status in (STATUS_COMPLETED, STATUS_FAILED):
            task.end_time = _to_millis(last_updated)
        return task

    def _count_completed_tasks(self) -> int:
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM kb_import_task WHERE task_type = %s "
                        "AND status = %s",
                        (TASK_TYPE_FILE_IMPORT, STATUS_COMPLETED),
                    )
                    return int(cursor.fetchone()[0])
        except Exception:
            log.warning('count completed tasks failed', exc_info=True)
            return 0
