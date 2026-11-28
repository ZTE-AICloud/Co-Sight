"""混合检索：BM25 + 向量经 RRF 融合，重排可选且失败即退化。"""

import pytest

from text_to_sql import schema_retriever


class _Repo:
    def __init__(self, vector_hits, knowledge):
        self._vector = vector_hits
        self._knowledge = knowledge
        self.version = None

    def search_knowledge(self, version_id, embedding, limit=24, datasource_id=None):
        self.version = version_id
        return list(self._vector)

    def list_knowledge_text(self, version_id):
        return list(self._knowledge)


TABLE_ORDER = {'object_type': 'TABLE', 'object_key': 't-order',
               'title': 'public.order_info', 'content': '数据表 订单 支付金额 订单状态'}
TABLE_CITY = {'object_type': 'TABLE', 'object_key': 't-city',
              'title': 'public.region_info', 'content': '数据表 城市名称 地区'}
COLUMN_AMOUNT = {'object_type': 'COLUMN', 'object_key': 'c-amount',
                 'title': 'public.order_info.pay_amount',
                 'content': '字段 支付金额 金额'}


@pytest.fixture(autouse=True)
def _clear_cache():
    schema_retriever.clear_cache()
    yield
    schema_retriever.clear_cache()


def _repo():
    return _Repo(
        vector_hits=[{**TABLE_CITY, 'score': 0.9}, {**TABLE_ORDER, 'score': 0.8}],
        knowledge=[TABLE_ORDER, TABLE_CITY, COLUMN_AMOUNT])


def test_lexical_signal_promotes_exact_term_match():
    """向量把城市排第一，但问题字面命中「订单」时 BM25 应把订单表顶上来。"""
    result = schema_retriever.search(_repo(), 'v1', '订单的支付金额', [0.1, 0.2])
    assert result['hits'][0]['object_key'] == 't-order'
    assert result['sources']['lexical'] > 0
    assert result['sources']['vector'] == 2


def test_rrf_uses_ranks_not_raw_scores():
    """向量分数量纲不影响融合：只比名次。"""
    result = schema_retriever.search(_repo(), 'v1', '城市', [0.1])
    keys = [hit['object_key'] for hit in result['hits']]
    assert keys[0] == 't-city'
    assert set(keys) >= {'t-city', 't-order'}


def test_cache_is_keyed_by_version_and_immutable():
    repo = _repo()
    schema_retriever.search(repo, 'v1', '订单', [0.1])
    calls = []
    repo.list_knowledge_text = lambda version_id: calls.append(version_id) or []
    schema_retriever.search(repo, 'v1', '订单', [0.1])
    assert calls == []          # 命中缓存，没有再取一次正文
    schema_retriever.search(repo, 'v2', '订单', [0.1])
    assert calls == ['v2']


def test_rerank_failure_falls_back_to_fused_order(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError('endpoint down')

    monkeypatch.setattr(schema_retriever.retrieval, '_call_rerank', boom)
    result = schema_retriever.search(_repo(), 'v1', '订单', [0.1], rerank_model='m')
    assert result['reranked'] is False
    assert result['hits']


def test_rerank_reorders_with_scores(monkeypatch):
    monkeypatch.setattr(
        schema_retriever.retrieval, '_call_rerank',
        lambda question, documents, model: [0.1, 0.9, 0.5][:len(documents)])
    result = schema_retriever.search(_repo(), 'v1', '订单', [0.1], rerank_model='m')
    assert result['reranked'] is True
    assert result['hits'][0].get('rerank_score') is not None
    scores = [hit.get('rerank_score') for hit in result['hits'][:3]]
    assert scores == sorted(scores, reverse=True)


def test_empty_corpus_is_not_an_error():
    repo = _Repo(vector_hits=[], knowledge=[])
    result = schema_retriever.search(repo, 'v1', '订单', [0.1])
    assert result['hits'] == []
