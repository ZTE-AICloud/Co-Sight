"""向量检索的两张表与两条 SQL。

* 表存在性：在 schema ``kb_index`` 下查表是否存在
* 不带 chunk 的余弦相似度查询
* LEFT JOIN chunk 表（新知识库）

表名来自**调用方拼好的字符串**（``data_`` + baseName），schema 前缀写死在 SQL 里。
表名不能参数化（SQL 标识符），所以这里对标识符做白名单校验，
避免把拼接点变成注入面：``_validate_identifier`` 会收紧非法输入，
不影响任何合法输入的行为。
"""

from __future__ import annotations

from typing import Optional

from infrastructure.db.identifiers import SCHEMA, validate_identifier
from infrastructure.db.kb import connection
from shared.chunk_schema import node_columns
from shared.chunk_schema.vector import to_vector_literal  # noqa: F401  (re-export)

from infrastructure.db.rows import rows as _rows


def table_exists(table_name: str) -> bool:
    """``isTableExist``：``information_schema.tables`` 里 schema 固定 ``kb_index``。"""
    validate_identifier(table_name)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'SELECT EXISTS (SELECT 1 FROM information_schema.tables '
                "WHERE table_schema = %s AND table_name = %s)",
                (SCHEMA, table_name),
            )
            return bool(cursor.fetchone()[0])


def query_by_embedding_with_chunk(table_name: str, chunk_table_name: str,
                                  embedding_literal: str, score_threshold: float,
                                  limit: int) -> list[dict]:
    """带 chunk 正文的向量检索（新知识库，LEFT JOIN chunk 表）。

    注意 SELECT 的列里 ``chunk.text AS chunk_text`` / ``chunk.id AS chunk_id``
    是**给上层做替换用的**，不是直接进响应的。
    """
    validate_identifier(table_name)
    validate_identifier(chunk_table_name)
    sql = (
        # ⚠️ 展开列加 ``meta_`` 前缀：``chunk.id AS chunk_id`` 是**切片表主键**，
        #    与向量表的 ``chunk_id`` 列（切片序号）同名，不加前缀会互相覆盖。
        # 正文去重：普通新库行 idx.text 为 NULL（正文在 chunk.text）；
        # LLM 优化行 idx.text 是生成的问题，必须优先保留 —— 故 coalesce 顺序是 idx 在前。
        'SELECT idx.id, COALESCE(idx.text, chunk.text) AS text, idx.node_id, idx.embedding, '
        'idx.source AS meta_source, '
        'idx.content_expand AS meta_content_expand, idx.chunk_id AS meta_chunk_id, '
        'idx.type AS meta_type, '
        'chunk.text AS chunk_text, chunk.id AS chunk_id, '
        '1 - (idx.embedding <=> %s::vector) AS cosine_similarity '
        f'FROM kb_index.{table_name} AS idx '
        f'LEFT JOIN kb_index.{chunk_table_name} AS chunk '
        "ON idx.content_expand IS NOT NULL "
        "AND idx.content_expand = chunk.id "
        'WHERE idx.embedding <=> %s::vector <= %s '
        'ORDER BY idx.embedding <=> %s::vector ASC LIMIT %s'
    )
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (embedding_literal, embedding_literal,
                                 1.0 - score_threshold, embedding_literal, limit))
            rows = _rows(cursor)
    for row in rows:      # 展开列是 meta_ 前缀的，拼回 metadata 后把前缀列丢掉
        row['metadata'] = node_columns.metadata_from_row(row, prefix='meta_')
        for name in node_columns.EXPANDED_FIELDS:
            row.pop('meta_' + name, None)
    return rows


def select_table_name_by_kbase_id(kbase_id: str) -> Optional[str]:
    """``VectorChunkDao.generateChunkTableName`` 用到的 ``kb_kbase.table_name``。"""
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM kb_kbase WHERE kbase_id = %s",
                (kbase_id,),
            )
            row = cursor.fetchone()
    return row[0] if row else None
