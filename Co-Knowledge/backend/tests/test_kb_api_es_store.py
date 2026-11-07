"""ES 索引结构：扁平 mapping 与查询 clause。"""

import pytest

from retrieval.repository import es_store as es_store


@pytest.fixture(autouse=True)
def _clear_analyzer_cache():
    es_store._analyzer_cache.clear()
    yield
    es_store._analyzer_cache.clear()


def test_index_body_is_flat_strict_and_versioned():
    body = es_store.index_body(use_ik=False)

    mapping = body['mappings']
    assert mapping['dynamic'] == 'strict'
    assert mapping['_meta'] == {
        'schema': 'kb_index_document', 'schema_version': 2,
        'keyword_analyzer': 'standard',
    }
    assert set(mapping['properties']) == {
        'node_id', 'file_id', 'text', 'source', 'chunk_index', 'chunk_id', 'type',
    }
    assert 'metadata' not in mapping['properties']
    assert 'key' not in mapping['properties']
    assert mapping['properties']['text'] == {'type': 'text'}
    assert mapping['properties']['chunk_id'] == {'type': 'integer'}
    assert mapping['properties']['type'] == {'type': 'short'}


def test_index_body_uses_ik_when_available():
    body = es_store.index_body(use_ik=True)

    assert body['mappings']['properties']['text']['analyzer'] == 'ik_smart'
    assert body['settings']['analysis']['analyzer']['ik']['tokenizer'] == 'ik_smart'


def test_index_body_uses_english_analyzer():
    body = es_store.index_body(use_ik=False, keyword_analyzer='english')

    assert body['mappings']['properties']['text']['analyzer'] == 'english'
    assert body['mappings']['_meta']['keyword_analyzer'] == 'english'
    assert 'analysis' not in body['settings']


def test_index_body_falls_back_when_ik_missing():
    body = es_store.index_body(use_ik=False, keyword_analyzer='ik_smart')

    assert body['mappings']['properties']['text'] == {'type': 'text'}
    assert body['mappings']['_meta']['keyword_analyzer'] == 'standard'


class _FakeIndices:
    def __init__(self, mapping=None, exists=True):
        self.mapping = mapping or {}
        self.exists_result = exists
        self.search_body = None

    def get_mapping(self, index):
        return self.mapping

    def exists(self, index):
        return self.exists_result


class _FakeClient:
    def __init__(self, indices):
        self.indices = indices

    def search(self, index, body):
        self.indices.search_body = body
        return {'hits': {'hits': []}}


def test_match_clause_keeps_whole_question_without_ik():
    clause = es_store._match_clause('text', 'RAG 平台', use_ik=False)

    assert clause == {'match': {'text': {
        'query': 'RAG 平台', 'minimum_should_match': '100%',
    }}}


def test_match_clause_uses_ik_smart():
    clause = es_store._match_clause('text', 'RAG 平台', use_ik=True)

    assert clause == {'match': {'text': {
        'query': 'RAG 平台', 'analyzer': 'ik_smart',
    }}}


def test_match_clause_uses_explicit_english():
    clause = es_store._match_clause('text', 'RAG platform', use_ik=False,
                                    analyzer='english')

    assert clause == {'match': {'text': {
        'query': 'RAG platform', 'analyzer': 'english',
    }}}


def test_index_keyword_analyzer_reads_meta_and_caches(monkeypatch):
    calls = []

    class Indices(_FakeIndices):
        def get_mapping(self, index):
            calls.append(index)
            return {'doc_x': {'mappings': {
                '_meta': {'keyword_analyzer': 'english'},
                'properties': {'text': {'type': 'text', 'analyzer': 'english'}},
            }}}

    monkeypatch.setattr(es_store, '_client', lambda: _FakeClient(Indices()))

    assert es_store.index_keyword_analyzer('doc_x') == 'english'
    assert es_store.index_keyword_analyzer('doc_x') == 'english'
    assert calls == ['doc_x']


def test_index_keyword_analyzer_falls_back_to_mapping(monkeypatch):
    class Indices(_FakeIndices):
        def get_mapping(self, index):
            return {'doc_x': {'mappings': {
                'properties': {'text': {'type': 'text', 'analyzer': 'ik_smart'}},
            }}}

    monkeypatch.setattr(es_store, '_client', lambda: _FakeClient(Indices()))

    assert es_store.index_keyword_analyzer('doc_x') == 'ik_smart'


def test_search_queries_the_text_field(monkeypatch):
    from knowledge_base.repository import kbase as kbase_store

    indices = _FakeIndices(exists=True)
    client = _FakeClient(indices)
    monkeypatch.setattr(es_store, '_client', lambda: client)
    monkeypatch.setattr(es_store, 'ik_analyzer_enabled', lambda: False)
    monkeypatch.setattr(
        kbase_store, 'select_kbase_by_id',
        lambda kbase_id: {'id': 1, 'table_name': 'data_kb_index_x', 'kbase_id': kbase_id},
    )

    es_store.search('x', 'RAG', 5)

    query = indices.search_body['query']
    assert list(query) == ['match']
    value = query['match']['text']
    # 索引 mapping 读不到 analyzer 时用 standard；查询侧显式带上。
    assert value['analyzer'] == 'standard'


def test_index_name_prefers_kbase_id_when_table_name_present():
    assert es_store.index_name('data_kb_index_abc', 7, 'abc') == 'doc_abc'
    assert es_store.index_name('', 7, 'abc') == 'doc_7'
