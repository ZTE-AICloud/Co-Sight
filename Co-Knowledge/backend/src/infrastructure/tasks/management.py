"""统一任务管理面：查询、统计、取消、重试、优先级。

只读写 ``task_center.task``，不依赖文件/图谱运行时；取消后的领域状态同步通过
``infrastructure.tasks.registry`` 里登记的回调完成（回调失败只记日志）。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from infrastructure.db.kb import connection
from infrastructure.db.rows import rows as _rows
from infrastructure.http.pagination import page as paginate
from infrastructure.logging.logutil import log
from infrastructure.tasks import pg_queue, registry
from infrastructure.tasks.pg import TASK_TABLE
from infrastructure.tasks.types import (
    RETRYABLE_STATUSES,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RETRY,
    STATUS_RUNNING,
)
from shared.errors.api import KbConflictError, KbNotFoundError, KbValidationError

STATUSES = (
    STATUS_PENDING, STATUS_RUNNING, STATUS_RETRY, STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_ERRORS, STATUS_FAILED, STATUS_CANCELLED,
)

PRIORITY_MIN = -1000
PRIORITY_MAX = 1000
MAX_PAGE_SIZE = 200
MAX_REASON_LENGTH = 500

#: 列表不返回 payload/extra（可能很大），详情才返回；附带文件名的投影与库名。
_LIST_COLUMNS = (
    't.id, t.task_type, t.lane, t.status, t.priority, t.progress, '
    't.attempt, t.max_attempts, t.kbase_id, t.error_message, '
    't.start_time, t.finish_time, t.available_at, t.locked_by, '
    't.locked_until, t.heartbeat_at, t.cancel_requested, '
    't.cancel_requested_at, t.created_at, t.updated_at, '
    "t.payload -> 'fileHandle' ->> 'fileName' AS file_name, k.name AS kbase_name"
)
_DETAIL_COLUMNS = _LIST_COLUMNS + ', t.payload, t.extra'
_TASK_FROM = f'{TASK_TABLE} t LEFT JOIN kb_kbase k ON k.kbase_id = t.kbase_id'


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if isinstance(value, datetime) else value


def _task_dict(row: dict, *, include_payload: bool = False) -> dict[str, Any]:
    item = {
        'id': row.get('id'),
        'taskType': row.get('task_type'),
        'lane': row.get('lane'),
        'status': row.get('status'),
        'priority': int(row.get('priority') or 0),
        'progress': int(row.get('progress') or 0),
        'attempt': int(row.get('attempt') or 0),
        'maxAttempts': int(row.get('max_attempts') or 0),
        'kbaseId': row.get('kbase_id'),
        'kbaseName': row.get('kbase_name'),
        'fileName': row.get('file_name'),
        'errorMessage': row.get('error_message'),
        'startTime': _iso(row.get('start_time')),
        'finishTime': _iso(row.get('finish_time')),
        'availableAt': _iso(row.get('available_at')),
        'lockedBy': row.get('locked_by'),
        'lockedUntil': _iso(row.get('locked_until')),
        'heartbeatAt': _iso(row.get('heartbeat_at')),
        'cancelRequested': bool(row.get('cancel_requested')),
        'cancelRequestedAt': _iso(row.get('cancel_requested_at')),
        'createdAt': _iso(row.get('created_at')),
        'updatedAt': _iso(row.get('updated_at')),
    }
    if include_payload:
        item['payload'] = row.get('payload') or {}
        item['extra'] = row.get('extra') or {}
    return item


def _parse_statuses(value: Optional[str]) -> Optional[list[str]]:
    if value is None or not str(value).strip():
        return None
    result = [part.strip().upper() for part in str(value).split(',') if part.strip()]
    invalid = [part for part in result if part not in STATUSES]
    if invalid:
        raise KbValidationError(None)
    return result


def _page_params(value: int, size: int) -> tuple[int, int]:
    if value < 1 or size < 1 or size > MAX_PAGE_SIZE:
        raise KbValidationError(None)
    return value, size


def _where_clause(*, task_type: Optional[str], statuses: Optional[list[str]],
                  lane: Optional[str], kbase_id: Optional[str],
                  keyword: Optional[str], keyword_scope: str = 'tasks'
                  ) -> tuple[str, list]:
    clauses, params = [], []
    if task_type:
        clauses.append('t.task_type = %s')
        params.append(task_type)
    if statuses:
        clauses.append('t.status = ANY(%s)')
        params.append(statuses)
    if lane:
        clauses.append('t.lane = %s')
        params.append(lane)
    if kbase_id == '__none__':
        clauses.append('t.kbase_id IS NULL')
    elif kbase_id:
        clauses.append('t.kbase_id = %s')
        params.append(kbase_id)
    if keyword:
        if keyword_scope == 'kb':
            clauses.append('(t.kbase_id = %s OR k.name ILIKE %s)')
            params.extend([keyword, f'%{keyword}%'])
        else:
            clauses.append(
                "(t.id = %s OR t.kbase_id = %s OR k.name ILIKE %s OR "
                "t.payload -> 'fileHandle' ->> 'fileName' ILIKE %s)")
            params.extend([keyword, keyword, f'%{keyword}%', f'%{keyword}%'])
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    return where, params


def list_tasks(*, task_type: Optional[str] = None, status: Optional[str] = None,
               lane: Optional[str] = None, kbase_id: Optional[str] = None,
               keyword: Optional[str] = None,
               page: int = 1, size: int = 20) -> dict:
    page, size = _page_params(int(page), int(size))
    statuses = _parse_statuses(status)
    where, params = _where_clause(
        task_type=task_type, statuses=statuses, lane=lane, kbase_id=kbase_id,
        keyword=keyword)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT count(*) FROM {_TASK_FROM}{where}', params)
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f'SELECT {_LIST_COLUMNS} FROM {_TASK_FROM}{where} '
                'ORDER BY t.created_at DESC, t.id DESC LIMIT %s OFFSET %s',
                params + [size, (page - 1) * size],
            )
            items = [_task_dict(row) for row in _rows(cursor)]
    return paginate(items, total, page, size)


def list_task_groups(*, task_type: Optional[str] = None, status: Optional[str] = None,
                     lane: Optional[str] = None, kbase_id: Optional[str] = None,
                     keyword: Optional[str] = None,
                     page: int = 1, size: int = 20) -> dict:
    """按知识库聚合任务；keyword 在树模式下只匹配库 id/名称。"""
    page, size = _page_params(int(page), int(size))
    statuses = _parse_statuses(status)
    where, params = _where_clause(
        task_type=task_type, statuses=statuses, lane=lane, kbase_id=kbase_id,
        keyword=keyword, keyword_scope='kb')
    status_counts = ', '.join(
        f"count(*) FILTER (WHERE t.status = '{name}') AS {name.lower()}"
        for name in STATUSES)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT count(*) FROM (SELECT 1 FROM {_TASK_FROM}{where} '
                'GROUP BY t.kbase_id) grouped', params)
            total = int(cursor.fetchone()[0])
            cursor.execute(
                f'SELECT count(*) FROM {_TASK_FROM}{where}', params)
            task_total = int(cursor.fetchone()[0])
            cursor.execute(
                f'SELECT t.kbase_id, k.name AS kbase_name, count(*) AS total, '
                f'max(t.created_at) AS latest_created_at, {status_counts} '
                f'FROM {_TASK_FROM}{where} '
                'GROUP BY t.kbase_id, k.name '
                'ORDER BY max(t.created_at) DESC NULLS LAST, t.kbase_id '
                'LIMIT %s OFFSET %s',
                params + [size, (page - 1) * size],
            )
            items = [_group_dict(row) for row in _rows(cursor)]
    return paginate(items, total, page, size, taskTotal=task_total)


def _group_dict(row: dict) -> dict[str, Any]:
    by_status = {name: int(row.get(name.lower()) or 0) for name in STATUSES}
    return {
        'kbaseId': row.get('kbase_id'),
        'kbaseName': row.get('kbase_name'),
        'total': int(row.get('total') or 0),
        'byStatus': by_status,
        'latestCreatedAt': _iso(row.get('latest_created_at')),
    }


def get_task(task_id: str) -> dict:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT {_DETAIL_COLUMNS} FROM {_TASK_FROM} WHERE t.id = %s',
                (task_id,),
            )
            rows = _rows(cursor)
            if not rows:
                raise KbNotFoundError(None, problem_code='task_not_found')
            cursor.execute(
                'SELECT attempt, worker_id, status, error_message, '
                'started_at, finished_at FROM task_center.task_attempt '
                'WHERE task_id = %s ORDER BY attempt, id',
                (task_id,),
            )
            attempts = [_attempt_dict(row) for row in _rows(cursor)]
    item = _task_dict(rows[0], include_payload=True)
    item['attempts'] = attempts
    return item


def _attempt_dict(row: dict) -> dict[str, Any]:
    started = row.get('started_at')
    finished = row.get('finished_at')
    duration = None
    if isinstance(started, datetime) and isinstance(finished, datetime):
        duration = max(0, int((finished - started).total_seconds() * 1000))
    return {
        'attempt': int(row.get('attempt') or 0),
        'workerId': row.get('worker_id'),
        'status': row.get('status'),
        'errorMessage': row.get('error_message'),
        'startedAt': _iso(started),
        'finishedAt': _iso(finished),
        'durationMs': duration,
    }


def stats() -> dict:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT status, count(*) FROM {TASK_TABLE} GROUP BY status')
            by_status = {status: 0 for status in STATUSES}
            for status, count in cursor.fetchall():
                by_status[str(status)] = int(count)

            cursor.execute(
                f'SELECT lane, status, count(*) FROM {TASK_TABLE} '
                'GROUP BY lane, status')
            by_lane: dict[str, dict[str, int]] = {}
            for lane, status, count in cursor.fetchall():
                counts = by_lane.setdefault(
                    str(lane), {name: 0 for name in STATUSES})
                counts[str(status)] = int(count)

            cursor.execute(
                f'SELECT task_type, count(*) FROM {TASK_TABLE} GROUP BY task_type')
            by_type = {str(task_type): int(count)
                       for task_type, count in cursor.fetchall()}

            cursor.execute(
                f"SELECT COALESCE(extract(epoch FROM now() - min(created_at)), 0)::bigint "
                f"FROM {TASK_TABLE} WHERE status IN ('PENDING', 'RETRY')")
            oldest_pending = int(cursor.fetchone()[0] or 0)

            cursor.execute(
                f"SELECT count(*) FROM {TASK_TABLE} "
                "WHERE status = 'RUNNING' AND locked_until < now()")
            overdue_running = int(cursor.fetchone()[0] or 0)

    queue_depth = by_status[STATUS_PENDING] + by_status[STATUS_RETRY]
    return {
        'total': sum(by_status.values()),
        'queueDepth': queue_depth,
        'oldestPendingAgeSeconds': oldest_pending,
        'overdueRunning': overdue_running,
        'byStatus': by_status,
        'byLane': by_lane,
        'byType': by_type,
    }


def cancel_task(task_id: str, reason: Optional[str] = None) -> dict:
    text = (reason or '').strip() or 'Cancelled by user'
    if len(text) > MAX_REASON_LENGTH:
        raise KbValidationError(None)

    row = pg_queue.cancel(task_id, text)
    if row is not None:
        _run_cancel_hook(row)
        return _task_dict(row, include_payload=True)

    # 已在执行：只打取消标记，由 runner 在安全点协作中止。
    running = pg_queue.request_cancel(task_id)
    if running is not None:
        try:
            pg_queue.notify_cancel(task_id)
        except Exception:                                # noqa: BLE001
            log.warning('task cancel notify failed for %s', task_id, exc_info=True)
        return _task_dict(running, include_payload=True)

    current = pg_queue.task_status(task_id)
    if current is None:
        raise KbNotFoundError(None, problem_code='task_not_found')
    raise KbConflictError(None, problem_code='task_not_cancellable')


def retry_task(task_id: str) -> dict:
    existing = pg_queue.get(task_id)
    if existing is None:
        raise KbNotFoundError(None, problem_code='task_not_found')
    if existing.get('status') not in RETRYABLE_STATUSES:
        raise KbConflictError(None, problem_code='task_not_retryable')
    if not _retry_input_available(existing):
        raise KbConflictError(None, problem_code='task_input_expired')

    row = pg_queue.retry(task_id)
    if row is None:
        # 另一个管理请求抢先改了状态；按当前状态返回冲突。
        current = pg_queue.task_status(task_id)
        if current is None:
            raise KbNotFoundError(None, problem_code='task_not_found')
        raise KbConflictError(None, problem_code='task_not_retryable')

    _run_retry_hook(row)
    # RETRY 后通知对应车道；跨进程靠 LISTEN/NOTIFY，本进程由监听线程转发。
    try:
        pg_queue.notify(row['lane'])
    except Exception:                                    # noqa: BLE001
        log.warning('task retry notify failed for lane %s', row.get('lane'),
                    exc_info=True)
    return _task_dict(row, include_payload=True)


def _retry_input_available(row: dict) -> bool:
    """图谱任务的输入是临时目录/临时 zip；失败执行后可能已被清理。"""
    task_type = row.get('task_type')
    payload = row.get('payload') or {}
    if task_type == 'GRAPH_EXTRACT':
        path = payload.get('tmpDir')
        return bool(path) and os.path.isdir(path)
    if task_type == 'GRAPH_IMPORT':
        path = payload.get('zipPath')
        return bool(path) and os.path.isfile(path)
    return True


def set_priority(task_id: str, priority: Any) -> dict:
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise KbValidationError(None)
    if priority < PRIORITY_MIN or priority > PRIORITY_MAX:
        raise KbValidationError(None)

    row = pg_queue.set_priority(task_id, priority)
    if row is None:
        current = pg_queue.task_status(task_id)
        if current is None:
            raise KbNotFoundError(None, problem_code='task_not_found')
        raise KbConflictError(None, problem_code='task_not_queued')
    return _task_dict(row, include_payload=True)


def _run_cancel_hook(row: dict) -> None:
    hook = registry.cancel_hook_for(row['task_type'])
    if hook is None:
        return
    try:
        hook(row)
    except Exception:                                    # noqa: BLE001
        log.warning('task cancel hook failed: task=%s type=%s',
                    row.get('id'), row.get('task_type'), exc_info=True)


def _run_retry_hook(row: dict) -> None:
    hook = registry.retry_hook_for(row['task_type'])
    if hook is None:
        return
    try:
        hook(row)
    except Exception:                                    # noqa: BLE001
        log.warning('task retry hook failed: task=%s type=%s',
                    row.get('id'), row.get('task_type'), exc_info=True)


__all__ = [
    'STATUSES', 'cancel_task', 'get_task', 'list_task_groups', 'list_tasks',
    'retry_task', 'set_priority', 'stats',
]
