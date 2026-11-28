"""统一任务表的持久化队列操作：认领、续租、完成、重排、失败、回收。

所有 worker 共享同一张 ``task_center.task``；认领用 ``FOR UPDATE SKIP LOCKED``
保证多 worker / 多实例下同一行只被一个执行者拿到。租约（``locked_until``）用于
执行者崩溃后的回收：过期 RUNNING 会被 ``reclaim_expired`` 放回 PENDING（或按
``max_attempts`` 判 FAILED）。

注意：这是 **at-least-once** 语义。任务 runner 必须能承受崩溃后重跑。
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from infrastructure.db.kb import connection
from infrastructure.db.rows import rows as _rows
from infrastructure.tasks.pg import TASK_TABLE

#: 默认租约时长。长任务（抽图）需要 runner 侧定期续租。
DEFAULT_LEASE_SECONDS = 60

#: 提交任务后的唤醒通道；payload 是 lane 名。
NOTIFY_CHANNEL = 'task_center_task'
#: 取消 RUNNING 任务的通道；payload 是 taskId。
CANCEL_NOTIFY_CHANNEL = 'task_center_cancel'


def notify(lane: str) -> None:
    """提交后 NOTIFY 对应车道；跨实例 worker 靠它立即醒来，轮询只是兜底。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT pg_notify(%s, %s)', (NOTIFY_CHANNEL, lane))


def notify_cancel(task_id: str) -> None:
    """通知各实例：某条 RUNNING 任务已请求取消。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT pg_notify(%s, %s)',
                           (CANCEL_NOTIFY_CHANNEL, task_id))


def listen_connection():
    """建立一条专用的 LISTEN 连接（autocommit，不占用连接池）。"""
    import psycopg2
    from infrastructure.db.connection_info import get_db_conn_info
    from infrastructure.db.kb import get_kbase_db_name

    info = dict(get_db_conn_info())
    info.pop('driver', None)
    database = info.pop('database', get_kbase_db_name())
    conn = psycopg2.connect(database=database, connect_timeout=2, **info)
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    with conn.cursor() as cursor:
        cursor.execute(f'LISTEN {NOTIFY_CHANNEL}')
        cursor.execute(f'LISTEN {CANCEL_NOTIFY_CHANNEL}')
    return conn


def claim(lane: str, task_types: Iterable[str], worker_id: str,
          lease_seconds: int = DEFAULT_LEASE_SECONDS) -> Optional[dict]:
    """认领一条可执行任务；没有则返回 None。

    认领即把行置为 RUNNING 并加租约。``status IN ('PENDING','RETRY')`` 都会
    被认领；``RETRY`` 的 ``available_at`` 控制最早可认领时间。
    """
    types = list(task_types)
    if not types:
        return None
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                WITH candidate AS (
                    SELECT id
                    FROM {TASK_TABLE}
                    WHERE lane = %s
                      AND task_type = ANY(%s)
                      AND status IN ('PENDING', 'RETRY')
                      AND available_at <= now()
                    ORDER BY priority DESC, created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE {TASK_TABLE} t
                SET status = 'RUNNING',
                    locked_by = %s,
                    locked_until = now() + make_interval(secs => %s),
                    heartbeat_at = now(),
                    start_time = COALESCE(start_time, now()),
                    updated_at = now()
                FROM candidate c
                WHERE t.id = c.id
                RETURNING t.*
                """,
                (lane, types, worker_id, lease_seconds),
            )
            claimed = _rows(cursor)
            return claimed[0] if claimed else None


def heartbeat(task_id: str, worker_id: str,
              lease_seconds: int = DEFAULT_LEASE_SECONDS) -> bool:
    """续租；只有当前认领者且仍 RUNNING 时才生效。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TASK_TABLE} '
                'SET locked_until = now() + make_interval(secs => %s), '
                'heartbeat_at = now(), updated_at = now() '
                "WHERE id = %s AND locked_by = %s AND status = 'RUNNING'",
                (lease_seconds, task_id, worker_id),
            )
            return cursor.rowcount > 0


def release(task_id: str, worker_id: str) -> bool:
    """释放租约但**不改状态**（runner 自己管理状态时用）。

    ⚠️ 不能要求 ``status='RUNNING'``：runner 通常先把状态写成
    COMPLETED/FAILED，再交回引擎释放租约；带状态条件会导致锁永远留着。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TASK_TABLE} '
                'SET locked_by = NULL, locked_until = NULL, heartbeat_at = NULL, '
                'updated_at = now() '
                'WHERE id = %s AND locked_by = %s',
                (task_id, worker_id),
            )
            return cursor.rowcount > 0


