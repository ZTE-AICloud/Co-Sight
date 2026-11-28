"""按数据源分表的向量存储（定长维度 + HNSW）。

为什么不再用一张共享表：允许每个数据源选不同 embedding 模型，维度就不同；
而 pgvector 的 HNSW 要求列**定长**（``vector(N)``），共享的 typmod-less 列根本
建不了索引（实测 ``column does not have dimensions``）。

所以每个数据源一张表：``text2sql_index.t2s_vec_<datasource_id 去横线>``，
列类型 ``vector(N)``，N 来自数据源固定的 embedding 模型维度，并建 HNSW。
与文档侧 ``doc_<id>_vector`` 是同一套惯例。没有数据源就没有向量表，
检索只认本数据源的表。
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA = 'text2sql_index'


def table_name(datasource_id: str) -> str:
    """``t2s_vec_<32 位十六进制>``：只保留 [a-z0-9_]，可安全拼进 DDL。"""
    compact = ''.join(char for char in str(datasource_id).lower() if char.isalnum())
    if not compact:
        raise ValueError('datasource_id 不能为空')
    return f't2s_vec_{compact}'


def qualified(datasource_id: str) -> str:
    return f'{SCHEMA}.{table_name(datasource_id)}'


def ensure_table(cursor, datasource_id: str, dimensions: int) -> str:
    """确保该数据源的向量表存在；维度与既有表不一致时直接报错。

    表已存在但维度不同，说明数据源的模型被改过——那是需要人工处理的状态，
    静默降级只会让检索结果莫名变差。
    """
    if dimensions <= 0:
        raise ValueError('dimensions 必须为正整数')
    name = qualified(datasource_id)
    cursor.execute(
        """
        SELECT format_type(a.atttypid, a.atttypmod) AS column_type
          FROM pg_catalog.pg_attribute a
          JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %s AND c.relname = %s AND a.attname = 'embedding'
        """, (SCHEMA, table_name(datasource_id)))
    existing = cursor.fetchone()
    if existing is not None:
        column_type = existing['column_type'] if isinstance(existing, dict) else existing[0]
        expected = f'vector({dimensions})'
        if column_type != expected:
            raise ValueError(
                f'{name} 已是 {column_type}，与当前维度 {expected} 不一致；'
                '请新建数据源或归档旧版本后重建该表')
        return name

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {name} (
            knowledge_id UUID PRIMARY KEY REFERENCES text2sql.t2s_knowledge(id)
                ON DELETE CASCADE,
            datasource_id UUID NOT NULL,
            version_id   UUID NOT NULL,
            content      TEXT NOT NULL,
            embedding    vector({int(dimensions)}) NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS {table_name(datasource_id)}_version
            ON {name} (version_id)
    """)
    cursor.execute(f"""
        CREATE INDEX IF NOT EXISTS {table_name(datasource_id)}_hnsw
            ON {name} USING hnsw (embedding vector_cosine_ops)
    """)
    return name


def upsert(cursor, datasource_id: str, knowledge_id: str, version_id: str,
           content: str, embedding: list[float]) -> None:
    cursor.execute(
        f"""
        INSERT INTO {qualified(datasource_id)}
            (knowledge_id, datasource_id, version_id, content, embedding)
        VALUES (%s, %s, %s, %s, %s::vector)
        ON CONFLICT (knowledge_id) DO UPDATE
           SET embedding = EXCLUDED.embedding, content = EXCLUDED.content
        """,
        (knowledge_id, datasource_id, version_id, content, json.dumps(embedding)))


def search(cursor, datasource_id: str, version_id: str,
           embedding: list[float], limit: int) -> list[dict[str, Any]]:
    """版本隔离的余弦检索。

    表不存在说明这个数据源没有构建过任何版本——那是状态不一致，
    直接报错，不用空结果掩盖过去。
    """
    if not _table_exists(cursor, datasource_id):
        raise RuntimeError(
            f'数据源 {datasource_id} 还没有向量表 {qualified(datasource_id)}；'
            '请先构建并发布一个版本')
    cursor.execute(
        f"""
        SELECT k.id, k.object_type, k.object_key, k.title, k.content,
               k.metadata, k.table_id, k.column_id, k.value_id,
               k.relation_id, k.metric_id,
               1 - (v.embedding <=> %s::vector) AS score
          FROM {qualified(datasource_id)} v
          JOIN text2sql.t2s_knowledge k ON k.id = v.knowledge_id
         WHERE v.version_id = %s
         ORDER BY v.embedding <=> %s::vector
         LIMIT %s
        """, (json.dumps(embedding), version_id, json.dumps(embedding), int(limit)))
    return [dict(item) for item in cursor.fetchall()]


def _table_exists(cursor, datasource_id: str) -> bool:
    cursor.execute(
        """
        SELECT 1 FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %s AND c.relname = %s
        """, (SCHEMA, table_name(datasource_id)))
    return cursor.fetchone() is not None
