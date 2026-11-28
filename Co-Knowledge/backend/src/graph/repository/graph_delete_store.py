"""删图谱库时要连带清掉的几张表。

同一个图谱库在库里有**两种**形态的标识，别搞混：

===================  ==========================================  ==========================
标识符                形态                                         用在哪
===================  ==========================================  ==========================
图谱库名              ``graph_<kbId>``                            ``graph_registry.kb_id``
任务行 ``kbase_id``    ``<kbId>``（裸的）                            ``task_center.task``
===================  ==========================================  ==========================

另有两张**表名本身带 uuid** 的动态表要 drop：``graph_<kbId>_chunk`` 与
``graph_<kbId>_vector``（都建在 ``kb_index`` schema 下）。

任务行统一存在 ``task_center.task``；``kbase_id`` 是**裸 id**，删除时按
``task_type`` 区分抽取与导入。导入接口对外返回的 ``kb_id`` 仍带 ``graph_``
前缀，但那是 store 返回时拼的，不进库。
"""

from __future__ import annotations

from graph.constants import GRAPH_TABLE_PREFIX
from infrastructure.db.kb import connection
from infrastructure.tasks.pg import TASK_TABLE

EXTRACT_TASK_TYPE = 'GRAPH_EXTRACT'
IMPORT_TASK_TYPE = 'GRAPH_IMPORT'


def graph_db_name(kbase_id: str) -> str:
    """``graph_<kbId>``。"""
    return f'{GRAPH_TABLE_PREFIX}{kbase_id}'


def chunk_table(kbase_id: str) -> str:
    return f'kb_index.{GRAPH_TABLE_PREFIX}{kbase_id}_chunk'


def vector_table(kbase_id: str) -> str:
    return f'kb_index.{GRAPH_TABLE_PREFIX}{kbase_id}_vector'


def exists_knowledge_graph_info(db_name: str) -> bool:
    """``KbaseDao.existsKnowledgeGraphInfo``：先判**表**在不在，再判**行**在不在。

    表不在时返回 False（不报错）—— 上游原样保留了这个两步写法。
    """
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_name = 'graph_registry'")
            if int(cursor.fetchone()[0]) == 0:
                return False
            cursor.execute(
                'SELECT COUNT(*) FROM graph_registry WHERE kb_id = %s', (db_name,))
            return int(cursor.fetchone()[0]) > 0


def delete_knowledge_graph_info(db_name: str) -> None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM graph_registry WHERE kb_id = %s', (db_name,))


def delete_import_tasks(kbase_id: str) -> int:
    """按裸 ``kbase_id`` 删统一表里的 ``GRAPH_IMPORT`` 任务。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {TASK_TABLE} WHERE task_type = %s AND kbase_id = %s',
                (IMPORT_TASK_TYPE, kbase_id))
            return cursor.rowcount


def delete_extract_tasks(kbase_id: str) -> int:
    """按裸 ``kbase_id`` 删统一表里的 ``GRAPH_EXTRACT`` 任务。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {TASK_TABLE} WHERE task_type = %s AND kbase_id = %s',
                (EXTRACT_TASK_TYPE, kbase_id))
            return cursor.rowcount


def drop_table_if_exists(qualified_name: str) -> bool:
    """``dropTable`` 幂等版：表不存在就跳过。返回是否真的删了。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS {qualified_name}')
            return True
