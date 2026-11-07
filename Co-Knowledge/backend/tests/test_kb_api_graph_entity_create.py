"""手工创建实体的写入链路。

回归场景：``knowledge_base.store`` 改名/挪到 ``knowledge_base.repository`` 后，
``graph_write_service`` 仍从 ``knowledge_base.service.kbase_service`` 取
``set_kbase_status_modified``，而服务层没有转发这个函数 —— 实体/边已经写进库，
接口却回 400，用户重试变成
「实体已存在」。这组用例钉住四件事：

1. 正常创建：实体、边、发布状态都会写；
2. 边校验必须发生在实体写入之前（失败不能留孤儿实体）；
3. 边写入失败时补偿删除刚创建的实体；
4. 状态回写失败不能把已成功的写入判成失败。
"""

from __future__ import annotations

import json

import pytest

from knowledge_base.service import kbase_service
from shared.errors.api import KbApiError
from graph.service import graph_write_service as service

KB_ID = 'kb-1'

SCHEMA = {
    'entities': [
        {
            'entity_type': 'Person',
            'properties': [
                {'name': 'name', 'type': 'STRING'},
                {'name': 'age', 'type': 'INTEGER'},
            ],
        },
    ],
    'edges': [
        {
            'edge_type': 'Knows',
            'source_entity': 'Person',
            'target_entity': 'Person',
            'properties': [
                {'name': 'since', 'type': 'STRING'},
                {'name': 'weight', 'type': 'FLOAT'},
            ],
        },
    ],
}


def _kbase():
    return {
        'kbase_id': KB_ID,
        'table_name': 'graph_demo',
        'embedding_model': 'm',
        'schema_obj': json.dumps(SCHEMA),
    }


def _payload(**overrides):
    payload = {
        'kbId': KB_ID,
        'entityId': 'Person_new',
        'entityType': 'Person',
        'properties': {'name': 'New', 'age': 30},
        'edgeInfo': {
            'edgeId': 'Knows_1792',
            'edgeType': 'Knows',
            'currentEntityId': 'Person_current',
            'direction': 'in',
            'properties': {'since': '2024'},
        },
    }
    payload.update(overrides)
    return payload


def _patch(monkeypatch):
    calls = {
        'entities': [],
        'edges': [],
        'status': [],
        'deleted_entities': [],
        'deleted_edges': [],
    }
    monkeypatch.setattr(service.kbase_store, 'get_kbase_row', lambda kb_id: _kbase())
    monkeypatch.setattr(service.graph_pg, 'new_client', lambda name: object())
    monkeypatch.setattr(service.graph_pg, 'entity_exists',
                        lambda client, entity_type, entity_id: (
                            entity_type == 'Person' and entity_id == 'Person_current'))
    monkeypatch.setattr(service.graph_pg, 'extract_entity_type_from_id',
                        lambda value: str(value).split('_', 1)[0] if value else None)
    monkeypatch.setattr(service.graph_pg, 'add_entity',
                        lambda client, data: calls['entities'].append(data))
    monkeypatch.setattr(service.graph_pg, 'add_edge',
                        lambda client, data: calls['edges'].append(data))
    monkeypatch.setattr(service.graph_pg, 'delete_edges_by_entity',
                        lambda client, entity_type, entity_id: calls['deleted_edges'].append(
                            (entity_type, entity_id)))
    monkeypatch.setattr(service.graph_pg, 'delete_entity',
                        lambda client, entity_type, entity_id: calls['deleted_entities'].append(
                            (entity_type, entity_id)))
    monkeypatch.setattr(service, '_sync_entity_index', lambda *args: None)
    monkeypatch.setattr(service, '_sync_edge_index', lambda *args: None)
    monkeypatch.setattr(service, '_delete_entity_index', lambda *args: None)
    monkeypatch.setattr(service, '_delete_edge_index', lambda *args: None)
    monkeypatch.setattr(service.kbase_store, 'set_kbase_status_modified',
                        lambda kb_id: calls['status'].append(kb_id))
    return calls


def test_create_entity_writes_entity_edge_and_publish_state(monkeypatch):
    calls = _patch(monkeypatch)

    response = service.create_entity(_payload())

    assert response['success'] is True
    assert [item.entity_id for item in calls['entities']] == ['Person_new']
    assert len(calls['edges']) == 1
    edge = calls['edges'][0]
    assert (edge.edge_id, edge.edge_type) == ('Knows_1792', 'Knows')
    # direction='in' 表示当前实体是起点。
    assert (edge.source_id, edge.target_id) == ('Person_current', 'Person_new')
    assert edge.properties == {'since': '2024'}
    assert calls['status'] == [KB_ID]


def test_invalid_edge_is_rejected_before_entity_is_written(monkeypatch):
    calls = _patch(monkeypatch)
    payload = _payload()
    payload['edgeInfo']['direction'] = 'sideways'

    with pytest.raises(KbApiError):
        service.create_entity(payload)

    assert calls['entities'] == []
    assert calls['edges'] == []


def test_edge_value_type_mismatch_is_rejected_before_entity_is_written(monkeypatch):
    calls = _patch(monkeypatch)
    payload = _payload()
    payload['edgeInfo']['properties'] = {'weight': 'heavy'}

    with pytest.raises(KbApiError):
        service.create_entity(payload)

    assert calls['entities'] == []
    assert calls['edges'] == []


def test_edge_write_failure_rolls_back_the_created_entity(monkeypatch):
    calls = _patch(monkeypatch)

    def explode(client, data):
        raise RuntimeError('edge write failed')

    monkeypatch.setattr(service.graph_pg, 'add_edge', explode)

    with pytest.raises(KbApiError):
        service.create_entity(_payload())

    assert [item.entity_id for item in calls['entities']] == ['Person_new']
    assert calls['deleted_edges'] == [('Person', 'Person_new')]
    assert calls['deleted_entities'] == [('Person', 'Person_new')]
    assert calls['status'] == []


def test_unexpected_error_does_not_leak_internal_details(monkeypatch):
    _patch(monkeypatch)

    def explode(client, data):
        raise RuntimeError(
            "module 'knowledge_base.service.kbase_service' has no attribute 'x'")

    monkeypatch.setattr(service.graph_pg, 'add_entity', explode)

    with pytest.raises(KbApiError) as caught:
        service.create_entity(_payload())

    message = caught.value.render('zh')
    assert 'knowledge_base' not in message
    assert 'has no attribute' not in message


def test_missing_kbase_keeps_the_source_npe_text(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(service.kbase_store, 'get_kbase_row', lambda kb_id: None)

    with pytest.raises(KbApiError) as caught:
        service.create_entity(_payload())

    assert 'Cannot invoke' in caught.value.render('zh')


def test_publish_state_failure_does_not_fail_a_successful_write(monkeypatch):
    calls = _patch(monkeypatch)

    def explode(kb_id):
        raise RuntimeError('status write failed')

    monkeypatch.setattr(service.kbase_store, 'set_kbase_status_modified', explode)

    response = service.create_entity(_payload())

    assert response['success'] is True
    assert [item.entity_id for item in calls['entities']] == ['Person_new']
    assert len(calls['edges']) == 1


@pytest.mark.parametrize('name', [
    'set_kbase_status_modified',
    'generate_kbase_id',
    'count_files',
    'find_kbases_by_name',
    'insert_kbase',
    'update_schema',
    'get_kbase_row',
])
def test_service_exposes_graph_write_and_import_dependencies(name):
    """The graph domain must not reach into another domain's repository."""
    assert callable(getattr(kbase_service, name))
