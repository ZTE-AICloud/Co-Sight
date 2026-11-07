"""``POST /retrieval`` 的测试。

不连库、不连网关：向量表访问与 embedding 调用都用假的替换掉。这一层要钉住的是
**线上真实行为**——包括几处看着像 bug、但必须原样保留的地方。

跑法（服务目录下）::

    python -m pytest tests/test_kb_api_retrieve.py -q
"""


import pytest

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import http_api as kb_router  # noqa: E402
from model import gateway as model_gateway  # noqa: E402
from retrieval.service import node_mapper as node_mapper, retrieve_service as retrieve_service  # noqa: E402
from retrieval.repository import es_store as es_store, vector_store as vector_store  # noqa: E402

KB_ID = '447a9eb509e44d399790dbfd97f25360'
BASE = f'doc_{KB_ID}'
VECTOR_TABLE = f'{BASE}_vector'


def _vector_record(**overrides) -> dict:
    record = {
        'id': 1,
        'text': '这是一段用于验证自定义定长切分算子的测试文本。',
        # ``metadata_`` 这个 JSON 列已**展开成 5 个物理列**（见
        # ``compat/kb_api/store/node_columns.py``）。存储层查询（``vector_store`` /
        # ``chunk_store``）会先按 ``node_columns.metadata_from_row()`` 把列拼回一个
        # ``metadata`` dict 再交给这里，所以**桩要模拟的是那个形状**。
        'metadata': {
            'chunk_index': '', 'source': 'sample-op.md', 'type': 0, 'chunk_id': 1,
            'content_expand': '1',
        },
        'node_id': 'n1',
        'embedding': None,
        'cosine_similarity': 0.15211237513684173,
        'chunk_text': '切片正文',
        'chunk_id': '1',
    }
    record.update(overrides)
    return record


@pytest.fixture()
def store_stub(monkeypatch):
    """向量表 / kb_kbase 的桩。默认：新知识库、有 chunk 表、命中一条。"""
    state = {'records': [_vector_record()], 'vector_table': True,
             'chunk_table': True, 'pk_id': 1}

    monkeypatch.setattr(vector_store, 'table_exists',
                        lambda name: state['vector_table'] if not name.endswith('_chunk')
                        else state['chunk_table'])
    monkeypatch.setattr(vector_store, 'select_table_name_by_kbase_id',
                        lambda kb_id: VECTOR_TABLE)
    monkeypatch.setattr(vector_store, 'query_by_embedding_with_chunk',
                        lambda *a, **k: list(state['records']))
    monkeypatch.setattr(model_gateway, 'embed', lambda question, model: [0.1] * 768)
    return state


def _payload(**overrides) -> dict:
    body = {
        'question': 'RAG',
        'type': 0,
        'bases': [{'baseList': [BASE], 'priority': 0, 'top_k': 3, 'score_threshold': 0.0}],
    }
    body.update(overrides)
    return body


# ----------------------------------------------------------------------
# 入参校验：走 0004（不是空结果）
# ----------------------------------------------------------------------


def test_missing_question_raises_validation_error_not_empty_result():
    """校验失败是 0004 + bo=null，与「检索失败 → bo=[]」**不是同一回事**。

    ``retrieve()`` 里 ``_validate`` 在 ``try`` **之前**跑，所以它抛出的
    ``KbValidationError`` 不会被那个 ``except Exception`` 吞成空结果 ——
    这个顺序是刻意的，改动了会让入参错误伪装成「没检索到」。
    """
    from shared.errors.api import KbValidationError

    with pytest.raises(KbValidationError) as excinfo:
        retrieve_service.retrieve(_payload(question='  '))

    assert excinfo.value.render('en') == 'Question cannot be null or empty'


def test_validation_failure_over_http_returns_0004(client):
    response = client.post(f'{kb_router.KBASE_PREFIX}/retrieval', json=_payload(question=''))
    body = response.json()

    assert response.status_code == 422
    assert body['code'] == 'validation_failed'
    assert body['detail'] == 'Question cannot be null or empty'


