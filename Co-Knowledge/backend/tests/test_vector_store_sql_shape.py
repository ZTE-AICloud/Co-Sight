"""向量检索 SQL 的 ANN 可索引形状（P1-ANN）。

pgvector 的 HNSW 只认 ``ORDER BY embedding <=> q`` **升序**；写成
``ORDER BY 1 - distance DESC`` 会退化成 Seq Scan + Sort。本组测试钉住
两条检索 SQL 的形状与参数顺序。

跑法::

    python -m pytest tests/test_vector_store_sql_shape.py -q
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from retrieval.repository import vector_store as vector_store


class _Cursor:
    description = []

    def __init__(self):
        self.sql = ''
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def close(self):
        pass


def _capture(monkeypatch):
    cursor = _Cursor()

    @contextmanager
    def _connection():
        yield _Conn(cursor)

    monkeypatch.setattr(vector_store, 'connection', _connection)
    return cursor


def test_query_by_embedding_with_chunk_uses_raw_distance_order(monkeypatch):
    cursor = _capture(monkeypatch)

    vector_store.query_by_embedding_with_chunk(
        'data_kb_index_demo', 'data_kb_index_demo_chunk', '[0.2]', 0.0, 5)

    assert 'ORDER BY idx.embedding <=> %s::vector ASC' in cursor.sql
    assert 'WHERE idx.embedding <=> %s::vector <= %s' in cursor.sql
    # 正文去重：普通新库行 idx.text 为 NULL，正文取 chunk.text；
    # LLM 优化行 idx.text 是问题文本，必须优先保留（顺序不能反）。
    assert 'COALESCE(idx.text, chunk.text) AS text' in cursor.sql
    assert 'ORDER BY cosine_similarity DESC' not in cursor.sql
    assert cursor.params[0] == '[0.2]'
    assert cursor.params[1] == '[0.2]'
    assert cursor.params[2] == pytest.approx(1.0)
    assert cursor.params[3] == '[0.2]'
    assert cursor.params[4] == 5
