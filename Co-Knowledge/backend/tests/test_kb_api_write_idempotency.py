"""身份唯一性与幂等写的 SQL 形状测试。

钉住四条：

1. 新建向量表带 ``UNIQUE (node_id)``，并在建表前 ``CREATE SCHEMA IF NOT EXISTS``；
2. ``save_vectors`` 用 ``ON CONFLICT (node_id) DO NOTHING``；
3. ``batch_insert_relations`` 用 ``ON CONFLICT (kbase_id, node_id) DO NOTHING``；
4. ``insert_kbase`` 的唯一键冲突翻成 ``KbStoreError(DUPLICATE)``，由服务层映射业务错误。

跑法::

    python -m pytest tests/test_kb_api_write_idempotency.py -q
"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg2
import pytest

from shared.errors.api import KbStoreError
from infrastructure.db import ddl
from knowledge_base.repository import kbase as kbase_store
from retrieval.repository.vector_write_store import save_vectors
from knowledge_base.repository.node_relation import batch_insert_relations


class _Cursor:
    def __init__(self, statements, error=None):
        self.statements = statements
        self.error = error
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if self.error is not None:
            raise self.error
        self.statements.append((sql, params))

    def executemany(self, sql, params):
        self.statements.append((sql, params))
        self.rowcount = len(params)

    def fetchone(self):
        return [1]

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def __init__(self, statements, error=None):
        self.cursor_obj = _Cursor(statements, error)

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _fake_connection(monkeypatch, module, statements, error=None):
    @contextmanager
    def _connection():
        yield _Conn(statements, error)

    monkeypatch.setattr(module, 'connection', _connection)


def test_create_vector_table_ensures_schema_and_unique_node(monkeypatch):
    statements = []
    monkeypatch.setattr(ddl, 'table_exists', lambda _name: False)
    _fake_connection(monkeypatch, ddl, statements)

    assert ddl.create_vector_table('data_kb_index_demo') is True

    sql_text = '\n'.join(str(sql) for sql, _ in statements)
    assert 'CREATE SCHEMA IF NOT EXISTS kb_index' in sql_text
    assert 'UNIQUE INDEX' in sql_text
    assert '(node_id)' in sql_text
    assert 'embedding vector(1024)' in sql_text
    assert 'USING hnsw (embedding vector_cosine_ops)' in sql_text


def test_create_vector_table_skips_hnsw_above_pgvector_limit(monkeypatch):
    statements = []
    monkeypatch.setattr(ddl, 'table_exists', lambda _name: False)
    _fake_connection(monkeypatch, ddl, statements)

    ddl.create_vector_table('data_kb_index_demo', 2560)

    sql_text = '\n'.join(str(sql) for sql, _ in statements)
    assert 'embedding vector(2560)' in sql_text
    assert 'USING hnsw' not in sql_text


def test_create_vector_table_uses_given_dimension(monkeypatch):
    statements = []
    monkeypatch.setattr(ddl, 'table_exists', lambda _name: False)
    _fake_connection(monkeypatch, ddl, statements)

    ddl.create_vector_table('data_kb_index_demo', 768)

    sql_text = '\n'.join(str(sql) for sql, _ in statements)
    assert 'embedding vector(768)' in sql_text


def test_save_vectors_uses_on_conflict_node_id(monkeypatch):
    statements = []
    _fake_connection(monkeypatch, __import__(
        'retrieval.repository.vector_write_store', fromlist=['connection']), statements)

    save_vectors('data_kb_index_demo', [{
        'text': 't', 'node_id': 'n1', 'embedding': [0.1],
        'metadata': {}, 'metadata_': {},
    }])

    sql_text = ' '.join(str(sql) for sql, _ in statements)
    assert 'ON CONFLICT (node_id) DO NOTHING' in sql_text


def test_batch_insert_relations_uses_on_conflict_kbase_node(monkeypatch):
    statements = []
    _fake_connection(monkeypatch, __import__(
        'knowledge_base.repository.node_relation', fromlist=['connection']), statements)

    batch_insert_relations('kb-1', 'f1', ['n1', 'n2'])

    sql_text = ' '.join(str(sql) for sql, _ in statements)
    assert 'ON CONFLICT (kbase_id, node_id) DO NOTHING' in sql_text


def test_insert_kbase_maps_unique_violation_to_store_duplicate(monkeypatch):
    _fake_connection(monkeypatch, kbase_store, [], psycopg2.errors.UniqueViolation())

    with pytest.raises(KbStoreError) as caught:
        kbase_store.insert_kbase(
            kbase_id='a' * 32, name='x', description='', kbase_type='document',
            embedding_model='m', table_name='data_kb_index_x',
            es_index_name='doc_x', category=1, status='0',
            file_count_limit=5000, org_id=None, created_by='u')

    assert caught.value.kind == KbStoreError.DUPLICATE