def test_type_out_of_range_message(client):
    body = client.post(f'{kb_router.KBASE_PREFIX}/retrieval',
                       json=_payload(type=7)).json()

    assert body['detail'] == 'Type must be 0 or 1'


def test_empty_bases_message(client):
    body = client.post(f'{kb_router.KBASE_PREFIX}/retrieval',
                       json=_payload(bases=[])).json()

    assert body['detail'] == 'Bases cannot be empty'


@pytest.fixture()
def client(store_stub):
    app = FastAPI()
    kb_router.register_rkb_api(app)
    return TestClient(app)


# ----------------------------------------------------------------------
# 分组与降级语义
# ----------------------------------------------------------------------


def test_priority_groups_are_queried_high_to_low(store_stub, monkeypatch):
    seen = []

    def fake_related(embedding, base_list, threshold, top_k):
        seen.append(base_list[0])
        return [{'base_name': base_list[0], 'docs': []}]     # 空 docs → 继续降级

    monkeypatch.setattr(retrieve_service, '_related_embeddings', fake_related)

    retrieve_service.retrieve(_payload(bases=[
        {'baseList': ['doc_low'], 'priority': 1},
        {'baseList': ['doc_high'], 'priority': 9},
    ]))

    assert seen == ['doc_high', 'doc_low']


def test_returns_at_first_group_with_non_empty_docs(store_stub, monkeypatch):
    seen = []

    def fake_related(embedding, base_list, threshold, top_k):
        seen.append(base_list[0])
        # 高优先级那条**有**命中，低优先级那条没有 —— 用来验证「命中即停止降级」
        docs = [{'node': {'text': 'x'}}] if base_list[0].endswith('high') else []
        return [{'base_name': base_list[0], 'docs': docs}]

    monkeypatch.setattr(retrieve_service, '_related_embeddings', fake_related)

    result = retrieve_service.retrieve(_payload(bases=[
        {'baseList': ['doc_low'], 'priority': 1},
        {'baseList': ['doc_high'], 'priority': 9},
    ]))

    # 高优先级组有非空 docs → 只返回它，低优先级不再查（seen 不含 low）
    assert seen == ['doc_high']
    assert len(result) == 1 and result[0]['baseName'] == 'doc_high'


def test_all_empty_groups_return_accumulated_entries_not_empty_list(store_stub, monkeypatch):
    monkeypatch.setattr(
        retrieve_service, '_related_embeddings',
        lambda e, base_list, t, k: [{'base_name': base_list[0], 'docs': []}])

    result = retrieve_service.retrieve(_payload(bases=[
        {'baseList': ['doc_a'], 'priority': 1},
    ]))

    # 「全程无命中」返回的是每个 base 一条（docs 为空）的全量，**不是** []
    assert result == [{'baseName': 'doc_a', 'docs': []}]


def test_null_priority_collapses_whole_request_to_empty(store_stub):
    """``priority`` 缺失时不校验直接使用会崩，被 catch 吞成 bo=[]。

    看着不合理但是真实行为：这里同样收敛成空结果，而不是报校验错。
    """
    result = retrieve_service.retrieve(_payload(bases=[{'baseList': [BASE]}]))

    assert result == []


# ----------------------------------------------------------------------
# 向量路细节
# ----------------------------------------------------------------------


def test_vector_table_missing_skips_the_base_entirely(store_stub):
    store_stub['vector_table'] = False

    result = retrieve_service.retrieve(_payload())

    assert result == []          # 该 base 完全不产出条目（不是空 docs 的条目）


def test_new_kbase_with_zero_hits_collapses_whole_request(store_stub):
    """**刻意保留的行为缺陷**：新库 0 命中 → 整请求 bo=[]。

    联合查询后无条件取第一条结果打日志，空结果直接下标越界，冒到
    ``retrieve()`` 的 catch。删掉那行会让行为变成「该库空 docs」，是行为变更。
    """
    store_stub['records'] = []

    assert retrieve_service.retrieve(_payload()) == []


