"""图谱导入任务的读写（统一任务表 ``task_center.task``，``task_type='GRAPH_IMPORT'``）。

对外仍暴露 ``graph_import_task`` 的字段形状与
``PENDING/PROCESSING/COMPLETED/COMPLETED_WITH_ERRORS/FAILED`` 状态：
统一表内部用 ``PENDING/RUNNING/COMPLETED/COMPLETED_WITH_ERRORS/FAILED``。
``graph_import_task`` 是只读兼容视图。

三处与直觉不符的地方：

1. **统一表的 ``kbase_id`` 存裸 id**；对外返回的 ``kb_id`` 仍拼回
   ``graph_<kbId>``（与 ``graph_registry.kb_id`` 同形）。
2. ``created_at`` / ``updated_at`` 是 **timestamptz**，插入取默认 ``now()``、
   更新由触发器刷新。
3. 这张表是**物理删**（全库统一硬删除）。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from infrastructure.db.kb import connection
from infrastructure.tasks.pg import TASK_TABLE

TABLE = TASK_TABLE
TASK_TYPE = 'GRAPH_IMPORT'
LANE = 'graph_import'

# ``GraphDataImportServiceImpl`` 的状态常量（对外）
STATUS_PENDING = 'PENDING'
STATUS_PROCESSING = 'PROCESSING'
STATUS_COMPLETED = 'COMPLETED'
STATUS_COMPLETED_WITH_ERRORS = 'COMPLETED_WITH_ERRORS'
STATUS_FAILED = 'FAILED'

_TO_UNIFIED = {
    STATUS_PENDING: 'PENDING',
    STATUS_PROCESSING: 'RUNNING',
    STATUS_COMPLETED: 'COMPLETED',
    STATUS_COMPLETED_WITH_ERRORS: 'COMPLETED_WITH_ERRORS',
    STATUS_FAILED: 'FAILED',
}
_TO_DOMAIN = {value: key for key, value in _TO_UNIFIED.items()}

# ``kb_id`` 列的前缀（``importFromZip`` 的调用方拼好再传进来）
KB_ID_PREFIX = 'graph_'

# ``error_message`` 是 varchar(20000)
ERROR_MESSAGE_MAX = 20000


def _bare_kbase_id(kb_index_name: str) -> str:
    """``graph_<kbId>`` → ``<kbId>``；没有前缀时原样返回。"""
    if kb_index_name.startswith(KB_ID_PREFIX):
        return kb_index_name[len(KB_ID_PREFIX):]
    return kb_index_name


def create_task(task_id: str, kb_index_name: str, schema_id: str, *,
                lane: str = LANE, max_attempts: int = 2,
                payload: Optional[dict] = None) -> None:
    """``createTask``：建一条 PENDING，六个计数全 0。

    ``payload`` 是 DB 队列的可重建输入：``kbIndexName`` / ``schemaId`` /
    ``schemaObj`` / ``zipPath``。``lane=graph_import_internal`` 用于图谱抽图
    导入阶段生成的内部进度行，不会被 ``graph_import`` 车道认领。
    """
    payload = dict(payload or {})
    payload.setdefault('schemaId', schema_id)
    extra = json.dumps({
        'entity_total': 0, 'entity_success': 0, 'entity_failed': 0,
        'edge_total': 0, 'edge_success': 0, 'edge_failed': 0,
        'failed_records': None,
    })
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {TABLE} (id, task_type, lane, status, progress, attempt, '
                'max_attempts, kbase_id, payload, extra) '
                'VALUES (%s, %s, %s, %s, 0, 1, %s, %s, %s::jsonb, %s::jsonb)',
                (task_id, TASK_TYPE, lane, _TO_UNIFIED[STATUS_PENDING],
                 max_attempts, _bare_kbase_id(kb_index_name),
                 json.dumps(payload, ensure_ascii=False, default=str), extra))


def update_status(task_id: str, status: str,
                  error_message: Optional[str] = None) -> None:
    """``updateStatus``：**每次都写 ``error_message``**（null 会把旧值清掉）。"""
    unified = _TO_UNIFIED.get(status, STATUS_FAILED)
    sets = ['status = %s', 'error_message = %s', 'updated_at = NOW()']
    params: list = [unified, error_message]
    if unified in ('COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED'):
        sets.append('finish_time = NOW()')
    params.extend([task_id, TASK_TYPE])
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TABLE} SET {", ".join(sets)} '
                'WHERE id = %s AND task_type = %s',
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


def update_progress(task_id: str, progress: int, entity: Any, edge: Any) -> None:
    """``updateProgress``：六个计数 + ``failed_records``（空列表写 NULL）。"""
    failed = list(entity.failed_records) + list(edge.failed_records)
    extra = json.dumps({
        'entity_total': entity.total,
        'entity_success': entity.success,
        'entity_failed': entity.failed,
        'edge_total': edge.total,
        'edge_success': edge.success,
        'edge_failed': edge.failed,
        'failed_records': failed or None,
    }, ensure_ascii=False, default=str)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TABLE} SET progress = %s, extra = %s::jsonb, '
                'updated_at = NOW() WHERE id = %s AND task_type = %s',
                (progress, extra, task_id, TASK_TYPE))


def select_task(task_id: str) -> Optional[dict]:
    """按任务 id 取一行，返回旧 ``graph_import_task`` 的字段形状。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, kbase_id, payload ->> 'schemaId' AS schema_id, "
                'status, progress, extra, error_message, created_at, updated_at '
                f'FROM {TABLE} WHERE id = %s AND task_type = %s',
                (task_id, TASK_TYPE),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            (task_id, kbase_id, schema_id, status, progress, extra,
             error_message, created_at, updated_at) = row
    extra = extra or {}
    return {
        'task_id': task_id,
        'kb_id': f'{KB_ID_PREFIX}{kbase_id}' if kbase_id else None,
        'schema_id': schema_id,
        'status': _TO_DOMAIN.get(status, STATUS_FAILED),
        'progress': progress,
        'entity_total': extra.get('entity_total', 0),
        'entity_success': extra.get('entity_success', 0),
        'entity_failed': extra.get('entity_failed', 0),
        'edge_total': extra.get('edge_total', 0),
        'edge_success': extra.get('edge_success', 0),
        'edge_failed': extra.get('edge_failed', 0),
        'failed_records': extra.get('failed_records'),
        'error_message': error_message,
        'created_at': created_at,
        'updated_at': updated_at,
    }


def abbrev(text: Optional[str]) -> Optional[str]:
    """``abbrev``：``error_message`` 列是 varchar(20000)，超了截断。"""
    if text is None:
        return None
    return text if len(text) <= ERROR_MESSAGE_MAX else text[:ERROR_MESSAGE_MAX]
