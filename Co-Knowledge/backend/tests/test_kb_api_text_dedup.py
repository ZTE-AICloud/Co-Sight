"""正文去重的读写形状。

规则：新库正文只存 ``chunk.text`` 一份；``vector.text`` 普通行为 NULL、
LLM 优化行保留问题文本；``chunk.content_expand`` 不再写第二份正文。
读侧统一 ``COALESCE(idx.text, chunk.text)`` —— idx 在前，优化行的问题文本优先。
"""

from __future__ import annotations

from contextlib import contextmanager

from knowledge_base.repository import chunk as chunk_store
from retrieval.repository import vector_write_store as vector_write_store


class _Cursor:
    description = []

    def __init__(self):
        self.sql = []
        self.params = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)

    def fetchall(self):
        return []

    def fetchone(self):
        return (0,)

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

    monkeypatch.setattr(chunk_store, 'connection', _connection)
    return cursor


def test_index_select_uses_chunk_text():
    from_sql, select = chunk_store.index_select_sql({'table_name': 'data_kb_index_demo'})

    assert 'LEFT JOIN kb_index.data_kb_index_demo_chunk AS chunk' in from_sql
    assert 'COALESCE(idx.text, chunk.text) AS text' in select


def test_file_join_coalesces_chunk_text():
    join, text_expr = chunk_store._file_join({'table_name': 'data_kb_index_demo'})

    assert 'LEFT JOIN kb_index.data_kb_index_demo_chunk AS CHUNK' in join
    assert text_expr == 'COALESCE(VEC_CHUNK.text, CHUNK.text)'


def test_page_keyword_filters_on_coalesced_text(monkeypatch):
    cursor = _capture(monkeypatch)

    chunk_store.query_page_by_keyword(
        {'table_name': 'data_kb_index_demo'}, '关键词', 1, 10)

    count_sql, select_sql = cursor.sql
    assert 'COALESCE(idx.text, chunk.text) LIKE %s' in count_sql
    assert 'COALESCE(idx.text, chunk.text) LIKE %s' in select_sql


def test_chunk_write_does_not_store_second_text_copy():
    params = vector_write_store._chunk_params({
        'id': 'chunk-1', 'text': '正文',
        'metadata': {'content_expand': '正文'},
    })
    # 文档库列序：id, kbId, source, text, chunk_id, type —— 没有 content_expand 列
    assert len(params) == 6
    assert params[3] == '正文'


def test_update_chunk_text_does_not_write_removed_columns(monkeypatch):
    cursor = _capture(monkeypatch)

    chunk_store.update_chunk_text(
        {'table_name': 'doc_demo_vector'}, 'chunk-1', '新正文', {})

    sql = cursor.sql[0]
    assert 'text = %s' in sql
    assert 'content_expand' not in sql
    assert 'chunk_index' not in sql