def test_chunk_table_name_prefers_table_name_column(store_stub, monkeypatch):
    captured = {}

    def fake_query(table, chunk_table, *rest):
        captured['chunk_table'] = chunk_table
        return [_vector_record()]

    monkeypatch.setattr(vector_store, 'query_by_embedding_with_chunk', fake_query)

    retrieve_service.retrieve(_payload())

    assert captured['chunk_table'] == f'{BASE}_chunk'


# ----------------------------------------------------------------------
# 输出映射
# ----------------------------------------------------------------------


def test_doc_fields_match_the_live_contract(store_stub):
    """各字段对齐对外契约（含 ``chunkId`` 是字符串、``sourceDocId`` 为 null）。"""
    doc = retrieve_service.retrieve(_payload())[0]['docs'][0]

    assert doc['chunkId'] == '1'                       # String.valueOf(1) → "1"
    assert doc['content'] == '这是一段用于验证自定义定长切分算子的测试文本。'
    assert doc['score'] == 0.15211237513684173
    assert doc['sourceDocId'] is None                  # 新库分支不设 node.file_id
    assert doc['metadata']['chunk_id'] == 1            # 存储里是数字，原样透出
    assert doc['metadata']['chunk_index'] == ''
    assert doc['metadata']['source'] == 'sample-op.md'


def test_only_two_internal_metadata_keys_are_stripped():
    """``INTERNAL_METADATA_KEYS`` 只有两个键，其余（含 chunk_id/source/type）原样透出。"""
    assert node_mapper.INTERNAL_METADATA_KEYS == {
        'content_expand', 'context_expand_method'}

    doc = node_mapper.to_search_doc({
        'node': {'text': 'x', 'metadata': {
            'content_expand': 'c', 'context_expand_method': 'm',
            'chunk_id': 9, 'source': 's', 'type': 0,
        }},
        'score': 1,
    })

    assert doc['metadata'] == {'chunk_id': 9, 'source': 's', 'type': 0}


def test_null_metadata_record_degrades_to_empty_doc():
    """``metadata_`` 为 null 时 ``processOldTableRecord`` 返回空 map → 字段全 null。"""
    node = node_mapper.process_vector_record({'metadata_': None, 'text': 'x'})

    assert node == {}


def test_vector_literal_uses_float32_shortest_repr():
    assert vector_store.to_vector_literal([]) == '[]'
    assert vector_store.to_vector_literal([1.0, 0.5]) == '[1.0,0.5]'


def test_identifier_validation_rejects_injection():
    """表名走字符串拼接，所以必须有白名单。"""
    with pytest.raises(ValueError):
        vector_store.validate_identifier('data_x; DROP TABLE kb_kbase')


# ----------------------------------------------------------------------
# 关键词路
# ----------------------------------------------------------------------


def test_keyword_path_uses_es_and_ignores_score_threshold(store_stub, monkeypatch):
    called = {}

    def fake_search(kbase_id, question, top_k):
        called.update(kbase_id=kbase_id, question=question, top_k=top_k)
        return [{'_id': 'doc1', '_score': 2.5, '_source': {
            'node_id': 'n1', 'file_id': 'file-1', 'text': '正文',
            'source': 'a.md', 'chunk_index': '', 'chunk_id': 1, 'type': 0,
        }}]

    monkeypatch.setattr(es_store, 'search', fake_search)
    monkeypatch.setattr(retrieve_service.model_gateway, 'embed',
                        lambda q, m: pytest.fail('关键词路不该调 embedding'))

    result = retrieve_service.retrieve(_payload(type=1, bases=[
        {'baseList': [BASE], 'priority': 0, 'top_k': 5, 'score_threshold': 0.9}]))

    assert called == {'kbase_id': '447a9eb509e44d399790dbfd97f25360',
                      'question': 'RAG', 'top_k': 5}
    doc = result[0]['docs'][0]
    assert doc['content'] == '正文'
    assert doc['score'] == 2.5
    assert doc['sourceDocId'] == 'file-1'      # 关键词路**有** file_id
    assert doc['metadata'] == {'chunk_index': '', 'source': 'a.md', 'chunk_id': 1, 'type': 0}


