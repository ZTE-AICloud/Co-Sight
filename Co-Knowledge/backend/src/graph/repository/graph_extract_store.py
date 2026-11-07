"""``graph_extract_task``（抽图任务）的读写。

表名是 **``graph_extract_task``（单数）** —— 与 ``graph_import_task``（复数）
不是一套，实测库里就是这么建的两个名字，别「顺手统一」。

这张表是**物理删**（全库统一硬删除）。

列与 ``GraphExtractTaskPO`` 一一对应：

    id, kb_id, schema_id, operator_id, file_count, status, progress,
    error_message, result_file_path, created_by, created_at, updated_at,
    start_time, finish_time

``created_at`` 是 ``NOT NULL DEFAULT CURRENT_TIMESTAMP``（后面三个可空）。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.db.kb import connection

from infrastructure.db.rows import rows as _rows

TABLE = 'graph_extract_task'

# ``GraphExtractTaskStatusEnum``：``status`` 列存的是**字符串**，不是那个 int
STATUS_INIT = 'INIT'
STATUS_RUNNING = 'RUNNING'
STATUS_SUCCESS = 'SUCCESS'
STATUS_FAIL = 'FAIL'

# 与 ``GraphExtractTaskPO`` 字段声明同序（查询出来的键序按这个走）
COLUMNS = ('id', 'kb_id', 'schema_id', 'operator_id', 'file_count', 'status',
           'progress', 'error_message', 'result_file_path', 'created_by',
           'created_at', 'updated_at', 'start_time', 'finish_time')


def select_task(task_id: str) -> Optional[dict]:
    """按 id 取任务（``WHERE id = ?``）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'SELECT {", ".join(COLUMNS)} FROM {TABLE} WHERE id = %s',
                           (task_id,))
            rows = _rows(cursor)
            return rows[0] if rows else None


def insert_task(kbase_id: str, schema_id: str, operator_id: int, file_count: int,
                created_by: str) -> str:
    """建一条 ``INIT`` 任务；id 为 32 位无横线 uuid。"""
    import uuid

    task_id = uuid.uuid4().hex
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO {TABLE} (id, kb_id, schema_id, operator_id, file_count, '
                'status, progress, created_by, created_at, updated_at) '
                "VALUES (%s, %s, %s, %s, %s, %s, 0, %s, NOW(), NOW())",
                (task_id, kbase_id, schema_id, operator_id, file_count,
                 STATUS_INIT, created_by))
    return task_id


def update_task_status(task_id: str, status: str, progress: int,
                       error_message: Optional[str] = None) -> None:
    """``GraphExtractTaskDao.updateTaskStatus``。

    ⚠️ 两个**只在特定状态才写**的时间戳（保持）：
    ``startTime`` 仅在 ``RUNNING`` 时写、``finishTime`` 仅在 ``SUCCESS``/``FAIL`` 时写。
    两者都是**只在当前这一步**写一次，别改成「每次更新都刷新」。
    """
    sets = ['status = %s', 'progress = %s', 'error_message = %s', 'updated_at = NOW()']
    params: list = [status, progress, error_message]
    if status == STATUS_RUNNING:
        sets.append('start_time = NOW()')
    elif status in (STATUS_SUCCESS, STATUS_FAIL):
        sets.append('finish_time = NOW()')
    params.append(task_id)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'UPDATE {TABLE} SET {", ".join(sets)} WHERE id = %s', params)

def update_task_schema_id(task_id: str, schema_id: str) -> None:
    """``GraphExtractTaskDao.updateTaskSchemaId``：通用图谱导入完 schema 后回填真正的 id。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'UPDATE {TABLE} SET schema_id = %s, updated_at = NOW() WHERE id = %s',
                (schema_id, task_id),
            )
