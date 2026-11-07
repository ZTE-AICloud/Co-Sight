"""ES 写侧：扁平文档构造、``_id=node_id``、索引缺失失败、更新脚本。"""

import json

from retrieval.repository import es_store as es_store, vector_write_store as vector_write_store


class _FakeIndices:
    def __init__(self, exists=True):
        self.exists_result = exists

    def exists(self, index):
        return self.exists_result


class _FakeClient:
    def __init__(self, bulk_results=None):
        self.indices = _FakeIndices()
        self.bulk_results = list(bulk_results or [])
        self.bulk_calls = []
        self.update_calls = []

    def bulk(self, body):
        self.bulk_calls.append(body)
        if self.bulk_results:
            return self.bulk_results.pop(0)
        return {'errors': False}

    def update_by_query(self, index, body, conflicts='abort'):
        self.update_calls.append((index, body, conflicts))
        return {'updated': 1}


def _parse_bulk(body_lines):
    return [json.loads(body_lines[i]) for i in range(0, len(body_lines), 2)], \
        [json.loads(body_lines[i + 1]) for i in range(0, len(body_lines), 2)]


def test_flat_document_omits_none_and_keeps_falsy_values():
    doc = vector_write_store.flat_document(
        'n1', None, 'body',
        {'source': None, 'chunk_index': '', 'chunk_id': 0, 'type': 0},
    )

    assert doc == {
        'node_id': 'n1', 'text': 'body',
        'chunk_index': '', 'chunk_id': 0, 'type': 0,
    }


def test_flat_document_skips_non_integer_chunk_id():
    doc = vector_write_store.flat_document(
        'n1', 'f1', 'body', {'chunk_id': 'a-uuid', 'type': 0},
    )

    assert 'chunk_id' not in doc
    assert doc['type'] == 0


def test_save_es_documents_writes_v2_flat_doc_with_id(monkeypatch):
    from knowledge_base.repository import kbase as kbase_store

    client = _FakeClient()
    monkeypatch.setattr(es_store, '_client', lambda: client)
    monkeypatch.setattr(
        kbase_store, 'select_kbase_by_id',
        lambda kbase_id: {'id': 1, 'table_name': 'data_kb_index_x'},
    )

    vector_write_store.save_es_documents('x', 'file-1', [{
        'node_id': 'n1', 'text': 'body',
        'metadata': {
            'source': 'a.md', 'chunk_index': '', 'chunk_id': 1, 'type': 0,
            'content_expand': 'ignored', 'extra': {'ignored': True},
        },
    }])

    actions, docs = _parse_bulk(client.bulk_calls[0])
    assert actions == [{'index': {'_index': 'doc_x', '_id': 'n1'}}]
    assert docs == [{
        'node_id': 'n1', 'file_id': 'file-1', 'text': 'body',
        'source': 'a.md', 'chunk_index': '', 'chunk_id': 1, 'type': 0,
    }]


def test_update_es_document_rewrites_flat_fields(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(vector_write_store, '_es_index_for', lambda kbase_id: 'doc_x')
    monkeypatch.setattr(es_store, '_client', lambda: client)

    vector_write_store.update_es_document_by_node_id(
        'x', 'n1', 'new body',
        {'source': 'a.md', 'chunk_index': '', 'chunk_id': 1, 'type': 0,
         'content_expand': 'ignored', 'extra': {}},
    )

    _, body, conflicts = client.update_calls[0]
    script = body['script']
    assert conflicts == 'proceed'
    assert script['params'] == {
        'text': 'new body',
        'fields': {'source': 'a.md', 'chunk_index': '', 'chunk_id': 1, 'type': 0},
    }


def test_save_es_documents_raises_when_index_missing(monkeypatch):
    """索引缺失不能静默成功：否则 PG 有数据、关键词路永远为空。"""
    from knowledge_base.repository import kbase as kbase_store

    class _MissingClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self.indices = _FakeIndices(exists=False)

    monkeypatch.setattr(es_store, '_client', lambda: _MissingClient())
    monkeypatch.setattr(kbase_store, 'select_kbase_by_id',
                        lambda _id: {'table_name': 'data_kb_index_demo', 'id': 1})

    import pytest
    with pytest.raises(RuntimeError, match='does not exist'):
        vector_write_store.save_es_documents('x', 'file-1', [{
            'node_id': 'n1', 'text': 't', 'metadata': {}}])


def test_index_body_defaults_to_zero_replicas(monkeypatch):
    """单节点默认 0 副本，避免集群长期 yellow（P1）。"""
    monkeypatch.delenv('ES_NUMBER_OF_REPLICAS', raising=False)
    assert es_store.index_body(False)['settings']['number_of_replicas'] == 0


def test_index_body_honors_replicas_env(monkeypatch):
    monkeypatch.setenv('ES_NUMBER_OF_REPLICAS', '1')
    assert es_store.index_body(False)['settings']['number_of_replicas'] == 1