def test_keyword_path_reads_flat_es_document(store_stub, monkeypatch):
    """v2 扁平文档：chunkId/metadata 与向量路对齐。"""
    def fake_search(kbase_id, question, top_k):
        return [{'_id': 'n1', '_score': 2.5, '_source': {
            'node_id': 'n1', 'file_id': 'file-1', 'text': '正文',
            'source': 'a.md', 'chunk_index': '', 'chunk_id': 1, 'type': 0,
        }}]

    monkeypatch.setattr(es_store, 'search', fake_search)
    monkeypatch.setattr(retrieve_service.model_gateway, 'embed',
                        lambda q, m: pytest.fail('关键词路不该调 embedding'))

    doc = retrieve_service.retrieve(_payload(type=1))[0]['docs'][0]

    assert doc['chunkId'] == '1'
    assert doc['content'] == '正文'
    assert doc['sourceDocId'] == 'file-1'
    assert doc['metadata'] == {
        'chunk_index': '', 'source': 'a.md', 'chunk_id': 1, 'type': 0,
    }
    assert list(doc['metadata']) == ['chunk_index', 'source', 'chunk_id', 'type']


def test_scope_suffix_is_stripped_from_base_name_and_table(store_stub):
    """``|#|dev`` 后缀要剥掉：``baseName`` 与拼出的表名都不能带它。"""
    asked = []
    original = vector_store.table_exists
    store_stub['vector_table'] = True

    import retrieval.repository.vector_store as vs

    def spy(name):
        asked.append(name)
        return True

    vs.table_exists = spy
    try:
        result = retrieve_service.retrieve(_payload(bases=[
            {'baseList': [BASE + '|#|dev'], 'priority': 0}]))
    finally:
        vs.table_exists = original

    assert asked and asked[0] == VECTOR_TABLE        # 表名不带后缀
    assert result[0]['baseName'] == BASE


# ----------------------------------------------------------------------
# 检索基名：doc_ 前缀
# ----------------------------------------------------------------------


@pytest.mark.parametrize('raw, expected', [
    ('doc_447a9eb509e44d399790dbfd97f25360', '447a9eb509e44d399790dbfd97f25360'),
    # doc_ 同时是物理表名前缀：传表名时先把 _vector/_chunk 剥掉
    ('doc_447a9eb509e44d399790dbfd97f25360_vector', '447a9eb509e44d399790dbfd97f25360'),
    ('doc_447a9eb509e44d399790dbfd97f25360_chunk', '447a9eb509e44d399790dbfd97f25360'),
    ('447a9eb509e44d399790dbfd97f25360', None),
    ('', None),
])
def test_kbase_id_from_base_name_accepts_doc_and_legacy(raw, expected):
    assert retrieve_service._kbase_id_from_base_name(raw) == expected


def test_doc_base_name_resolves_the_doc_vector_table(store_stub, monkeypatch):
    """新基名 ``doc_<uuid>`` 走 kbaseId → ``kb_kbase.table_name``，与旧名同一条路。"""
    kbase_id = '447a9eb509e44d399790dbfd97f25360'
    asked = []

    monkeypatch.setattr(vector_store, 'table_exists',
                        lambda name: asked.append(name) or True)
    monkeypatch.setattr(vector_store, 'select_table_name_by_kbase_id',
                        lambda kb_id: f'doc_{kb_id}_vector')

    result = retrieve_service.retrieve(_payload(bases=[
        {'baseList': [f'doc_{kbase_id}'], 'priority': 0}]))

    assert asked and asked[0] == f'doc_{kbase_id}_vector'
    assert result[0]['baseName'] == f'doc_{kbase_id}'
