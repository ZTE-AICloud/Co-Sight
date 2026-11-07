"""删图谱库时要连带清掉的几张表。

三个**不同**的标识符指向同一个图谱库，别搞混：

===================  ==========================================  ==========================
标识符                形态                                         用在哪
===================  ==========================================  ==========================
图谱库名              ``graph_<kbId>``                            ``graph_registry.kb_id``
导入任务 ``kb_id``     ``graph_<kbId>``                          ``graph_import_task.kb_id``
抽取任务 ``kb_id``     ``<kbId>``（裸的）                            ``graph_extract_task.kb_id``
===================  ==========================================  ==========================

另有两张**表名本身带 uuid** 的动态表要 drop：``graph_<kbId>_chunk`` 与
``graph_<kbId>_vector``（都建在 ``kb_index`` schema 下）。

⚠️ 表名：抽取任务是 **``graph_extract_task``（单数）**，导入任务是
``graph_import_task``（复数）—— 一个单数一个复数，实测库里就是这么建的。
"""

from __future__ import annotations

from graph.constants import GRAPH_TABLE_PREFIX
from infrastructure.db.kb import connection

# 导入任务表里存的是带前缀的形态（``AsyncGraphExtractServiceV2`` 与
# ``deleteGraph`` 两边都拼这个）
IMPORT_TASK_KB_ID_PREFIX = 'graph_'


def graph_db_name(kbase_id: str) -> str:
    """``graph_<kbId>``。"""
    return f'{GRAPH_TABLE_PREFIX}{kbase_id}'


def import_task_table() -> str:
    return 'graph_import_task'


def extract_task_table() -> str:
    return 'graph_extract_task'


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
    """按 ``graph_<kbId>`` 删（**不是** bare kbId）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {import_task_table()} WHERE kb_id = %s',
                (IMPORT_TASK_KB_ID_PREFIX + kbase_id,))
            return cursor.rowcount


def delete_extract_tasks(kbase_id: str) -> int:
    """按 **裸 kbId** 删（与导入任务那条相反）。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f'DELETE FROM {extract_task_table()} WHERE kb_id = %s', (kbase_id,))
            return cursor.rowcount


def drop_table_if_exists(qualified_name: str) -> bool:
    """``dropTable`` 幂等版：表不存在就跳过。返回是否真的删了。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f'DROP TABLE IF EXISTS {qualified_name}')
            return True
