"""``graph_import_task``（图谱导入任务）的读写。

## 三处与直觉不符的地方

1. **``kb_id`` 列存的是 ``graph_<kbId>``**（与 ``graph_registry.kb_id`` 同形），
   不是裸 uuid。``deleteKbase`` 按这个形状删任务行；改成裸 uuid 会漏删任务。
2. ``created_at`` / ``updated_at`` 是 **timestamptz**，插入取默认 ``now()``、
   更新由触发器刷新。别往时间列塞字符串。
3. 这张表是**物理删**（全库统一硬删除）。
"""

from __future__ import annotations

import json
from typing import Any, Optional

from infrastructure.db.kb import connection

TABLE = 'graph_import_task'

# ``GraphDataImportServiceImpl`` 的状态常量
STATUS_PENDING = 'PENDING'
STATUS_PROCESSING = 'PROCESSING'
STATUS_COMPLETED = 'COMPLETED'
STATUS_COMPLETED_WITH_ERRORS = 'COMPLETED_WITH_ERRORS'
STATUS_FAILED = 'FAILED'

# ``kb_id`` 列的前缀（``importFromZip`` 的调用方拼好再传进来）
KB_ID_PREFIX = 'graph_'

# ``error_message`` 是 varchar(20000)
ERROR_MESSAGE_MAX = 20000


def create_task(task_id: str, kb_index_name: str, schema_id: str) -> None:
    """``createTask``：建一条 PENDING，六个计数全 0。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {TABLE} (task_id, kb_id, schema_id, status, '
                'progress, entity_total, entity_success, entity_failed, '
                'edge_total, edge_success, edge_failed) '
                'VALUES (%s, %s, %s, %s, 0, 0, 0, 0, 0, 0, 0)',
                (task_id, kb_index_name, schema_id, STATUS_PENDING))


def update_status(task_id: str, status: str,
                  error_message: Optional[str] = None) -> None:
    """``updateStatus``：**每次都写 ``error_message``**（null 会把旧值清掉）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TABLE} SET status = %s, error_message = %s '
                'WHERE task_id = %s',
                (status, error_message, task_id))


def update_progress(task_id: str, progress: int, entity: Any, edge: Any) -> None:
    """``updateProgress``：六个计数 + ``failed_records``（空列表写 NULL）。"""
    failed = list(entity.failed_records) + list(edge.failed_records)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TABLE} SET progress = %s, entity_total = %s, entity_success = %s, '
                'entity_failed = %s, edge_total = %s, edge_success = %s, edge_failed = %s, '
                'failed_records = %s WHERE task_id = %s',
                (progress, entity.total, entity.success, entity.failed,
                 edge.total, edge.success, edge.failed,
                 json.dumps(failed, ensure_ascii=False, default=str) if failed else None,
                 task_id))


def select_task(task_id: str) -> Optional[dict]:
    """按主键取一行（测试与排障用；查询端点在图谱抽取那边）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT * FROM {TABLE} WHERE task_id = %s', (task_id,))
            names = [description[0] for description in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
            return rows[0] if rows else None


def abbrev(text: Optional[str]) -> Optional[str]:
    """``abbrev``：``error_message`` 列是 varchar(20000)，超了截断。"""
    if text is None:
        return None
    return text if len(text) <= ERROR_MESSAGE_MAX else text[:ERROR_MESSAGE_MAX]
