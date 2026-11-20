"""抽图任务的读写（统一任务表 ``task_center.task``，``task_type='GRAPH_EXTRACT'``）。

对外仍暴露 ``GraphExtractTaskPO`` 的字段形状与 ``INIT/RUNNING/SUCCESS/FAIL``
状态：统一表内部用 ``PENDING/RUNNING/COMPLETED/FAILED``，本模块负责双向映射。
``graph_extract_task`` 是只读兼容视图。

这张表是**物理删**（全库统一硬删除）。
"""

from __future__ import annotations

import json
from typing import Optional

from infrastructure.db.kb import connection
from infrastructure.db.rows import rows as _rows
from infrastructure.tasks.pg import TASK_TABLE

TABLE = TASK_TABLE
TASK_TYPE = 'GRAPH_EXTRACT'
LANE = 'graph_extract'

# ``GraphExtractTaskStatusEnum``：对外仍是这四个字符串
STATUS_INIT = 'INIT'
STATUS_RUNNING = 'RUNNING'
STATUS_SUCCESS = 'SUCCESS'
STATUS_FAIL = 'FAIL'

# 领域状态 ↔ 统一表状态
_TO_UNIFIED = {
    STATUS_INIT: 'PENDING',
    STATUS_RUNNING: 'RUNNING',
    STATUS_SUCCESS: 'COMPLETED',
    STATUS_FAIL: 'FAILED',
}
_TO_DOMAIN = {value: key for key, value in _TO_UNIFIED.items()}

# 与 ``GraphExtractTaskPO`` 字段声明同序（查询出来的键序按这个走）
COLUMNS = ('id', 'kb_id', 'schema_id', 'operator_id', 'file_count', 'status',
           'progress', 'error_message', 'result_file_path', 'created_by',
           'created_at', 'updated_at', 'start_time', 'finish_time')


def select_task(task_id: str) -> Optional[dict]:
    """按 id 取任务，返回领域形状（``kb_id`` / 领域状态）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, kbase_id AS kb_id, "
                "payload ->> 'schemaId' AS schema_id, "
                "(payload ->> 'operatorId')::integer AS operator_id, "
                "(payload ->> 'fileCount')::integer AS file_count, "
                "status, progress, error_message, "
                "extra ->> 'resultFilePath' AS result_file_path, "
                'NULL::character varying(255) AS created_by, '
                'created_at, updated_at, start_time, finish_time '
                f'FROM {TABLE} WHERE id = %s AND task_type = %s',
                (task_id, TASK_TYPE),
            )
            rows = _rows(cursor)
            if not rows:
                return None
            row = rows[0]
            row['status'] = _TO_DOMAIN.get(row.get('status'), STATUS_FAIL)
            return row


def insert_task(kbase_id: str, schema_id: str, operator_id: int, file_count: int,
                payload: Optional[dict] = None,
                max_attempts: int = 2) -> str:
    """建一条 ``INIT`` 任务；id 为 32 位无横线 uuid。

    ``payload`` 必须是可重建的队列输入：``tmpDir`` / ``dto`` / ``schemaObj`` /
    ``isUpdate`` / ``cacheSchemaId``。队列 worker 崩溃后靠它重跑。
    """
    import uuid

    task_id = uuid.uuid4().hex
    payload = dict(payload or {})
    payload.setdefault('schemaId', schema_id)
    payload.setdefault('operatorId', operator_id)
    payload.setdefault('fileCount', file_count)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {TABLE} (id, task_type, lane, status, progress, attempt, '
                'max_attempts, kbase_id, payload) '
                'VALUES (%s, %s, %s, %s, 0, 1, %s, %s, %s::jsonb)',
                (task_id, TASK_TYPE, LANE, _TO_UNIFIED[STATUS_INIT], max_attempts,
                 kbase_id, json.dumps(payload, ensure_ascii=False)))
    return task_id


def update_task_status(task_id: str, status: str, progress: int,
                       error_message: Optional[str] = None) -> None:
    """``GraphExtractTaskDao.updateTaskStatus``。

    ⚠️ 两个**只在特定状态才写**的时间戳（保持）：
    ``startTime`` 仅在 ``RUNNING`` 时写、``finishTime`` 仅在 ``SUCCESS``/``FAIL`` 时写。
    """
    unified = _TO_UNIFIED.get(status, 'FAILED')
    sets = ['status = %s', 'progress = %s', 'error_message = %s', 'updated_at = NOW()']
    params: list = [unified, progress, error_message]
    if status == STATUS_RUNNING:
        sets.append('start_time = NOW()')
    elif status in (STATUS_SUCCESS, STATUS_FAIL):
        sets.append('finish_time = NOW()')
    params.extend([task_id, TASK_TYPE])
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TABLE} SET {", ".join(sets)} WHERE id = %s AND task_type = %s',
                params)


def cancel_task(task_id: str, reason: str = 'Cancelled by user') -> None:
    """领域 runner 协作中止后落 CANCELLED（仅从 RUNNING 迁入）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE} SET status = 'CANCELLED', progress = 0, "
                'error_message = %s, finish_time = COALESCE(finish_time, NOW()), '
                "updated_at = NOW() WHERE id = %s AND task_type = %s "
                "AND status = 'RUNNING'",
                (reason, task_id, TASK_TYPE),
            )


def update_task_schema_id(task_id: str, schema_id: str) -> None:
    """``GraphExtractTaskDao.updateTaskSchemaId``：通用图谱导入完 schema 后回填真正的 id。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"UPDATE {TABLE} "
                "SET payload = jsonb_set(COALESCE(payload, '{}'::jsonb), "
                "'{schemaId}', to_jsonb(%s::text)), updated_at = NOW() "
                'WHERE id = %s AND task_type = %s',
                (schema_id, task_id, TASK_TYPE),
            )
