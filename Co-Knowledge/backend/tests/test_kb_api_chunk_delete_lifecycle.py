"""``delete_chunk`` 的删除顺序与副作用。

钉住三条：

1. ES 在**任何 PG 删除之前**；ES 失败时 PG 一行不动，重试仍可用；
2. 新库删 chunk 表行，老库不删（``content_expand`` 双语义）；
3. relation **最后**删（它是 chunkId 的唯一寻址锚点）。

跑法::

    python -m pytest tests/test_kb_api_chunk_delete_lifecycle.py -q
"""

from __future__ import annotations

import pytest

from knowledge_base.service import chunk_service as service


def _install(monkeypatch, events, *, es_error=False,
             vector_error=False):
    monkeypatch.setattr(service, '_relation_or_raise',
                        lambda chunk_id, kbase_id: {'node_id': 'node-1'})
    monkeypatch.setattr(service, '_kbase_or_raise',
                        lambda kbase_id: {'kbase_id': kbase_id})

    monkeypatch.setattr(service.chunk_store, 'query_by_node_id',
                        lambda kbase, node_id: {'metadata': {
                            service.CONTENT_EXPAND: 'chunk-row-1'}})

    def _es(kbase_id, field, node_ids):
        events.append('es')
        if es_error:
            raise RuntimeError('es down')

    def _chunk_row(kbase, chunk_id):
        events.append('chunk_row')
        return 1

    def _vectors(kbase, node_ids):
        events.append('vector')
        if vector_error:
            raise RuntimeError('pg down')

    def _relation(chunk_id):
        events.append('relation')

    monkeypatch.setattr(service.vector_store_write,
                        'delete_es_documents_by_query', _es)
    monkeypatch.setattr(service.chunk_store, 'delete_chunk_by_id', _chunk_row)
    monkeypatch.setattr(service.chunk_store, 'delete_by_node_ids', _vectors)
    monkeypatch.setattr(service.chunk_store, 'delete_relation', _relation)


def test_delete_chunk_order_es_then_pg_then_relation(monkeypatch):
    events = []
    _install(monkeypatch, events)

    service.delete_chunk(42, 'kb-1')

    assert events == ['es', 'chunk_row', 'vector', 'relation']


def test_es_failure_leaves_pg_untouched(monkeypatch):
    events = []
    _install(monkeypatch, events, es_error=True)

    with pytest.raises(RuntimeError, match='es down'):
        service.delete_chunk(42, 'kb-1')

    assert events == ['es']


def test_vector_failure_keeps_relation_for_retry(monkeypatch):
    events = []
    _install(monkeypatch, events, vector_error=True)

    with pytest.raises(RuntimeError, match='pg down'):
        service.delete_chunk(42, 'kb-1')

    assert events == ['es', 'chunk_row', 'vector']
    assert 'relation' not in events
