"""手工实体/边写入的向量索引同步。

钉住四条：

1. 实体新增/更新后 upsert `_vector`，文本来自 图存储 的**业务属性**（去掉  等）；
2. 边新增/更新后 upsert，key 仍是 ``"<source>,<target>"``；
3. 删除实体/边后清对应 key；
4. 索引失败不判死主操作（只记 ERROR，不抛）。

跑法::

    python -m pytest tests/test_kb_api_graph_write_index_sync.py -q
"""

from __future__ import annotations

from graph.repository import graph_pg
from graph.service import graph_write_service as service
from graph.repository import graph_index_store


def _kbase():
    return {'kbase_id': 'kb-1', 'table_name': 'graph_demo', 'embedding_model': 'm'}


def test_sync_entity_index_upserts_clean_text(monkeypatch):
    monkeypatch.setattr(graph_pg, 'get_entity_properties', lambda *a: {
        'name': '张三', '@rid': '#1:0', '@class': 'Person', 'out_Knows': '#2:0'})
    monkeypatch.setattr(service, '_embed_one', lambda text, model: [0.1])
    captured = {}
    monkeypatch.setattr(graph_index_store, 'upsert_vectors',
                        lambda base, key_type, rows: captured.update(
                            {'base': base, 'type': key_type, 'rows': list(rows)}))

    service._sync_entity_index(_kbase(), object(), 'Person_1', 'Person')

    assert captured['base'] == 'graph_demo'
    assert captured['type'] == graph_index_store.KEY_TYPE_ENTITY
    key_id, text, labels, vector = captured['rows'][0]
    assert key_id == 'Person_1'
    assert 'entity_type: Person' in text
    assert 'name: 张三' in text
    assert '@rid' not in text and 'out_Knows' not in text
    assert labels == ['Person']
    assert vector == [0.1]


def test_sync_edge_index_upserts_endpoint_key(monkeypatch):
    monkeypatch.setattr(graph_pg, 'get_edge_properties', lambda *a: {
        'out': '#1:0', 'in': '#1:1', 'position': '工程师',
        'source_id': 'Person_1', 'target_id': 'Company_1'})
    monkeypatch.setattr(graph_pg, 'extract_entity_id_from_rid',
                        lambda rid: {'#1:0': 'Person_1', '#1:1': 'Company_1'}[rid])
    monkeypatch.setattr(service, '_embed_one', lambda text, model: [0.2])
    captured = {}
    monkeypatch.setattr(graph_index_store, 'upsert_vectors',
                        lambda base, key_type, rows: captured.update(
                            {'type': key_type, 'rows': list(rows)}))

    service._sync_edge_index(_kbase(), object(), 'WorksAt_1', 'WorksAt')

    assert captured['type'] == graph_index_store.KEY_TYPE_EDGE
    key_id, text, labels, vector, edge_id, source, target = captured['rows'][0]
    assert key_id == 'WorksAt_1'
    assert edge_id == 'WorksAt_1'
    assert (source, target) == ('Person_1', 'Company_1')
    assert 'edge_type: WorksAt' in text
    assert labels == ['WorksAt']
    assert vector == [0.2]


def test_delete_helpers_remove_keys(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_index_store, 'delete_vector_keys',
                        lambda base, key_type, ids: calls.append(
                            ('keys', base, key_type, list(ids))))
    monkeypatch.setattr(graph_index_store, 'delete_edge_vectors_touching',
                        lambda base, ids: calls.append(
                            ('touching', base, list(ids))))

    service._delete_entity_index(_kbase(), 'Person_1')
    service._delete_edge_index(_kbase(), 'WorksAt_1')

    assert calls == [
        ('keys', 'graph_demo', graph_index_store.KEY_TYPE_ENTITY, ['Person_1']),
        ('touching', 'graph_demo', ['Person_1']),
        ('keys', 'graph_demo', graph_index_store.KEY_TYPE_EDGE, ['WorksAt_1']),
    ]


def test_sync_failure_is_logged_not_raised(monkeypatch):
    monkeypatch.setattr(graph_pg, 'get_entity_properties', lambda *a: {'name': 'x'})
    monkeypatch.setattr(service, '_embed_one',
                        lambda text, model: (_ for _ in ()).throw(RuntimeError('gateway')))

    # 不应抛异常：图存储 主操作已经成功
    service._sync_entity_index(_kbase(), object(), 'Person_1', 'Person')