def complete(task_id: str, worker_id: str, progress: int = 100,
            extra: Optional[dict[str, Any]] = None) -> bool:
    """成功完成并释放租约。

    ``extra`` 是 runner 通过 ``TaskContext.set_result`` 收集的结果摘要；
    传入时与已有值合并（不覆盖 runner 先前写入的字段）。
    """
    sets = [
        "status = 'COMPLETED'",
        'progress = %s',
        'error_message = NULL',
        'finish_time = now()',
        'locked_by = NULL',
        'locked_until = NULL',
        'heartbeat_at = NULL',
        'updated_at = now()',
    ]
    params: list[Any] = [progress]
    if extra is not None:
        sets.append("extra = COALESCE(extra, '{}'::jsonb) || %s::jsonb")
        params.append(json.dumps(extra, ensure_ascii=False, default=str))
    params.extend([task_id, worker_id])
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TASK_TABLE} SET {", ".join(sets)} '
                "WHERE id = %s AND locked_by = %s AND status = 'RUNNING'",
                params,
            )
            return cursor.rowcount > 0


def reschedule(task_id: str, worker_id: str, attempt: int, delay_seconds: float,
               error_message: Optional[str]) -> bool:
    """重排为 RETRY，``available_at = now() + delay``。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TASK_TABLE} '
                "SET status = 'RETRY', attempt = %s, "
                'available_at = now() + make_interval(secs => %s), '
                'error_message = %s, locked_by = NULL, locked_until = NULL, '
                'heartbeat_at = NULL, updated_at = now() '
                "WHERE id = %s AND locked_by = %s AND status = 'RUNNING'",
                (attempt, delay_seconds, error_message, task_id, worker_id),
            )
            return cursor.rowcount > 0


def fail(task_id: str, worker_id: str, error_message: Optional[str]) -> bool:
    """判失败并释放租约。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TASK_TABLE} '
                "SET status = 'FAILED', error_message = %s, finish_time = now(), "
                'locked_by = NULL, locked_until = NULL, heartbeat_at = NULL, '
                'updated_at = now() '
                "WHERE id = %s AND locked_by = %s AND status = 'RUNNING'",
                (error_message, task_id, worker_id),
            )
            return cursor.rowcount > 0


