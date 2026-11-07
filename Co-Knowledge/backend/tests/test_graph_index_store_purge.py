"""图谱索引删除链的纯逻辑测试。

钉住三点：

1. ``chunk_id`` 是逗号分隔字符串，按**精确 id** 匹配，不做子串匹配；
2. 删顶点后返回实际删掉的 ``entity_id``，PG 侧据此清 entity/edge 向量；
3. 图存储删除失败不静默（由调用方决定整体失败/重试）。

跑法::

    python -m pytest tests/test_graph_index_store_purge.py -q
"""

from __future__ import annotations

import pytest

from graph.repository import graph_pg
from graph.repository import graph_index_store as store


class _Client:
    def __init__(self):
        self.dbname = 'graph_demo'


def test_list_vertices_matches_exact_chunk_ids_only(monkeypatch):
    rows = [
        {'@class': 'Entity', 'entity_id': 'E1', 'chunk_id': 'c1, c2'},
        {'@class': 'Entity', 'entity_id': 'E2', 'chunk_id': 'c10'},
        {'@class': 'Entity', 'entity_id': 'E3', 'chunk_id': None},
        {'@class': 'Entity', 'entity_id': 'E4', 'chunk_id': 'c3'},
    ]
    monkeypatch.setattr(graph_pg, 'list_all_vertices', lambda client: rows)

    matched = graph_pg.list_vertices_by_chunk_ids(_Client(), ['c2'])

    assert [row['entity_id'] for row in matched] == ['E1']


def test_delete_entities_by_chunk_ids_returns_deleted_ids(monkeypatch):
    rows = [
        {'@class': 'Person', 'entity_id': 'P1', 'chunk_id': 'c1'},
        {'@class': 'Person', 'entity_id': 'P2', 'chunk_id': 'c9'},
    ]
    deleted = []
    monkeypatch.setattr(graph_pg, 'list_all_vertices', lambda client: rows)
    monkeypatch.setattr(graph_pg, 'delete_entity',
                        lambda client, entity_type, entity_id: deleted.append(
                            (entity_type, entity_id)))

    result = graph_pg.delete_entities_by_chunk_ids(_Client(), ['c1'])

    assert result == ['P1']
    assert deleted == [('Person', 'P1')]


def test_delete_entities_by_chunk_ids_continues_after_one_failure(monkeypatch):
    rows = [
        {'@class': 'Person', 'entity_id': 'P1', 'chunk_id': 'c1'},
        {'@class': 'Person', 'entity_id': 'P2', 'chunk_id': 'c1'},
    ]
    monkeypatch.setattr(graph_pg, 'list_all_vertices', lambda client: rows)

    def _delete(_client, _type, entity_id):
        if entity_id == 'P1':
            raise RuntimeError('bad record')

    monkeypatch.setattr(graph_pg, 'delete_entity', _delete)

    assert graph_pg.delete_entities_by_chunk_ids(_Client(), ['c1']) == ['P2']


def test_delete_source_graph_data_cleans_all_three_key_types(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_pg, 'new_client', lambda name: object())
    monkeypatch.setattr(graph_pg, 'delete_entities_by_chunk_ids',
                        lambda client, ids: ['E1', 'E2'])
    monkeypatch.setattr(store, 'delete_vector_keys',
                        lambda base, key_type, ids: calls.append(
                            ('delete', key_type, list(ids))) or len(list(ids)))
    monkeypatch.setattr(store, '_delete_edge_vectors_touching',
                        lambda base, entity_ids: calls.append(
                            ('edges', sorted(entity_ids))) or 3)

    stats = store.delete_source_graph_data('graph_demo', 'kb-1', ['c1', 'c2'])

    assert stats == {'entities': 2, 'edges': 3, 'chunks': 2}
    assert ('delete', store.KEY_TYPE_ENTITY, ['E1', 'E2']) in calls
    assert ('delete', store.KEY_TYPE_CHUNK, ['c1', 'c2']) in calls
    assert ('edges', ['E1', 'E2']) in calls


def test_delete_source_graph_data_empty_ids_is_noop(monkeypatch):
    monkeypatch.setattr(graph_pg, 'new_client',
                        lambda name: pytest.fail('must not connect'))
    assert store.delete_source_graph_data('graph_demo', 'kb-1', []) == {
        'entities': 0, 'edges': 0, 'chunks': 0}
