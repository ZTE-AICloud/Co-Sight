"""文件导入任务的门面：统一引擎 + ``task`` 表持久化 + 内存任务表。

执行已下沉到 ``infrastructure.tasks``（``file_import`` 车道，5 个 worker）。
生产运行时使用 **DB 队列**（``queue_mode='db'``）：worker 用
``FOR UPDATE SKIP LOCKED`` 从 ``task_center.task`` 认领，带租约/心跳/回收；
进程重启后继续处理库里的 ``PENDING/RETRY``。单测默认 ``memory``，不连库。

本类保留原有公开方法（``submit_task`` / ``get_task`` / ``statistics`` /
``failed_tasks`` / ``shutdown``），供上传、重试与监控接口继续使用。

任务行写**统一任务表** ``task_center.task``（``task_type='FILE_IMPORT'``）。

几个保持不变的语义：

* 队列容量 **2000**、最大重试 **3**（总执行 1+3 次）
* ``persistTask`` 只在 submit 时 insert；之后只 update ``status`` + ``updated_at``
* ``file_id`` 是 ``char(32)``，超长要截断
* 从库里恢复的任务**只有 fileId，没有 file_handle**
* **重启不重投**：引擎不做恢复，库里的 PENDING/RUNNING 行保持原样
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Optional

from infrastructure.db.kb import connection
from infrastructure.tasks import (
    REQUEUE_FAILED_MESSAGE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRY,
    STATUS_RUNNING,
    TaskEngine,
    TaskKind,
    TaskRecord,
    TaskRejectedError,
)
from infrastructure.tasks import pg_queue
from infrastructure.tasks.pg import TASK_TABLE
from knowledge_base.task import executor as file_runner
from knowledge_base.task.wrapper import (
    ACTIVE_STATUSES,
    TASK_TYPE_FILE_IMPORT,
    FileTask,
    parse_status,
)
from infrastructure.logging.logutil import log

QUEUE_CAPACITY = 2000
MAX_RETRY_COUNT = 3

FILE_IMPORT_KIND = 'file_import'
FILE_IMPORT_LANE = 'file_import'


def _to_millis(value: Optional[datetime]) -> Optional[datetime]:
    """把微秒截到毫秒。

    只用在**从库恢复**的路径上：毫秒以下的精度在持久化映射时就丢了。
    内存里的任务不截（两边都是各自的 ``now()``，本来就不等值）。
    """
    if value is None:
        return None
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _format_failure_message(error_message: Optional[str], retry_count: int) -> str:
    """与内存路径 ``FileTask.failure_message`` 保持同一文案。"""
    if error_message == REQUEUE_FAILED_MESSAGE:
        return error_message
    return 'Task failed after %d retries. Error: %s' % (
        retry_count, error_message or 'null')


def _cancel_file_task(row: dict) -> None:
    """取消排队中的文件任务后，把文件行也落成失败，避免一直显示「处理中」。"""
    payload = row.get('payload') or {}
    file_id = payload.get('fileId') or (payload.get('fileHandle') or {}).get('fileId')
    if not file_id:
        return
    from knowledge_base.repository import directory as directory_store

    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            directory_store.update_file_status(cursor, file_id, 2, 'Task cancelled')


def _retry_file_task(row: dict) -> None:
    """重试文件任务后，把文件行从失败（2）退回待处理（0）并清空失败原因。"""
    payload = row.get('payload') or {}
    file_id = payload.get('fileId') or (payload.get('fileHandle') or {}).get('fileId')
    if not file_id:
        return
    from knowledge_base.repository import directory as directory_store

    with directory_store.connection() as conn:
        with conn.cursor() as cursor:
            directory_store.claim_file_for_retry(cursor, file_id)


class FileTaskQueue:
    """文件导入任务门面；执行由统一任务引擎的车道负责。"""

    def __init__(self, capacity: int = QUEUE_CAPACITY,
                 max_retry_count: int = MAX_RETRY_COUNT,
                 engine: Optional[TaskEngine] = None,
                 queue_mode: str = 'memory'):
        self.capacity = capacity
        self.max_retry_count = max_retry_count
        self.queue_mode = queue_mode
        self._tasks: dict[str, FileTask] = {}
        self._lock = threading.Lock()
        self._shutdown = False

        self._engine = engine or TaskEngine()
        self._lane = self._engine.register_lane(
            FILE_IMPORT_LANE, workers=file_runner.WORKER_THREAD_COUNT,
            capacity=capacity, mode=queue_mode)
        self._store = _FileImportStore(self)
        self._engine.register_kind(
            TaskKind(name=FILE_IMPORT_KIND, lane=FILE_IMPORT_LANE,
                     max_attempts=max_retry_count + 1,
                     retry_delay=file_runner.retry_delay,
                     queue_mode=queue_mode, persist_type=TASK_TYPE_FILE_IMPORT,
                     cancel_hook=_cancel_file_task,
                     retry_hook=_retry_file_task),
            file_runner.run_file_task, self._store)

    def start(self) -> None:
        """启动车道（DB 模式会开始认领库里已有的 PENDING/RETRY 任务）。"""
        self._engine.start()

    # ------------------------------------------------------------------
    # 提交
    # ------------------------------------------------------------------

    def submit_task(self, file_handle: dict) -> str:
        """入队并落 ``task_center.task``。队满或已关闭都**显式抛错**。"""
        with self._lock:
            if self._shutdown:
                raise RuntimeError('Queue is shutdown, cannot accept new tasks')
            task = FileTask(task_id=FileTask.new_task_id(), file_handle=file_handle,
                            max_retry_count=self.max_retry_count)
            self._tasks[task.task_id] = task

        if self.queue_mode == 'db':
            payload = {'fileHandle': file_handle,
                       'fileId': task.related_identifier_id}
        else:
            payload = {'task': task}
        try:
            self._engine.submit(FILE_IMPORT_KIND, payload, task_id=task.task_id)
        except TaskRejectedError as error:
            with self._lock:
                self._tasks.pop(task.task_id, None)
            if self._engine.is_shutdown:
                raise RuntimeError('Queue is shutdown, cannot accept new tasks') from error
            raise RuntimeError('Task queue is full, cannot accept new task') from error
        return task.task_id

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[FileTask]:
        """内存优先；不在内存则从 ``task_center.task`` 恢复（**不恢复 file_handle**）。"""
        with self._lock:
            task = self._tasks.get(task_id)
        return task if task is not None else self._load_task_from_db(task_id)

    def statistics(self) -> dict:
        if self.queue_mode == 'db':
            try:
                counts = pg_queue.count_by_lane(FILE_IMPORT_LANE)
            except Exception:                              # noqa: BLE001
                log.warning('count file import tasks failed', exc_info=True)
                counts = {}
            pending = counts.get('PENDING', 0)
            retry = counts.get('RETRY', 0)
            return {
                'pendingCount': pending,
                'runningCount': counts.get('RUNNING', 0),
                'completedCount': counts.get('COMPLETED', 0),
                'failedCount': counts.get('FAILED', 0),
                'retryCount': retry,
                'queueSize': pending + retry,
                'queueCapacity': self.capacity,
                'shutdown': self._shutdown,
            }
        with self._lock:
            tasks = list(self._tasks.values())
        lane_stats = self._engine.stats().get(FILE_IMPORT_LANE)
        # 键序固定（对 JSON 语义无影响，便于对照）
        return {
            'pendingCount': sum(1 for t in tasks if t.status == STATUS_PENDING),
            'runningCount': sum(1 for t in tasks if t.status == STATUS_RUNNING),
            # 已完成的不在内存表里，只能查库
            'completedCount': self._count_completed_tasks(),
            'failedCount': sum(1 for t in tasks if t.status == STATUS_FAILED),
            'retryCount': sum(1 for t in tasks if t.status == STATUS_RETRY),
            'queueSize': lane_stats.queued if lane_stats is not None else 0,
            'queueCapacity': self.capacity,
            'shutdown': self._shutdown,
        }

    def failed_tasks(self) -> list[FileTask]:
        """失败任务：DB 模式查库（重启后仍然可见），内存模式查内存表。"""
        if self.queue_mode == 'db':
            return self._load_failed_tasks_from_db()
        with self._lock:
            return [t for t in self._tasks.values() if t.status == STATUS_FAILED]

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """置标志、记录活跃任务，然后关停引擎车道。"""
        with self._lock:
            self._shutdown = True
            pending = [t.task_id for t in self._tasks.values()
                       if t.status in ACTIVE_STATUSES]
            if pending:
                log.warning('%d import task(s) still active at shutdown: %s',
                            len(pending), pending)
        self._engine.shutdown()
        log.info('file task queue shut down')

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    # ------------------------------------------------------------------
    # task_center.task
    # ------------------------------------------------------------------

    def _persist_task(self, task: FileTask) -> None:
        """只在 submit 时 insert；异常只记日志。"""
        file_handle = task.file_handle or {}
        if self.queue_mode == 'db':
            payload = json.dumps({
                'fileId': task.related_identifier_id,
                'fileHandle': file_handle,
            }, ensure_ascii=False, default=str)
        elif task.related_identifier_id:
            payload = json.dumps({'fileId': task.related_identifier_id})
        else:
            payload = '{}'
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f'INSERT INTO {TASK_TABLE} '
                        '(id, task_type, lane, status, progress, attempt, max_attempts, '
                        'kbase_id, payload) '
                        'VALUES (%s, %s, %s, %s, 0, 1, %s, %s, %s::jsonb) '
                        'ON CONFLICT (id) DO NOTHING',
                        (task.task_id, TASK_TYPE_FILE_IMPORT, FILE_IMPORT_LANE,
                         task.status, self.max_retry_count + 1,
                         file_handle.get('kbaseId'), payload),
                    )
        except Exception:
            log.warning('persist task %s failed', task.task_id, exc_info=True)

    def _persist_task_status(self, task: FileTask,
                             extra: Optional[dict] = None) -> None:
        progress = 100 if task.status == STATUS_COMPLETED else 0
        terminal = task.status in (STATUS_COMPLETED, STATUS_FAILED)
        sets = ['status = %s', 'progress = %s', 'attempt = %s',
                'error_message = %s', 'start_time = COALESCE(start_time, %s)',
                'finish_time = %s', 'updated_at = NOW()']
        params: list = [task.status, progress, task.retry_count + 1,
                        task.error_message, task.start_time,
                        task.end_time if terminal else None]
        if extra is not None:
            sets.append("extra = COALESCE(extra, '{}'::jsonb) || %s::jsonb")
            params.append(json.dumps(extra, ensure_ascii=False, default=str))
        params.extend([task.task_id, TASK_TYPE_FILE_IMPORT])
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f'UPDATE {TASK_TABLE} SET {", ".join(sets)} '
                        'WHERE id = %s AND task_type = %s',
                        params,
                    )
        except Exception:
            log.warning('persist task status %s failed', task.task_id, exc_info=True)

    def _delete_task(self, task_id: str) -> None:
        """提交被拒时撤销刚 insert 的行。"""
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f'DELETE FROM {TASK_TABLE} WHERE id = %s AND task_type = %s',
                        (task_id, TASK_TYPE_FILE_IMPORT))
        except Exception:
            log.warning('delete rejected task %s failed', task_id, exc_info=True)

    def _load_failed_tasks_from_db(self) -> list[FileTask]:
        try:
            with connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f'SELECT id, payload, attempt, max_attempts, error_message, '
                        f'created_at, start_time, finish_time, updated_at '
                        f"FROM {TASK_TABLE} WHERE task_type = %s AND status = 'FAILED' "
                        'ORDER BY updated_at DESC',
                        (TASK_TYPE_FILE_IMPORT,),
                    )
                    rows = cursor.fetchall()
        except Exception:
            log.warning('load failed tasks failed', exc_info=True)
            return []

        result: list[FileTask] = []
        for (task_id, payload, attempt, max_attempts, error_message,
             created_at, start_time, finish_time, updated_at) in rows:
            payload = payload or {}
            file_handle = payload.get('fileHandle')
            if not file_handle:
                file_id = payload.get('fileId')
                file_handle = {'fileId': file_id} if file_id else None
            retry_count = max(0, int(attempt or 1) - 1)
            task = FileTask(
                task_id=task_id,
                file_handle=file_handle,
                status=STATUS_FAILED,
                retry_count=retry_count,
                max_retry_count=max(0, int(max_attempts or 1) - 1),
                create_time=_to_millis(created_at),
                error_message=_format_failure_message(error_message, retry_count),
            )
            task.start_time = _to_millis(start_time)
            task.end_time = _to_millis(finish_time or updated_at)
            result.append(task)
        return result

    def _load_task_from_db(self, task_id: str) -> Optional[FileTask]:
        """``load_task_from_db``：已完成任务被移出内存、或应用重启后仍能查到详情。

        三个容易漏的点，都会让 ``/file-tasks/{id}`` 的输出不对：

        * ``fileId`` 是**恢复得出来的**（来自 ``file_id``），
          只有 ``fileName`` 恢复不出来。早先这里只 select 了三列，``fileId`` 就丢了。
        * ``createTime`` 取库里的 ``created_at``，**不是** ``now()``。
        * 时间要**截到毫秒**：库里那两列是 ``timestamp``（微秒），直接透传会多出
          3 位小数。
        """
        with connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f'SELECT id, status, payload, attempt, max_attempts, error_message, '
                    f'created_at, start_time, finish_time, updated_at '
                    f'FROM {TASK_TABLE} WHERE id = %s AND task_type = %s',
                    (task_id, TASK_TYPE_FILE_IMPORT),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        (_task_id, raw_status, payload, attempt, max_attempts, error_message,
         created_at, start_time, finish_time, last_updated) = row
        payload = payload or {}
        file_handle = payload.get('fileHandle')
        if not file_handle:
            file_id = payload.get('fileId')
            file_handle = {'fileId': file_id} if file_id else None
        if self.queue_mode == 'db':
            retry_count = max(0, int(attempt or 1) - 1)
            task = FileTask(
                task_id=_task_id,
                file_handle=file_handle,
                status=parse_status(raw_status),
                retry_count=retry_count,
                max_retry_count=max(0, int(max_attempts or 1) - 1),
                create_time=_to_millis(created_at),
                error_message=error_message,
            )
            task.start_time = _to_millis(start_time)
            if task.status in (STATUS_COMPLETED, STATUS_FAILED):
                task.end_time = _to_millis(finish_time or last_updated)
            if task.status == STATUS_FAILED:
                task.error_message = _format_failure_message(error_message, retry_count)
        else:
            task = FileTask(
                task_id=_task_id,
                file_handle=file_handle,
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
                        f'SELECT count(*) FROM {TASK_TABLE} WHERE task_type = %s '
                        'AND status = %s',
                        (TASK_TYPE_FILE_IMPORT, STATUS_COMPLETED),
                    )
                    return int(cursor.fetchone()[0])
        except Exception:
            log.warning('count completed tasks failed', exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # 引擎状态 → FileTask
    # ------------------------------------------------------------------

    def _sync_task(self, task: FileTask, record: TaskRecord,
                   persist: bool = True) -> None:
        """把引擎的状态投影回 ``FileTask``；DB 模式由队列层负责持久化。"""
        task.status = record.status
        task.retry_count = max(0, record.attempt - 1)
        task.start_time = record.start_time
        task.error_message = record.error_message

        if record.status == STATUS_COMPLETED:
            task.end_time = record.end_time
        elif record.status == STATUS_CANCELLED:
            task.end_time = record.end_time
            task.error_message = record.error_message or 'Task cancelled'
        elif record.status == STATUS_FAILED:
            task.end_time = record.end_time
            if record.error_message == REQUEUE_FAILED_MESSAGE:
                # 原实现这条分支就是 markAsFailed('Failed to resubmit task: ...')，
                # 不再套「Task failed after N retries」。
                task.error_message = REQUEUE_FAILED_MESSAGE
            else:
                task.error_message = 'Task failed after %d retries. Error: %s' % (
                    task.retry_count, record.error_message or 'null')

        with self._lock:
            if record.status == STATUS_COMPLETED:
                self._tasks.pop(task.task_id, None)
            else:
                self._tasks[task.task_id] = task
        if persist:
            if record.extra:
                self._persist_task_status(task, extra=record.extra)
            else:
                self._persist_task_status(task)

    def _discard_task(self, record: TaskRecord) -> None:
        with self._lock:
            self._tasks.pop(record.task_id, None)
        self._delete_task(record.task_id)


class _FileImportStore:
    """引擎与 ``FileTaskQueue`` 之间的持久化适配器。"""

    def __init__(self, queue: FileTaskQueue):
        self._queue = queue

    def _task_for(self, record: TaskRecord) -> FileTask:
        task = record.payload.get('task')
        if task is not None:
            return task
        with self._queue._lock:
            task = self._queue._tasks.get(record.task_id)
        if task is not None:
            return task
        handle = record.payload.get('fileHandle') or {}
        return FileTask(task_id=record.task_id, file_handle=handle,
                        max_retry_count=self._queue.max_retry_count)

    def on_submit(self, record: TaskRecord) -> None:
        self._queue._persist_task(self._task_for(record))

    def on_change(self, record: TaskRecord) -> None:
        self._queue._sync_task(
            self._task_for(record), record,
            persist=self._queue.queue_mode != 'db')

    def on_reject(self, record: TaskRecord) -> None:
        self._queue._discard_task(record)

    def load(self, task_id: str) -> Optional[TaskRecord]:
        return None
