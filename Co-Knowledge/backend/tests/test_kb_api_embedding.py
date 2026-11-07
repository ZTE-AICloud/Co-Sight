"""整批向量化（``embed_many``）的纯逻辑测试。

embedding 接口接受数组，**一次 HTTP 请求发整批**；
逐条循环是本项目犯过的错 —— 请求数 N 倍（一个文件几十上百次 HTTP），远端网关的
每次抖动都被放大成一次「整条文件链回滚」的风险。这里的判据就是钉住
「**一条请求**」这个事实，别让将来的重构改回去。

跑法::

    python -m pytest tests/test_kb_api_embedding.py -q
"""


import pytest

from model import gateway as model_gateway  # noqa: E402

DIMENSION = 4          # 测试里固定维度，绕开 EMBEDDING_DIMENSION 环境依赖


@pytest.fixture(autouse=True)
def _fixed_dimension(monkeypatch):
    """把模型解析钉死，测试只关心「怎么发请求、怎么排响应」。

    解析结果是 :class:`~compat.kb_api.client.model_gateway.EmbeddingTarget`
    （带端点与 key —— 模型注册表允许每个模型指向自己的端点），桩要与它保持一致。
    """
    monkeypatch.setattr(model_gateway, 'resolve_model', lambda _requested: model_gateway.EmbeddingTarget(
        api_model='test-model', dimension=DIMENSION, url='http://gw:8000/v1/embeddings',
        api_key='', model_name='test-model', origin='env'))


def _install_post(monkeypatch, *, vectors, with_index=True, status=200):
    """替换 ``requests.post``，返回记录调用请求体的列表。"""
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            if status >= 400:
                raise RuntimeError(f'HTTP {status}')

        def json(self):
            data = []
            for position, vector in enumerate(vectors):
                item = {'embedding': vector}
                if with_index:
                    item['index'] = position
                data.append(item)
            return {'data': data}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append({'url': url, 'json': json, 'headers': headers})
        return FakeResponse()

    monkeypatch.setattr(model_gateway.egress, 'post', fake_post)
    return calls


def _vector(value):
    return [value] * DIMENSION


# ----------------------------------------------------------------------
# 核心：一条请求发整批
# ----------------------------------------------------------------------


def test_embed_many_sends_one_request_for_many_texts(monkeypatch):
    """**N 个文本 = 1 次请求** —— 这是这个函数存在的全部理由。"""
    calls = _install_post(monkeypatch, vectors=[_vector(0.1), _vector(0.2), _vector(0.3)])

    vectors = model_gateway.embed_many(['a', 'b', 'c'], None)

    assert len(calls) == 1, f'应该是 1 次请求，实际 {len(calls)} 次'
    assert calls[0]['json'] == {'input': ['a', 'b', 'c'], 'model': 'test-model'}
    assert len(vectors) == 3 and vectors[0][0] == 0.1


def test_embed_single_delegates_to_one_request(monkeypatch):
    """单条重载（``doEmbedding(String)``）也走同一条路，只有 1 个元素。"""
    calls = _install_post(monkeypatch, vectors=[_vector(0.5)])

    vector = model_gateway.embed('question', None)

    assert calls[0]['json']['input'] == ['question']
    assert vector[0] == 0.5


def test_embed_many_orders_by_index(monkeypatch):
    """响应乱序时按 ``index`` 排回来（不能把向量错位写进库）。"""
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {'data': [{'index': 1, 'embedding': _vector(0.2)},
                             {'index': 0, 'embedding': _vector(0.1)}]}

    monkeypatch.setattr(model_gateway.egress, 'post', lambda *a, **k: FakeResponse())

    vectors = model_gateway.embed_many(['a', 'b'], None)

    assert vectors[0][0] == 0.1 and vectors[1][0] == 0.2


def test_embed_many_without_index_keeps_response_order(monkeypatch):
    """网关不给 ``index`` 就按响应顺序。"""
    _install_post(monkeypatch, vectors=[_vector(0.1), _vector(0.2)], with_index=False)

    vectors = model_gateway.embed_many(['a', 'b'], None)

    assert [v[0] for v in vectors] == [0.1, 0.2]


def test_embed_many_empty_short_circuits(monkeypatch):
    """空列表不发请求（别为 0 个文本产生一次 HTTP 调用）。"""
    calls = _install_post(monkeypatch, vectors=[])

    assert model_gateway.embed_many([], None) == []
    assert model_gateway.embed_many(None, None) == []
    assert calls == []


# ----------------------------------------------------------------------
# 坏响应：宁可报错，也别错位写库
# ----------------------------------------------------------------------


def test_embed_many_rejects_count_mismatch(monkeypatch):
    _install_post(monkeypatch, vectors=[_vector(0.1)])

    with pytest.raises(model_gateway.EmbeddingError, match='1 vectors for 2 inputs'):
        model_gateway.embed_many(['a', 'b'], None)


def test_embed_many_rejects_dimension_mismatch(monkeypatch):
    _install_post(monkeypatch, vectors=[[0.1, 0.2]])          # 2 维 ≠ 4 维

    with pytest.raises(model_gateway.EmbeddingError, match='dimension mismatch'):
        model_gateway.embed_many(['a'], None)


def test_embed_many_wraps_gateway_failure(monkeypatch):
    _install_post(monkeypatch, vectors=[], status=502)

    with pytest.raises(model_gateway.EmbeddingError, match='unavailable'):
        model_gateway.embed_many(['a'], None)


# ----------------------------------------------------------------------
# 调用点：链路上不许再有逐条循环
# ----------------------------------------------------------------------


def test_file_chain_embeds_in_one_batch():
    """文件链路的 ``_embed`` 必须走整批（防止将来有人改回循环）。"""
    import inspect

    from knowledge_base.task import handlers

    source = inspect.getsource(handlers._embed)
    assert 'embed_many' in source
    assert 'model_gateway.embed(' not in source
