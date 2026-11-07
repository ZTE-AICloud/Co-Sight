"""``kb_node_relation`` 的读写。

这张 relation 表是「文件 → 向量行」的桥：删文件时先按 ``directory_id``（= fileId）查出
``node_id``，再按 node_id 去动态向量表里删行，最后删 relation 行本人。

关系表操作的约定：

* 查 node_id → 每 2000 一批删向量表 → 删 relation
* **``file_ids`` 为空直接返回 0**（不做「删全库」这种危险操作）
* relation 表是**物理删**（``kb_directory`` 也是物理删）
"""

from __future__ import annotations

from typing import Iterable

from infrastructure.db.kb import connection
from infrastructure.db import ddl, identifiers

RELATION_BATCH_SIZE = 2000


def select_node_ids_by_directory_ids(file_ids: Iterable[str]) -> list[str]:
    ids = list(file_ids)
    if not ids:
        return []
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT node_id FROM kb_node_relation WHERE directory_id = ANY(%s)',
                (ids,),
            )
            return [row[0] for row in cursor.fetchall() if row[0]]


def delete_by_directory_ids(kbase_pk_id: int, file_ids: Iterable[str],
                            vector_table: str | None = None) -> int:
    """删掉这些文件的向量行与 relation 行。返回删掉的 relation 行数。

    :param vector_table: 动态向量表名；省略时按 ``kb_kbase`` 的 ``table_name`` 解析。
    """
    ids = list(file_ids)
    if not ids:
        return 0

    node_ids = select_node_ids_by_directory_ids(ids)
    table = vector_table or _resolve_vector_table(kbase_pk_id)
    for start in range(0, len(node_ids), RELATION_BATCH_SIZE):
        batch = node_ids[start:start + RELATION_BATCH_SIZE]
        if table:
            ddl.delete_by_node_ids(table, batch)

    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'DELETE FROM kb_node_relation WHERE directory_id = ANY(%s)', (ids,))
            return cursor.rowcount


def _resolve_vector_table(kbase_pk_id: int) -> str | None:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM kb_kbase WHERE id = %s",
                (kbase_pk_id,),
            )
            row = cursor.fetchone()
    return row[0] if row and row[0] else identifiers.doc_vector_table(str(kbase_pk_id))


def batch_insert_relations(kbase_id: str, file_id: str, node_ids: list[str]) -> None:
    """关系表 DAO 的 ``batchInsert``：每批 2000 插 ``(kbase_id, directory_id, node_id)``。

    留到 B2 的向量化环节用；先放在这里，与删除逻辑同处一文件便于对照。
    """
    if not node_ids:
        return
    rows = [(kbase_id, file_id, node_id) for node_id in node_ids]
    with connection() as conn:
        with conn.cursor() as cursor:
            for start in range(0, len(rows), RELATION_BATCH_SIZE):
                batch = rows[start:start + RELATION_BATCH_SIZE]
                cursor.executemany(
                    'INSERT INTO kb_node_relation (kbase_id, directory_id, node_id) '
                    'VALUES (%s, %s, %s) '
                    # 重试幂等：一个 node 在一个 KB 内只属于一个文件
                    # （唯一索引 (kbase_id, node_id) 由 DDL 保证）。
                    'ON CONFLICT (kbase_id, node_id) DO NOTHING',
                    batch,
                )