def pending_count(lane: str) -> int:
    """车道上还没被认领的任务数（PENDING + RETRY），用于准入判断。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT count(*) FROM {TASK_TABLE} '
                "WHERE lane = %s AND status IN ('PENDING', 'RETRY')",
                (lane,),
            )
            return int(cursor.fetchone()[0])


def get(task_id: str) -> Optional[dict]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT * FROM {TASK_TABLE} WHERE id = %s', (task_id,))
            rows = _rows(cursor)
            return rows[0] if rows else None


def task_status(task_id: str) -> Optional[str]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT status FROM {TASK_TABLE} WHERE id = %s', (task_id,))
            row = cursor.fetchone()
            return row[0] if row else None


def cancel(task_id: str, reason: str = 'Cancelled by user') -> Optional[dict]:
    """取消尚未开始的任务；RUNNING 不在此处理（调用方回 409）。

    ``PENDING``/``RETRY`` 与 worker 的认领是两条带状态条件的 UPDATE，
    谁先成功谁生效：认领赢 → 取消方看到 RUNNING 并拒绝；取消赢 → 认领跳过。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {TASK_TABLE}
                    SET status = 'CANCELLED',
                        cancel_requested = true,
                        cancel_requested_at = now(),
                        finish_time = now(),
                        available_at = now(),
                        error_message = %s,
                        locked_by = NULL,
                        locked_until = NULL,
                        heartbeat_at = NULL,
                        updated_at = now()
                    WHERE id = %s AND status IN ('PENDING', 'RETRY')
                    RETURNING *""",
                (reason, task_id),
            )
            rows = _rows(cursor)
            return rows[0] if rows else None


def request_cancel(task_id: str) -> Optional[dict]:
    """给 RUNNING 任务打取消标记；执行者看到后走协作式中止。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {TASK_TABLE}
                    SET cancel_requested = true,
                        cancel_requested_at = now(),
                        updated_at = now()
                    WHERE id = %s AND status = 'RUNNING'
                    RETURNING *""",
                (task_id,),
            )
            rows = _rows(cursor)
            return rows[0] if rows else None


def cancel_requested_ids(task_ids: Iterable[str]) -> list[str]:
    """心跳兜底：返回这些任务里已被请求取消的 id。"""
    ids = list(task_ids)
    if not ids:
        return []
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT id FROM {TASK_TABLE} '
                "WHERE id = ANY(%s) AND status = 'RUNNING' AND cancel_requested",
                (ids,),
            )
            return [row[0] for row in cursor.fetchall()]


def cancel_running(task_id: str, worker_id: str,
                   reason: str = 'Cancelled by user') -> bool:
    """执行者确认中止后落 CANCELLED；带 locked_by 条件做围栏。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {TASK_TABLE}
                    SET status = 'CANCELLED',
                        finish_time = now(),
                        error_message = %s,
                        cancel_requested = true,
                        cancel_requested_at = COALESCE(cancel_requested_at, now()),
                        locked_by = NULL,
                        locked_until = NULL,
                        heartbeat_at = NULL,
                        updated_at = now()
                    WHERE id = %s AND locked_by = %s AND status = 'RUNNING'""",
                (reason, task_id, worker_id),
            )
            return cursor.rowcount > 0


def retry(task_id: str) -> Optional[dict]:
    """把 FAILED/CANCELLED 重新放回 PENDING（attempt 从 1 重算）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {TASK_TABLE}
                    SET status = 'PENDING',
                        attempt = 1,
                        progress = 0,
                        error_message = NULL,
                        start_time = NULL,
                        finish_time = NULL,
                        available_at = now(),
                        cancel_requested = false,
                        cancel_requested_at = NULL,
                        locked_by = NULL,
                        locked_until = NULL,
                        heartbeat_at = NULL,
                        updated_at = now()
                    WHERE id = %s AND status IN ('FAILED', 'CANCELLED')
                    RETURNING *""",
                (task_id,),
            )
            rows = _rows(cursor)
            return rows[0] if rows else None


def set_priority(task_id: str, priority: int) -> Optional[dict]:
    """调整排队中任务的优先级；已开始/已结束的任务不允许改。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""UPDATE {TASK_TABLE}
                    SET priority = %s, updated_at = now()
                    WHERE id = %s AND status IN ('PENDING', 'RETRY')
                    RETURNING *""",
                (int(priority), task_id),
            )
            rows = _rows(cursor)
            return rows[0] if rows else None


def reclaim_expired() -> list[dict]:
    """回收过期 RUNNING：未超次数 → PENDING（attempt+1），否则 FAILED。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE {TASK_TABLE}
                SET status = CASE
                        WHEN attempt >= max_attempts THEN 'FAILED'
                        ELSE 'PENDING'
                    END,
                    attempt = CASE
                        WHEN attempt >= max_attempts THEN attempt
                        ELSE attempt + 1
                    END,
                    available_at = now(),
                    error_message = CASE
                        WHEN attempt >= max_attempts THEN 'Worker lease expired'
                        ELSE error_message
                    END,
                    finish_time = CASE
                        WHEN attempt >= max_attempts THEN now()
                        ELSE finish_time
                    END,
                    locked_by = NULL,
                    locked_until = NULL,
                    heartbeat_at = NULL,
                    updated_at = now()
                WHERE status = 'RUNNING'
                  AND locked_until IS NOT NULL
                  AND locked_until < now()
                RETURNING id, task_type, lane, attempt, max_attempts, status
                """
            )
            return _rows(cursor)


def count_by_lane(lane: str) -> dict[str, int]:
    """按状态统计一条车道的任务数（用于统一观测）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'SELECT status, count(*) FROM {TASK_TABLE} '
                'WHERE lane = %s GROUP BY status',
                (lane,),
            )
            return {str(status): int(count) for status, count in cursor.fetchall()}
